import streamlit as st
import folium
import pandas as pd
from shapely.geometry import shape
from streamlit_folium import st_folium
from branca.element import Template, MacroElement
import datetime
import ee
import os

# ================================================================
# ✅ IMPORTS UTILS
# ================================================================
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


# ================================================================
# ✅ INITIALISATION GEE
# ================================================================
service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
private_key = st.secrets["GEE_PRIVATE_KEY"]
init_gee(service_account, private_key)

st.title("🌱 NDVI – Analyse simple & Comparateur NDVI 2 dates")


# ================================================================
# ✅ MODULE DE SAUVEGARDE CSV
# ================================================================
def ensure_history_dir():
    if not os.path.exists("history"):
        os.makedirs("history")

def save_dataframe(df, filename, save_name, meta=None):
    ensure_history_dir()
    path = os.path.join("history", filename)

    df2 = df.copy()
    df2["save_name"] = save_name

    if meta:
        for k, v in meta.items():
            df2[k] = v

    if os.path.exists(path):
        df2.to_csv(path, mode="a", header=False, index=False)
    else:
        df2.to_csv(path, mode="w", header=True, index=False)

def load_history(filename):
    path = os.path.join("history", filename)
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


# ================================================================
# ✅ SESSION STATE
# ================================================================
DEFAULTS = {
    "available_dates_single": None,
    "available_dates_A": None,
    "available_dates_B": None,

    "image_single": None,
    "date_single": None,

    "imageA": None,
    "dateA": None,
    "run_A": False,

    "imageB": None,
    "dateB": None,
    "run_B": False,

    "run_comparison": False
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ================================================================
# ✅ SIDEBAR : choix du mode
# ================================================================
analyse_mode = st.sidebar.radio(
    "Mode d'analyse",
    [
        "Analyse simple (1 date)",
        "Comparaison entre 2 dates",
        "📚 Mémoire"
    ]
)


# ================================================================
# ✅ UPLOAD SIG
# ================================================================
uploaded = st.file_uploader("📁 Charger un SHP (ZIP) ou GEOJSON", type=["zip", "geojson"])

if not uploaded:
    st.stop()

features = load_vector(uploaded)
st.success(f"{len(features)} parcelles chargées ✅")

geoms = [f["geometry"] for f in features]
minx = min(g.bounds[0] for g in geoms)
miny = min(g.bounds[1] for g in geoms)
maxx = max(g.bounds[2] for g in geoms)
maxy = max(g.bounds[3] for g in geoms)

aoi = ee.Geometry.Rectangle([minx, miny, maxx, maxy])


# ================================================================
# ✅ CLASSIFICATIONS
# ================================================================
def classify_ndvi(nd):
    if nd is None: return ("Indéterminé", "#bdbdbd")
    if nd < 0.25: return ("Sol nu", "#d73027")
    if nd < 0.50: return ("Végétation faible", "#fee08b")
    return ("Végétation dense", "#1a9850")

def classify_delta(delta):
    if delta is None: return ("Indéterminé", "#bdbdbd")
    if delta < -0.10: return ("Baisse", "#d73027")
