import ee
import numpy as np

def zonal_stats_ndvi(ndvi_img, veg_mask, geom):

    geom_ee = ee.Geometry.Polygon(list(geom.exterior.coords))

    # mean NDVI
    mean_dict = ndvi_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e9
    ).getInfo()

    veg_dict = veg_mask.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e9
    ).getInfo()

    ndvi = mean_dict.get("NDVI", None)
    veg = veg_dict.get("VEG", None)

    if ndvi is not None:
        ndvi = float(ndvi)
    if veg is not None:
        veg = float(veg)

    return ndvi, veg
