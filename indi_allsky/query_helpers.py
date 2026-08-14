from sqlalchemy import and_
from sqlalchemy import exists


def panorama_source_image_not_excluded_clause(panorama_model, image_model):
    """Return a clause that rejects panoramas from excluded source images.

    Panorama rows have no foreign key to their rendered source image.  Local
    capture and Sync API rows do, however, share the camera and integer-second
    capture timestamp.  Keep unmatched panorama rows eligible so standalone
    panorama synchronization continues to work.
    """
    excluded_source_image = exists().where(
        and_(
            image_model.camera_id == panorama_model.camera_id,
            image_model.createDate == panorama_model.createDate,
            image_model.exclude.is_(True),
        )
    )

    return ~excluded_source_image
