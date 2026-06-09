"""Usage: python flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg.

Flask app with a three-pane HTML/Leaflet UI.
Map click events are sent back to the server via JavaScript fetch() — no clipboard.
Coordinates are collected in memory; no EXIF writing happens here.
Press Ctrl-C to quit and print the collected dict.
"""

import socket
import sys
import time
import webbrowser
from pathlib import Path
from threading import Thread

from flask import Flask, jsonify, render_template_string, request, send_file

from template import TEMPLATE_HTML

app = Flask(__name__)

photos = [Path(p).absolute() for p in sys.argv[1:]]
# Keyed by filename (not absolute Path!) — assumes unique basenames across the selection.
photo_index: dict[str, Path] = {p.name: p for p in photos}
# Filled incrementally as the user clicks the map; printed on exit.
coords: dict[str, tuple[float, float]] = {}

# ── Flask routes ──────────────────────────────────────────────────────────────


@app.route('/')
def index():
    # Pass only the filenames to the template; full paths stay server-side.
    return render_template_string(TEMPLATE_HTML, photos=list(photo_index))


@app.route('/photo/<name>')
def serve_photo(name):
    # Serve a photo by its basename. Only names present in photo_index are
    # accepted, so the user cannot request arbitrary filesystem paths.
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
    if not photos:
        print('Usage: python flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg')
        return

    port = find_open_port()
    # Run Flask in a daemon thread so the main thread can stay free for the
    # KeyboardInterrupt that triggers the final printout.
    Thread(
        target=lambda: app.run(host='localhost', port=port, debug=False),
        daemon=True,
    ).start()
    webbrowser.open(f'http://localhost:{port}/')
    print(f'Serving at http://localhost:{port}/  —  Ctrl-C to quit and print results')

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    # Print the result dict in a format that can be pasted directly into Python.
    if coords:
        print('\nCollected coordinates:')
        for photo, (lat, lng) in coords.items():
            print(f'  {photo_index[photo]!r}: ({lat:.6f}, {lng:.6f})')
    else:
        print('\nNo coordinates collected.')


if __name__ == '__main__':
    main()
