CREATE INDEX idx_image_createDate_Y on image (CAST(STRFTIME("%Y", "createDate") AS INTEGER));
CREATE INDEX idx_image_createDate_m on image (CAST(STRFTIME("%m", "createDate") AS INTEGER));
CREATE INDEX idx_image_createDate_d on image (CAST(STRFTIME("%d", "createDate") AS INTEGER));
CREATE INDEX idx_image_createDate_H on image (CAST(STRFTIME("%H", "createDate") AS INTEGER));

CREATE INDEX idx_video_dayDate_Y on video (CAST(STRFTIME("%Y", "dayDate") AS INTEGER));
CREATE INDEX idx_video_dayDate_m on video (CAST(STRFTIME("%m", "dayDate") AS INTEGER));
