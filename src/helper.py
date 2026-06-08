import logging
import logging.config
import mimetypes
import shutil
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING

import clipboard
import folium
import piexif
import yaml
from folium.plugins import MousePosition
from PIL import Image

if TYPE_CHECKING:
    from collections.abc import Iterable

data = yaml.safe_load(
    (Path.home() / 'programmieren/set_GPSIFD/logging.config').read_text(),
)
logging.config.dictConfig(data)
logger = logging.getLogger('flask_set_GPSIFD')


def create_map() -> folium.Map:
    m = folium.Map(
        location=[0, 0],
        zoom_start=6,
        tiles='OpenStreetMap',
    )
    # TODO(Philipp): Vorauswahl an Orten <03-05-2026>  # noqa: FIX002, TD003
    # m.add_child(folium.ClickForMarker())
    m.add_child(MousePosition())
    m.add_child(folium.LatLngPopup())
    m.add_child(
        folium.ClickForLatLng(
            format_str='lat + "|" + lng',
            alert=False,
        ),
    )
    # folium.TileLayer(
    #     tiles='https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    #     attr="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors",
    #     # referrer_policy='strict-origin',
    # ).add_to(m)
    # folium.TileLayer(
    #     'https://tileserver.memomaps.de/tilegen/{z}/{x}/{y}.png',
    #     maxZoom=18,
    #     attr='Map <a href="https://memomaps.de/">memomaps.de</a> <a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    # )
    return m


def lat_lng_from_clipboard() -> tuple[float, float]:
    lat, lng = sys.float_info.max, sys.float_info.max
    clipboard.copy('')
    while clipboard.paste() == '':
        time.sleep(0.5)
        try:
            lat, lng = map(float, clipboard.paste().split('|'))
        except ValueError:
            logger.debug(
                {
                    'message': 'Failed converting clipboard into Lat-Lng-Coordinates.',
                    'clipboard': clipboard.paste(),
                },
            )
            continue
        logger.info(
            {
                'message': f'Selected Coordinates: {lat}, {lng}.',
                'lat': lat,
                'lng': lng,
            },
        )
        # if input('Neue Koordinaten auswählen [y/n]? ') == 'y':
        #     clipboard.copy('')
    assert lat != sys.maxsize != lng
    return lat, lng


def write_map_to_tmpfile(m: folium.Map):
    tf_name = ''
    with tempfile.NamedTemporaryFile(
        prefix='GPSPos_setzen_',
        suffix='.html',
        delete=False,
        delete_on_close=False,
    ) as tf:
        tf_name = tf.name
        m.save(tf_name)
    logger.debug(
        {
            'message': 'Karte gespeichert.',
            'tf_name': tf_name,
        },
    )
    return tf_name


def get_fotos(paths: 'Iterable[str]') -> list[Path]:
    """Filter out Fotos with corresponding GPS Tags in their EXIF data."""
    files = [Path(f).absolute() for f in paths]
    jpgs_candidates: list[Path] = [f for f in files if f.is_file()]
    jpgs_without_gps_pos: list[Path] = []
    jpgs_with_gps_pos: list[Path] = []
    for jpg in files:
        mt, _ = mimetypes.guess_type(jpg)
        assert mt is not None
        if mt.lower().split('/')[0] in ('image', 'video'):
            img = Image.open(jpg)
            gps_exif = piexif.load(img.info.get('exif', b''))['GPS']
            img.close()
            # If GPS Pos information is complete, skip foto, …
            if (
                piexif.GPSIFD.GPSLatitude in gps_exif
                and piexif.GPSIFD.GPSLatitudeRef in gps_exif
                and piexif.GPSIFD.GPSLongitude in gps_exif
                and piexif.GPSIFD.GPSLongitudeRef in gps_exif
            ):
                jpgs_with_gps_pos.append(jpg)
            # …ie. only collect fotos without valid GPS Position information
            else:
                jpgs_without_gps_pos.append(jpg)
    if len(jpgs_candidates) == 0 == len(jpgs_without_gps_pos):
        logger.info({'message': 'No JPGs found or no JPGs without GPS Position found.'})
        sys.exit(0)
    logger.info(
        {
            'message': 'Selected Fotos from Selection without proper GPS EXIF data.',
            'fotos without GPS IFD': jpgs_without_gps_pos,
            'fotos with GPS IFD': jpgs_with_gps_pos,
        },
    )
    return jpgs_without_gps_pos


def add_gps_pos_to_exif(
    lat: float,
    lng: float,
    jpgs: 'Iterable[Path]',
):
    log_defaults = {
        'lat': lat,
        'lng': lng,
    }
    logger.info(
        log_defaults
        | {
            'message': 'Write GPS data to EXIF...',
            'fotos': jpgs,
        },
    )
    try:
        for p in jpgs:
            set_gps_on_file(p, lat, lng, make_backup=True)
    except Exception:
        logger.exception(
            log_defaults
            | {
                'message': 'Writing GPS EXIF data failed.',
                'image': p,
            },
        )


def set_gps_on_file(
    jpg: Path,
    lat: float,
    lng: float,
    *,
    make_backup: bool,
):
    backup_path = jpg.with_name(jpg.name + '.bak')
    if make_backup and not backup_path.exists():
        shutil.copy2(jpg, backup_path)
        img = Image.open(jpg)
        # In case try-except is needed: exif_dict = {'0th': {}, 'Exif': {}, 'GPS': {}, '1st': {}, 'thumbnail': None}
        exif_dict = piexif.load(img.info.get('exif', b''))
        gps_ifd = make_gps_exif(lat, lng)
        exif_dict['GPS'].update(gps_ifd)
        exif_bytes = piexif.dump(exif_dict)
        img.save(jpg, 'jpeg', exif=exif_bytes)
        img.close()
        logger.info(
            {
                'message': 'GPS EXIF data written successfully.',
                'image': jpg,
            },
        )
    else:
        logger.info(
            {
                'message': 'GPS data not set on JPG. Either `make_backup` is `False` or `backup_path` already exists.',
                'jpg': jpg,
                'lat': lat,
                'lng': lng,
                'make_backup': make_backup,
                'backup_path': backup_path,
                'backup_path_exists': backup_path.exists(),
            },
        )


def make_gps_exif(lat: float, lng: float):
    """Transform GPS Coordinates into EXIF format."""
    # lat, lng in decimal degrees
    lat_ref = 'N' if lat >= 0 else 'S'
    lon_ref = 'E' if lng >= 0 else 'W'
    lat_dms = _deg_to_dms_rational(lat)
    lon_dms = _deg_to_dms_rational(lng)

    return {
        piexif.GPSIFD.GPSLatitudeRef: lat_ref.encode(),
        piexif.GPSIFD.GPSLatitude: lat_dms,
        piexif.GPSIFD.GPSLongitudeRef: lon_ref.encode(),
        piexif.GPSIFD.GPSLongitude: lon_dms,
    }


def _deg_to_dms_rational(deg_float):
    """Convert Degree to 'Degree Minute Seconds'."""
    # deg_float can be negative
    deg = int(abs(deg_float))
    minutes_float = (abs(deg_float) - deg) * 60
    minutes = int(minutes_float)
    seconds = round((minutes_float - minutes) * 60, 6)

    def to_rational(number):
        """Convert float to rational tuple (nom, den)."""
        f = Fraction(str(number)).limit_denominator(1000000)
        return (f.numerator, f.denominator)

    return (to_rational(deg), to_rational(minutes), to_rational(seconds))
