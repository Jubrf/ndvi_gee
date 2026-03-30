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

st.title("🌱 Analyse NDVI (GEE) – Simple & Comparateur")


# -----------------------------------------------------------
# ✅ SESSION STATE
# -----------------------------------------------------------
DEFAULTS = {
    "available_dates": None,
    "selected_date": None,
    "image": None,
    "date_used": None,
    "run_analysis": False,

    "imageA": None,
    "dateA": None,
    "run_A": False,

    "imageB": None,
    "dateB": None,
    "run_B": False,

    "run_comparison": False,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# -----------------------------------------------------------
# ✅ SIDEBAR : choix du mode d’analyse
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


# -----------------------------------------------------------
# ✅ LECTURE DU SIG
# -----------------------------------------------------------
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
# ✅ CLASSIFICATION KERMAP
# -----------------------------------------------------------
def classify_ndvi(nd):
    if nd is None:
        return ("Indéterminé", "#bdbdbd")
    if nd < 0.25:
        return ("Sol nu", "#d73027")
    if nd < 0.50:
        return ("Végétation faible", "#fee08b")
    return ("Végétation dense", "#1a9850")


def classify_delta(delta):
    if delta is None:
        return ("Indéterminé", "#bdbdbd")
    if delta < -0.10:
        return ("Baisse", "#d73027")
    if delta > 0.10:
        return ("Hausse", "#1a9850")
    return ("Stable", "#fee08b")


def couvert_status(p):
    if p is None:
        return "Indéterminé"
    return "✅ Couvert (≥ 50%)" if p >= 0.5 else "❌ Non couvert (< 50%)"


# -----------------------------------------------------------
# ✅ MÉTHODES UTILITAIRES : Sélection d'une tuile
# -----------------------------------------------------------
def tuile_selector(label):

    mode = st.radio(
        f"{label} – Choisir méthode de sélection",
        ["Dernière tuile", "Tuiles disponibles", "Recherche par mois"],
        key=f"selector_mode_{label}"
    )

    # ------------------------
    # ✅ DERNIÈRE TUILE
    # ------------------------
    if mode == "Dernière tuile":
        if st.button(f"▶️ Charger dernière tuile ({label})"):
            img, d = get_latest_s2_image(aoi)
            if img is None:
                st.error("❌ Aucune tuile disponible.")
                return None, None
            return img, d
        return None, None

    # ------------------------
    # ✅ LISTE DES TUILES
    # ------------------------
    if mode == "Tuiles disponibles":

        if st.button(f"📅 Afficher tuiles dispo ({label})"):
            st.session_state[f"dates_{label}"] = get_available_s2_dates(aoi, 120)

        if st.session_state.get(f"dates_{label}"):

            dsel = st.selectbox(
                f"Dates disponibles ({label})",
                st.session_state[f"dates_{label}"],
                format_func=lambda d: d.strftime("%Y-%m-%d"),
                key=f"date_select_{label}"
            )

            if st.button(f"▶️ Charger cette date ({label})"):
                img, d = get_closest_s2_image(aoi, dsel)
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
            format_func=lambda x: x[1],
            key=f"month_{label}"
        )

        start = f"{year}-{month_num}-01"
        if month_num == "12":
            end = f"{year+1}-01-01"
        else:
            end = f"{year}-{int(month_num)+1:02d}-01"

        if st.button(f"📅 Charger tuiles du mois ({label})"):
            col = (ee.ImageCollection("COPERNICUS/S2_SR")
                   .filterBounds(aoi)
                   .filterDate(start, end)
                   .sort("system:time_start", False))

            timestamps = col.aggregate_array("system:time_start").getInfo()

            if len(timestamps) == 0:
                st.error("❌ Aucune tuile ce mois.")
                return None, None

            month_dates = sorted(
                set(datetime.datetime.utcfromtimestamp(t/1000).date() for t in timestamps),
                reverse=True
            )

            st.session_state[f"dates_{label}"] = month_dates

        if st.session_state.get(f"dates_{label}"):
            dsel = st.selectbox(
                f"DATES du mois ({label})",
                st.session_state[f"dates_{label}"],
                format_func=lambda d: d.strftime("%Y-%m-%d"),
                key=f"month_select_{label}"
            )

            if st.button(f"▶️ Charger cette date ({label})"):
                img, d = get_closest_s2_image(aoi, dsel)
                return img, d

        return None, None


# -----------------------------------------------------------
# ✅ MODE 1 : ANALYSE SIMPLE
# -----------------------------------------------------------
if analyse_mode == "Analyse simple (1 date)":

    img, d = tuile_selector("Date unique")

    if img and d:
        st.success(f"✅ Tuile utilisée : {d}")

        ndvi = compute_ndvi(img)
        veg_mask = compute_vegetation_mask(ndvi, threshold=0.25)

        rows = []

        for feat in features:
            geom = feat["geometry"]
            props = feat["properties"]
            num_ilot = props.get("NUM_ILOT", "ILOT")

            ndvi_mean, veg_prop = zonal_stats_ndvi(ndvi, veg_mask, geom)
            classe_txt, classe_color = classify_ndvi(ndvi_mean)
            couvert = couvert_status(veg_prop)

            rows.append({
                "NUM_ILOT": num_ilot,
                "NDVI_moyen": ndvi_mean,
                "Classe": classe_txt,
                "Proportion_couvert": veg_prop,
                "Couvert": couvert,
                "Date": str(d)
            })

        df = pd.DataFrame(rows)
        st.subheader("📋 Résultats NDVI")
    st.dataframe(df)

    st.subheader("🗺️ Carte NDVI (Kermap)")
    m = folium.Map(location=[(miny+maxy)/2,(minx+maxx)/2], zoom_start=14)

    for i, feat in enumerate(features):
        geom = feat["geometry"]
        nd = df.iloc[i]["NDVI_moyen"]
        color = classify_ndvi(nd)[1]

        folium.GeoJson(
            geom.__geo_interface__,
            style_function=lambda x, val=color: {
                "fillColor": val,
                "color": "black",
                "weight": 1,
                "fillOpacity": 0.7
            },
            tooltip=f"{df.iloc[i]['NUM_ILOT']} — NDVI={nd:.2f} — {df.iloc[i]['Classe']}"
        ).add_to(m)

    st_folium(m, height=600)

    st.download_button(
        "📥 Télécharger CSV",
        df.to_csv(index=False).encode(),
        "ndvi_1date.csv"
    )


# -----------------------------------------------------------
# ✅ MODE 2 : COMPARAISON 2 DATES
# -----------------------------------------------------------
else:
    st.header("🔄 Comparateur NDVI entre deux dates")

    # -------------------------
    # ✅ DATE A
    # -------------------------
    st.subheader("📌 Choisir Date A")
    imgA, dA = tuile_selector("A")

    if imgA and dA:
        st.success(f"✅ Date A sélectionnée : {dA}")
        st.session_state.imageA = imgA
        st.session_state.dateA = dA
        st.session_state.run_A = True

    # -------------------------
    # ✅ DATE B
    # -------------------------
    st.subheader("📌 Choisir Date B")
    imgB, dB = tuile_selector("B")

    if imgB and dB:
        st.success(f"✅ Date B sélectionnée : {dB}")
        st.session_state.imageB = imgB
        st.session_state.dateB = dB
        st.session_state.run_B = True

    # -------------------------
    # ✅ BOUTON COMPARER
    # -------------------------
    if st.session_state.run_A and st.session_state.run_B:

        if st.button("📊 Comparer NDVI A ↔ B"):
            st.session_state.run_comparison = True

    # -------------------------
    # ✅ ANALYSE COMPARATIVE
    # -------------------------
    if st.session_state.run_comparison:

        st.success(f"Comparaison entre : {st.session_state.dateA} ➜ {st.session_state.dateB}")

        ndviA = compute_ndvi(st.session_state.imageA)
        ndviB = compute_ndvi(st.session_state.imageB)

        rows = []

        for feat in features:
            geom = feat["geometry"]
            props = feat["properties"]
            num_ilot = props.get("NUM_ILOT", "ILOT")

            ndA, _ = zonal_stats_ndvi(ndviA, None, geom)
            ndB, _ = zonal_stats_ndvi(ndviB, None, geom)

            delta = (ndB - ndA) if (ndA is not None and ndB is not None) else None

            delta_txt, delta_color = classify_delta(delta)

            rows.append({
                "NUM_ILOT": num_ilot,
                "NDVI_A": ndA,
                "NDVI_B": ndB,
                "Delta_NDVI": delta,
                "Interprétation": delta_txt
            })

        df2 = pd.DataFrame(rows)
        st.subheader("📋 Résultats comparaison NDVI")
        st.dataframe(df2)

        # -------------------------
        # ✅ CARTE VARIATION NDVI
        # -------------------------
        st.subheader("🗺️ Carte variation NDVI (ΔNDVI)")

        m2 = folium.Map(
            location=[(miny+maxy)/2,(minx+maxx)/2],
            zoom_start=14
        )

        for i, feat in enumerate(features):
            geom = feat["geometry"]
            delta = df2.iloc[i]["Delta_NDVI"]
            _, c = classify_delta(delta)

            folium.GeoJson(
                geom.__geo_interface__,
                style_function=lambda x, col=c: {
                    "fillColor": col,
                    "color": "black",
                    "weight": 1,
                    "fillOpacity": 0.7
                },
                tooltip=(
                    f"{df2.iloc[i]['NUM_ILOT']} — ΔNDVI="
                    f"{delta if delta is not None else 'NA'} — "
                    f"{df2.iloc[i]['Interprétation']}"
                )
            ).add_to(m2)

        st_folium(m2, height=600)

        st.download_button(
            "📥 Télécharger CSV comparaison",
            df2.to_csv(index=False).encode(),
            "ndvi_comparaison.csv"
        )
