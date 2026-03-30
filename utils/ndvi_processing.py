import ee

def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule :
    - NDVI moyen sur la parcelle
    - proportion de pixels NDVI > seuil (uniquement si veg_mask != None)

    Paramètres :
    - ndvi_img : ee.Image NDVI
    - veg_mask : ee.Image booléenne (NDVI > 0.25) ou None en mode comparaison
    - geom : géométrie shapely de la parcelle
    """

    # Convertir géométrie shapely → géométrie Earth Engine
    geom_ee = ee.Geometry.Polygon(list(geom.exterior.coords))

    # -------------------------------------------------------
    # ✅ Calcul NDVI moyen (toujours exécuté)
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
    # ✅ CAS 1 : veg_mask = None → mode comparaison
    #   → on renvoie NDVI moyen et pas de proportion
    # -------------------------------------------------------
    if veg_mask is None:
        return ndvi_mean, None

    # -------------------------------------------------------
    # ✅ CAS 2 : veg_mask fourni → calcul proportion NDVI>seuil
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
