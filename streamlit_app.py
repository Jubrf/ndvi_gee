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

st.title("🌱 NDVI (GEE) — Classification Kermap + Sélection manuelle")


# -----------------------------------------------------------
# ✅ SESSION STATE (tout est contrôlé ici)
# -----------------------------------------------------------
for key, default in [
    ("available_dates", None),
    ("selected_date", None),
    ("image", None),
    ("date_used", None),
    ("run_analysis", False)
]:
    if key not in st.session_state:
        st.session_state[key] = default


# -----------------------------------------------------------
# ✅ UPLOAD
# -----------------------------------------------------------
uploaded = st.file_uploader("📁 Upload SHP (ZIP) ou GEOJSON", type=["zip", "geojson"])

if not uploaded:
    st.stop()   # ✅ rien ne doit se passer tant qu’il n’y a pas d’upload


# -----------------------------------------------------------
# ✅ SI UPLOAD → AFFICHAGE
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
    "Choisir le mode d'analyse",
    [
        "Dernière tuile disponible",
        "Choisir une tuile parmi celles disponibles"
    ]
)


# -----------------------------------------------------------
# ✅ LOGIQUE POUR CHAQUE MODE
# -----------------------------------------------------------

# ✅ MODE 1 : Dernière tuile dispo
if mode == "Dernière tuile disponible":

    if st.button("▶️ Lancer analyse (dernière tuile ≤ 30 jours)"):
        st.info("Recherche de la tuile...")
        img, d = get_latest_s2_image(aoi)

        if img is None:
            st.error("❌ Aucune tuile trouvée dans les 30 derniers jours.")
            st.stop()

        st.session_state.image = img
        st.session_state.date_used = d
        st.session_state.run_analysis = True


# ✅ MODE 2 : Choix manuel de la tuile
else:

    if st.button("📅 Afficher les tuiles disponibles"):
        st.info("Récupération des dates...")
        st.session_state.available_dates = get_available_s2_dates(aoi, max_days=120)

    # Une fois les dates chargées → afficher selectbox
    if st.session_state.available_dates:

        st.session_state.selected_date = st.selectbox(
            "Sélectionner une date",
            st.session_state.available_dates,
            format_func=lambda d: d.strftime("%Y-%m-%d")
        )

        if st.button("▶️ Lancer analyse avec cette tuile"):
            if st.session_state.selected_date:
                img, d = get_closest_s2_image(aoi, st.session_state.selected_date)

                if img is None:
                    st.error("❌ Aucune tuile trouvée autour de cette date.")
                    st.stop()

                st.session_state.image = img
                st.session_state.date_used = d
                st.session_state.run_analysis = True

    else:
        # STOP tant que l’utilisateur n’a pas demandé la liste
        st.stop()


# -----------------------------------------------------------
# ✅ STOPPER SI RUN PAS ACTIVÉ
# -----------------------------------------------------------
if not st.session_state.run_analysis:
    st.stop()

# STOP si image ou date manquante (évite NameError)
if st.session_state.image is None or st.session_state.date_used is None:
    st.error("❌ Aucun résultat disponible.")
    st.stop()


# -----------------------------------------------------------
# ✅ L’ANALYSE COMMENCE ICI (ET UNIQUEMENT ICI)
# -----------------------------------------------------------
st.success(f"✅ Tuile utilisée : {st.session_state.date_used}")

image = st.session_state.image
date_used = st.session_state.date_used

# NDVI & masque
ndvi = compute_ndvi(image)
veg_mask = compute_vegetation_mask(ndvi, threshold=0.25)

st.info("📊 Analyse NDVI parcelle par parcelle…")

rows = []

for i, feat in enumerate(features):
    geom = feat["geometry"]
    props = feat["properties"]
    num_ilot = props.get("NUM_ILOT", f"ILOT_{i+1}")

    ndvi_mean, veg_prop = zonal_stats_ndvi(ndvi, veg_mask, geom)

    # Classification
    def classify(nd):
        if nd is None: return ("Indéterminé", "#bdbdbd")
        if nd < 0.25: return ("Sol nu", "#d73027")
        if nd < 0.50: return ("Végétation faible", "#fee08b")
        return ("Végétation dense", "#1a9850")

    classe_txt, classe_color = classify(ndvi_mean)
    couvert = "✅ Couvert (≥ 50%)" if (veg_prop and veg_prop >= 0.5) else "❌ Non couvert"

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
st.subheader("🗺️ Carte NDVI — Classification Kermap")

m = folium.Map(
    location=[(miny + maxy)/2, (minx + maxx)/2],
    zoom_start=14
)

def color(nd):
    if nd is None: return "#bdbdbd"
    if nd < 0.25: return "#d73027"
    if nd < 0.50: return "#fee08b"
    return "#1a9850"

for i, feat in enumerate(features):
    geom = feat["geometry"]
    ndvi_val = df.iloc[i]["NDVI_moyen"]

    folium.GeoJson(
        geom.__geo_interface__,
        style_function=lambda x, nd=ndvi_val: {
            "fillColor": color(nd),
            "color": "black",
            "weight": 1,
            "fillOpacity": 0.7
        },
        tooltip=f"{df.iloc[i]['NUM_ILOT']} — NDVI={ndvi_val:.2f} — {df.iloc[i]['Classe']}"
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
