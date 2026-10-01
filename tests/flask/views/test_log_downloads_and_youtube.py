from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path


def test_log_download_endpoints(flask_app, system_db):
    client = flask_app.test_client()

    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True

    with patch.dict(flask_app.config, {"LOGIN_DISABLED": True}), \
         patch("indi_allsky.flask.views.current_user", mock_user):

        # 1. Main log download - file missing
        res_missing = client.get("/indi-allsky/log/download")
        assert res_missing.status_code == 200
        assert b"does not exist" in res_missing.data

        # 2. Main log download - file exists
        mock_stat = MagicMock()
        mock_stat.st_size = 500
        with patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "stat", return_value=mock_stat), \
             patch("io.open", mock_open(read_data=b"Log contents line 1\nLog contents line 2\n")):
            res_log = client.get("/indi-allsky/log/download")
            assert res_log.status_code == 200

        # 3. Webapp log download
        res_webapp = client.get("/indi-allsky/log/webapp_download")
        assert res_webapp.status_code == 200

        # 4. Syslog download
        res_syslog = client.get("/indi-allsky/log/syslog_download")
        assert res_syslog.status_code == 200

        # 5. Kern log download
        res_kern = client.get("/indi-allsky/log/kern_download")
        assert res_kern.status_code == 200

        # 6. Indiserver log download
        res_indi = client.get("/indi-allsky/log/indiserver_download")
        assert res_indi.status_code == 200

        # 7. Upgrade log download
        res_upgrade = client.get("/indi-allsky/log/upgrade_download")
        assert res_upgrade.status_code == 200
