import streamlit as st
import folium
import pandas as pd
from shapely.geometry import shape
from streamlit_folium import st_folium
import datetime
import ee

from utils.vector_io import load_vector
from utils.gee_ndvi import (
    init_gee,
    get_latest_s2_image,
    get_available_s2_dates,
    get_closest_s2_image,
    compute_ndvi,
    compute_vegetation_mask
)
from utils.ndvi_processing import zonal_stats_ndvi


# -----------------------------------------------------------
# ✅ INIT GEE
# -----------------------------------------------------------
service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
private_key = st.secrets["GEE_PRIVATE_KEY"]
init_gee(service_account, private_key)

st.title("🌱 Analyse NDVI (1 date) & Comparateur NDVI (2 dates)")


# -----------------------------------------------------------
# ✅ SESSION STATE
# -----------------------------------------------------------
DEFAULTS = {
    "available_dates_A": None,
    "available_dates_B": None,

    "imageA": None,
    "dateA": None,
    "run_A": False,

    "imageB": None,
    "dateB": None,
    "run_B": False,

    "image_single": None,
    "date_single": None,
    "run_single": False,

    "run_comparison": False,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -----------------------------------------------------------
# ✅ SIDEBAR — choix du mode
# -----------------------------------------------------------
analyse_mode = st.sidebar.radio(
    "Mode d'analyse",
    ["Analyse simple (1 date)", "Comparaison entre 2 dates"]
)


# -----------------------------------------------------------
# ✅ UPLOAD
# -----------------------------------------------------------
uploaded = st.file_uploader("📁 Upload SHP (ZIP) ou GEOJSON", type=["zip", "geojson"])

if not uploaded:
    st.stop()

features = load_vector(uploaded)
st.success(f"{len(features)} parcelles chargées ✅")

# BBOX
geoms = [f["geometry"] for f in features]
minx = min(g.bounds[0] for g in geoms)
miny = min(g.bounds[1] for g in geoms)
maxx = max(g.bounds[2] for g in geoms)
maxy = max(g.bounds[3] for g in geoms)
