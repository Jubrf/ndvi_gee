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
aoi = ee.Geometry.Rectangle([minx, miny, maxx, maxy])


# -----------------------------------------------------------
# ✅ CLASSIFICATION NDVI Kermap
# -----------------------------------------------------------
def classify_ndvi(nd):
    if nd is None: return ("Indéterminé", "#bdbdbd")
    if nd < 0.25: return ("Sol nu", "#d73027")
    if nd < 0.50: return ("Végétation faible", "#fee08b")
    return ("Végétation dense", "#1a9850")


def classify_delta(delta):
    if delta is None: return ("Indéterminé", "#bdbdbd")
    if delta < -0.10: return ("Baisse", "#d73027")
    if delta > 0.10: return ("Hausse", "#1a9850")
    return ("Stable", "#fee08b")


def couvert_status(p):
    if p is None:
        return "Indéterminé"
    return "✅ Couvert (≥ 50%)" if p >= 0.5 else "❌ Non couvert (< 50%)"


# -----------------------------------------------------------
# ✅ TUile selector (3 modes)
# -----------------------------------------------------------
def tuile_selector(label, date_key, dates_key):
    mode = st.radio(
        f"{label} – méthode de sélection",
        ["Dernière tuile", "Tuiles disponibles", "Recherche par mois"],
        key=f"mode_{label}"
    )

    # ------------------------
    # ✅ DERNIÈRE TUILE
    # ------------------------
    if mode == "Dernière tuile":
        if st.button(f"▶️ Charger dernière tuile ({label})"):
            img, d = get_latest_s2_image(aoi)
            return img, d
        return None, None

    # ------------------------
    # ✅ LISTE DES TUILES
    # ------------------------
    if mode == "Tuiles disponibles":

        if st.button(f"📅 Afficher tuiles ({label})"):
            st.session_state[dates_key] = get_available_s2_dates(aoi, 120)

        if st.session_state.get(dates_key):
            chosen = st.selectbox(
                f"Dates ({label})",
                st.session_state[dates_key],
                format_func=lambda d: d.strftime("%Y-%m-%d"),
                key=f"sel_{label}"
            )

            if st.button(f"▶️ Charger cette date ({label})"):
                img, d = get_closest_s2_image(aoi, chosen)
                return img, d

        return None, None

    # ------------------------
    # ✅ RECHERCHE PAR MOIS
    # ------------------------
    if mode == "Recherche par mois":

        year = st.selectbox(
            f"Année ({label})",
            list(range(2017, datetime.date.today().year + 1))[::-1],
            key=f"year_{label}"
        )

        month_num, month_label = st.selectbox(
            f"Mois ({label})",
            [
                ("01", "Janvier"), ("02", "Février"), ("03", "Mars"),
                ("04", "Avril"), ("05", "Mai"), ("06", "Juin"),
                ("07", "Juillet"), ("08", "Août"), ("09", "Septembre"),
                ("10", "Octobre"), ("11", "Novembre"), ("12", "Décembre")
            ],
            key=f"month_{label}",
            format_func=lambda x: x[1]
        )

        start = f"{year}-{month_num}-01"
        end = f"{year+1}-01-01" if month_num == "12" else f"{year}-{int(month_num)+1:02d}-01"

        if st.button(f"📅 Tuiles du mois ({label})"):
            col = (ee.ImageCollection("COPERNICUS/S2_SR")
                   .filterBounds(aoi)
                   .filterDate(start, end)
                   .sort("system:time_start", False))

            timestamps = col.aggregate_array("system:time_start").getInfo()

            if len(timestamps) == 0:
                st.error("❌ Aucune tuile ce mois.")
                return None, None

            month_dates = sorted(
                set(datetime.datetime.utcfromtimestamp(t/1000).date()
                    for t in timestamps),
                reverse=True
            )

            st.session_state[dates_key] = month_dates

        if st.session_state.get(dates_key):
            chosen = st.selectbox(
                f"Dates du mois ({label})",
                st.session_state[dates_key],
                key=f"sel_month_{label}"
            )

            if st.button(f"▶️ Charger date ({label})"):
                img, d = get_closest_s2_image(aoi, chosen)
                return img, d

        return None, None


# -----------------------------------------------------------
# ✅ MODE 1 : ANALYSE SIMPLE
# -----------------------------------------------------------
if analyse_mode == "Analyse simple (1 date)":

    img, d = tuile_selector("Simple", "date_single", "available_dates_single")

    if img and d:

        st.success(f"✅ Tuile chargée : **{d}**")
        ndvi = compute_ndvi(img)
        veg_mask = compute_vegetation_mask(ndvi, threshold=0.25)

        rows = []
        for feat in features:
            geom = feat["geometry"]
            props = feat["properties"]
            num_ilot = props.get("NUM_ILOT")

            nd_mean, veg_prop = zonal_stats_ndvi(ndvi, veg_mask, geom)
            classe_txt, classe_color = classify_ndvi(nd_mean)

            rows.append({
                "NUM_ILOT": num_ilot,
                "NDVI_moyen": nd_mean,
                "Classe": classe_txt,
                "Proportion_couvert": veg_prop,
                "Couvert": couvert_status(veg_prop),
                "Date": str(d)
            })

        df = pd.DataFrame(rows)
        st.dataframe(df)

        m = folium.Map(location=[(miny+maxy)/2,(minx+maxx)/2], zoom_start=14)

        for i, feat in enumerate(features):
            geom = feat["geometry"]
            nd = df.iloc[i]["NDVI_moyen"]
            color = classify_ndvi(nd)[1]

            folium.GeoJson(
                geom.__geo_interface__,
                style_function=lambda x, col=color: {
                    "fillColor": col,
                    "color": "black",
                    "weight": 1,
                    "fillOpacity": 0.7
                },
                tooltip=f"{df.iloc[i]['NUM_ILOT']} — NDVI={nd:.2f}"
            ).add_to(m)

        st_folium(m, height=600)

        st.download_button(
            "📥 Télécharger CSV",
            df.to_csv(index=False).encode(),
            "ndvi_1_date.csv"
        )

    st.stop()


# -----------------------------------------------------------
# ✅ MODE 2 : COMPARAISON
# -----------------------------------------------------------
st.header("🔄 Comparateur NDVI entre deux dates")


# -------------------------
# ✅ DATE A
# -------------------------
st.subheader("📌 Choisir Date A")
imgA, dA = tuile_selector("A", "dateA", "available_dates_A")

if imgA and dA:
    st.session_state.imageA = imgA
    st.session_state.dateA = dA
    st.session_state.run_A = True


# -------------------------
# ✅ DATE B
# -------------------------
st.subheader("📌 Choisir Date B")
imgB, dB = tuile_selector("B", "dateB", "available_dates_B")

if imgB and dB:
    st.session_state.imageB = imgB
    st.session_state.dateB = dB
    st.session_state.run_B = True


# -----------------------------------------------------------
# ✅ AFFICHAGE PERMANENT (PATCH)
# -----------------------------------------------------------
st.markdown("### ✅ Statut des sélections")
if st.session_state.run_A:
    st.success(f"📌 Date A chargée : **{st.session_state.dateA}**")
else:
    st.info("📌 Date A non définie")

if st.session_state.run_B:
    st.success(f"📌 Date B chargée : **{st.session_state.dateB}**")
else:
    st.info("📌 Date B non définie")


# -----------------------------------------------------------
# ✅ BOUTON COMPARER
# -----------------------------------------------------------
if st.session_state.run_A and st.session_state.run_B:
    if st.button("📊 Comparer NDVI A ↔ B"):
        st.session_state.run_comparison = True


# -----------------------------------------------------------
# ✅ ANALYSE COMPARATIVE
# -----------------------------------------------------------
if st.session_state.run_comparison:

    st.success(f"Comparaison : {st.session_state.dateA} ➜ {st.session_state.dateB}")

    ndviA = compute_ndvi(st.session_state.imageA)
    ndviB = compute_ndvi(st.session_state.imageB)

    rows = []

    for feat in features:
        geom = feat["geometry"]
        props = feat["properties"]
        num_ilot = props.get("NUM_ILOT")

        ndA, _ = zonal_stats_ndvi(ndviA, None, geom)
        ndB, _ = zonal_stats_ndvi(ndviB, None, geom)

        delta = (ndB - ndA) if (ndA is not None and ndB is not None) else None
        delta_txt, delta_col = classify_delta(delta)

        rows.append({
            "NUM_ILOT": num_ilot,
            "NDVI_A": ndA,
            "NDVI_B": ndB,
            "Delta_NDVI": delta,
            "Interprétation": delta_txt
        })

    dfc = pd.DataFrame(rows)
    st.dataframe(dfc)

    # -----------------------------------------------------------
    # ✅ CARTE DELTA
    # -----------------------------------------------------------
    st.subheader("🗺️ Carte ΔNDVI")

    m2 = folium.Map(location=[(miny+maxy)/2,(minx+maxx)/2], zoom_start=14)

    for i, feat in enumerate(features):
        geom = feat["geometry"]
        delta = dfc.iloc[i]["Delta_NDVI"]
        _, col = classify_delta(delta)

        folium.GeoJson(
            geom.__geo_interface__,
            style_function=lambda x, c=col: {
                "fillColor": c,
                "color": "black",
                "weight": 1,
                "fillOpacity": 0.7
            },
            tooltip=f"{dfc.iloc[i]['NUM_ILOT']} — ΔNDVI={delta}"
        ).add_to(m2)

    st_folium(m2, height=600)

    st.download_button(
        "📥 Télécharger CSV comparaison",
        dfc.to_csv(index=False).encode(),
        "ndvi_comparaison.csv"
    )
