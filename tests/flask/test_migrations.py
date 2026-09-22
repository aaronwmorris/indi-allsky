from sqlalchemy import inspect


def test_database_schema_and_tables_exist(flask_app, db):
    """Verify that all core tables are created in the active database engine."""
    with flask_app.app_context():
        inspector = inspect(db.engine)
        table_names = inspector.get_table_names()

        # Verify core tables are present in the SQLite database
        assert "user" in table_names
        assert "camera" in table_names
        assert "config" in table_names
        assert "image" in table_names
        assert "video" in table_names
        assert "notification" in table_names
        assert "taskqueue" in table_names


def test_camera_table_columns_parity(flask_app, db):
    """Ensure core columns exist in the active camera table schema."""
    with flask_app.app_context():
        inspector = inspect(db.engine)
        columns = [c["name"] for c in inspector.get_columns("camera")]
        assert "serialNumber" in columns
        assert "nightSunAlt" in columns
        assert "friendlyName" in columns
        assert "driver" in columns
