from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from indi_allsky import constants
from indi_allsky.flask import db
from indi_allsky.flask.models import (
    IndiAllSkyDbImageTable,
    IndiAllSkyDbVideoTable,
    IndiAllSkyDbMiniVideoTable,
    IndiAllSkyDbStarTrailsVideoTable,
    IndiAllSkyDbPanoramaImageTable,
    IndiAllSkyDbPanoramaVideoTable,
    IndiAllSkyDbTaskQueueTable,
    TaskQueueQueue,
    TaskQueueState,
)
from indi_allsky.flask.views import (
    JsonLatestImageView,
    VirtualSkyView,
    LatestImageRedirect,
    LatestTimelapseVideoRedirect,
    LatestTimelapseVideoWatchRedirect,
    JsonImageLoopView,
    JsonPanoramaLoopView,
    JsonChartView,
    ImageViewerView,
    AjaxImageViewerView,
    FitsImageViewerView,
    AjaxFitsImageViewerView,
    GalleryViewerView,
    AjaxGalleryViewerView,
    VideoViewerView,
    AjaxVideoViewerView,
    MiniVideoViewerView,
    AjaxMiniVideoViewerView,
    AjaxMiniVideoDeleteView,
    TimelapseImageView,
    TimelapseVideoView,
    MiniTimelapseVideoView,
    MiniTimelapseGeneratorView,
    AjaxMiniTimelapseGeneratorView,
    AjaxUploadYoutubeView,
    ImageCircleHelperView,
)


def _always_valid(self, *args, **kwargs):
    return True


def test_latest_image_and_redirects_coverage(flask_app, system_db):
    """Test JsonLatestImageView, VirtualSkyView, and redirect view edge branches."""
    cam = system_db
    # Line 357: latest_image_p exists but st_mtime <= max_age
    with flask_app.test_request_context('/?camera_id=1&night=1&limit_s=100'):
        view = JsonLatestImageView()
        view.cameraSetup(cam.id)
        view.indi_allsky_config.update({
            'IMAGE_FOLDER': '/tmp',
            'IMAGE_FILE_TYPE': 'jpg',
            'FOCUS_MODE': True,
        })
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_mtime = (view.camera_now - timedelta(seconds=1000)).timestamp()
            res = view.get_objects()
            assert isinstance(res, dict)

    # Line 401: daytime capture without save, latest image file does not exist
    with flask_app.test_request_context('/?camera_id=1&night=0&limit_s=100'):
        view2 = JsonLatestImageView()
        view2.cameraSetup(cam.id)
        view2.daytime_capture = True
        view2.daytime_capture_save = False
        with patch.object(Path, 'exists', return_value=False):
            res2 = view2.get_objects()
            assert isinstance(res2, dict)

    # Line 444: getLatestImage with web_nonlocal_images and verify_admin_network True
    with flask_app.test_request_context('/?camera_id=1&night=1&limit_s=100'):
        view3 = JsonLatestImageView()
        view3.cameraSetup(cam.id)
        view3.web_nonlocal_images = True
        view3.web_local_images_admin = True
        with patch.object(view3, 'verify_admin_network', return_value=True):
            data = view3.getLatestImage(cam.id, history_seconds=100)
            assert isinstance(data, dict)

    # VirtualSkyView Lines 551-552: focus mode active with circle mask
    with flask_app.test_request_context('/?camera_id=1'):
        vview = VirtualSkyView(template_name='virtualsky.html')
        vview.setupSession()
        vview.indi_allsky_config.update({
            'IMAGE_CIRCLE_MASK': {'ENABLE': True, 'OPACITY': 100, 'OUTLINE': False, 'DIAMETER': 2500},
            'FOCUS_MODE': True,
            'LENS_OFFSET_X': 10,
            'LENS_OFFSET_Y': 20,
        })
        ctx = vview.get_context()
        assert ctx['overlay_image_mask'] is not None

    # Line 611: LatestImageRedirect with web_nonlocal_images
    img = IndiAllSkyDbImageTable(
        filename='test_redirect.jpg',
        dayDate=datetime.now(timezone.utc),
        createDate=datetime.now(timezone.utc),
        camera=cam,
        exposure=10.0,
        gain=100.0,
        adu=1000.0,
    )
    db.session.add(img)
    db.session.commit()

    with flask_app.test_request_context('/latest_image?camera_id=1'):
        l_redir = LatestImageRedirect()
        l_redir.web_nonlocal_images = True
        resp = l_redir.dispatch_request()
        assert resp.status_code == 302

    # Line 697: LatestTimelapseVideoRedirect with web_nonlocal_images
    vid = IndiAllSkyDbVideoTable(
        filename='test_vid.mp4',
        dayDate=datetime.now(timezone.utc),
        createDate=datetime.now(timezone.utc),
        camera=cam,
        night=True,
    )
    db.session.add(vid)
    db.session.commit()

    with flask_app.test_request_context('/latest_timelapse?camera_id=1'):
        v_redir = LatestTimelapseVideoRedirect()
        v_redir.web_nonlocal_images = True
        resp = v_redir.dispatch_request()
        assert resp.status_code == 302

    # Lines 843-845: LatestTimelapseVideoWatchRedirect with night filter
    with flask_app.test_request_context('/latest_watch?camera_id=1&night=1'):
        w_redir = LatestTimelapseVideoWatchRedirect()
        resp = w_redir.dispatch_request()
        assert resp.status_code == 302


def test_loops_and_charts_coverage(flask_app, system_db):
    """Test JsonImageLoopView, JsonPanoramaLoopView, and JsonChartView edge branches."""
    cam = system_db
    now = datetime.now(timezone.utc)

    # Add images
    img1 = IndiAllSkyDbImageTable(
        filename='loop1.jpg',
        dayDate=now,
        createDate=now,
        camera=cam,
        exposure=10.0,
        gain=100.0,
        adu=1000.0,
        width=1920,
        height=1080,
        sqm=18.5,
        data={'sensor_user_8': 18.0, 'sensor_user_9': 100.0, 'sensor_user_7': 18.2},
    )
    db.session.add(img1)
    db.session.commit()

    # JsonImageLoopView: Lines 1330-1333, 1351-1353, 1365, 1408-1409
    with flask_app.test_request_context('/?camera_id=1&virtualsky=1'):
        view = JsonImageLoopView()
        view.cameraSetup(cam.id)
        view.limit = 100
        view.web_nonlocal_images = True
        view.web_local_images_admin = False
        with patch.object(view, 'verify_admin_network', return_value=False):
            # Test getUrl ValueError branch (1351-1353)
            with patch.object(IndiAllSkyDbImageTable, 'getUrl', side_effect=ValueError('Relative path error')):
                res = view.getLoopImages(cam.id, now + timedelta(seconds=100), 900)
                assert isinstance(res, list)

            # Test SQM without sqm attribute (1408-1409)
            class NoSqmImg:
                data = {'sensor_user_8': 0.0, 'sensor_user_9': 0.0, 'sensor_user_7': 0.0}
            with patch.object(IndiAllSkyDbImageTable, 'query') as mock_q:
                mock_q.join.return_value.filter.return_value.order_by.return_value = [NoSqmImg()]
                sqm_res = view.getSqmData(cam.id, now + timedelta(minutes=10))
                assert isinstance(sqm_res, tuple)

    # JsonPanoramaLoopView: Lines 1608, 1614-1615, 1636-1637
    pano = IndiAllSkyDbPanoramaImageTable(
        filename='pano1.jpg',
        dayDate=now,
        createDate=now,
        camera=cam,
        exposure=10.0,
        gain=100.0,
        width=2000,
        height=500,
        data={},
    )
    db.session.add(pano)
    db.session.commit()

    with flask_app.test_request_context(f'/?camera_id={cam.id}&source_width=2000&source_height=500'):
        pview = JsonPanoramaLoopView()
        pview.cameraSetup(cam.id)
        pview.limit = 100
        pview.indi_allsky_config.update({'FISH2PANO': {'ENABLE': True}})
        # Mock Path.stat to return st_size == 0 for 1608
        with patch.object(Path, 'stat') as mock_stat:
            mock_stat.return_value.st_size = 0
            with patch.object(pview, 'getLoopImages', return_value=[{'id': pano.id, 'width': 2000, 'height': 500, 'url': '/p1'}]):
                pdata = pview.dispatch_request()
                assert pdata.status_code == 200

        # Mock getFilesystemPath raising OSError for 1614-1615
        with patch.object(IndiAllSkyDbPanoramaImageTable, 'getFilesystemPath', side_effect=OSError('Not found')):
            with patch.object(pview, 'getLoopImages', return_value=[{'id': pano.id, 'width': 2000, 'height': 500, 'url': '/p1'}]):
                pdata2 = pview.dispatch_request()
                assert pdata2.status_code == 200

    # JsonChartView: Lines 1895, 1897, 2140-2142
    with flask_app.test_request_context('/?camera_id=1'):
        cview = JsonChartView()
        cview.cameraSetup(cam.id)
        cview.indi_allsky_config.update({'TEMP_DISPLAY': 'f', 'SQM_ROI': [10, 20, 100, 200]})
        mock_img = MagicMock()
        mock_img.temp = 20.0
        mock_img.stars_rolling = 5
        mock_img.exposure = 5.0
        mock_img.gain = 100.0
        mock_img.detections = 0
        mock_img.jsqm = 18.0
        mock_img.data = {}
        mock_img.createDate = now
        mock_img.binmode = 1
        mock_p = MagicMock(spec=Path)
        mock_p.exists.return_value = True
        mock_p.suffix = '.jpg'
        mock_img.getFilesystemPath.return_value = mock_p

        import numpy as np
        dummy_arr = np.zeros((300, 300, 3), dtype=np.uint8)

        # Test TEMP_DISPLAY f and k and SQM_ROI lines 2140-2142
        with patch.object(IndiAllSkyDbImageTable, 'query') as mock_q, \
             patch('io.open', MagicMock()), \
             patch('simplejpeg.decode_jpeg', return_value=dummy_arr):
            mock_q.add_columns.return_value.join.return_value.filter.return_value.order_by.return_value = [mock_img]
            mock_q.join.return_value.filter.return_value.order_by.return_value.first.return_value = mock_img
            res_f = cview.getChartData(cam.id, now, 900)
            assert res_f['temp'][0]['y'] == ((20.0 * 9.0) / 5.0) + 32

            cview.indi_allsky_config['TEMP_DISPLAY'] = 'k'
            res_k = cview.getChartData(cam.id, now, 900)
            assert abs(res_k['temp'][0]['y'] - (20.0 + 273.15)) < 0.001


def test_image_fits_and_gallery_viewers_extended(flask_app, system_db):
    """Test ImageViewerView, FitsImageViewerView, and GalleryViewerView edge cases."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'

    # Line 4700: ImageViewerView admin local bypass
    with flask_app.test_request_context('/viewer?camera_id=1'):
        iview = ImageViewerView(template_name='image_viewer.html')
        iview.setupSession()
        iview.web_nonlocal_images = True
        iview.web_local_images_admin = True
        with patch.object(iview, 'verify_admin_network', return_value=True):
            ctx = iview.get_context()
            assert ctx['form_viewer'] is not None

    # Lines 4739-4742: AjaxImageViewerView nonlocal without admin network
    with flask_app.test_request_context('/ajax/image_viewer', method='POST', json={'CAMERA_ID': 1}):
        aiview = AjaxImageViewerView()
        aiview.cameraSetup(cam.id)
        aiview.web_nonlocal_images = True
        aiview.web_local_images_admin = True
        with patch.object(aiview, 'verify_admin_network', return_value=False):
            resp = aiview.dispatch_request()
            assert resp is not None

    # Line 4898: FitsImageViewerView admin local bypass
    with flask_app.test_request_context('/fits_viewer?camera_id=1'):
        fview = FitsImageViewerView(template_name='fits_viewer.html')
        fview.setupSession()
        fview.web_nonlocal_images = True
        fview.web_local_images_admin = True
        with patch.object(fview, 'verify_admin_network', return_value=True):
            fctx = fview.get_context()
            assert fctx['form_fits_viewer'] is not None

    # Lines 4934, 4969-4970, 4982-4989, 5011-5016, 5038-5049: AjaxFitsImageViewerView
    with flask_app.test_request_context('/ajax/fits_viewer', method='POST', json={'CAMERA_ID': 1, 'DAY_SELECT': 15, 'YEAR_SELECT': 2026, 'MONTH_SELECT': 9}):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            afview = AjaxFitsImageViewerView()
            afview.cameraSetup(cam.id)
            afview.web_nonlocal_images = True
            afview.web_local_images_admin = True
            with patch.object(afview, 'verify_admin_network', return_value=True):
                r_day = afview.dispatch_request()
                assert r_day.status_code == 200

    with flask_app.test_request_context('/ajax/fits_viewer', method='POST', json={'CAMERA_ID': 1, 'MONTH_SELECT': 9, 'YEAR_SELECT': 2026}):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            afview = AjaxFitsImageViewerView()
            afview.cameraSetup(cam.id)
            r_month = afview.dispatch_request()
            assert r_month.status_code == 200

    with flask_app.test_request_context('/ajax/fits_viewer', method='POST', json={'CAMERA_ID': 1, 'YEAR_SELECT': 2026}):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            afview = AjaxFitsImageViewerView()
            afview.cameraSetup(cam.id)
            r_year = afview.dispatch_request()
            assert r_year.status_code == 200

    with flask_app.test_request_context('/ajax/fits_viewer', method='POST', json={'CAMERA_ID': 1}):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            afview = AjaxFitsImageViewerView()
            afview.cameraSetup(cam.id)
            r_empty = afview.dispatch_request()
            assert r_empty is not None

    # Lines 5222, 5268-5273, 5278, 5345-5346, 5368-5369: GalleryViewerView and AjaxGalleryViewerView
    with flask_app.test_request_context('/gallery?camera_id=1'):
        gview = GalleryViewerView(template_name='gallery.html')
        gview.setupSession()
        gview.web_nonlocal_images = True
        gview.web_local_images_admin = True
        with patch.object(gview, 'verify_admin_network', return_value=True):
            gctx = gview.get_context()
            assert gctx['form_viewer'] is not None

    with flask_app.test_request_context('/ajax/gallery', method='POST', json={
        'CAMERA_ID': 1,
        'FILTER_ASI676MC_REPAIRED': True,
        'FILTER_ASI676MC_EXCLUDED': True,
        'FILTER_ASI676MC_FAILED': True,
        'MONTH_SELECT': 9,
        'YEAR_SELECT': 2026,
    }):
        agview = AjaxGalleryViewerView()
        agview.cameraSetup(cam.id)
        agview.indi_allsky_config.update({'IMAGE_ASI676MC_REPAIR': {'ENABLE': True, 'GALLERY_ENABLE': True}})
        agview.web_nonlocal_images = True
        agview.web_local_images_admin = True
        with patch('indi_allsky.asi676mc.camera_record_matches', return_value=True), \
             patch.object(agview, 'verify_admin_network', return_value=True):
            r_gal = agview.dispatch_request()
            assert r_gal.status_code == 200

    with flask_app.test_request_context('/ajax/gallery', method='POST', json={'CAMERA_ID': 1, 'YEAR_SELECT': 2026}):
        agview = AjaxGalleryViewerView()
        agview.cameraSetup(cam.id)
        r_gal_yr = agview.dispatch_request()
        assert r_gal_yr.status_code == 200


def test_videos_mini_videos_and_delete_branches(flask_app, system_db):
    """Test VideoViewerView, MiniVideoViewerView, and AjaxMiniVideoDeleteView edge cases."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'

    # VideoViewerView Line 5432, AjaxVideoViewerView Line 5468
    with flask_app.test_request_context('/video_viewer?camera_id=1'):
        vv = VideoViewerView(template_name='video_viewer.html')
        vv.setupSession()
        vv.web_nonlocal_images = True
        vv.web_local_images_admin = True
        with patch.object(vv, 'verify_admin_network', return_value=True):
            ctx = vv.get_context()
            assert ctx['form_video_viewer'] is not None

    with flask_app.test_request_context('/ajax/video_viewer', method='POST', json={'CAMERA_ID': 1}):
        avv = AjaxVideoViewerView()
        avv.cameraSetup(cam.id)
        avv.web_nonlocal_images = True
        avv.web_local_images_admin = True
        with patch.object(avv, 'verify_admin_network', return_value=True):
            resp = avv.dispatch_request()
            assert resp.status_code == 200

    # MiniVideoViewerView Line 5532, AjaxMiniVideoViewerView Line 5565
    with flask_app.test_request_context('/mini_video_viewer?camera_id=1'):
        mvv = MiniVideoViewerView(template_name='mini_video_viewer.html')
        mvv.setupSession()
        mvv.web_nonlocal_images = True
        mvv.web_local_images_admin = True
        with patch.object(mvv, 'verify_admin_network', return_value=True):
            ctx = mvv.get_context()
            assert ctx['form_mini_video_viewer'] is not None

    with flask_app.test_request_context('/ajax/mini_video_viewer', method='POST', json={'CAMERA_ID': 1}):
        amvv = AjaxMiniVideoViewerView()
        amvv.cameraSetup(cam.id)
        amvv.web_nonlocal_images = True
        amvv.web_local_images_admin = True
        with patch.object(amvv, 'verify_admin_network', return_value=True):
            resp = amvv.dispatch_request()
            assert resp.status_code == 200

    # AjaxMiniVideoDeleteView: Lines 5649-5650, 5695-5696
    mini_v = IndiAllSkyDbMiniVideoTable(
        filename='del_mini.mp4',
        dayDate=datetime.now(timezone.utc),
        createDate=datetime.now(timezone.utc),
        targetDate=datetime.now(timezone.utc),
        startDate=datetime.now(timezone.utc),
        endDate=datetime.now(timezone.utc),
        note='test note',
        camera=cam,
        data={'generation_task_id': 'invalid_int', 'generation_task_created': ''},
    )
    db.session.add(mini_v)
    # Add active upload task with malformed data for 5695-5696
    upload_t = IndiAllSkyDbTaskQueueTable(
        queue=TaskQueueQueue.UPLOAD,
        state=TaskQueueState.RUNNING,
        priority=100,
        data={'model': None, 'id': 'invalid_id'},
    )
    db.session.add(upload_t)
    db.session.commit()

    with flask_app.test_request_context('/admin/ajax/mini_video_delete', method='POST', json={'CAMERA_ID': cam.id, 'VIDEO_ID': mini_v.id}):
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('indi_allsky.flask.views._can_save_standard_configuration', return_value=True), \
             patch.object(mini_v, 'deleteAsset'):
            del_view = AjaxMiniVideoDeleteView()
            del_view.cameraSetup(cam.id)
            r_del = del_view.dispatch_request()
            assert r_del.status_code == 200


def test_youtube_video_views_and_generator_branches(flask_app, system_db):
    """Test AjaxUploadYoutubeView, TimelapseVideoView, and MiniTimelapseGeneratorView branches."""
    cam = system_db
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.username = 'admin'
    now = datetime.now(timezone.utc)

    # AjaxUploadYoutubeView Lines 11266-11267, 11269-11270, 11272-11273
    mv = IndiAllSkyDbMiniVideoTable(
        filename='mv.mp4',
        dayDate=now,
        createDate=now,
        targetDate=now,
        startDate=now,
        endDate=now,
        note='mv test',
        camera=cam,
    )
    stv = IndiAllSkyDbStarTrailsVideoTable(filename='stv.mp4', dayDate=now, createDate=now, camera=cam)
    pv = IndiAllSkyDbPanoramaVideoTable(filename='pv.mp4', dayDate=now, createDate=now, camera=cam)
    db.session.add_all([mv, stv, pv])
    db.session.commit()

    for asset_type, v_id in [(constants.MINI_VIDEO, mv.id), (constants.STARTRAIL_VIDEO, stv.id), (constants.PANORAMA_VIDEO, pv.id)]:
        with flask_app.test_request_context('/admin/ajax/upload_youtube', method='POST', json={
            'CAMERA_ID': cam.id,
            'VIDEO_ID': v_id,
            'ASSET_TYPE': asset_type,
        }):
            with patch('flask_login.utils._get_user', return_value=mock_user):
                uy_view = AjaxUploadYoutubeView()
                uy_view.cameraSetup(cam.id)
                r_uy = uy_view.dispatch_request()
                assert r_uy.status_code == 200

    # TimelapseImageView Line 11389: nonlocal admin bypass
    img = IndiAllSkyDbImageTable(
        filename='tl_img.jpg',
        dayDate=now,
        createDate=now,
        camera=cam,
        exposure=10.0,
        gain=100.0,
        adu=1000.0,
    )
    db.session.add(img)
    db.session.commit()

    with flask_app.test_request_context(f'/timelapse_image?id={img.id}&camera_id={cam.id}'):
        tiv = TimelapseImageView(template_name='timelapse_image.html')
        tiv.setupSession()
        tiv.web_nonlocal_images = True
        tiv.web_local_images_admin = True
        with patch.object(tiv, 'verify_admin_network', return_value=True):
            ctx_ti = tiv.get_context()
            assert ctx_ti['image_url'] != ''

    # TimelapseVideoView Lines 11473, 11486
    vid = IndiAllSkyDbVideoTable(
        filename='tl_vid.mp4',
        dayDate=now,
        createDate=now,
        camera=cam,
        night=True,
    )
    db.session.add(vid)
    db.session.commit()

    with flask_app.test_request_context(f'/timelapse_video?camera_id={cam.id}'):
        tvv = TimelapseVideoView(template_name='timelapse_video.html')
        tvv.setupSession()
        tvv.web_nonlocal_images = True
        tvv.web_local_images_admin = True
        with patch.object(tvv, 'verify_admin_network', return_value=True):
            ctx_tv = tvv.get_context()
            assert ctx_tv['video_id'] == vid.id

    # MiniTimelapseVideoView Lines 11532, 11538
    with flask_app.test_request_context(f'/mini_timelapse_video?id=99999&camera_id={cam.id}'):
        mtvv = MiniTimelapseVideoView(template_name='mini_timelapse_video.html')
        mtvv.setupSession()
        with patch.object(TimelapseVideoView, 'get_context', return_value={'video_url': 'http://vid', 'video_id': 99999}):
            ctx_mtv = mtvv.get_context()
            assert ctx_mtv.get('video_delete_allowed') is False

    # MiniTimelapseGeneratorView Lines 11644-11645, 11699, 11709, 11737, 11758, 11784
    with flask_app.test_request_context(f'/mini_timelapse_generator?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            mtgv = MiniTimelapseGeneratorView(template_name='mini_timelapse_generator.html')
            mtgv.setupSession()
            mtgv.indi_allsky_config.update({'FISH2PANO': {'ENABLE': False}, 'FFMPEG_BITRATE': 'invalid_bitrate'})
            ctx_mtg = mtgv.get_context()
            assert ctx_mtg['form_mini_timelapse'] is not None

    # AjaxMiniTimelapseGeneratorView Lines 11894, 11920
    with flask_app.test_request_context('/admin/ajax/mini_timelapse_generator', method='POST', json={
        'IMAGE_ID': img.id,
        'CAMERA_ID': cam.id,
        'PRE_SECONDS': 240,
        'POST_SECONDS': 120,
        'FRAMERATE': 10,
        'BITRATE': '5000k',
        'NOTE': '',
    }):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            amtgv = AjaxMiniTimelapseGeneratorView()
            amtgv.cameraSetup(cam.id)
            amtgv.indi_allsky_config.update({'FISH2PANO': {'ENABLE': True}})
            r_pan, c_pan = amtgv._queuePanoramaMiniVideo({'IMAGE_ID': img.id, 'CAMERA_ID': cam.id, 'PRE_SECONDS': 240, 'POST_SECONDS': 120, 'FRAMERATE': 10, 'BITRATE': '5000k', 'NOTE': ''})
            assert c_pan == 400

    # ImageCircleHelperView Lines 13758-13764: nonlocal admin bypass
    with flask_app.test_request_context(f'/admin/imagecircle?camera_id={cam.id}'):
        with patch('flask_login.utils._get_user', return_value=mock_user):
            ichv = ImageCircleHelperView(template_name='image_circle.html')
            ichv.setupSession()
            ichv.web_nonlocal_images = True
            ichv.web_local_images_admin = True
            with patch.object(ichv, 'verify_admin_network', return_value=True):
                ctx_ich = ichv.get_context()
                assert ctx_ich['form_imagecircle'] is not None
