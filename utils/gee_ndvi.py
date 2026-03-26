import ee
import datetime
import numpy as np

def init_gee(service_account, private_key):
    credentials = ee.ServiceAccountCredentials(service_account, key_data=private_key)
    ee.Initialize(credentials)

def get_latest_s2_image(aoi_geom, max_days=30):
    today = datetime.date.today()

    for i in range(max_days + 1):
        day = today - datetime.timedelta(days=i)
        start = f"{day}T00:00"
        end   = f"{day}T23:59"

        col = (ee.ImageCollection("COPERNICUS/S2_SR")
               .filterBounds(aoi_geom)
               .filterDate(start, end)
               .filter("SCL != 9")  # remove high clouds
               .filter("SCL != 8")  # medium clouds
               .sort("SYSTEM:TIME_START", False))

        img = col.first()
        if img.getInfo() is not None:
            return img, day

    return None, None


def compute_ndvi(img):
    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    return ndvi


def compute_vegetation_mask(ndvi_image, threshold=0.3):
    return ndvi_image.gt(threshold).rename("VEG")
