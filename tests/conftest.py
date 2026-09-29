import os
import tempfile
from pathlib import Path


os.environ.pop('DATABASE_URL', None)
_TEST_DB_DIRECTORY = tempfile.TemporaryDirectory(prefix='malindang-tests-')
os.environ['MALINDANG_SQLITE_PATH'] = str(Path(_TEST_DB_DIRECTORY.name) / 'health_app.db')
