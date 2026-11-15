"""Preserve an operator's bulk deletion when recent media are reconciled."""
from datetime import timedelta


def _mark(mark, *args):
    from sqlalchemy.exc import IntegrityError
    from .flask import db
    try:
        mark(*args)
    except IntegrityError:
        # A concurrent encoder may have just inserted the claim row.
        db.session.rollback()
        mark(*args)


def suppress_movie_repair(camera_id, date, night, panorama):
    from . import night_movie
    _mark(night_movie.suppress_repair, camera_id, date, night, panorama)


def suppress_deleted_local_product(entry):
    """Used by explicit Sync API DELETE, never by upload replacement or expiry."""
    from .flask.models import (
        IndiAllSkyDbVideoTable as Movie, IndiAllSkyDbPanoramaVideoTable as PanoramaMovie,
        IndiAllSkyDbKeogramTable as Keogram, IndiAllSkyDbStarTrailsTable as StarTrails,
        IndiAllSkyDbStarTrailsVideoTable as StarMovie,
    )
    stills = {Keogram: 'keogram', StarTrails: 'startrail', StarMovie: 'startrail_timelapse'}
    model = type(entry)
    if model not in (Movie, PanoramaMovie) and model not in stills:
        return
    if not entry.camera.local:
        return
    from . import derived_media, night_movie
    args = entry.camera_id, entry.dayDate, bool(entry.night)
    if model in stills:
        _mark(derived_media.suppress_repair, *args, stills[model])
    else:
        _mark(night_movie.suppress_repair, *args, model is PanoramaMovie)


def suppress_flushed_periods(config, camera_id, *, daytime_only=False):
    from .flask import db
    from .flask.models import (
        IndiAllSkyDbCameraTable as Camera, IndiAllSkyDbImageTable as Image,
        IndiAllSkyDbPanoramaImageTable as Panorama, IndiAllSkyDbVideoTable as Movie,
        IndiAllSkyDbPanoramaVideoTable as PanoramaMovie, IndiAllSkyDbKeogramTable as Keogram,
        IndiAllSkyDbStarTrailsTable as StarTrails, IndiAllSkyDbStarTrailsVideoTable as StarMovie,
    )
    from .utils import IndiAllSkyDateCalcs

    camera = db.session.get(Camera, camera_id)
    if not camera or not camera.local or camera.latitude is None or camera.longitude is None:
        return
    from . import derived_media, night_movie
    today = IndiAllSkyDateCalcs(config, [camera.latitude, camera.longitude, camera.elevation or 0]).getDayDate()
    days = min(config.get('IMAGE_EXPIRE_DAYS', 10), config.get('TIMELAPSE_EXPIRE_DAYS', 365))
    cutoff = today - timedelta(days=days)
    periods = set()
    # Include source-only periods: a repair may already be encoding and may
    # not yet have created a movie row. Don't suppress the ongoing period.
    for model in (Image, Panorama, Movie, PanoramaMovie, Keogram, StarTrails, StarMovie):
        query = db.session.query(model.dayDate, model.night).filter(
            model.camera_id == camera_id, model.dayDate >= cutoff, model.dayDate < today)
        if daytime_only:
            query = query.filter(model.night.is_(False))
        periods.update(query.distinct())

    for date, night in sorted(periods):
        args = camera_id, date, night
        _mark(night_movie.suppress_repair, *args, False)
        _mark(night_movie.suppress_repair, *args, True)
        _mark(derived_media.suppress_repair, *args)
