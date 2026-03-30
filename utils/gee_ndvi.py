import ee
import datetime

# ----------------------------------------------------------
# ✅ INITIALISATION GEE
# ----------------------------------------------------------
def init_gee(service_account, private_key):
    credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
    ee.Initialize(credentials)


def compute_ndvi(img):
    """
    Calcule un NDVI robuste sur S2_SR en détectant automatiquement les bandes RED et NIR.
    Fonctionne même si les bandes s'appellent B4, B04, B4_1, B8, B08, B8A, etc.
    """

    # Récupération des noms de bandes disponibles
    bands = img.bandNames().getInfo()

    # Liste des noms possibles pour les bandes S2
    red_candidates = ["B4", "B04", "B4_1"]
    nir_candidates = ["B8", "B08", "B8A", "B8_1"]

    # Trouver une bande valable dans les tuiles
    red = next((b for b in red_candidates if b in bands), None)
    nir = next((b for b in nir_candidates if b in bands), None)

    if red is None or nir is None:
        # Si rien n'est trouvé → NDVI = None partout (évite crash)
        return ee.Image.constant(0).rename("NDVI").updateMask(ee.Image.constant(0))

    # NDVI Sentinel‑2
    ndvi = img.normalizedDifference([nir, red]).rename("NDVI")

    return ndvi


# ----------------------------------------------------------
# ✅ Récupérer la dernière tuile Sentinel‑2 ≤ 30 jours
# ----------------------------------------------------------
def get_latest_s2_image(aoi_geom, max_days=30):
    today = datetime.date.today()

    for delta in range(0, max_days + 1):
        day = today - datetime.timedelta(days=delta)
        start = f"{day}T00:00"
        end = f"{day}T23:59"

        col = (ee.ImageCollection("COPERNICUS/S2_SR")
               .filterBounds(aoi_geom)
               .filterDate(start, end)
               .filter("SCL != 9")   # nuages élevés
               .filter("SCL != 8")   # nuages moyens
               .sort("system:time_start", False))

        img = col.first()
        if img.getInfo() is not None:
            return img, day

    return None, None


# ----------------------------------------------------------
# ✅ Liste des dates disponibles (120 jours max)
# ----------------------------------------------------------
def get_available_s2_dates(aoi_geom, max_days=120):

    today = datetime.date.today()
    start = today - datetime.timedelta(days=max_days)

    col = (ee.ImageCollection("COPERNICUS/S2_SR")
           .filterBounds(aoi_geom)
           .filterDate(str(start), str(today))
           .sort("system:time_start", False))

    timestamps = col.aggregate_array("system:time_start").getInfo()

    dates = []
    for t in timestamps:
        d = datetime.datetime.utcfromtimestamp(t / 1000).date()
        if d not in dates:
            dates.append(d)

    return sorted(dates, reverse=True)


# ----------------------------------------------------------
# ✅ Récupérer la tuile la plus proche d'une date choisie
# ----------------------------------------------------------
def get_closest_s2_image(aoi_geom, target_date, max_days=120):

    if isinstance(target_date, str):
        target_date = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()

    for delta in range(0, max_days + 1):

        d = target_date - datetime.timedelta(days=delta)
        start = f"{d}T00:00"
        end = f"{d}T23:59"

        col = (ee.ImageCollection("COPERNICUS/S2_SR")
               .filterBounds(aoi_geom)
               .filterDate(start, end)
               .filter("SCL != 9")
               .filter("SCL != 8")
               .sort("system:time_start", False))

        img = col.first()

        if img.getInfo() is not None:
            return img, d

    return None, None
