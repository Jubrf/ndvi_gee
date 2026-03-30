import ee

def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule :
    - NDVI moyen sur la parcelle
    - Proportion NDVI > 0.25 (uniquement si veg_mask != None)

    Fonction compatible :
    ✅ Analyse simple -> veg_mask = image booléenne NDVI > 0.25
    ✅ Comparaison 2 dates -> veg_mask = None (pas de masque)
    """

    # Conversion de la géométrie shapely → Earth Engine
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
    # ✅ Mode comparaison → veg_prop = None
    # -------------------------------------------------------
    if veg_mask is None:
        return ndvi_mean, None

    # -------------------------------------------------------
    # ✅ Mode analyse simple → proportion NDVI > seuil
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
