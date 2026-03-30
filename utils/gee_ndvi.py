def get_available_s2_dates(aoi_geom, max_days=120):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=max_days)

    col = (ee.ImageCollection("COPERNICUS/S2_SR")
           .filterBounds(aoi_geom)
           .filterDate(str(start), str(today))
           .sort("system:time_start", False))

    timestamps = col.aggregate_array("system:time_start").getInfo()

    dates = []
    for t in timestamps:
        d = datetime.datetime.utcfromtimestamp(t/1000).date()
        if d not in dates:
            dates.append(d)

    return sorted(dates, reverse=True)


def get_closest_s2_image(aoi_geom, target_date, max_days=120):
    if isinstance(target_date, str):
        target_date = datetime.datetime.strptime(target_date, "%Y-%m-%d").date()

    for delta in range(0, max_days+1):

        d = target_date - datetime.timedelta(days=delta)
        start = f"{d}T00:00"
        end   = f"{d}T23:59"

        col = (ee.ImageCollection("COPERNICUS/S2_SR")
               .filterBounds(aoi_geom)
               .filterDate(start, end)
               .filter("SCL != 9")
               .filter("SCL != 8")
               .sort("system:time_start", False))

        img = col.first()
        if img.getInfo() is not None:
            return img, d

    return None, None
