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
# ✅ INITIALISATION EARTH ENGINE
# -----------------------------------------------------------
service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
private_key = st.secrets["GEE_PRIVATE_KEY"]
init_gee(service_account, private_key)

st.title("🌱 NDVI (GEE) — Classification Kermap + Sélection manuelle des tuiles")


# -----------------------------------------------------------
# ✅ SESSION STATE
# -----------------------------------------------------------
DEFAULTS = {
    "available_dates": None,
    "selected_date": None,
    "image": None,
    "date_used": None,
    "run_analysis": False,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -----------------------------------------------------------
# ✅ UPLOAD
# -----------------------------------------------------------
uploaded = st.file_uploader("📁 Upload SHP (ZIP) ou GEOJSON", type=["zip", "geojson"])

# ✅ STOP NET si aucun fichier uploadé
if not uploaded:
    st.stop()


# -----------------------------------------------------------
# ✅ LECTURE DES PARCELLES
# -----------------------------------------------------------
features = load_vector(uploaded)
st.success(f"{len(features)} parcelles chargées ✅")

# BBOX globale
all_geoms = [f["geometry"] for f in features]
minx = min(g.bounds[0] for g in all_geoms)
miny = min(g.bounds[1] for g in all_geoms)
maxx = max(g.bounds[2] for g in all_geoms)
maxy = max(g.bounds[3] for g in all_geoms)
aoi = ee.Geometry.Rectangle([minx, miny, maxx, maxy])


# -----------------------------------------------------------
# ✅ CHOIX DU MODE
# -----------------------------------------------------------
mode = st.radio(
    "Mode d'analyse",
    [
        "Dernière tuile disponible",
        "Choisir une tuile parmi celles disponibles",
        "Choisir un mois (filtre mensuel)"
    ]
)


# ============================================================
# ✅ MODE 1 : DERNIÈRE TUILE DISPONIBLE
# ============================================================
if mode == "Dernière tuile disponible":

    if st.button("▶️ Lancer analyse (dernière tuile ≤ 30 jours)"):
        img, d = get_latest_s2_image(aoi)

        if img is None:
            st.error("❌ Aucune tuile trouvée dans les 30 derniers jours.")
            st.stop()

        st.session_state.image = img
        st.session_state.date_used = d
        st.session_state.run_analysis = True


# ============================================================
# ✅ MODE 2 : CHOIX PARMI LES TUILES DISPONIBLES
# ============================================================
elif mode == "Choisir une tuile parmi celles disponibles":

    if st.button("📅 Afficher les tuiles disponibles (120 jours)"):
        st.info("Recherche des dates…")
        st.session_state.available_dates = get_available_s2_dates(aoi, max_days=120)

    if st.session_state.available_dates:

        st.session_state.selected_date = st.selectbox(
            "Sélectionnez une date",
            st.session_state.available_dates,
            format_func=lambda d: d.strftime("%Y-%m-%d")
        )

        if st.button("▶️ Lancer l’analyse sur cette tuile"):
            img, d = get_closest_s2_image(aoi, st.session_state.selected_date)

            if img is None:
                st.error("❌ Aucune tuile trouvée.")
                st.stop()

            st.session_state.image = img
            st.session_state.date_used = d
            st.session_state.run_analysis = True

    else:
        st.stop()


# ============================================================
# ✅ MODE 3 : CHOISIR UN MOIS
# ============================================================
elif mode == "Choisir un mois (filtre mensuel)":

    # Sélecteur année
    year = st.selectbox(
        "Année :",
        list(range(2017, datetime.date.today().year + 1))[::-1]
    )

    # Sélecteur mois
    month_num, month_label = st.selectbox(
        "Mois :", [
            ("01", "Janvier"), ("02", "Février"), ("03", "Mars"),
            ("04", "Avril"), ("05", "Mai"), ("06", "Juin"),
            ("07", "Juillet"), ("08", "Août"), ("09", "Septembre"),
            ("10", "Octobre"), ("11", "Novembre"), ("12", "Décembre")
        ],
        format_func=lambda x: x[1]
    )

    start = f"{year}-{month_num}-01"
    if month_num == "12":
        end = f"{int(year)+1}-01-01"
    else:
        end = f"{year}-{int(month_num)+1:02d}-01"

    # Bouton -> recherche données du mois
    if st.button("📅 Afficher les tuiles du mois"):
        st.info(f"Recherche des tuiles du mois {month_label} {year}…")

        col = (ee.ImageCollection("COPERNICUS/S2_SR")
               .filterBounds(aoi)
               .filterDate(start, end)
               .sort("system:time_start", False))

        timestamps = col.aggregate_array("system:time_start").getInfo()

        if len(timestamps) == 0:
            st.error("❌ Aucune tuile trouvée pour ce mois.")
            st.stop()

        month_dates = sorted(
            set(datetime.datetime.utcfromtimestamp(ts/1000).date() for ts in timestamps),
            reverse=True
        )

        st.session_state.available_dates = month_dates

    # Selectbox si les dates existent
    if st.session_state.available_dates:

        st.session_state.selected_date = st.selectbox(
            "Dates disponibles ce mois :",
            st.session_state.available_dates,
            format_func=lambda d: d.strftime("%Y-%m-%d")
        )

        if st.button("▶️ Lancer l’analyse du mois"):
            img, d = get_closest_s2_image(aoi, st.session_state.selected_date)

            if img is None:
                st.error("❌ Impossible de charger la tuile.")
                st.stop()

            st.session_state.image = img
            st.session_state.date_used = d
            st.session_state.run_analysis = True

    else:
        st.stop()


# -----------------------------------------------------------
# ✅ STOP SI RUN PAS ACTIVÉ
# -----------------------------------------------------------
if not st.session_state.run_analysis:
    st.stop()


# -----------------------------------------------------------
# ✅ ANALYSE NDVI
# -----------------------------------------------------------
image = st.session_state.image
date_used = st.session_state.date_used

if image is None or date_used is None:
    st.stop()

st.success(f"✅ Tuile utilisée : {date_used}")

# NDVI
ndvi = compute_ndvi(image)
veg_mask = compute_vegetation_mask(ndvi, threshold=0.25)

st.info("📊 Analyse NDVI parcelle par parcelle…")

rows = []

def classify_kermap(nd):
    if nd is None: return ("Indéterminé", "#bdbdbd")
    if nd < 0.25: return ("Sol nu", "#d73027")
    if nd < 0.50: return ("Végétation faible", "#fee08b")
    return ("Végétation dense", "#1a9850")

for i, feat in enumerate(features):
    geom = feat["geometry"]
    props = feat["properties"]
    num_ilot = props.get("NUM_ILOT", f"ILOT_{i+1}")

    ndvi_mean, veg_prop = zonal_stats_ndvi(ndvi, veg_mask, geom)

    classe_txt, classe_color = classify_kermap(ndvi_mean)
    couvert = "✅ Couvert" if (veg_prop and veg_prop >= 0.5) else "❌ Non couvert"

    rows.append({
        "NUM_ILOT": num_ilot,
        "NDVI_moyen": ndvi_mean,
        "Classe": classe_txt,
        "Proportion_couvert": veg_prop,
        "Couvert": couvert,
        "Date": str(date_used)
    })

df = pd.DataFrame(rows)

st.subheader("📋 Résultats NDVI par parcelle")
st.dataframe(df)


# -----------------------------------------------------------
# ✅ CARTE
# -----------------------------------------------------------
def colorize(nd):
    if nd is None: return "#bdbdbd"
    if nd < 0.25: return "#d73027"
    if nd < 0.50: return "#fee08b"
    return "#1a9850"

st.subheader("🗺️ Carte NDVI — classification Kermap")

m = folium.Map(location=[(miny+maxy)/2, (minx+maxx)/2], zoom_start=14)

for i, feat in enumerate(features):
    geom = feat["geometry"]
    nd = df.iloc[i]["NDVI_moyen"]

    folium.GeoJson(
        geom.__geo_interface__,
        style_function=lambda x, val=nd: {
            "fillColor": colorize(val),
            "color": "black",
            "weight": 1,
            "fillOpacity": 0.7
        },
        tooltip=f"{df.iloc[i]['NUM_ILOT']} — NDVI {nd:.2f} — {df.iloc[i]['Classe']}"
    ).add_to(m)

st_folium(m, height=600)


# -----------------------------------------------------------
# ✅ EXPORT
# -----------------------------------------------------------
st.download_button(
    "📥 Télécharger CSV",
    df.to_csv(index=False).encode(),
    "ndvi_par_parcelle_kermap.csv"
)
