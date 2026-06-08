"""Usage: python src/flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg.

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

app = Flask(__name__)

photos = [Path(p).absolute() for p in sys.argv[1:]]
# Keyed by filename — assumes unique basenames across the selection.
photo_index: dict[str, Path] = {p.name: p for p in photos}
coords: dict[str, tuple[float, float]] = {}

# ── HTML template ─────────────────────────────────────────────────────────────

TEMPLATE = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>GPS EXIF Setter</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { display: flex; height: 100vh; font-family: sans-serif; font-size: 14px; }

    #sidebar {
      width: 220px; min-width: 220px;
      display: flex; flex-direction: column;
      border-right: 1px solid #ccc; overflow-y: auto;
    }
    #sidebar h2 { padding: 10px; font-size: 14px; border-bottom: 1px solid #eee; }
    .photo-btn {
      display: block; width: 100%; text-align: left;
      padding: 7px 10px; border: none; background: none;
      cursor: pointer; border-bottom: 1px solid #f0f0f0;
    }
    .photo-btn:hover  { background: #f5f5f5; }
    .photo-btn.active { background: #ddeeff; font-weight: bold; }
    .photo-btn.tagged::after { content: " ✓"; color: #2a2; }

    #preview {
      flex: 1; display: flex; flex-direction: column;
      border-right: 1px solid #ccc; overflow: hidden;
      min-width: 0;
    }
    #status {
      padding: 6px 10px; font-size: 12px; color: #555;
      border-bottom: 1px solid #eee; white-space: nowrap; overflow: hidden;
      text-overflow: ellipsis;
    }
    #img-wrap {
      flex: 1; display: flex;
      align-items: center; justify-content: center;
      background: #1a1a1a; overflow: hidden;
    }
    #img-wrap img { max-width: 100%; max-height: 100%; object-fit: contain; }

    #map { flex: 1; min-width: 0; }
  </style>
</head>
<body>

<div id="sidebar">
  <h2>Photos</h2>
  {% for name in photos %}
  <button class="photo-btn" data-name="{{ name }}"
          onclick="selectPhoto('{{ name }}', this)">{{ name }}</button>
  {% endfor %}
</div>

<div id="preview">
  <div id="status">← Select a photo, then click the map.</div>
  <div id="img-wrap"><img id="img" src="" alt=""/></div>
</div>

<div id="map"></div>

<script>
  let current = null;
  let marker  = null;
  const stored = {};   // client-side mirror of server coords

  const map = L.map('map').setView([48.5, 9.0], 6);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  }).addTo(map);

  function selectPhoto(name, btn) {
    current = name;
    document.getElementById('img').src = '/photo/' + encodeURIComponent(name);
    document.querySelectorAll('.photo-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    if (stored[name]) {
      placeMarker(stored[name].lat, stored[name].lng);
      map.setView([stored[name].lat, stored[name].lng], 12);
    } else if (marker) {
      marker.remove();
      marker = null;
    }
    refreshStatus();
  }

  function placeMarker(lat, lng) {
    if (marker) marker.remove();
    marker = L.marker([lat, lng]).addTo(map);
  }

  function refreshStatus() {
    const el = document.getElementById('status');
    if (!current) { el.textContent = '← Select a photo, then click the map.'; return; }
    const c = stored[current];
    el.textContent = c
      ? current + '  →  ' + c.lat.toFixed(6) + ',  ' + c.lng.toFixed(6)
      : current + '  —  click the map to assign coordinates';
  }

  map.on('click', function (e) {
    if (!current) return;
    const { lat, lng } = e.latlng;
    placeMarker(lat, lng);
    stored[current] = { lat, lng };
    document.querySelector(`.photo-btn[data-name="${CSS.escape(current)}"]`)
            .classList.add('tagged');
    refreshStatus();
    fetch('/coords', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ photo: current, lat, lng }),
    });
  });
</script>

</body>
</html>
"""

# ── Flask routes ──────────────────────────────────────────────────────────────


@app.route('/')
def index():
    return render_template_string(TEMPLATE, photos=list(photo_index))


@app.route('/photo/<name>')
def serve_photo(name):
    path = photo_index.get(name)
    if path is None:
        return 'Not found', 404
    return send_file(path)


@app.route('/coords', methods=['POST'])
def receive_coords():
    body = request.get_json(force=True)
    name = body.get('photo', '')
    if name in photo_index:
        coords[name] = (float(body['lat']), float(body['lng']))
    return jsonify({k: list(v) for k, v in coords.items()})


@app.route('/coords', methods=['GET'])
def get_coords():
    return jsonify({k: list(v) for k, v in coords.items()})


# ── Helpers ───────────────────────────────────────────────────────────────────


def find_open_port(prefer: int = 5000) -> int:
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
        print('Usage: python src/flask_fetch_set_GPSIFD.py foto1.jpg foto2.jpg')
        return

    port = find_open_port()
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

    if coords:
        print('\nCollected coordinates:')
        for name, (lat, lng) in coords.items():
            print(f'  {photo_index[name]!r}: ({lat:.6f}, {lng:.6f})')
    else:
        print('\nNo coordinates collected.')


if __name__ == '__main__':
    main()
