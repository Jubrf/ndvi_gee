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
# ✅ INITIALISATION GEE
# -----------------------------------------------------------
service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
private_key = st.secrets["GEE_PRIVATE_KEY"]
init_gee(service_account, private_key)

st.title("🌱 NDVI (GEE) — Classification Kermap + Sélection manuelle des tuiles")

uploaded = st.file_uploader("📁 Upload SHP (ZIP) ou GEOJSON", type=["zip", "geojson"])


# -----------------------------------------------------------
# ✅ Classification type Kermap
# -----------------------------------------------------------
def classify_ndvi(ndvi):
    if ndvi is None:
        return ("Indéterminé", "#bdbdbd")
    if ndvi < 0.25:
        return ("Sol nu", "#d73027")
    elif ndvi < 0.50:
        return ("Végétation faible", "#fee08b")
    else:
        return ("Végétation dense", "#1a9850")


def couvert_status(veg_prop):
    if veg_prop is None:
        return "Indéterminé"
    return "✅ Couvert (≥ 50%)" if veg_prop >= 0.5 else "❌ Non couvert (< 50%)"


def colorize_kermap(ndvi):
    if ndvi is None:
        return "#bdbdbd"
    if ndvi < 0.25:
        return "#d73027"
    elif ndvi < 0.50:
        return "#fee08b"
    else:
        return "#1a9850"


# -----------------------------------------------------------
# ✅ SESSION STATE (évite la perte de sélection)
# -----------------------------------------------------------
if "available_dates" not in st.session_state:
    st.session_state.available_dates = None

if "selected_date" not in st.session_state:
    st.session_state.selected_date = None

if "run_analysis" not in st.session_state:
    st.session_state.run_analysis = False


# -----------------------------------------------------------
# ✅ MAIN
# -----------------------------------------------------------
if uploaded:

    features = load_vector(uploaded)
    st.success(f"{len(features)} parcelles chargées ✅")

    # BBOX globale
    all_geoms = [f["geometry"] for f in features]
    minx = min(g.bounds[0] for g in all_geoms)
    miny = min(g.bounds[1] for g in all_geoms)
    maxx = max(g.bounds[2] for g in all_geoms)
    maxy = max(g.bounds[3] for g in all_geoms)

    aoi = ee.Geometry.Rectangle([minx, miny, maxx, maxy])

    # ----------------------
    # ✅ Choix du mode
    # ----------------------
    mode = st.radio(
        "Choisir le mode d'analyse",
        [
            "Dernière tuile disponible",
            "Choisir une tuile parmi celles disponibles"
        ]
    )


    # ===============================================================
    # ✅ MODE : DERNIÈRE TUILE DISPONIBLE
    # ===============================================================
    if mode == "Dernière tuile disponible":

        if st.button("▶️ Lancer l’analyse (dernière tuile ≤ 30 jours)"):
            st.session_state.run_analysis = True
            image, date_used = get_latest_s2_image(aoi)

            if image is None:
                st.error("❌ Aucune tuile trouvée dans les 30 derniers jours.")
                st.stop()


    # ===============================================================
    # ✅ MODE : TUILE CHOISIE PARMI CELLES DISPONIBLES
    # ===============================================================
    else:

        if st.button("📅 Afficher les tuiles disponibles"):
            st.info("Récupération des dates Sentinel‑2…")
            st.session_state.available_dates = get_available_s2_dates(aoi, max_days=120)

        # afficher la liste si déjà récupérée
        if st.session_state.available_dates:

            st.session_state.selected_date = st.selectbox(
                "Sélectionnez une date",
                st.session_state.available_dates,
                format_func=lambda d: d.strftime("%Y-%m-%d")
            )

            if st.button("▶️ Lancer l’analyse avec cette tuile"):
                st.session_state.run_analysis = True
                image, date_used = get_closest_s2_image(aoi, st.session_state.selected_date)

                if image is None:
                    st.error("❌ Aucune tuile trouvée autour de cette date.")
                    st.stop()
        else:
            st.stop()


    # -----------------------------------------------------------
    # ✅ STOP si RUN non cliqué
    # -----------------------------------------------------------
    if not st.session_state.run_analysis:
        st.stop()


    # -----------------------------------------------------------
    # ✅ Vérification & Calcul NDVI
    # -----------------------------------------------------------
    st.success(f"✅ Tuile utilisée : {date_used}")

    ndvi = compute_ndvi(image)
    veg_mask = compute_vegetation_mask(ndvi, threshold=0.25)

    st.info("📊 Analyse NDVI parcelle par parcelle…")

    rows = []

    for i, feat in enumerate(features):
        geom = feat["geometry"]
        props = feat["properties"]
        num_ilot = props.get("NUM_ILOT", f"ILOT_{i+1}")

        ndvi_mean, veg_prop = zonal_stats_ndvi(ndvi, veg_mask, geom)

        classe_txt, classe_color = classify_ndvi(ndvi_mean)
        couvert = couvert_status(veg_prop)

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
    # ✅ Carte NDVI
    # -----------------------------------------------------------
    st.subheader("🗺️ Carte NDVI — Classification Kermap")

    m = folium.Map(
        location=[(miny + maxy)/2, (minx + maxx)/2],
        zoom_start=14
    )

    for i, feat in enumerate(features):
        geom = feat["geometry"]
        ndvi_val = df.iloc[i]["NDVI_moyen"]

        folium.GeoJson(
            geom.__geo_interface__,
            style_function=lambda x, ndvi=ndvi_val: {
                "fillColor": colorize_kermap(ndvi),
                "color": "black",
                "weight": 1,
                "fillOpacity": 0.7
            },
            tooltip=(
                f"{df.iloc[i]['NUM_ILOT']} — NDVI={ndvi_val:.2f} — "
                f"{df.iloc[i]['Classe']} — {df.iloc[i]['Couvert']}"
            )
        ).add_to(m)

    st_folium(m, height=600)

    # -----------------------------------------------------------
    # ✅ Export CSV
    # -----------------------------------------------------------
    st.download_button(
        "📥 Télécharger CSV",
        df.to_csv(index=False).encode(),
        "ndvi_par_parcelle_kermap.csv"
    )
