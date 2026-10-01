from datetime import datetime, timedelta
import pytest
from sqlalchemy.orm.exc import NoResultFound

from indi_allsky.flask.miscDb import miscDb
from indi_allsky.flask.models import NotificationCategory, IndiAllSkyDbNotificationTable


def test_misc_db_camera(app):
    with app.app_context():
        misc_db = miscDb({})
        metadata = {
            'name': 'Test ASI Camera',
            'serialNumber': 'SN12345678',
            'connected': True,
        }

        # Add camera by serial
        camera = misc_db.addCamera(metadata)
        assert camera.name == 'Test ASI Camera'
        assert camera.serialNumber == 'SN12345678'

        # Match camera again
        camera2 = misc_db.addCamera(metadata)
        assert camera2.id == camera.id


def test_misc_db_state(app):
    with app.app_context():
        misc_db = miscDb({})

        # Plaintext state
        misc_db.setState('TEST_KEY', 'test_value')
        assert misc_db.getState('TEST_KEY') == 'test_value'

        # Encrypted state
        misc_db.setEncryptedState('ENC_KEY', 'secret_data')
        assert misc_db.getState('ENC_KEY') == 'secret_data'

        # Remove state
        misc_db.removeState('TEST_KEY')
        with pytest.raises(NoResultFound):
            misc_db.getState('TEST_KEY')


def test_misc_db_notification(app):
    with app.app_context():
        misc_db = miscDb({})

        notice = misc_db.addNotification(
            category=NotificationCategory.GENERAL,
            item='system',
            notification='System online',
            expire=timedelta(minutes=10),
        )
        assert notice is not None

        # Adding same notification while active returns None
        assert misc_db.addNotification(
            category=NotificationCategory.GENERAL,
            item='system',
            notification='System online duplicate',
            expire=timedelta(minutes=10),
        ) is None

        # Clear notification
        misc_db.clearNotification(NotificationCategory.GENERAL, 'system')
        active_notice = IndiAllSkyDbNotificationTable.query.filter(
            IndiAllSkyDbNotificationTable.item == 'system',
            IndiAllSkyDbNotificationTable.category == NotificationCategory.GENERAL,
            IndiAllSkyDbNotificationTable.expireDate > datetime.now(),
        ).first()
        assert active_notice is None


def test_misc_db_long_term_keogram_data(app):
    with app.app_context():
        misc_db = miscDb({})
        pixels = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128), (50, 50, 50)]

        entry = misc_db.add_long_term_keogram_data(
            exp_date=datetime.now(),
            camera_id=1,
            rgb_pixel_list=pixels,
        )
        assert entry.r1 == 255
        assert entry.g2 == 255
        assert entry.b3 == 255
