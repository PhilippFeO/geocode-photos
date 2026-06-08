"""Usage: streamlit run src/streamlit_set_GPSIFD.py -- foto1.jpg foto2.jpg.

Three-pane UI: photo list (sidebar) | photo preview | map.
Click the map to assign GPS coordinates to the selected photo.
Coordinates are collected in session state; no EXIF writing happens here.
"""

import sys
from pathlib import Path

import folium
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(layout='wide', page_title='GPS EXIF Setter')

photos = [Path(p).absolute() for p in sys.argv[1:]]
if not photos:
    st.error(
        'Pass photo paths as arguments: '
        'streamlit run src/streamlit_set_GPSIFD.py -- foto1.jpg foto2.jpg',
    )
    st.stop()

if 'coords' not in st.session_state:
    st.session_state.coords: dict[str, tuple[float, float]] = {}

# ── Photo list (sidebar) ──────────────────────────────────────────────────────
st.sidebar.title('Photos')
names = [p.name for p in photos]
selected_name = st.sidebar.radio(
    'Select photo',
    names,
    label_visibility='collapsed',
    format_func=lambda n: (
        f'✓ {n}' if str(photos[names.index(n)]) in st.session_state.coords else n
    ),
)
selected_photo = photos[names.index(selected_name)]
selected_key = str(selected_photo)

# ── Main layout: image (left) | map (right) ───────────────────────────────────
col_img, col_map = st.columns(2)

with col_img:
    coord = st.session_state.coords.get(selected_key)
    caption = f'{coord[0]:.6f}, {coord[1]:.6f}' if coord else 'no coordinates yet'
    st.caption(f'**{selected_photo.name}** — {caption}')
    st.image(str(selected_photo), width='stretch')

with col_map:
    stored = st.session_state.coords.get(selected_key)
    center = list(stored) if stored else [48.5, 9.0]
    zoom = 12 if stored else 6

    m = folium.Map(location=center, zoom_start=zoom)
    m.add_child(folium.LatLngPopup())
    if stored:
        folium.Marker(location=list(stored), tooltip='stored position').add_to(m)

    # key changes with selected photo so the map recenters when switching photos
    result = st_folium(
        m,
        use_container_width=True,
        # width='stretch',
        height=500,
        key=f'map_{selected_key}',
    )

    if result.get('last_clicked'):
        lat = result['last_clicked']['lat']
        lng = result['last_clicked']['lng']
        if stored != (lat, lng):
            st.session_state.coords[selected_key] = (lat, lng)
            st.rerun()

# ── Collected coordinates ─────────────────────────────────────────────────────
if st.session_state.coords:
    st.divider()
    st.write('Collected coordinates:')
    for path, (lat, lng) in st.session_state.coords.items():
        st.write(f'- `{Path(path).name}`: {lat:.6f}, {lng:.6f}')
