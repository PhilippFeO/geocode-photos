"""Usage: python flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg.

Flask app with a three-pane HTML/Leaflet UI.
Map click events are sent back to the server via JavaScript fetch() — no clipboard.
Press Ctrl-C to stop the server; GPS + location EXIF tags are then written via exiftool.
A .bak copy is created next to each file before its first write.
"""

import logging
import logging.config
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
import PIL
import requests
import yaml
from flask import Flask, jsonify, render_template_string, request, send_file
from PIL import Image

app = Flask(__name__)
logger = logging.getLogger('geocode')

photos: list[Path] = []

# Keyed by filename (not absolute Path!) — assumes unique basenames across the selection.
photo_index: dict[str, Path] = {}
coords: dict[str, tuple[float, float]] = {}
"""Filled incrementally as the user clicks the map; written to EXIF on exit."""
pre_tagged: set[str] = set()
"""Photos already carrying coordinates — skipped when writing EXIF metadata."""


def _setup_logging() -> None:
    config_path = Path(__file__).parent / 'logging.yaml'
    with config_path.open() as f:
        logging.config.dictConfig(yaml.safe_load(f))


# ── EXIF helpers ──────────────────────────────────────────────────────────────


def _read_gps_from_file(photo: Path) -> tuple[float, float] | None:
    """Return (lat, lng) from a file's GPS EXIF, or None if absent/unreadable."""
    logger.debug(msg='Read GPS from file.', extra={'photo': photo})
    try:
        img = Image.open(photo)
        gps = piexif.load(img.info.get('exif', b'')).get('GPS', {})
        img.close()
        if (
            piexif.GPSIFD.GPSLatitude not in gps
            or piexif.GPSIFD.GPSLongitude not in gps
        ):
            logger.info(
                msg='No GPS info attached to photo.',
                extra={
                    'photo': photo,
                },
            )
            return None

        def dms_to_deg(dms):
            return sum(
                r[0] / r[1] / factor
                for r, factor in zip(dms, (1, 60, 3600), strict=False)
            )

        lat = dms_to_deg(gps[piexif.GPSIFD.GPSLatitude])
        lng = dms_to_deg(gps[piexif.GPSIFD.GPSLongitude])
        if gps.get(piexif.GPSIFD.GPSLatitudeRef, b'N') in (b'S', 'S'):
            lat = -lat
        if gps.get(piexif.GPSIFD.GPSLongitudeRef, b'E') in (b'W', 'W'):
            lng = -lng
    except (PIL.UnidentifiedImageError, FileNotFoundError):
        logger.warning(msg='Could not read GPS EXIF.', extra={'photo': str(photo)})
        return None
    else:
        logger.info(
            msg='Coordinates red from photo and transformed.',
            extra={
                'photo': photo,
                'lat': lat,
                'lng': lng,
            },
        )
        return lat, lng


def _reverse_geocode(lat: float, lng: float) -> dict | None:
    """Return address fields from Nominatim, or None on failure."""
    logger.debug(
        msg='Start reverse geocoding.',
        extra={'lat': lat, 'lng': lng},
    )
    try:
        r = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={
                'lat': lat,
                'lon': lng,
                # geocodejson also available.
                'format': 'json',
            },
            headers={
                'User-Agent': 'geocoding_photos/1.0',
                'Accept-Language': 'de, en;q=0.9',
            },
            timeout=10,
        )
        addr = r.json().get('address', {})
        logger.debug(
            msg='Nominatim API call successful.',
        )
        return {
            'city': addr.get('city') or addr.get('town') or addr.get('village', ''),
            'state': addr.get('state') or addr.get('county', ''),
            'country': addr.get('country', ''),
            'country_code': addr.get('country_code', '').upper(),
            # filter(None, ...) drops falsy entries (None, ''): when None is passed,
            # filter substitutes `lambda x: x` internally. Since filter only evaluates
            # the return value as a boolean (keep/discard), and bool(x) and x yield the
            # same boolean outcome, None effectively acts as `lambda x: bool(x)`.
            'sub_location': ', '.join(
                filter(
                    None,
                    [
                        addr.get('amenity')
                        or addr.get('building')
                        or addr.get('tourism'),
                        # Drop missing parts before joining so 'Hauptstraße None' can't happen.
                        ' '.join(
                            filter(
                                None,
                                [
                                    addr.get('road'),
                                    addr.get('house_number'),
                                ],
                            ),
                        ),
                        addr.get('suburb')
                        or addr.get('neighbourhood')
                        or addr.get('quarter'),
                    ],
                ),
            ),
        }
    except requests.exceptions.Timeout:
        logger.warning(
            msg='Nominatim request timed out.',
            extra={
                'lat': lat,
                'lng': lng,
            },
        )
        return None


def _write_exif(
    photo: Path,
    lat: float,
    lng: float,
    city: str,
    state: str,
    country: str,
    country_code: str,
    sub_location: str,
) -> None:
    # Bare tag names (no IPTC:/XMP- prefix) let exiftool write both IPTC and
    # XMP-photoshop in one pass, keeping both metadata blocks in sync.
    logger.info(
        msg='Writing EXIF',
        extra={
            'photo': str(photo),
            'lat': lat,
            'lng': lng,
            'city': city,
            'state': state,
            'country_code': country_code,
            'country': country,
            'sub_location': sub_location,
        },
    )
    subprocess.run(
        [
            '/usr/bin/exiftool',
            f'-GPSLatitude={abs(lat)}',
            f'-GPSLatitudeRef={"N" if lat >= 0 else "S"}',
            f'-GPSLongitude={abs(lng)}',
            f'-GPSLongitudeRef={"E" if lng >= 0 else "W"}',
            f'-City={city}',
            f'-Province-State={state}',
            f'-Country-PrimaryLocationName={country}',
            f'-Country-PrimaryLocationCode={country_code}',
            f'-Sub-location={sub_location}',
            '-overwrite_original',
            str(photo),
        ],
        check=True,
        capture_output=True,
    )


# ── Flask routes ──────────────────────────────────────────────────────────────


@app.route('/')
def index():
    # Pass only the filenames to the template; full paths stay server-side.
    return render_template_string(
        (
            Path.home() / Path('programmieren/geocoding-photos/template.html')
        ).read_text(),
        photos=list(photo_index),
    )


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
        logger.info(
            msg='Coords received',
            extra={
                'photo': photo,
                'lat': body['lat'],
                'lng': body['lng'],
            },
        )
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
            except OSError:
                continue
            else:
                return port
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────


def main():
    _setup_logging()
    # Otherwise the functions don't see the populated contents, because new locals are created.
    global photos, photo_index  # noqa: PLW0603
    photos = [Path(p).absolute() for p in sys.argv[1:]]
    photo_index = {p.name: p for p in photos}

    if not photos:
        logger.error(
            msg='No photos provided',
            extra={'usage': 'python geocode.py foto1.jpg foto2.jpg'},
        )
        return

    # Some photos already have coordinates. To indicate this, they will be 'tagged'.
    for name, photo in photo_index.items():
        result = _read_gps_from_file(photo)
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
    logger.info(
        msg='Server started',
        extra={'url': f'http://localhost:{port}/', 'photos': len(photos)},
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    # Filter out pre_tagged photos. Their GSP coords were not updated and don't have to be written (again).
    to_write = {n: v for n, v in coords.items() if n not in pre_tagged}
    if not to_write:
        logger.info(msg='No new coordinates — nothing written')
        return

    logger.info(msg='Writing EXIF tags', extra={'count': len(to_write)})
    for name, (lat, lng) in to_write.items():
        photo = photo_index[name]
        try:
            location = _reverse_geocode(lat, lng) or {}
            city = location.get('city', '')
            state = location.get('state', '')
            country = location.get('country', '')
            country_code = location.get('country_code', '')
            sub_location = location.get('sub_location', '')
            _write_exif(
                photo,
                lat,
                lng,
                city,
                state,
                country,
                country_code,
                sub_location,
            )
            label = f'{city}, {country}' if city or country else 'location unknown'
            logger.info(
                msg='EXIF written',
                extra={
                    'photo': str(photo),
                    'lat': lat,
                    'lng': lng,
                    'label': label,
                },
            )
        except Exception as exc:
            logger.exception(
                msg='Failed to write EXIF',
                extra={'photo': str(photo), 'error': str(exc)},
            )


if __name__ == '__main__':
    main()
