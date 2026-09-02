import logging
from unittest.mock import MagicMock, patch
import sys


def test_wsgi_import():
    mock_handler = logging.NullHandler()
    with patch('logging.handlers.SysLogHandler', return_value=mock_handler):
        import indi_allsky.wsgi as wsgi_mod
        assert wsgi_mod.application is not None

        # Clean up handler from global logger to avoid test cross-contamination
        logger = logging.getLogger('indi_allsky')
        if mock_handler in logger.handlers:
            logger.removeHandler(mock_handler)
