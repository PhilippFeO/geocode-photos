"""Usage: python flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg.

Flask app with a three-pane HTML/Leaflet UI.
Map click events are sent back to the server via JavaScript fetch() — no clipboard.
Press Ctrl-C to stop the server; GPS EXIF tags are then written to all tagged photos.
A .bak copy is created next to each file before its first write.
"""

import shutil
import socket
import sys
import time
import webbrowser
from fractions import Fraction
from pathlib import Path
from threading import Thread

import piexif
import PIL
from flask import Flask, jsonify, render_template_string, request, send_file
from PIL import Image

from template import TEMPLATE_HTML

app = Flask(__name__)

photos: list[Path] = []
# Keyed by filename (not absolute Path!) — assumes unique basenames across the selection.
photo_index: dict[str, Path] = {}
# Filled incrementally as the user clicks the map; printed on exit.
coords: dict[str, tuple[float, float]] = {}
# Fotos already carrying coordinates. Are skipped when writing EXIF metadata.
pre_tagged: set[str] = set()

# ── EXIF helpers ──────────────────────────────────────────────────────────────


def _deg_to_dms_rational(deg_float):
    deg = int(abs(deg_float))
    minutes_float = (abs(deg_float) - deg) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60, 6)

    def to_rational(n):
        f = Fraction(str(n)).limit_denominator(1_000_000)
        return (f.numerator, f.denominator)

    return (to_rational(deg), to_rational(minutes), to_rational(seconds))


def _make_gps_exif(lat: float, lng: float) -> dict:
    return {
        piexif.GPSIFD.GPSLatitudeRef: (b'N' if lat >= 0 else b'S'),
        piexif.GPSIFD.GPSLatitude: _deg_to_dms_rational(lat),
        piexif.GPSIFD.GPSLongitudeRef: (b'E' if lng >= 0 else b'W'),
        piexif.GPSIFD.GPSLongitude: _deg_to_dms_rational(lng),
    }


def _write_gps_to_file(path: Path, lat: float, lng: float) -> None:
    backup = path.with_name(path.name + '.bak')
    if not backup.exists():
        shutil.copy2(path, backup)
    img = Image.open(path)
    exif_dict = piexif.load(img.info.get('exif', b''))
    exif_dict['GPS'].update(_make_gps_exif(lat, lng))
    img.save(path, 'jpeg', exif=piexif.dump(exif_dict))
    img.close()


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
        # If coordinates were updated, remove it from pre_tagged
        pre_tagged.discard(photo)
    # Return the full dict so the client could sync state on page reload if needed.
    # Currently, not used.
    return jsonify({k: list(v) for k, v in coords.items()})


@app.route('/coords', methods=['GET'])
def get_coords():
    """Open in browser or curl to inspect collected coords (Convenience endpoint)."""
    return jsonify({k: list(v) for k, v in coords.items()})


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
    # Some photos already have coordinates. To indicate this, they will be 'tagged'.
    for name, path in photo_index.items():
        result = _read_gps_from_file(path)
        if result:
            coords[name] = result
    # Not within 'global' because the object is altered directly and not assignment happens
    pre_tagged.update(coords)

    if not photos:
        print('Usage: python flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg')
        return

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

    if not coords:
        print('\nNo coordinates collected — nothing written.')
        return

    print('\nWriting GPS EXIF tags...')
    for name, (lat, lng) in coords.items():
        # Skip photos which already have coordinates
        if name in pre_tagged:
            continue
        path = photo_index[name]
        try:
            _write_gps_to_file(path, lat, lng)
            print(f'  ✅  {path}  ({lat:.6f}, {lng:.6f})')
        except (
            OSError,
            FileNotFoundError,
            PIL.UnidentifiedImageError,
            piexif.InvalidImageDataError,
            KeyError,
        ) as exc:
            print(f'  ❌  {path}: {exc}')


if __name__ == '__main__':
    main()
