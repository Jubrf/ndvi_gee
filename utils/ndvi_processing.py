import ee

def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule :
    - NDVI moyen de la parcelle
    - Proportion NDVI > seuil (seulement si veg_mask != None)

    geom : shapely geometry
    """

    # Convertir la géométrie Shapely en géométrie Earth Engine
    geom_ee = ee.Geometry.Polygon(list(geom.exterior.coords))

    # -------------------------------------------------------
    # ✅ NDVI MOYEN (toujours calculé)
    # -------------------------------------------------------
    mean_dict = ndvi_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e9
    ).getInfo()

    ndvi_mean = mean_dict.get("NDVI", None)
    if ndvi_mean is not None:
        ndvi_mean = float(ndvi_mean)

    # -------------------------------------------------------
    # ✅ CAS COMPARATEUR : veg_mask = None → on renvoie juste NDVI
    # -------------------------------------------------------
    if veg_mask is None:
        return ndvi_mean, None

    # -------------------------------------------------------
    # ✅ MODE ANALYSE SIMPLE : on calcule proportion NDVI>seuil
    # -------------------------------------------------------
    veg_dict = veg_mask.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e9
    ).getInfo()

    veg_prop = veg_dict.get("VEG", None)
    if veg_prop is not None:
        veg_prop = float(veg_prop)

    return ndvi_mean, veg_prop
