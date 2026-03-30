import ee
import datetime

# ----------------------------------------------------------
# ✅ INITIALISATION GEE
# ----------------------------------------------------------
def init_gee(service_account, private_key):
    credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
    ee.Initialize(credentials)


# ----------------------------------------------------------
# ✅ NDVI ROBUSTE MULTI-NOM DE BANDES
# ----------------------------------------------------------
def compute_ndvi(img):
    """
    Calcule un NDVI robuste sur S2_SR en détectant automatiquement les bandes RED et NIR.
    """

    bands = img.bandNames().getInfo()

    red_candidates = ["B4", "B04", "B4_1"]
    nir_candidates = ["B8", "B08", "B8A", "B8_1"]

    red = next((b for b in red_candidates if b in bands), None)
    nir = next((b for b in nir_candidates if b in bands), None)

    if red is None or nir is None:
        return ee.Image.constant(0).rename("NDVI").updateMask(ee.Image.constant(0))

    return img.normalizedDifference([nir, red]).rename("NDVI")


# ----------------------------------------------------------
# ✅ Masque végétation NDVI > threshold
# ----------------------------------------------------------
def compute_vegetation_mask(ndvi_img, threshold=0.25):
    return ndvi_img.gt(threshold).rename("VEG")


# ----------------------------------------------------------
# ✅ Récupérer la dernière image Sentinel
# ----------------------------------------------------------
def get_latest_s2_image(aoi_geom, max_days=30):
    today = datetime.date.today()

    for delta in range(max_days + 1):
        day = today - datetime.timedelta(days=delta)
        start = f"{day}T00:00"
        end = f"{day}T23:59"

        col = (
            ee.ImageCollection("COPERNICUS/S2_SR")
            .filterBounds(aoi_geom)
            .filterDate(start, end)
            .sort("system:time_start", False)
        )

        img = col.first()
        if img.getInfo() is not None:
            return img, day

    return None, None


# ----------------------------------------------------------
# ✅ Liste des dates disponibles
# ----------------------------------------------------------
def get_available_s2_dates(aoi_geom, max_days=120):

    today = datetime.date.today()
    start = today - datetime.timedelta(days=max_days)

    col = (
        ee.ImageCollection("COPERNICUS/S2_SR")
        .filterBounds(aoi_geom)
        .filterDate(str(start), str(today))
        .sort("system:time_start", False)
    )

    timestamps = col.aggregate_array("system:time_start").getInfo()

    dates = []
    for t in timestamps:
        d = datetime.datetime.fromtimestamp(t / 1000, datetime.UTC).date()
        if d not in dates:
            dates.append(d)

    return sorted(dates, reverse=True)


# ----------------------------------------------------------
# ✅ Récupérer la tuile la plus proche
# ----------------------------------------------------------
def get_closest_s2_image(aoi_geom, target_date, max_days=120):

    if isinstance(target_date, str):
        target_date = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()

    for delta in range(max_days + 1):

        d = target_date - datetime.timedelta(days=delta)
        start = f"{d}T00:00"
        end = f"{d}T23:59"

        col = (
            ee.ImageCollection("COPERNICUS/S2_SR")
            .filterBounds(aoi_geom)
            .filterDate(start, end)
            .sort("system:time_start", False)
        )

        img = col.first()

        if img.getInfo() is not None:
            return img, d

    return None, None
