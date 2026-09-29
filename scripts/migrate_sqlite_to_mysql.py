import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pymysql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / 'health_app.db'
TABLES_IN_COPY_ORDER = (
    'users',
    'assessments',
    'facilities',
    'guidelines',
    'activity_logs',
    'password_reset_tokens',
    'login_attempts',
    'RISK_LEVELS',
    'CONDITIONS',
    'SYMPTOMS',
    'SYMPTOM_TERMS',
    'EXPERT_RULES',
    'RULE_SYMPTOMS',
)


def migrate(source_path):
    if not os.environ.get('DATABASE_URL', '').strip():
        raise RuntimeError('Set DATABASE_URL to the target MySQL database before migrating.')
    if not source_path.is_file():
        raise FileNotFoundError(f'SQLite source database was not found: {source_path}')

    previous_skip_seed = os.environ.get('MALINDANG_SKIP_DB_SEED')
    os.environ['MALINDANG_SKIP_DB_SEED'] = '1'
    try:
        import app
        from db import get_db_connection, using_mysql
    finally:
        if previous_skip_seed is None:
            os.environ.pop('MALINDANG_SKIP_DB_SEED', None)
        else:
            os.environ['MALINDANG_SKIP_DB_SEED'] = previous_skip_seed

    if not using_mysql():
        raise RuntimeError('DATABASE_URL did not select the MySQL backend.')

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    target = get_db_connection()
    counts = {}
    try:
        available = {
            row['name']
            for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        for table in TABLES_IN_COPY_ORDER:
            exists = target.execute(f'SELECT COUNT(*) FROM `{table}`').fetchone()[0]
            if exists:
                raise RuntimeError(
                    f'Target table {table} is not empty; migration stopped without copying data.'
                )

        user_rows = source.execute('SELECT password_hash FROM users').fetchall() if 'users' in available else []
        for row in user_rows:
            stored_hash = row['password_hash'] or ''
            if not stored_hash.startswith(('scrypt:', 'pbkdf2:')) or '$' not in stored_hash:
                raise RuntimeError(
                    'The SQLite database contains a password value that is not a recognized '
                    'Werkzeug password hash. No data was copied.'
                )

        for table in TABLES_IN_COPY_ORDER:
            if table not in available:
                counts[table] = 0
                continue

            column_names = [
                row['name'] for row in source.execute(f'PRAGMA table_info(`{table}`)').fetchall()
            ]
            rows = source.execute(f'SELECT * FROM `{table}`').fetchall()
            if not rows:
                counts[table] = 0
                continue

            column_sql = ', '.join(f'`{column}`' for column in column_names)
            placeholders = ', '.join('?' for _ in column_names)
            insert_sql = f'INSERT INTO `{table}` ({column_sql}) VALUES ({placeholders})'
            target.executemany(
                insert_sql,
                [tuple(row[column] for column in column_names) for row in rows],
            )
            counts[table] = len(rows)

        target.commit()
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()

    app.init_db(seed_defaults=True)
    print(f'Migrated SQLite data from {source_path}:')
    for table, count in counts.items():
        print(f'  {table}: {count}')


def main():
    parser = argparse.ArgumentParser(
        description='Copy the existing SQLite application data to an empty MySQL database.'
    )
    parser.add_argument(
        '--source',
        type=Path,
        default=DEFAULT_SOURCE,
        help=f'SQLite database file (default: {DEFAULT_SOURCE})',
    )
    args = parser.parse_args()
    try:
        migrate(args.source)
    except (OSError, RuntimeError, ValueError, sqlite3.Error, pymysql.MySQLError) as error:
        print(f'Migration failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
