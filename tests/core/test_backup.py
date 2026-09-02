import os
import pytest
from pathlib import Path
import sqlite3
import subprocess
import psutil

from indi_allsky.backup import IndiAllskyDatabaseBackup
from indi_allsky.exceptions import BackupFailure

def test_init(flask_app, db):
    config = {'VARLIB_FOLDER': '/tmp/custom'}
    backup = IndiAllskyDatabaseBackup(config)
    assert backup.config == config
    assert backup.varlib_folder_p == Path('/tmp/custom')
    assert backup.backup_folder_p == Path('/var/lib/indi-allsky/backup')

def test_init_default(flask_app, db):
    backup = IndiAllskyDatabaseBackup({})
    assert backup.varlib_folder_p == Path('/var/lib/indi-allsky')
    assert backup.backup_folder_p == Path('/var/lib/indi-allsky/backup')

def test_checkAvailableSpace_pass(flask_app, db, mocker):
    backup = IndiAllskyDatabaseBackup({})
    
    # Mock psutil
    mock_partition = mocker.MagicMock()
    mock_partition.mountpoint = '/'
    
    mock_partition2 = mocker.MagicMock()
    mock_partition2.mountpoint = '/home'
    
    mocker.patch('psutil.disk_partitions', return_value=[mock_partition, mock_partition2])
    
    mock_usage = mocker.MagicMock()
    mock_usage.total = 2000 * 1024 * 1024 # 2000 MB
    mocker.patch('psutil.disk_usage', return_value=mock_usage)
    
    # Should not raise
    backup.checkAvailableSpace()

def test_checkAvailableSpace_fail(flask_app, db, mocker):
    backup = IndiAllskyDatabaseBackup({})
    
    # Mock psutil
    mock_partition = mocker.MagicMock()
    mock_partition.mountpoint = '/var'
    
    mocker.patch('psutil.disk_partitions', return_value=[mock_partition])
    
    mock_usage = mocker.MagicMock()
    mock_usage.total = 500 * 1024 * 1024 # 500 MB (less than 1000)
    mocker.patch('psutil.disk_usage', return_value=mock_usage)
    
    with pytest.raises(BackupFailure) as excinfo:
        backup.checkAvailableSpace()
    assert 'Not enough available space on /var' in str(excinfo.value)

def test_getFolderFilesByExt(flask_app, db, tmp_path):
    backup = IndiAllskyDatabaseBackup({})
    
    # Create some files
    (tmp_path / 'test.gz').touch()
    (tmp_path / 'test.sqlite').touch()
    (tmp_path / 'test.txt').touch()
    
    sub = tmp_path / 'sub'
    sub.mkdir()
    (sub / 'test2.gz').touch()
    (sub / 'test2.txt').touch()
    
    file_list = []
    backup._getFolderFilesByExt(str(tmp_path), file_list, extension_list=['gz', 'sqlite'])
    
    paths = {p.relative_to(tmp_path) for p in file_list}
    assert paths == {Path('test.gz'), Path('test.sqlite'), Path('sub/test2.gz')}

def test_expireBackups(flask_app, db, tmp_path):
    backup = IndiAllskyDatabaseBackup({})
    backup.backup_folder_p = tmp_path
    
    for i in range(10):
        f = tmp_path / f'backup_{i}.gz'
        f.touch()
        # Set modify time to i
        os.utime(str(f), (i, i))
        
    backup.keep_backups = 3
    backup.expireBackups()
    
    remaining = list(tmp_path.iterdir())
    assert len(remaining) == 3
    # The newest should be 7, 8, 9
    names = {f.name for f in remaining}
    assert names == {'backup_7.gz', 'backup_8.gz', 'backup_9.gz'}

def test_db_backup(flask_app, db, tmp_path, mocker):
    backup = IndiAllskyDatabaseBackup({})
    backup.backup_folder_p = tmp_path
    
    mocker.patch.object(backup, 'checkAvailableSpace')
    mocker.patch.object(backup, 'expireBackups')
    
    # Mock _miscDb.setState
    mock_setState = mocker.patch.object(backup._miscDb, 'setState')
    
    # Mock sqlite3.connect
    mock_backup_conn = mocker.MagicMock()
    mocker.patch('sqlite3.connect', return_value=mock_backup_conn)
    
    # Mock db.engine.raw_connection
    mock_raw_connection = mocker.MagicMock()
    mocker.patch('indi_allsky.backup.db.engine.raw_connection', return_value=mock_raw_connection)
    
    # Mock chmod
    mock_chmod = mocker.patch('pathlib.Path.chmod')
    
    # Mock subprocess.run
    mock_run = mocker.patch('subprocess.run')
    
    result = backup.db_backup()
    
    mock_setState.assert_called_once()
    assert mock_setState.call_args[0][0] == 'BACKUP_DB_TS'
    
    mock_raw_connection.backup.assert_called_once_with(mock_backup_conn)
    mock_raw_connection.close.assert_called_once()
    mock_backup_conn.close.assert_called_once()
    
    mock_chmod.assert_called_once_with(0o640)
    mock_run.assert_called_once()
    assert 'gzip' in mock_run.call_args[0][0][0]
    
    backup.expireBackups.assert_called_once()
    
    assert result.endswith('.gz')
    assert result.startswith(str(tmp_path))

def test_db_backup_fail(flask_app, db, tmp_path, mocker):
    backup = IndiAllskyDatabaseBackup({})
    backup.backup_folder_p = tmp_path
    
    mocker.patch.object(backup, 'checkAvailableSpace')
    mocker.patch.object(backup._miscDb, 'setState')
    
    mocker.patch('sqlite3.connect')
    mock_raw_connection = mocker.MagicMock()
    mocker.patch('indi_allsky.backup.db.engine.raw_connection', return_value=mock_raw_connection)
    mocker.patch('pathlib.Path.chmod')
    
    mocker.patch('subprocess.run', side_effect=OSError("Boom"))
    
    with pytest.raises(BackupFailure) as excinfo:
        backup.db_backup()
    
    assert 'Backup compress failed' in str(excinfo.value)
