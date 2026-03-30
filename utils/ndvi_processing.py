import ee
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import transform

def shapely_to_ee(geom):
    """Convertit toutes géométries Shapely → EarthEngine (Polygon/MultiPolygon)."""

    # retirer Z si présent
    def strip_z(x, y, z=None):
        return (x, y)

    geom2d = transform(strip_z, geom)

    if isinstance(geom2d, Polygon):
        return ee.Geometry.Polygon([list(geom2d.exterior.coords)])

    elif isinstance(geom2d, MultiPolygon):
        parts = []
        for poly in geom2d:
            parts.append([list(poly.exterior.coords)])
        return ee.Geometry.MultiPolygon(parts)

    return None


def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule :
      - NDVI moyen
      - proportion NDVI > 0.25
    Compatible Polygon / MultiPolygon
    """

    geom_ee = shapely_to_ee(geom)
    if geom_ee is None:
        return None, None

    # ✅ Clip obligatoire (corrige NDVI=None lorsque les dalles ne se superposent que partiellement)
    ndvi_local = ndvi_img.clip(geom_ee)
    veg_local = veg_mask.clip(geom_ee) if veg_mask is not None else None

    # ✅ NDVI MOYEN
    mean_dict = ndvi_local.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e10
    ).getInfo()

    ndvi_mean = mean_dict.get("NDVI", None)
    if ndvi_mean is not None:
        ndvi_mean = float(ndvi_mean)

    # ✅ Mode comparaison
    if veg_local is None:
        return ndvi_mean, None

    # ✅ Proportion NDVI > 0.25
    veg_dict = veg_local.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=geom_ee,
        scale=10,
        maxPixels=1e10
    ).getInfo()

    veg_prop = veg_dict.get("VEG", None)
    if veg_prop is not None:
        veg_prop = float(veg_prop)

    return ndvi_mean, veg_prop
