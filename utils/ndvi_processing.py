import ee

def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule :
    - NDVI moyen sur la parcelle
    - Proportion NDVI > 0.25 (uniquement si veg_mask != None)

    Paramètres :
        ndvi_img : ee.Image NDVI (band 'NDVI')
        veg_mask : ee.Image booléenne (band 'VEG') OU None en comparaison
        geom     : géométrie shapely de la parcelle

    Retour :
        (ndvi_mean, veg_prop)
        veg_prop = None si veg_mask = None (mode comparaison)
    """

    # Convertir shapely → Earth Engine Geometry
    geom_ee = ee.Geometry.Polygon(list(geom.exterior.coords))

    # -------------------------------------------------------
    # ✅ Calcul NDVI moyen (toujours calculé)
    # -------------------------------------------------------
    mean_dict = ndvi_img.reduceRegion(
        reducer = ee.Reducer.mean(),
        geometry = geom_ee,
        scale = 10,
        maxPixels = 1e9
    ).getInfo()

    ndvi_mean = mean_dict.get("NDVI", None)
    if ndvi_mean is not None:
        ndvi_mean = float(ndvi_mean)

    # -------------------------------------------------------
    # ✅ Mode comparaison → pas de veg_mask
    # -------------------------------------------------------
    if veg_mask is None:
        return ndvi_mean, None

    # -------------------------------------------------------
    # ✅ Mode analyse simple → calcul proportion NDVI > 0.25
    # -------------------------------------------------------
    veg_dict = veg_mask.reduceRegion(
        reducer = ee.Reducer.mean(),
        geometry = geom_ee,
        scale = 10,
        maxPixels = 1e9
    ).getInfo()

    veg_prop = veg_dict.get("VEG", None)
    if veg_prop is not None:
        veg_prop = float(veg_prop)

    return ndvi_mean, veg_prop
