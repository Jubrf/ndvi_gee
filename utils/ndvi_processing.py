import ee
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform

def shapely_to_ee(geom):
    """
    Convertit Polygon ou MultiPolygon shapely → ee.Geometry valide
    - enlève les trous
    - force 2D
    - gère multipolygones complexes
    """

    def strip_z(x, y, z=None):
        return (x, y)

    geom2d = transform(strip_z, geom)  # force Z → XY plano

    if isinstance(geom2d, Polygon):
        # on retire les trous pour éviter INVALID RING
        return ee.Geometry.Polygon([list(geom2d.exterior.coords)])

    elif isinstance(geom2d, MultiPolygon):
        parts = []
        for poly in geom2d:
            parts.append([list(poly.exterior.coords)])
        return ee.Geometry.MultiPolygon(parts)

    else:
        return None


def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule NDVI moyen + proportion NDVI>0.25
    Fonction robuste pour Polygon/MultiPolygon complexes
    """

    geom_ee = shapely_to_ee(geom)

    if geom_ee is None:
        return None, None

    # ✅ NDVI moyen
    mean_dict = ndvi_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e10
    ).getInfo()

    ndvi_mean = mean_dict.get("NDVI", None)
    if ndvi_mean is not None:
        ndvi_mean = float(ndvi_mean)

    # ✅ Mode comparaison
    if veg_mask is None:
        return ndvi_mean, None

    # ✅ proportion NDVI > 0.25
    veg_dict = veg_mask.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e10
    ).getInfo()

    veg_prop = veg_dict.get("VEG", None)
    if veg_prop is not None:
        veg_prop = float(veg_prop)

    return ndvi_mean, veg_prop
