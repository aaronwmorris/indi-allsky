CREATE INDEX idx_image_createDate_YmdH on image (
 CAST(STRFTIME("%Y", "createDate") AS INTEGER),
 CAST(STRFTIME("%m", "createDate") AS INTEGER),
 CAST(STRFTIME("%d", "createDate") AS INTEGER),
 CAST(STRFTIME("%H", "createDate") AS INTEGER)
);


CREATE INDEX idx_video_dayDate_Ym on video (
 CAST(STRFTIME("%Y", "dayDate") AS INTEGER),
 CAST(STRFTIME("%m", "dayDate") AS INTEGER)
);


CREATE INDEX idx_mini_video_dayDate_Ym on mini_video (
 CAST(STRFTIME("%Y", "dayDate") AS INTEGER),
 CAST(STRFTIME("%m", "dayDate") AS INTEGER)
);

