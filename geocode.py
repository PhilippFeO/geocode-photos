"""Usage: python flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg.

Flask app with a three-pane HTML/Leaflet UI.
Map click events are sent back to the server via JavaScript fetch() — no clipboard.
Press Ctrl-C to stop the server; GPS + location EXIF tags are then written via exiftool.
A .bak copy is created next to each file before its first write.
"""

import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from threading import Thread

import piexif
import requests
from flask import Flask, jsonify, render_template_string, request, send_file
from PIL import Image

from template import TEMPLATE_HTML

app = Flask(__name__)

photos: list[Path] = []
# Keyed by filename (not absolute Path!) — assumes unique basenames across the selection.
photo_index: dict[str, Path] = {}
# Filled incrementally as the user clicks the map; written to EXIF on exit.
coords: dict[str, tuple[float, float]] = {}
# Photos already carrying coordinates — skipped when writing EXIF metadata.
pre_tagged: set[str] = set()

# ── EXIF helpers ──────────────────────────────────────────────────────────────


def _read_gps_from_file(path: Path) -> tuple[float, float] | None:
    """Return (lat, lng) from a file's GPS EXIF, or None if absent/unreadable."""
    try:
        img = Image.open(path)
        gps = piexif.load(img.info.get('exif', b'')).get('GPS', {})
        img.close()
        if (
            piexif.GPSIFD.GPSLatitude not in gps
            or piexif.GPSIFD.GPSLongitude not in gps
        ):
            return None

        def dms_to_deg(dms):
            return sum(r[0] / r[1] / factor for r, factor in zip(dms, (1, 60, 3600)))

        lat = dms_to_deg(gps[piexif.GPSIFD.GPSLatitude])
        lng = dms_to_deg(gps[piexif.GPSIFD.GPSLongitude])
        if gps.get(piexif.GPSIFD.GPSLatitudeRef, b'N') in (b'S', 'S'):
            lat = -lat
        if gps.get(piexif.GPSIFD.GPSLongitudeRef, b'E') in (b'W', 'W'):
            lng = -lng
        return lat, lng
    except Exception:
        return None


def _reverse_geocode(lat: float, lng: float) -> tuple[str, str] | None:
    """Return (city, country) from Nominatim, or None on failure."""
    try:
        r = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={'lat': lat, 'lon': lng, 'format': 'json'},
            headers={
                'User-Agent': 'geocoding_photos/1.0',
                'Accept-Language': 'de, en;q=0.9',
            },
            timeout=10,
        )
        addr = r.json().get('address', {})
        city = addr.get('city') or addr.get('town') or addr.get('village', '')
        country = addr.get('country', '')
    except requests.exceptions.Timeout:
        return None
    else:
        return city, country


def _write_exif(path: Path, lat: float, lng: float, city: str, country: str) -> None:
    subprocess.run(
        [
            '/usr/bin/exiftool',
            f'-GPSLatitude={abs(lat)}',
            f'-GPSLatitudeRef={"N" if lat >= 0 else "S"}',
            f'-GPSLongitude={abs(lng)}',
            f'-GPSLongitudeRef={"E" if lng >= 0 else "W"}',
            f'-IPTC:City={city}',
            f'-IPTC:Country-PrimaryLocationName={country}',
            '-overwrite_original',
            str(path),
        ],
        check=True,
        capture_output=True,
    )


# ── Flask routes ──────────────────────────────────────────────────────────────


@app.route('/')
def index():
    # Pass only the filenames to the template; full paths stay server-side.
    return render_template_string(TEMPLATE_HTML, photos=list(photo_index))


@app.route('/photo/<name>')
def serve_photo(name):
    """Serve a photo by its basename.

    Only names present in photo_index are accepted, so the user cannot request arbitrary filesystem paths.
    """
    path = photo_index.get(name)
    if path is None:
        return 'Not found', 404
    return send_file(path)


@app.route('/coords', methods=['POST'])
def receive_coords():
    """Set coordinates for a photo."""
    # Payload: {"photo": "<basename>", "lat": <float>, "lng": <float>}
    body = request.get_json(force=True)
    photo = body.get('photo', '')
    # Set coordinates of photo
    if photo in photo_index:
        coords[photo] = (float(body['lat']), float(body['lng']))
        # If coordinates were updated, remove it from pre_tagged so it gets written on exit.
        pre_tagged.discard(photo)
    # Return the full dict so the client could sync state on page reload if needed.
    # Currently, not used.
    return jsonify({k: list(v) for k, v in coords.items()})


@app.route('/coords', methods=['GET'])
def get_coords():
    """Open in browser or curl to inspect collected coords (Convenience endpoint)."""
    return jsonify({k: list(v) for k, v in coords.items()})


@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Trigger a clean shutdown — same effect as Ctrl-C."""
    os.kill(os.getpid(), signal.SIGINT)
    return 'Shutting down…'


# ── Helpers ───────────────────────────────────────────────────────────────────


def find_open_port(prefer: int = 5000) -> int:
    # Try ports in sequence until one is not in use.
    for port in range(prefer, prefer + 100):
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    # Otherwise the functions don't see the populated contents, because new locals are created.
    global photos, photo_index  # noqa: PLW0603
    photos = [Path(p).absolute() for p in sys.argv[1:]]
    photo_index = {p.name: p for p in photos}

    if not photos:
        print('Usage: python flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg')
        return

    # Some photos already have coordinates. To indicate this, they will be 'tagged'.
    for name, path in photo_index.items():
        result = _read_gps_from_file(path)
        if result:
            coords[name] = result
    # Not within 'global' because the object is altered directly and no assignment happens.
    pre_tagged.update(coords)

    port = find_open_port()
    # Run Flask in a daemon thread so the main thread can stay free for the
    # KeyboardInterrupt that triggers the EXIF writing step.
    Thread(
        target=lambda: app.run(host='localhost', port=port, debug=False),
        daemon=True,
    ).start()
    webbrowser.open(f'http://localhost:{port}/')
    print(f'Serving at http://localhost:{port}/  —  Ctrl-C to stop and write EXIF tags')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    # Filter out pre_tagged photos
    to_write = {n: v for n, v in coords.items() if n not in pre_tagged}
    if not to_write:
        print('\nNo new coordinates — nothing written.')
        return

    print('\nWriting EXIF tags...')
    for name, (lat, lng) in to_write.items():
        path = photo_index[name]
        try:
            location = _reverse_geocode(lat, lng)
            city, country = location or ('', '')
            _write_exif(path, lat, lng, city, country)
            label = f'{city}, {country}' if city or country else 'location unknown'
            print(f'  ✅  {path}  ({lat:.6f}, {lng:.6f})  —  {label}')
        except Exception as exc:
            print(f'  ❌  {path}: {exc}')


if __name__ == '__main__':
    main()
