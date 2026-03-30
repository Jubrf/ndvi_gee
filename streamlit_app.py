import streamlit as st
import folium
import pandas as pd
from shapely.geometry import shape
from streamlit_folium import st_folium
import datetime
import ee
import os

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
# ✅ INIT EARTH ENGINE
# -----------------------------------------------------------
service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
private_key = st.secrets["GEE_PRIVATE_KEY"]
init_gee(service_account, private_key)

st.title("🌱 NDVI : Analyse simple & Comparateur NDVI (2 dates)")


# -----------------------------------------------------------
# ✅ MODULE DE SAUVEGARDE
# -----------------------------------------------------------
def ensure_history_dir():
    """Créer dossier history/ si non existant."""
    if not os.path.exists("history"):
        os.makedirs("history")


def save_dataframe(df, filename, save_name, meta=None):
    """
    Sauvegarde un DataFrame dans history/<filename>.
    Ajoute save_name + meta à chaque ligne.
    """
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
    """Charger un CSV depuis history/ si dispo."""
    path = os.path.join("history", filename)
    if os.path.exists(path):
        return pd.read_csv(path)
    return None


# -----------------------------------------------------------
# ✅ SESSION STATE CENTRALISÉ
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
# ✅ SIDEBAR — Choix du mode
# -----------------------------------------------------------
analyse_mode = st.sidebar.radio(
    "Mode d'analyse",
    [
        "Analyse simple (1 date)",
        "Comparaison entre 2 dates",
        "📚 Mémoire"
    ]
)


# -----------------------------------------------------------
# ✅ UPLOAD SIG / SHP / GEOJSON
# -----------------------------------------------------------
uploaded = st.file_uploader("📁 Upload SHP (ZIP) ou GEOJSON", type=["zip", "geojson"])

if not uploaded:
    st.info("Veuillez importer un fichier SIG pour commencer.")
    st.stop()

features = load_vector(uploaded)
st.success(f"{len(features)} parcelles chargées ✅")


# -----------------------------------------------------------
# ✅ CALCUL BBOX + AOI GEE
# -----------------------------------------------------------
geoms = [f["geometry"] for f in features]
minx = min(g.bounds[0] for g in geoms)
miny = min(g.bounds[1] for g in geoms)
maxx = max(g.bounds[2] for g in geoms)
maxy = max(g.bounds[3] for g in geoms)
aoi = ee.Geometry.Rectangle([minx, miny, maxx, maxy])


# -----------------------------------------------------------
# ✅ CLASSIFICATION NDVI KERMAP
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


def couvert_status(prop):
    if prop is None:
        return "Indéterminé"
    return "✅ Couvert (≥50%)" if prop >= 0.5 else "❌ Non couvert (<50%)"


# -----------------------------------------------------------
# ✅ SELECTEUR DE TUILE (dernière / liste / mois)
# -----------------------------------------------------------
def tuile_selector(label, dates_key):
    """
    Retourne : (image, date) ou (None, None)
    label = 'A', 'B', 'Simple'
    dates_key = clé session_state pour stocker les dates trouvées.
    """

    mode = st.radio(
        f"{label} – méthode de sélection",
        ["Dernière tuile", "Tuiles disponibles", "Recherche par mois"],
        key=f"mode_{label}"
    )

    # 1) DERNIÈRE TUILE
    if mode == "Dernière tuile":
        if st.button(f"▶️ Charger dernière tuile ({label})"):
            return get_latest_s2_image(aoi)
        return None, None

    # 2) TUILES DISPONIBLES
    if mode == "Tuiles disponibles":

        if st.button(f"📅 Lister tuiles ({label})"):
            st.session_state[dates_key] = get_available_s2_dates(aoi, 120)

        if st.session_state.get(dates_key):
            chosen = st.selectbox(
                f"Dates disponibles ({label})",
                st.session_state[dates_key],
                format_func=lambda d: d.strftime("%Y-%m-%d"),
                key=f"sel_{label}"
            )

            if st.button(f"▶️ Charger cette date ({label})"):
                return get_closest_s2_image(aoi, chosen)

        return None, None

    # 3) RECHERCHE PAR MOIS
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

        if st.button(f"📅 Lister tuiles du mois ({label})"):

            col = (ee.ImageCollection("COPERNICUS/S2_SR")
                   .filterBounds(aoi)
                   .filterDate(start, end)
                   .sort("system:time_start", False))

            timestamps = col.aggregate_array("system:time_start").getInfo()

            if not timestamps:
                st.error("❌ Aucune tuile trouvée ce mois.")
                return None, None

            month_dates = sorted(
                {datetime.datetime.utcfromtimestamp(t/1000).date() for t in timestamps},
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
                return get_closest_s2_image(aoi, chosen)

        return None, None
# -----------------------------------------------------------
# ✅ FONCTIONS LÉGENDE (NDVI & ΔNDVI)
# -----------------------------------------------------------
from branca.element import Template, MacroElement

def add_legend_ndvi(m):
    html = """
    {% macro html() %}
    <div style="
        position: fixed;
        bottom: 50px;
        right: 10px;
        z-index:9999;
        background-color: rgba(255,255,255,.9);
        padding: 10px;
        border:2px solid #999;
        border-radius:5px;
        font-size:14px;
        ">
        <b>Légende NDVI</b><br>
        <i style="background:#d73027;width:12px;height:12px;display:inline-block;"></i> Sol nu (<0.25)<br>
        <i style="background:#fee08b;width:12px;height:12px;display:inline-block;"></i> Végétation faible (0.25–0.50)<br>
        <i style="background:#1a9850;width:12px;height:12px;display:inline-block;"></i> Végétation dense (≥0.50)
    </div>
    {% endmacro %}
    """
    macro = MacroElement()
    macro._template = Template(html)
    m.get_root().add_child(macro)


def add_legend_delta(m):
    html = """
    {% macro html() %}
    <div style="
        position: fixed;
        bottom: 50px;
        right: 10px;
        z-index:9999;
        background-color: rgba(255,255,255,.9);
        padding: 10px;
        border:2px solid #999;
        border-radius:5px;
        font-size:14px;
        ">
        <b>Légende ΔNDVI</b><br>
        <i style="background:#d73027;width:12px;height:12px;display:inline-block;"></i> Baisse (< -0.10)<br>
        <i style="background:#fee08b;width:12px;height:12px;display:inline-block;"></i> Stable (-0.10 à +0.10)<br>
        <i style="background:#1a9850;width:12px;height:12px;display:inline-block;"></i> Hausse (> +0.10)
    </div>
    {% endmacro %}
    """
    macro = MacroElement()
    macro._template = Template(html)
    m.get_root().add_child(macro)



# ======================================================================
# ✅ MODE 1 : ANALYSE SIMPLE (1 DATE)
# ======================================================================
if analyse_mode == "Analyse simple (1 date)":

    st.header("🟩 Analyse NDVI — 1 Date")

    img, d = tuile_selector("Simple", "available_dates_single")

    if img and d:

        st.success(f"✅ Tuile utilisée : **{d}**")

        ndvi = compute_ndvi(img)
        veg_mask = compute_vegetation_mask(ndvi, threshold=0.25)

        rows = []
        for feat in features:
            geom = feat["geometry"]
            num_ilot = feat["properties"].get("NUM_ILOT", "ILOT")

            ndvi_mean, veg_prop = zonal_stats_ndvi(ndvi, veg_mask, geom)
            classe_txt, classe_color = classify_ndvi(ndvi_mean)

            rows.append({
                "NUM_ILOT": num_ilot,
                "NDVI_moyen": ndvi_mean,
                "Classe": classe_txt,
                "Proportion_couvert": veg_prop,
                "Couvert": couvert_status(veg_prop),
                "Date": str(d)
            })

        df = pd.DataFrame(rows)
        st.subheader("📋 Résultats NDVI")
        st.dataframe(df)

        # Carte NDVI
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

        # Ajout légende NDVI
        add_legend_ndvi(m)
        st_folium(m, height=600)

        # ✅ SAUVEGARDE
        st.subheader("💾 Sauvegarder cette analyse")
        save_name = st.text_input("Nom de la sauvegarde", key="save_simple")

        if st.button("💾 Sauvegarder (1 date)"):
            if not save_name:
                st.error("Veuillez fournir un nom.")
            else:
                save_dataframe(
                    df,
                    "analyses_simple.csv",
                    save_name,
                    meta={"analysis_type": "simple", "date": str(d)}
                )
                st.success(f"✅ Analyse sauvegardée sous : **{save_name}**")



# ======================================================================
# ✅ MODE 2 : COMPARAISON 2 DATES
# ======================================================================
elif analyse_mode == "Comparaison entre 2 dates":

    st.header("🟦 Comparateur NDVI — Deux Dates")

    # -------------------------
    # 📌 Sélection Date A
    # -------------------------
    st.subheader("📌 Date A (ancienne)")
    imgA, dA = tuile_selector("A", "available_dates_A")

    if imgA and dA:
        st.session_state.imageA = imgA
        st.session_state.dateA = dA
        st.session_state.run_A = True

    # -------------------------
    # 📌 Sélection Date B
    # -------------------------
    st.subheader("📌 Date B (récente)")
    imgB, dB = tuile_selector("B", "available_dates_B")

    if imgB and dB:
        st.session_state.imageB = imgB
        st.session_state.dateB = dB
        st.session_state.run_B = True

    # -----------------------------------------------------------
    # ✅ AFFICHAGE PERMANENT
    # -----------------------------------------------------------
    st.markdown("### ✅ Statut de sélection")

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

        st.success(f"Comparaison : **{st.session_state.dateA} ➜ {st.session_state.dateB}**")

        ndviA = compute_ndvi(st.session_state.imageA)
        ndviB = compute_ndvi(st.session_state.imageB)

        rows = []

        for feat in features:
            geom = feat["geometry"]
            num_ilot = feat["properties"].get("NUM_ILOT", "ILOT")

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
        st.subheader("📋 Résultats comparaison")
        st.dataframe(dfc)

        # -----------------------------------------------------------
        # ✅ CARTE ΔNDVI
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

        # Ajouter légende ΔNDVI
        add_legend_delta(m2)
        st_folium(m2, height=600)

        # -----------------------------------------------------------
        # ✅ SAUVEGARDE COMPARAISON
        # -----------------------------------------------------------
        st.subheader("💾 Sauvegarder cette comparaison")

        save_name = st.text_input("Nom de la sauvegarde", key="save_compare")

        if st.button("💾 Sauvegarder comparaison"):
            if not save_name:
                st.error("Veuillez fournir un nom.")
            else:
                save_dataframe(
                    dfc,
                    "analyses_compare.csv",
                    save_name,
                    meta={
                        "analysis_type": "comparaison",
                        "dateA": str(st.session_state.dateA),
                        "dateB": str(st.session_state.dateB)
                    }
                )
                st.success(f"✅ Comparaison sauvegardée sous : **{save_name}**")



# ======================================================================
# ✅ MODE 3 : MEMORY VIEWER
# ======================================================================
elif analyse_mode == "📚 Mémoire":

    st.header("📚 Mémoire des analyses sauvegardées")

    df1 = load_history("analyses_simple.csv")
    df2 = load_history("analyses_compare.csv")

    if df1 is not None:
        st.subheader("🗂️ Analyses simples")
        st.dataframe(df1)
    else:
        st.info("Aucune analyse simple sauvegardée.")

    if df2 is not None:
        st.subheader("🗂️ Comparaisons NDVI")
        st.dataframe(df2)
    else:
        st.info("Aucune comparaison sauvegardée.")
