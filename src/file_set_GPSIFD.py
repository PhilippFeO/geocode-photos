"""Usage: python src/file_set_GPSIFD.py [a.jpg ...].

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
import webbrowser
from pathlib import Path

import yaml

from helper import (
    add_gps_pos_to_exif,
    create_map,
    get_fotos,
    lat_lng_from_clipboard,
    write_map_to_tmpfile,
)

data = yaml.safe_load(Path('logging.config').read_text())
logging.config.dictConfig(data)
logger = logging.getLogger(__name__)


def main():
    # ─── Erstelle und öffne Karte ──────────
    m = create_map()
    tf_name = write_map_to_tmpfile(m)
    webbrowser.open(tf_name)

    # ─── Schreibe Koordianten in EXIF-Daten ──────────
    lat, lng = lat_lng_from_clipboard()
    jpgs = get_fotos()
    add_gps_pos_to_exif(lat, lng, jpgs)
