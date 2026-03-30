import ee
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
from shapely.ops import transform

def shapely_to_ee(geom):
    """
    Convertit toutes les géométries Shapely en géométries EarthEngine valides.
    - Polygon
    - MultiPolygon
    - GeometryCollection
    """

    # ✅ Retire la 3e dimension si présente
    def strip_z(x, y, z=None):
        return (x, y)

    geom2d = transform(strip_z, geom)

    # ✅ CAS 1 : Polygon simple
    if isinstance(geom2d, Polygon):
        return ee.Geometry.Polygon([list(geom2d.exterior.coords)])

    # ✅ CAS 2 : MultiPolygon
    elif isinstance(geom2d, MultiPolygon):
        parts = []
        for poly in geom2d.geoms:
            parts.append([list(poly.exterior.coords)])
        return ee.Geometry.MultiPolygon(parts)

    # ✅ CAS 3 : GeometryCollection → on extrait uniquement les polygones
    elif isinstance(geom2d, GeometryCollection):
        parts = []
        for geomPart in geom2d.geoms:
            if isinstance(geomPart, Polygon):
                parts.append([list(geomPart.exterior.coords)])
            elif isinstance(geomPart, MultiPolygon):
                for poly in geomPart.geoms:
                    parts.append([list(poly.exterior.coords)])
        if len(parts) == 1:
            return ee.Geometry.Polygon(parts[0])
        return ee.Geometry.MultiPolygon(parts)

    # ✅ Autres géométries non supportées
    return None


def zonal_stats_ndvi(ndvi_img, veg_mask, geom):
    """
    Calcule NDVI moyen + proportion NDVI > 0.25
    Compatible Polygon, MultiPolygon, GeometryCollection
    """

    # ✅ Convertit la géométrie Shapely en geometry EE
    geom_ee = shapely_to_ee(geom)

    if geom_ee is None:
        return None, None

    # ✅ CLIP obligatoire pour éviter NDVI=None
    ndvi_local = ndvi_img.clip(geom_ee)
    veg_local  = veg_mask.clip(geom_ee) if veg_mask is not None else None

    # ✅ NDVI moyen
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
