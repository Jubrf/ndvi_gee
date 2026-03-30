import streamlit as st
import folium
import pandas as pd
from streamlit_folium import st_folium
import datetime
import ee
import os
import re

# ============================================================
# ✅ IMPORT UTILS
# ============================================================
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


# ============================================================
# ✅ INIT EARTH ENGINE
# ============================================================
service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
private_key = st.secrets["GEE_PRIVATE_KEY"]
init_gee(service_account, private_key)

st.title("🌱 NDVI – Analyse simple & Comparateur 2 dates (Kermap)")


# ============================================================
# ✅ MODULE SAUVEGARDE CSV
# ============================================================
def ensure_history_dir():
    if not os.path.exists("history"):
        os.makedirs("history")

def sanitize_name(name):
    name = name.strip().lower()
    return re.sub(r"[^a-z0-9_-]+", "_", name)

def save_dataframe(df, filename, save_name, meta=None):
    ensure_history_dir()
    path = os.path.join("history", filename)

    if df is None or df.empty:
        st.error("❌ Impossible de sauvegarder : tableau vide")
        return

    df2 = df.copy()
    df2["save_name"] = save_name

    if meta:
        for k, v in meta.items():
            df2[k] = v

    if not os.path.exists(path):
        df2.to_csv(path, index=False)
    else:
        df2.to_csv(path, mode="a", header=False, index=False)

def load_history(filename):
    path = os.path.join("history", filename)
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path)
    except:
        return None


# ============================================================
# ✅ SESSION STATE
# ============================================================
DEFAULTS = {
    "available_dates_single": None,
    "available_dates_A": None,
    "available_dates_B": None,

    "image_single": None,
    "imageA": None,
    "imageB": None,

    "date_single": None,
    "dateA": None,
    "dateB": None,

    "result_single": None,
    "result_compare": None,

    "run_A": False,
    "run_B": False,
    "run_comparison": False,
}

for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ============================================================
# ✅ SIDEBAR MODES
# ============================================================
analyse_mode = st.sidebar.radio(
    "Mode",
    [
        "Analyse simple (1 date)",
        "Comparaison entre 2 dates",
        "📚 Mémoire"
    ]
)


# ============================================================
# ✅ UPLOAD SIG
# ============================================================
uploaded = st.file_uploader("📁 Charger un SHP (ZIP) ou GEOJSON", type=["zip","geojson"])
if not uploaded:
    st.stop()

features = load_vector(uploaded)
st.success(f"{len(features)} parcelles chargées ✅")

geoms = [f["geometry"] for f in features]
minx = min(g.bounds[0] for g in geoms)
miny = min(g.bounds[1] for g in geoms)
maxx = max(g.bounds[2] for g in geoms)
maxy = max(g.bounds[3] for g in geoms)

aoi = ee.Geometry.Rectangle([minx,miny,maxx,maxy])


# ============================================================
# ✅ CLASSIFICATION NDVI & COULEURS KERMAP
# ============================================================
def classify_ndvi(nd):
    if nd is None: return ("Indéterminé","#bdbdbd")
    if nd < 0.25: return ("Sol nu","#d73027")
    if nd < 0.50: return ("Végétation faible","#fee08b")
    return ("Végétation dense","#1a9850")

def classify_delta(delta):
    if delta is None: return ("Indéterminé","#bdbdbd")
    if delta < -0.10: return ("Baisse","#d73027")
    if delta > 0.10: return ("Hausse","#1a9850")
    return ("Stable","#fee08b")

def couvert_status(v):
    if v is None: return "Indéterminé"
    return "✅ Couvert (≥50%)" if v >= 0.5 else "❌ Non couvert (<50%)"

# ✅ Fonction couleur Kermap (3 classes)
def colorize(nd):
    if nd is None:
        return "#bbbbbb"
    if nd < 0.25:
        return "#d73027"
    if nd < 0.50:
        return "#fee08b"
    return "#1a9850"


# ============================================================
# ✅ SELECTEUR DE TUILE (DERNIERE / LISTE / MOIS)
# ============================================================
def tuile_selector(label, dates_key):

    mode = st.radio(
        f"Choisir la tuile ({label})",
        ["Dernière tuile","Tuiles disponibles","Recherche par mois"],
        key=f"mode_{label}"
    )

    # Dernière tuile
    if mode == "Dernière tuile":
        if st.button(f"🔍 Charger dernière tuile ({label})"):
            return get_latest_s2_image(aoi)
        return None,None

    # Liste
    if mode == "Tuiles disponibles":
        if st.button(f"📅 Lister ({label})"):
            st.session_state[dates_key] = get_available_s2_dates(aoi,120)

        if st.session_state.get(dates_key):
            chosen = st.selectbox(
                f"Dates ({label})",
                st.session_state[dates_key],
                key=f"sel_{label}",
                format_func=lambda d: d.strftime("%Y-%m-%d")
            )
            if st.button(f"✅ Charger ({label})"):
                return get_closest_s2_image(aoi,chosen)

        return None,None

    # Recherche mensuelle
    if mode == "Recherche par mois":

        year = st.selectbox(
            f"Année ({label})",
            list(range(2017, datetime.date.today().year+1))[::-1],
            key=f"year_{label}"
        )

        month_num, month_label = st.selectbox(
            f"Mois ({label})",
            [
                ("01","Janvier"),("02","Février"),("03","Mars"),("04","Avril"),
                ("05","Mai"),("06","Juin"),("07","Juillet"),("08","Août"),
                ("09","Septembre"),("10","Octobre"),("11","Novembre"),("12","Décembre")
            ],
            key=f"month_{label}",
            format_func=lambda x: x[1]
        )

        start = f"{year}-{month_num}-01"
        end = f"{year+1}-01-01" if month_num=="12" else f"{year}-{int(month_num)+1:02d}-01"

        if st.button(f"📅 Rechercher ({label})"):

            col = (
                ee.ImageCollection("COPERNICUS/S2_SR")
                .filterBounds(aoi)
                .filterDate(start,end)
                .sort("system:time_start", False)
            )

            timestamps = col.aggregate_array("system:time_start").getInfo()

            if not timestamps:
                st.error("❌ Aucune tuile ce mois.")
                return None,None

            month_dates = sorted(
                {datetime.datetime.utcfromtimestamp(t/1000).date()
                for t in timestamps},
                reverse=True
            )

            st.session_state[dates_key] = month_dates

        if st.session_state.get(dates_key):

            chosen = st.selectbox(
                f"Dates du mois ({label})",
                st.session_state[dates_key],
                key=f"sel_month_{label}"
            )

            if st.button(f"✅ Charger ({label})"):
                return get_closest_s2_image(aoi,chosen)

        return None,None


# =============================================================================
# ✅ MODE 1 — ANALYSE SIMPLE PERSISTANTE
# =============================================================================
if analyse_mode == "Analyse simple (1 date)":

    st.header("🟩 Analyse NDVI – 1 Date")

    img, d = tuile_selector("SIMPLE","available_dates_single")

    if img and d:
        st.session_state.date_single = d

        ndvi = compute_ndvi(img)
        veg_mask = compute_vegetation_mask(ndvi,0.25)

        rows=[]
        for feat in features:
            geom = feat["geometry"]
            num_ilot = feat["properties"].get("NUM_ILOT","ILOT")

            nd_mean, veg_prop = zonal_stats_ndvi(ndvi,veg_mask,geom)
            classe_txt, col = classify_ndvi(nd_mean)

            rows.append({
                "NUM_ILOT": num_ilot,
                "NDVI_moyen": nd_mean,
                "Classe": classe_txt,
                "Proportion_couvert": veg_prop,
                "Couvert": couvert_status(veg_prop),
                "Date": str(d)
            })

        st.session_state.result_single = pd.DataFrame(rows)

    # ✅ AFFICHAGE PERSISTANT
    if st.session_state.result_single is not None:

        df = st.session_state.result_single
        st.success(f"✅ Résultats NDVI — Tuile utilisée : {st.session_state.date_single}")
        st.dataframe(df)

        # ✅ CARTE KERMAP
        m = folium.Map(location=[(miny+maxy)/2,(minx+maxx)/2], zoom_start=14)

        for idx, feat in enumerate(features):
            geom = feat["geometry"]
            num_ilot = df.iloc[idx]["NUM_ILOT"]
            nd = df.iloc[idx]["NDVI_moyen"]
            classe_txt = df.iloc[idx]["Classe"]
            color = colorize(nd)

            tooltip_html = (
                f"<b>Ilot :</b> {num_ilot}<br>"
                f"<b>NDVI :</b> {nd:.3f}<br>"
                f"<b>Classe :</b> {classe_txt}"
            )

            folium.GeoJson(
                geom.__geo_interface__,
                style_function=lambda x, col=color: {
                    "fillColor": col,
                    "color": "black",
                    "weight": 1,
                    "fillOpacity": 0.7
                },
                tooltip=tooltip_html
            ).add_to(m)

        st_folium(m, height=600)

        # ✅ Sauvegarde
        st.subheader("💾 Sauvegarder")
        raw_name = st.text_input("Nom de la sauvegarde :", key="save_simple")
        save_name = sanitize_name(raw_name)

        if st.button("✅ Sauvegarder"):
            if not save_name:
                st.error("❌ Nom invalide")
            else:
                save_dataframe(
                    df,
                    "analyses_simple.csv",
                    save_name,
                    meta={"analysis_type":"simple","date":st.session_state.date_single}
                )
                st.success(f"✅ Sauvegarde effectuée sous : {save_name}")


# =============================================================================
# ✅ MODE 2 — COMPARAISON NDVI A ↔ B (PERSISTANTE)
# =============================================================================
elif analyse_mode == "Comparaison entre 2 dates":

    st.header("🟦 Comparateur NDVI – A → B")

    # --- DATE A ----------------------------------
    st.subheader("📌 Date A (ancienne)")
    imgA, dA = tuile_selector("A","available_dates_A")
    if imgA and dA:
        st.session_state.imageA = imgA
        st.session_state.dateA = dA
        st.session_state.run_A = True

    # --- DATE B ----------------------------------
    st.subheader("📌 Date B (récente)")
    imgB, dB = tuile_selector("B","available_dates_B")
    if imgB and dB:
        st.session_state.imageB = imgB
        st.session_state.dateB = dB
        st.session_state.run_B = True

    # --- STATUT ----------------------------------
    st.markdown("### ✅ Statut")
    if st.session_state.run_A:
        st.success(f"Date A : {st.session_state.dateA}")
    if st.session_state.run_B:
        st.success(f"Date B : {st.session_state.dateB}")

    if st.session_state.run_A and st.session_state.run_B:
        if st.button("📊 Lancer comparaison"):
            st.session_state.run_comparison = True

    # --- CALCUL COMPARATIF ------------------------
    if st.session_state.run_comparison:

        ndviA = compute_ndvi(st.session_state.imageA)
        ndviB = compute_ndvi(st.session_state.imageB)

        rows=[]
        for feat in features:
            geom=feat["geometry"]
            num_ilot=feat["properties"].get("NUM_ILOT","ILOT")

            ndA,_=zonal_stats_ndvi(ndviA,None,geom)
            ndB,_=zonal_stats_ndvi(ndviB,None,geom)
            delta=ndB-ndA if ndA is not None and ndB is not None else None

            txt,col = classify_delta(delta)

            rows.append({
                "NUM_ILOT":num_ilot,
                "NDVI_A":ndA,
                "NDVI_B":ndB,
                "Delta_NDVI":delta,
                "Interprétation":txt
            })

        st.session_state.result_compare = pd.DataFrame(rows)

    # --- AFFICHAGE PERSISTANT ----------------------
    if st.session_state.result_compare is not None:

        dfc = st.session_state.result_compare
        st.dataframe(dfc)

        m2 = folium.Map(location=[(miny+maxy)/2,(minx+maxx)/2], zoom_start=14)

        for idx, feat in enumerate(features):
            geom = feat["geometry"]
            num_ilot = dfc.iloc[idx]["NUM_ILOT"]
            delta = dfc.iloc[idx]["Delta_NDVI"]
            txt = dfc.iloc[idx]["Interprétation"]
            color = colorize(delta)

            tooltip_html = (
                f"<b>Ilot :</b> {num_ilot}<br>"
                f"<b>NDVI A :</b> {dfc.iloc[idx]['NDVI_A']:.3f}<br>"
                f"<b>NDVI B :</b> {dfc.iloc[idx]['NDVI_B']:.3f}<br>"
                f"<b>Δ NDVI :</b> {delta:.3f}<br>"
                f"<b>Tendance :</b> {txt}"
            )

            folium.GeoJson(
                geom.__geo_interface__,
                style_function=lambda x, col=color: {
                    "fillColor": col,
                    "color": "black",
                    "weight": 1,
                    "fillOpacity": 0.7
                },
                tooltip=tooltip_html
            ).add_to(m2)

        st_folium(m2, height=600)

        # ✅ Sauvegarde
        st.subheader("💾 Sauvegarder comparaison")
        raw_name = st.text_input("Nom de la sauvegarde comparaison :", key="save_compare")
        save_name = sanitize_name(raw_name)

        if st.button("✅ Sauvegarder comparaison"):
            if not save_name:
                st.error("❌ Nom invalide")
            else:
                save_dataframe(
                    dfc,
                    "analyses_compare.csv",
                    save_name,
                    meta={
                        "analysis_type":"comparaison",
                        "dateA":str(st.session_state.dateA),
                        "dateB":str(st.session_state.dateB)
                    }
                )
                st.success(f"✅ Comparaison sauvegardée sous : {save_name}")


# =============================================================================
# ✅ MODE MEMOIRE
# =============================================================================
else:

    st.header("📚 Mémoire des analyses")

    df1 = load_history("analyses_simple.csv")
    df2 = load_history("analyses_compare.csv")

    if df1 is not None:
        st.subheader("🟩 Analyses simples")
        st.dataframe(df1)

    if df2 is not None:
        st.subheader("🟦 Comparaisons NDVI")
        st.dataframe(df2)

    if df1 is None and df2 is None:
        st.info("Aucune sauvegarde trouvée.")
