import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest


@pytest.mark.parametrize('missing_keogram', [False, True])
def test_missing_startrails_are_reported_and_removed_separately(caplog, missing_keogram):
    source = Path(__file__).resolve().parents[1] / 'misc' / 'validate_db_entries.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    validator = next(node for node in tree.body
                     if isinstance(node, ast.ClassDef) and node.name == 'ValidateDatabaseEntries')
    models = {alias.name: MagicMock() for node in tree.body
              if isinstance(node, ast.ImportFrom) and node.module == 'indi_allsky.flask.models'
              for alias in node.names}
    valid_keogram = MagicMock()
    valid_keogram.validateFile.return_value = True
    valid_startrail = MagicMock()
    valid_startrail.validateFile.return_value = True
    absent_keogram = MagicMock()
    absent_keogram.validateFile.return_value = False
    absent_startrail = MagicMock()
    absent_startrail.validateFile.return_value = False
    entries = {
        'IndiAllSkyDbKeogramTable': [valid_keogram] + ([absent_keogram] if missing_keogram else []),
        'IndiAllSkyDbStarTrailsTable': [valid_startrail, absent_startrail],
    }
    for name, model in models.items():
        query = model.query
        query.filter.return_value = query
        query.order_by.return_value = query
        query.__iter__.return_value = entries.get(name, [])
        query.count.return_value = len(entries.get(name, []))
    session = MagicMock()
    approval = MagicMock(return_value='y')
    namespace = dict(models, db=SimpleNamespace(session=session),
                     logger=logging.getLogger('test.validate_db_entries'),
                     time=MagicMock(), sys=MagicMock(), sa_null=MagicMock(), sa_true=MagicMock(),
                     input=approval, print=MagicMock())
    exec(compile(ast.Module(body=[validator], type_ignores=[]), str(source), 'exec'), namespace)

    namespace['ValidateDatabaseEntries']().main()

    assert 'Keograms not found: {0:d}'.format(int(missing_keogram)) in caplog.messages
    assert 'Star trails not found: 1' in caplog.messages
    assert ('Removing 1 missing keogram entries' in caplog.messages) is missing_keogram
    assert 'Removing 1 missing star trail entries' in caplog.messages
    expected_deletions = ([call(absent_keogram)] if missing_keogram else []) + [call(absent_startrail)]
    assert session.delete.call_args_list == expected_deletions
    session.commit.assert_called_once_with()
    approval.assert_called_once()