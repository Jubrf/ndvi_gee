import streamlit as st
import folium
import pandas as pd
from shapely.geometry import shape
from streamlit_folium import st_folium

from utils.vector_io import load_vector
from utils.gee_ndvi import init_gee, get_latest_s2_image, compute_ndvi, compute_vegetation_mask
from utils.ndvi_processing import zonal_stats_ndvi
import ee

# ------------------------------
# INIT GEE
# ------------------------------
service_account = st.secrets["GEE_SERVICE_ACCOUNT"]
private_key     = st.secrets["GEE_PRIVATE_KEY"]

init_gee(service_account, private_key)

st.title("🌱 NDVI Google Earth Engine — Parcelle par parcelle (30 jours max)")

uploaded = st.file_uploader("📁 Upload SHP (ZIP) ou GEOJSON", type=["zip", "geojson"])

if uploaded:

    features = load_vector(uploaded)
    st.success(f"{len(features)} parcelles chargées ✅")

    # Construire BBOX globale
    all_geoms = [f["geometry"] for f in features]
    minx = min(g.bounds[0] for g in all_geoms)
    miny = min(g.bounds[1] for g in all_geoms)
    maxx = max(g.bounds[2] for g in all_geoms)
    maxy = max(g.bounds[3] for g in all_geoms)

    aoi = ee.Geometry.Rectangle([minx, miny, maxx, maxy])

    # Trouver la tuile la plus récente
    st.info("🔍 Recherche de la tuile Sentinel‑2 la plus récente (≤ 30 jours)…")
    image, date_used = get_latest_s2_image(aoi)

    if image is None:
        st.error("❌ Aucune tuile S2 trouvée ces 30 derniers jours.")
        st.stop()

    st.success(f"✅ Tuile trouvée du {date_used}")

    # NDVI global
    ndvi = compute_ndvi(image)
    veg_mask = compute_vegetation_mask(ndvi, threshold=0.3)

    # Zonal stats por parcelle
    rows = []

    for i, feat in enumerate(features):
        geom = feat["geometry"]
        props = feat["properties"]

        num_ilot = props.get("NUM_ILOT", f"ILOT_{i+1}")

        ndvi_mean, veg_prop = zonal_stats_ndvi(ndvi, veg_mask, geom)

        if veg_prop is not None:
            couvert = "✅ Oui" if veg_prop >= 0.5 else "❌ Non"
        else:
            couvert = "❓ Indéterminé"

        rows.append({
            "NUM_ILOT": num_ilot,
            "NDVI_moyen": ndvi_mean,
            "Proportion_couvert": veg_prop,
            "Couvert_≥50%": couvert,
            "Date": str(date_used)
        })

    df = pd.DataFrame(rows)

    st.subheader("📊 Résultats NDVI par parcelle")
    st.dataframe(df)

    # Carte NDVI
    st.subheader("🗺️ Carte NDVI — palette Kermap")

    m = folium.Map(location=[(miny+maxy)/2,(minx+maxx)/2], zoom_start=14)

    def colorize(v):
        if v is None: return "#bbbbbb"
        vv = (v+1)/2
        if vv < 0.33: return "#d73027"
        if vv < 0.66: return "#fee08b"
        return "#1a9850"

    for i, feat in enumerate(features):
        geom = feat["geometry"]
        ndvi_mean = df.iloc[i]["NDVI_moyen"]

        folium.GeoJson(
            geom.__geo_interface__,
            style_function=lambda x, ndvi=ndvi_mean: {
                "fillColor": colorize(ndvi),
                "color": "black",
                "weight": 1,
                "fillOpacity": 0.7
            },
            tooltip=f"{df.iloc[i]['NUM_ILOT']} — NDVI={ndvi_mean}"
        ).add_to(m)

    st_folium(m, height=600)

    # Export CSV
    st.download_button(
        "📥 Exporter CSV",
        df.to_csv(index=False).encode(),
        "ndvi_par_parcelle_gee.csv"
    )
