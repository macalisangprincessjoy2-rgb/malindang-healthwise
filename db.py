import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import unquote, urlparse


DB_PATH = Path(
    os.environ.get('MALINDANG_SQLITE_PATH', Path(__file__).with_name('health_app.db'))
)
DATABASE_URL = os.environ.get('DATABASE_URL', '').strip()


class HybridRow(Mapping):
    def __init__(self, values):
        self._values = tuple(values.values())
        self._mapping = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._mapping)

    def __len__(self):
        return len(self._mapping)

    def keys(self):
        return self._mapping.keys()


class MySQLResult:
    def __init__(self, cursor):
        self.lastrowid = cursor.lastrowid
        self._cursor = cursor
        if cursor.description is None:
            cursor.close()
            self._cursor = None

    def fetchone(self):
        row = self._cursor.fetchone()
        self._cursor.close()
        return HybridRow(row) if row is not None else None

    def fetchall(self):
        rows = self._cursor.fetchall()
        self._cursor.close()
        return [HybridRow(row) for row in rows]


class MySQLConnection:
    is_mysql = True

    def __init__(self, connection):
        self._connection = connection

    @staticmethod
    def _convert_placeholders(statement):
        converted = []
        quote_char = None
        escaped = False
        for char in statement:
            if quote_char:
                converted.append(char)
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == quote_char:
                    quote_char = None
            elif char in ("'", '"', '`'):
                quote_char = char
                converted.append(char)
            elif char == '?':
                converted.append('%s')
            else:
                converted.append(char)
        return ''.join(converted)

    def execute(self, statement, parameters=()):
        cursor = self._connection.cursor()
        cursor.execute(self._convert_placeholders(statement), parameters)
        return MySQLResult(cursor)

    def executemany(self, statement, parameters):
        cursor = self._connection.cursor()
        cursor.executemany(self._convert_placeholders(statement), parameters)
        return MySQLResult(cursor)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def using_mysql():
    return bool(DATABASE_URL)


def is_mysql_connection(connection):
    return bool(getattr(connection, 'is_mysql', False))


def get_db_connection():
    if not DATABASE_URL:
        connection = sqlite3.connect(DB_PATH)
        connection.row_factory = sqlite3.Row
        return connection

    parsed = urlparse(DATABASE_URL)
    if parsed.scheme not in ('mysql', 'mysql+pymysql'):
        raise ValueError('DATABASE_URL must use the mysql:// or mysql+pymysql:// scheme.')
    if not parsed.hostname or not parsed.path.strip('/'):
        raise ValueError('DATABASE_URL must include a MySQL host and database name.')

    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as error:
        raise RuntimeError('PyMySQL is required when DATABASE_URL is configured.') from error

    connection = pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=unquote(parsed.username or ''),
        password=unquote(parsed.password or ''),
        database=unquote(parsed.path.lstrip('/')),
        charset='utf8mb4',
        cursorclass=DictCursor,
        connect_timeout=10,
        autocommit=False,
    )
    return MySQLConnection(connection)
