import ee
from shapely.geometry import Polygon, MultiPolygon

def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule NDVI moyen + proportion NDVI>0.25
    Fonction robuste : gère Polygon et MultiPolygon
    """

    # ✅ Conversion shapely → Earth Engine Geometry
    if isinstance(geom, Polygon):
        geom_ee = ee.Geometry.Polygon(list(geom.exterior.coords))

    elif isinstance(geom, MultiPolygon):
        parts = []
        for poly in geom:
            parts.append(ee.Geometry.Polygon(list(poly.exterior.coords)))
        geom_ee = ee.Geometry.MultiPolygon(parts)

    else:
        return None, None   # type inconnu

    # ✅ NDVI moyen
    mean_dict = ndvi_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e9
    ).getInfo()

    ndvi_mean = mean_dict.get("NDVI", None)
    if ndvi_mean is not None:
        ndvi_mean = float(ndvi_mean)

    # ✅ Mode comparaison → pas de calcul du masque
    if veg_mask is None:
        return ndvi_mean, None

    # ✅ Proportion NDVI>0.25
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
