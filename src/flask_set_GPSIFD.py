"""Usage: python src/flask_set_GPSIFD.py [a.jpg ...].

Starts a local webserver and map. Click on the map to choose a location.
After selecting, the script will write GPS EXIF tags into all provided JPG files.


Vielleicht irgendwann mal interessant:
    - `Marker(draggable=True)`; Nachteil: Man muss ihn manuell ziehen, was nervig ist und in Vergrößerungs-Zieh-Schleifen endet.
    - https://gist.github.com/wrobstory/5609762
    - https://stackoverflow.com/questions/67628175/how-to-copy-a-markers-location-on-folium-map-by-clicking-on-it
    - https://github.com/randyzwitch/streamlit-folium/issues/122
"""

import logging
import logging.config
import socket
import sys
import webbrowser
from pathlib import Path
from threading import Thread

import yaml
from flask import Flask, send_file
from helper import (
    add_gps_pos_to_exif,
    create_map,
    get_fotos,
    lat_lng_from_clipboard,
    write_map_to_tmpfile,
)

data = yaml.safe_load(
    (Path.home() / 'programmieren/set_GPSIFD/logging.config').read_text(),
)
logging.config.dictConfig(data)
logger = logging.getLogger('flask_set_GPSIFD')

app = Flask('flask_set_GPSIFD')


def run_server(port):
    app.run(host='localhost', port=port, debug=False)


def find_open_port(prefer=5000):
    s = socket.socket()
    for p in range(prefer, prefer + 100):
        try:
            s.bind(('127.0.0.1', p))
            s.close()
        except OSError:  # noqa: PERF203
            continue
        else:
            return p
    s.close()
    return 0


@app.route('/')
def index():
    m = create_map()
    map_file_name = write_map_to_tmpfile(m)
    return send_file(map_file_name)


def main():
    # ─── Erstelle und öffne Karte ──────────
    selected_fotos = sys.argv[1:]
    logger.info(
        {
            'message': 'Conduct operation using Flask.',
            'selected_fotos': selected_fotos,
        },
    )
    port = find_open_port()
    t = Thread(target=run_server, args=(port,), daemon=True)
    t.start()
    webbrowser.open(f'localhost:{port}/')

    # ─── Schreibe Koordianten in EXIF-Daten ──────────
    lat, lng = lat_lng_from_clipboard()
    jpgs = get_fotos(selected_fotos)
    add_gps_pos_to_exif(lat, lng, jpgs)


if __name__ == '__main__':
    main()
