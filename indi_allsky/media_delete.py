"""Keep video recovery from undoing an operator's explicit deletion."""
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from . import night_movie
from .utils import IndiAllSkyDateCalcs


def suppress_movie_repair(camera_id, date, night, panorama):
    from .flask import db
    try:
        night_movie.suppress_repair(camera_id, date, night, panorama)
    except IntegrityError:
        # A concurrent encoder may have just inserted the claim row.
        db.session.rollback()
        night_movie.suppress_repair(camera_id, date, night, panorama)


def suppress_deleted_local_product(entry):
    """Only explicit Sync API DELETE uses this hook, never upload replacement or expiry."""
    from .flask.models import IndiAllSkyDbPanoramaVideoTable as PanoramaMovie, IndiAllSkyDbVideoTable as Movie
    is_panorama = isinstance(entry, PanoramaMovie)
    if not is_panorama and not (isinstance(entry, Movie) and entry.night):
        return
    if entry.camera.local:
        suppress_movie_repair(entry.camera_id, entry.dayDate, entry.night, is_panorama)


def suppress_flushed_periods(config, camera_id, *, daytime_only=False):
    from .flask import db
    from .flask.models import (
        IndiAllSkyDbCameraTable as Camera,
        IndiAllSkyDbImageTable as Image,
        IndiAllSkyDbPanoramaImageTable as Panorama,
        IndiAllSkyDbPanoramaVideoTable as PanoramaMovie,
        IndiAllSkyDbVideoTable as Movie,
    )
    camera = db.session.get(Camera, camera_id)
    if not camera or not camera.local or camera.latitude is None or camera.longitude is None:
        return
    today = IndiAllSkyDateCalcs(config, [camera.latitude, camera.longitude, camera.elevation or 0]).getDayDate()
    retention = min(config.get('IMAGE_EXPIRE_DAYS', 10), config.get('TIMELAPSE_EXPIRE_DAYS', 365))
    for panorama, models in ((False, (Image, Movie)), (True, (Panorama, PanoramaMovie))):
        if daytime_only and not panorama:
            continue
        cutoff = today - timedelta(days=retention if panorama else min(retention, night_movie.RECENT_DAYS))
        # An encoder may have started from source images without publishing a movie row yet.
        periods = set()
        for model in models:
            query = db.session.query(model.dayDate, model.night).filter(
                model.camera_id == camera_id, model.dayDate >= cutoff, model.dayDate < today)
            if not panorama:
                query = query.filter(model.night.is_(True))
            elif daytime_only:
                query = query.filter(model.night.is_(False))
            periods.update(query.distinct())
        for date, night in sorted(periods):
            suppress_movie_repair(camera_id, date, night, panorama)
