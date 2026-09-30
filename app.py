import csv
import hmac
import io
import json
import os
from pathlib import Path
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid

from flask import Flask, jsonify, render_template, request, redirect, url_for, session, send_file, abort, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

from community_health_concerns import COMMUNITY_HEALTH_CONCERNS
from health_system import assess_patient, normalize_symptom_text
from ml_module import MODEL_PATH, evaluate_model, predict_risk, retrain_model
from db import DB_PATH, get_db_connection, is_mysql_connection, using_mysql
from survey_questionnaire import (
    QUESTION_CODES,
    QUESTION_SECTIONS,
    QUESTIONNAIRE,
    RESPONDENT_GOAL,
    RESPONDENT_TYPES,
    SCALE,
    SEX_OPTIONS,
)
import rule_repository

app = Flask(__name__)

_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    _secret_key = secrets.token_hex(32)
    print(
        'WARNING: SECRET_KEY is not set. Using a random key generated for this '
        'process only -- existing sessions will be invalidated on every restart. '
        'Set the SECRET_KEY environment variable for a real deployment.'
    )
app.secret_key = _secret_key

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    # Set SESSION_COOKIE_SECURE=true in the environment once the app is served
    # over HTTPS -- it stays off by default so local http://127.0.0.1 dev
    # keeps working.
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '').lower() == 'true',
)

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW = timedelta(minutes=5)


def _login_is_locked(username):
    now = datetime.now(timezone.utc)
    cutoff = (now - LOGIN_LOCKOUT_WINDOW).isoformat()

    connection = get_db_connection()
    db_count = connection.execute(
        'SELECT COUNT(*) FROM login_attempts WHERE username = ? AND failed_at >= ?',
        (username, cutoff),
    ).fetchone()[0]
    connection.close()

    return db_count >= LOGIN_MAX_ATTEMPTS


def _record_failed_login(username):
    now = datetime.now(timezone.utc)
    connection = get_db_connection()
    connection.execute(
        'DELETE FROM login_attempts WHERE failed_at < ?',
        ((now - LOGIN_LOCKOUT_WINDOW).isoformat(),),
    )
    connection.execute(
        'INSERT INTO login_attempts (username, failed_at) VALUES (?, ?)',
        (username, now.isoformat()),
    )
    connection.commit()
    connection.close()


def _clear_login_attempts(username):
    connection = get_db_connection()
    connection.execute('DELETE FROM login_attempts WHERE username = ?', (username,))
    connection.commit()
    connection.close()

DATASET_PATH = Path(__file__).with_name('dataset').joinpath('health_assessment_dataset.csv')
PASSWORD_HASH_METHOD = 'scrypt:32768:8:1'


def hash_password(password):
    return generate_password_hash(password, method=PASSWORD_HASH_METHOD)

BARANGAYS_BY_MUNICIPALITY = {
    'Don Victoriano': [
        'Bagumbang', 'Gandawan', 'Lake Duminagat', 'Lalud', 'Lampasan',
        'Liboron', 'Maramat', 'Napangan', 'Nueva Vista', 'Petian', 'Siloy',
    ],
    'Tangub City': ['Owayan', 'Hoyohoy'],
}

# facility_type drives both display grouping (barangay-level shown first, as
# the nearest option; hospital shown last, as the emergency-escalation
# option) and the ordering in matching_facilities() below.
FACILITY_TYPE_BARANGAY = 'Barangay Health Station'
FACILITY_TYPE_HEALTH_OFFICE = 'Municipal/City Health Office'
FACILITY_TYPE_HOSPITAL = 'Hospital'
# Priority for sorting a resident's matched facility list, nearest/first-contact first.
FACILITY_TYPE_ORDER = {FACILITY_TYPE_BARANGAY: 0, FACILITY_TYPE_HEALTH_OFFICE: 1, FACILITY_TYPE_HOSPITAL: 2}

DEFAULT_FACILITIES = [
    # Verified against public sources -- see the citation next to each entry.
    # 5-bed capacity, converted from the municipal Rural Health Unit by
    # Republic Act No. 7329 (elibrary.judiciary.gov.ph/thebookshelf/showdocs/2/3233).
    ('Don Victoriano Health Infirmary', 'Don Victoriano', '', 'Municipal-level facility (5-bed capacity); the RHU converted into this infirmary under RA 7329.', FACILITY_TYPE_HEALTH_OFFICE),
    ('Owayan Barangay Health Station', 'Tangub City', 'Owayan', 'First-contact facility', FACILITY_TYPE_BARANGAY),
    ('Hoyohoy Barangay Health Station', 'Tangub City', 'Hoyohoy', 'First-contact facility', FACILITY_TYPE_BARANGAY),
    # City-level health office (healthcarephilippines.com/directory/tangub-city-health-office/).
    ('Tangub City Health Office', 'Tangub City', '', 'City-level health office; coordination and referral point for barangay health stations.', FACILITY_TYPE_HEALTH_OFFICE),
    # District hospital serving Tangub City, currently branded under the
    # provincial "Asenso Misamis Occidental" health system
    # (facebook.com/dmdtmh -- page name: "Asenso Misamis Occidental Second
    # District Hospital | Tangub City").
    ('Doña Maria D. Tan Memorial Hospital (Asenso Misamis Occidental Second District Hospital)', 'Tangub City', '', 'District hospital; destination for referrals beyond what barangay-level facilities or the Don Victoriano Health Infirmary can handle.', FACILITY_TYPE_HOSPITAL),
]

# Renamed from an earlier placeholder name -- kept so a startup against an
# already-seeded database renames the existing row instead of leaving a stale
# duplicate. Safe to delete once no deployment still has the old name.
_RENAMED_FACILITIES = {
    'Don Victoriano Municipal Health Office': 'Don Victoriano Health Infirmary',
}

DEFAULT_GUIDELINES = [
    ('Emergency signs', 'Difficulty breathing, chest pain, or severe dehydration require immediate referral.'),
    ('Waterborne symptoms', 'Prioritize hydration advice and health-professional consultation for diarrhea, vomiting, stomach pain, or suspected intestinal worms.'),
    ('Respiratory symptoms', 'Review persistent cough, asthma, smoke exposure, cold exposure, and dense fog exposure with a healthcare professional.'),
]

FACILITIES_BY_LOCATION = {
    'Don Victoriano': {
        'first_contact': 'Don Victoriano Barangay Health Station / Health Infirmary',
        'hospital': 'Don Victoriano Health Infirmary (5-bed capacity); cases beyond its capacity require further referral to Tangub City or Ozamiz City',
    },
    'Tangub City': {
        'first_contact': 'Tangub City Barangay Health Station',
        'hospital': 'Doña Maria D. Tan Memorial Hospital (Asenso Misamis Occidental Second District Hospital), Tangub City',
    },
}


def _ensure_column(connection, table, column, definition):
    if is_mysql_connection(connection):
        exists = connection.execute(
            f'SHOW COLUMNS FROM `{table}` LIKE ?', (column,)
        ).fetchone()
    else:
        exists = any(
            row['name'] == column
            for row in connection.execute(f'PRAGMA table_info({table})').fetchall()
        )
    if not exists:
        connection.execute(f'ALTER TABLE `{table}` ADD COLUMN {column} {definition}')


def _ensure_index(connection, table, index_name, columns):
    if is_mysql_connection(connection):
        exists = connection.execute(
            f'SHOW INDEX FROM `{table}` WHERE Key_name = ?', (index_name,)
        ).fetchone()
    else:
        exists = any(
            row['name'] == index_name
            for row in connection.execute(f'PRAGMA index_list({table})').fetchall()
        )
    if not exists:
        connection.execute(
            f'CREATE INDEX `{index_name}` ON `{table}` ({", ".join(columns)})'
        )


def _ensure_unique_index(connection, table, index_name, columns):
    if is_mysql_connection(connection):
        indexes = connection.execute(
            f'SHOW INDEX FROM `{table}` WHERE Key_name = ?', (index_name,)
        ).fetchall()
        is_unique = bool(indexes) and not indexes[0]['Non_unique']
    else:
        indexes = [
            row for row in connection.execute(f'PRAGMA index_list({table})').fetchall()
            if row['name'] == index_name
        ]
        is_unique = bool(indexes) and bool(indexes[0]['unique'])
    if is_unique:
        return

    if indexes:
        if is_mysql_connection(connection):
            connection.execute(f'DROP INDEX `{index_name}` ON `{table}`')
        else:
            connection.execute(f'DROP INDEX `{index_name}`')

    columns_sql = ', '.join(columns)
    duplicates = connection.execute(
        f"""
        SELECT 1 FROM `{table}`
        WHERE client_id IS NOT NULL
        GROUP BY {columns_sql}
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    if duplicates:
        raise RuntimeError(
            f'Cannot enforce unique offline assessment IDs: duplicate values in {table}.'
        )
    connection.execute(
        f'CREATE UNIQUE INDEX `{index_name}` ON `{table}` ({columns_sql})'
    )


def init_db(seed_defaults=True):
    connection = get_db_connection()
    primary_key = (
        'INTEGER PRIMARY KEY AUTO_INCREMENT'
        if is_mysql_connection(connection)
        else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {primary_key},
            username VARCHAR(150) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            full_name TEXT NOT NULL,
            age TEXT,
            municipality TEXT,
            barangay TEXT,
            address TEXT,
            gender TEXT,
            phone TEXT,
            email TEXT,
            birth_date TEXT,
            household_role TEXT,
            role VARCHAR(30) NOT NULL DEFAULT 'resident',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS assessments (
            id {primary_key},
            patient_name TEXT,
            age TEXT,
            municipality TEXT,
            barangay TEXT,
            address TEXT,
            risk_level TEXT,
            referral TEXT,
            priority TEXT,
            symptom_summary TEXT,
            gender TEXT,
            username VARCHAR(150),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS facilities (
            id {primary_key},
            name TEXT NOT NULL,
            municipality TEXT NOT NULL,
            barangay TEXT,
            description TEXT,
            facility_type VARCHAR(100) NOT NULL DEFAULT 'Health Facility',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS guidelines (
            id {primary_key},
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id {primary_key},
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id {primary_key},
            username TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS login_attempts (
            id {primary_key},
            username TEXT NOT NULL,
            failed_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS questionnaire_responses (
            id {primary_key},
            respondent_type VARCHAR(50) NOT NULL,
            barangay VARCHAR(150) NOT NULL,
            sex VARCHAR(20) NOT NULL,
            age INTEGER,
            comments TEXT,
            consent_version VARCHAR(30) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS questionnaire_answers (
            id {primary_key},
            response_id INTEGER NOT NULL,
            question_code VARCHAR(10) NOT NULL,
            rating INTEGER NOT NULL,
            UNIQUE (response_id, question_code),
            CONSTRAINT fk_questionnaire_answers_response
                FOREIGN KEY (response_id) REFERENCES questionnaire_responses(id)
        )
        """
    )
    _ensure_index(
        connection, 'login_attempts', 'idx_login_attempts_username_failed_at',
        ('username', 'failed_at'),
    )
    connection.execute(
        "DELETE FROM login_attempts WHERE failed_at <= ?",
        ((datetime.now(timezone.utc) - LOGIN_LOCKOUT_WINDOW).isoformat(),),
    )
    for column, definition in (
        ('gender', 'TEXT'), ('phone', 'TEXT'), ('email', 'TEXT'),
        ('birth_date', 'TEXT'), ('household_role', 'TEXT'),
        ('role', "VARCHAR(30) NOT NULL DEFAULT 'resident'"),
    ):
        _ensure_column(connection, 'users', column, definition)
    for column, definition in (
        ('gender', 'TEXT'), ('username', 'VARCHAR(150)'), ('client_id', 'VARCHAR(36)'),
    ):
        _ensure_column(connection, 'assessments', column, definition)
    _ensure_unique_index(
        connection, 'assessments', 'ux_assessments_username_client_id',
        ('username', 'client_id'),
    )
    _ensure_column(
        connection, 'facilities', 'facility_type',
        "VARCHAR(100) NOT NULL DEFAULT 'Health Facility'",
    )
    if seed_defaults:
        for old_name, new_name in _RENAMED_FACILITIES.items():
            connection.execute(
                'UPDATE facilities SET name = ? WHERE name = ?',
                (new_name, old_name),
            )
        # Seed each default facility independently so startup also adds newly
        # introduced defaults to an existing database.
        for name, municipality, barangay, description, facility_type in DEFAULT_FACILITIES:
            exists = connection.execute('SELECT 1 FROM facilities WHERE name = ?', (name,)).fetchone()
            if not exists:
                connection.execute(
                    'INSERT INTO facilities (name, municipality, barangay, description, facility_type) VALUES (?, ?, ?, ?, ?)',
                    (name, municipality, barangay, description, facility_type),
                )
            else:
                connection.execute(
                    "UPDATE facilities SET facility_type = ? WHERE name = ? AND facility_type = 'Health Facility'",
                    (facility_type, name),
                )
        if connection.execute('SELECT COUNT(*) FROM guidelines').fetchone()[0] == 0:
            connection.executemany('INSERT INTO guidelines (title, content) VALUES (?, ?)', DEFAULT_GUIDELINES)
        admin_password = os.environ.get('MALINDANG_ADMIN_PASSWORD')
        admin_reset_password = os.environ.get('MALINDANG_ADMIN_RESET_PASSWORD')
        admin_exists = connection.execute(
            "SELECT 1 FROM users WHERE username = 'admin'"
        ).fetchone() is not None
        if admin_reset_password and admin_exists:
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE username = 'admin'",
                (hash_password(admin_reset_password),),
            )
            print(
                'Admin password reset from MALINDANG_ADMIN_RESET_PASSWORD. '
                'Remove this environment variable after the deployment succeeds.'
            )
        elif not admin_exists and (admin_password or admin_reset_password):
            connection.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, 'admin')",
                (
                    'admin',
                    hash_password(admin_reset_password or admin_password),
                    'System Administrator',
                ),
            )
    connection.commit()

    # Core migration (docs/database/erd.md): the expert-system rule base and
    # Bisaya/English lexicon now live in real tables, seeded once from
    # health_system's hardcoded defaults, and are what the live app actually
    # reads from -- see assessment_from_form() below.
    rule_repository.ensure_schema(connection)
    if seed_defaults:
        rule_repository.seed_from_defaults(connection)

    connection.close()


def load_users():
    if not using_mysql() and not DB_PATH.exists():
        init_db()
    connection = get_db_connection()
    rows = connection.execute(
        "SELECT username, password_hash, full_name, age, municipality, barangay, address, gender, phone, email, birth_date, household_role, role FROM users"
    ).fetchall()
    connection.close()

    users = {}
    for row in rows:
        users[row['username']] = {
            'password': row['password_hash'],
            'full_name': row['full_name'],
            'age': row['age'],
            'municipality': row['municipality'],
            'barangay': row['barangay'],
            'address': row['address'],
            'gender': row['gender'],
            'phone': row['phone'],
            'email': row['email'],
            'birth_date': row['birth_date'],
            'household_role': row['household_role'],
            'role': row['role'],
        }
    return users


def load_records(username=None):
    """Return saved assessments, scoped to `username` unless it is None.

    `username=None` returns every record and must only be used from an
    admin-only code path (e.g. `/admin`'s aggregate counts) -- every
    resident-facing route must pass its own session username so residents
    never see each other's health records.
    """
    if not using_mysql() and not DB_PATH.exists():
        init_db()
    connection = get_db_connection()
    query = """
        SELECT id, patient_name, age, municipality, barangay, address, risk_level, referral, priority, symptom_summary, created_at
        FROM assessments
    """
    params = ()
    if username is not None:
        query += " WHERE username = ?"
        params = (username,)
    query += " ORDER BY id DESC"
    rows = connection.execute(query, params).fetchall()
    connection.close()

    records = []
    if rows:
        for row in rows:
            records.append({
                'id': row['id'],
                'full_name': row['patient_name'] or 'Unknown patient',
                'age': row['age'],
                'municipality': row['municipality'],
                'barangay': row['barangay'],
                'address': row['address'],
                'risk_level': row['risk_level'],
                'referral_recommendation': row['referral'],
                'priority': row['priority'],
                'symptom_text': row['symptom_summary'],
                'created_at': row['created_at'],
            })
        return records

    if rows or username is not None:
        # Either there genuinely are no saved records for this user, or the
        # table has rows but none for this user -- either way, don't fall
        # back to the shared sample dataset, which would otherwise look like
        # "this user's records."
        return []

    if not DATASET_PATH.exists():
        return []
    try:
        with DATASET_PATH.open('r', encoding='utf-8', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            return list(reader)
    except (OSError, csv.Error):
        return []


def load_assessment(assessment_id, username=None, allow_any=False):
    """Return one assessment by ID, scoped to `username` unless `allow_any` is True.

    `allow_any=True` is for admin oversight routes only -- every resident-facing
    route must pass its own session username and leave `allow_any` False, so a
    resident can never view another resident's assessment by guessing an ID.
    """
    connection = get_db_connection()
    if allow_any:
        row = connection.execute('SELECT * FROM assessments WHERE id = ?', (assessment_id,)).fetchone()
    else:
        row = connection.execute(
            'SELECT * FROM assessments WHERE id = ? AND username = ?', (assessment_id, username)
        ).fetchone()
    connection.close()
    if not row:
        return None
    record = dict(row)
    record['symptoms'] = [item.strip() for item in (record.get('symptom_summary') or '').split(',') if item.strip()]
    record['referral_facility'] = referral_facility(record.get('municipality', ''), record.get('barangay', ''))
    return record


def assessment_from_form(form_data):
    age = form_data.get('age', '').strip()
    bisaya_input = form_data.get('bisaya_symptoms', '').strip()
    symptoms = {
        key: key in form_data
        for key in (
            'fever', 'cough', 'difficulty_breathing', 'severe_fatigue',
            'chest_pain', 'diarrhea', 'vomiting', 'dehydration',
            'loss_of_appetite', 'body_weakness', 'stomach_pain',
            'intestinal_worms', 'cold_exposure', 'dense_fog',
            'smoke_exposure', 'chronic_cough', 'asthma',
        )
    }
    # Database-driven rule base + lexicon (docs/database/erd.md's EXPERT_RULES
    # /RULE_SYMPTOMS/SYMPTOM_TERMS), not the hardcoded fallback -- an admin
    # editing these tables directly changes what the live app does here.
    active_rules, phrase_map = rule_repository.get_active_rules_and_phrase_map()
    for key in normalize_symptom_text(bisaya_input, phrase_map=phrase_map):
        symptoms[key] = True
    result = assess_patient(symptoms, age=age or None, rules=active_rules)
    result.update(predict_risk(symptoms, age=age or None))
    return result


def save_assessment(username, form_data, client_id=None):
    if client_id:
        connection = get_db_connection()
        existing = connection.execute(
            'SELECT id FROM assessments WHERE username = ? AND client_id = ?',
            (username, client_id),
        ).fetchone()
        connection.close()
        if existing:
            return assessment_from_form(form_data), existing['id']

    result = assessment_from_form(form_data)
    user_data = load_users().get(username, {})
    connection = get_db_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO assessments (patient_name, age, municipality, barangay, address, risk_level, referral, priority, symptom_summary, gender, username, client_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_data.get('full_name', 'Patient'), result.get('age') or '',
                user_data.get('municipality', ''), user_data.get('barangay', ''),
                user_data.get('address', ''), result.get('risk_level', 'Low'),
                result.get('referral', 'Routine consultation / monitoring'),
                result.get('priority', 'Scheduled visit'),
                ', '.join(result.get('symptoms', [])) or form_data.get('bisaya_symptoms', ''),
                user_data.get('gender', ''),
                username,
                client_id,
            ),
        )
    except Exception:
        if not client_id:
            connection.close()
            raise
        connection.rollback()
        existing = connection.execute(
            'SELECT id FROM assessments WHERE username = ? AND client_id = ?',
            (username, client_id),
        ).fetchone()
        if not existing:
            connection.close()
            raise
        connection.close()
        return result, existing['id']
    connection.commit()
    connection.close()
    log_activity(username, 'assessment_created', f'Assessment {cursor.lastrowid}')
    return result, cursor.lastrowid


def referral_facility(municipality, barangay):
    facility = FACILITIES_BY_LOCATION.get(municipality, {})
    if municipality == 'Tangub City' and barangay in {'Owayan', 'Hoyohoy'}:
        first_contact = f'{barangay} Barangay Health Station'
    else:
        first_contact = facility.get('first_contact', 'Nearest available barangay health facility')
    return {
        'first_contact': first_contact,
        'hospital': facility.get('hospital', 'Nearest open hospital'),
        'location': f'{barangay}, {municipality}' if barangay and municipality else municipality,
    }


def load_reference_data():
    connection = get_db_connection()
    facilities = connection.execute(
        'SELECT name, municipality, barangay, description, facility_type FROM facilities ORDER BY municipality, barangay'
    ).fetchall()
    guidelines = connection.execute(
        'SELECT title, content FROM guidelines ORDER BY id'
    ).fetchall()
    connection.close()
    return facilities, guidelines


def get_location_referral(facilities, municipality, barangay):
    """Choose the best configured first-contact facility for a resident's area.

    This is a barangay/municipality match, not a live distance calculation:
    facility coordinates and verified travel routes are not stored by the app.
    """
    if not municipality:
        return None

    candidates = [
        dict(facility)
        for facility in facilities
        if facility['municipality'].casefold() == municipality.casefold()
    ]
    if not candidates:
        return None

    def sort_key(facility):
        exact_barangay = bool(
            barangay
            and facility.get('barangay')
            and facility['barangay'].casefold() == barangay.casefold()
        )
        facility_type_priority = FACILITY_TYPE_ORDER.get(
            facility.get('facility_type'), len(FACILITY_TYPE_ORDER)
        )
        return (not exact_barangay, facility_type_priority, facility['name'].casefold())

    candidates.sort(key=sort_key)
    recommended = candidates[0]
    hospital = next(
        (
            facility for facility in candidates
            if facility.get('facility_type') == FACILITY_TYPE_HOSPITAL
        ),
        None,
    )
    return {
        'facility': recommended,
        'hospital': hospital,
        'location': ', '.join(part for part in (barangay, municipality) if part),
        'matched_barangay': bool(
            barangay
            and recommended.get('barangay')
            and recommended['barangay'].casefold() == barangay.casefold()
        ),
    }


def log_activity(username, action, details=''):
    connection = get_db_connection()
    connection.execute(
        'INSERT INTO activity_logs (username, action, details) VALUES (?, ?, ?)',
        (username, action, details),
    )
    connection.commit()
    connection.close()


def admin_required():
    return session.get('role') == 'admin'


@app.before_request
def restrict_admin_to_research_monitoring():
    if not admin_required():
        return None

    allowed_paths = {
        '/',
        '/admin',
        '/admin-login',
        '/admin/survey/export',
        '/admin/survey/responses',
        '/logout',
        '/offline.html',
        '/service-worker.js',
    }
    if request.path in allowed_paths or request.path.startswith('/static/'):
        return None

    if request.path.startswith('/api/'):
        return jsonify({'error': 'Administrators can only access research survey monitoring.'}), 403
    return redirect(url_for('admin_dashboard'))


init_db(seed_defaults=os.environ.get('MALINDANG_SKIP_DB_SEED') != '1')
users = load_users()


@app.route('/')
def index():
    if 'username' in session:
        if admin_required():
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/service-worker.js')
def service_worker():
    response = send_from_directory(
        app.static_folder, 'service-worker.js', mimetype='application/javascript'
    )
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Cache-Control'] = 'no-cache'
    return response


@app.route('/offline.html')
def offline_page():
    return send_from_directory(app.static_folder, 'offline.html')


def render_questionnaire(error=None, form_data=None, submitted=False):
    csrf_token = session.get('_survey_csrf_token')
    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        session['_survey_csrf_token'] = csrf_token
    return render_template(
        'survey.html',
        error=error,
        form_data=form_data or {},
        submitted=submitted,
        question_sections=QUESTION_SECTIONS,
        scale=SCALE,
        respondent_types=RESPONDENT_TYPES,
        barangays_by_municipality=BARANGAYS_BY_MUNICIPALITY,
        sex_options=SEX_OPTIONS,
        csrf_token=csrf_token,
    )


@app.route('/survey', methods=['GET', 'POST'])
def research_survey():
    if request.method == 'GET':
        return render_questionnaire()

    form_data = request.form
    csrf_token = session.get('_survey_csrf_token', '')
    if not csrf_token or not hmac.compare_digest(
        csrf_token, form_data.get('csrf_token', '')
    ):
        return render_questionnaire(
            'Ni-expire na o wala ma-verify kining porma. Palihog susiha pag-usab ang imong mga tubag ug isumiter pag-usab.',
            form_data,
        ), 400

    respondent_type = form_data.get('respondent_type', '')
    barangay = form_data.get('barangay', '').strip()
    sex = form_data.get('sex', '')
    age_text = form_data.get('age', '').strip()
    comments = form_data.get('comments', '').strip()
    allowed_types = {value for value, _ in RESPONDENT_TYPES}
    allowed_barangays = {
        barangay
        for barangays in BARANGAYS_BY_MUNICIPALITY.values()
        for barangay in barangays
    }

    if respondent_type not in allowed_types:
        return render_questionnaire('Palihog pilia ang matang sa motubag.', form_data), 400
    if barangay not in allowed_barangays:
        return render_questionnaire('Palihog pilia ang imong barangay gikan sa listahan.', form_data), 400
    if sex not in SEX_OPTIONS:
        return render_questionnaire('Palihog pilia ang lalaki o babaye.', form_data), 400
    if age_text:
        try:
            age = int(age_text)
        except ValueError:
            return render_questionnaire('Isulod ang hustong edad gikan sa 0 hangtod 120.', form_data), 400
        if age < 0 or age > 120:
            return render_questionnaire('Isulod ang hustong edad gikan sa 0 hangtod 120.', form_data), 400
    else:
        age = None
    if len(comments) > 2000:
        return render_questionnaire('Dili molapas sa 2,000 ka karakter ang mga komento.', form_data), 400
    if form_data.get('consent') != 'yes':
        return render_questionnaire('Palihog kumpirmaha nga boluntaryo ang imong pag-apil sa dili pa isumiter ang mga tubag.', form_data), 400

    ratings = {}
    allowed_ratings = {str(value) for value, _, _ in SCALE}
    for code in QUESTION_CODES:
        value = form_data.get(f'answer_{code}', '')
        if value not in allowed_ratings:
            return render_questionnaire(
                'Tubaga ang matag pahayag pinaagi sa pagpili og usa ka marka gikan sa 1 hangtod 5.',
                form_data,
            ), 400
        ratings[code] = int(value)

    connection = get_db_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO questionnaire_responses
                (respondent_type, barangay, sex, age, comments, consent_version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (respondent_type, barangay, sex, age, comments or None, '2026-09-v1'),
        )
        response_id = cursor.lastrowid
        connection.executemany(
            'INSERT INTO questionnaire_answers (response_id, question_code, rating) VALUES (?, ?, ?)',
            [(response_id, code, rating) for code, rating in ratings.items()],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    session.pop('_survey_csrf_token', None)
    return render_questionnaire(submitted=True)


def _spreadsheet_safe(value):
    text = '' if value is None else str(value)
    if text.startswith(('=', '+', '-', '@', '\t', '\r')):
        return "'" + text
    return text


@app.route('/login', methods=['GET', 'POST'])
def login():
    return _handle_login()


@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    return _handle_login(admin_only=True)


def _handle_login(admin_only=False):
    global users
    users = load_users()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if username and _login_is_locked(username):
            return render_template(
                'login.html',
                error='Daghan na kaayo ka sayop nga pagsulay. Palihug hulat ug pipila ka minuto ug sulayi pag-usab.',
                admin_login=admin_only,
            )

        user_data = users.get(username)
        if (
            user_data
            and check_password_hash(user_data['password'], password)
            and (not admin_only or user_data.get('role') == 'admin')
        ):
            _clear_login_attempts(username)
            stored_hash = user_data['password']
            if not stored_hash.startswith(f'{PASSWORD_HASH_METHOD}$'):
                connection = get_db_connection()
                connection.execute(
                    'UPDATE users SET password_hash = ? WHERE username = ?',
                    (hash_password(password), username),
                )
                connection.commit()
                connection.close()
            session['username'] = username
            session['full_name'] = user_data['full_name']
            session['role'] = user_data.get('role', 'resident')
            session['municipality'] = user_data.get('municipality', '')
            session['barangay'] = user_data.get('barangay', '')
            log_activity(username, 'login')
            return redirect(url_for('admin_dashboard' if admin_only else 'dashboard'))

        if username:
            _record_failed_login(username)
        return render_template(
            'login.html',
            error='Sayop ang username o password.',
            admin_login=admin_only,
        )

    return render_template('login.html', admin_login=admin_only)


@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        new_password = request.form.get('new_password', '')
        user = load_users().get(username)
        if not user or not email or user.get('email', '').lower() != email or len(new_password) < 8:
            return render_template('reset_password.html', error='Susiha ang username, email, ug password (8 ka karakter minimum).')
        connection = get_db_connection()
        connection.execute('UPDATE users SET password_hash = ? WHERE username = ?', (hash_password(new_password), username))
        connection.commit()
        connection.close()
        _clear_login_attempts(username)
        log_activity(username, 'password_reset')
        return redirect(url_for('login'))
    return render_template('reset_password.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    global users
    users = load_users()

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        full_name = request.form.get('full_name', '').strip() or ' '.join(filter(None, (first_name, last_name)))
        age = request.form.get('age', '').strip()
        username = request.form.get('username', '').strip()
        municipality = request.form.get('municipality', '').strip()
        barangay = request.form.get('barangay', '').strip()
        address = request.form.get('address', '').strip()
        gender = request.form.get('gender', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        birth_date = request.form.get('birth_date', '').strip()
        household_role = request.form.get('household_role', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not all([full_name, age, username, municipality, barangay, address, password]):
            return render_template('register.html', error='Kinahanglan ang tanan nga impormasyon.')

        if password != confirm_password:
            return render_template('register.html', error='Dili parehas ang password.')

        if municipality not in BARANGAYS_BY_MUNICIPALITY or barangay not in BARANGAYS_BY_MUNICIPALITY[municipality]:
            return render_template('register.html', error='Pilia ang husto nga barangay para sa pinili nga munisipyo.')

        if username in users:
            return render_template('register.html', error='Naa na ang username nga imong gitipigan.')

        password_hash = hash_password(password)
        connection = get_db_connection()
        connection.execute(
            "INSERT INTO users (username, password_hash, full_name, age, municipality, barangay, address, gender, phone, email, birth_date, household_role) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (username, password_hash, full_name, age, municipality, barangay, address, gender, phone, email, birth_date, household_role),
        )
        connection.commit()
        connection.close()
        users = load_users()
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    if session.get('username'):
        log_activity(session['username'], 'logout')
    session.pop('username', None)
    session.pop('role', None)
    session.pop('municipality', None)
    session.pop('barangay', None)
    return render_template('logout.html')


@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login'))
    if admin_required():
        return redirect(url_for('admin_dashboard'))
    own_records = load_records(username=session['username'])
    records = own_records[:5]
    facilities, guidelines = load_reference_data()
    nearby_referral = get_location_referral(
        facilities,
        session.get('municipality', ''),
        session.get('barangay', ''),
    )
    return render_template(
        'index.html',
        username=session['username'],
        records=records,
        total_assessments=len(own_records),
        moderate_count=sum(record.get('risk_level') == 'Moderate' for record in own_records),
        high_count=sum(record.get('risk_level') == 'High' for record in own_records),
        facilities=facilities,
        guidelines=guidelines,
        community_health_concerns=COMMUNITY_HEALTH_CONCERNS,
        nearby_referral=nearby_referral,
    )


@app.route('/api/dashboard')
def dashboard_api():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorised'}), 401
    records = load_records(username=session['username'])
    return jsonify({
        'total_assessments': len(records),
        'moderate_count': sum(record.get('risk_level') == 'Moderate' for record in records),
        'high_count': sum(record.get('risk_level') == 'High' for record in records),
        'records': records[:5],
    })


@app.route('/api/preview', methods=['POST'])
def preview_assessment():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorised'}), 401
    result = assessment_from_form(request.form)
    return jsonify(result)


@app.route('/sync', methods=['POST'])
def sync_assessments():
    if 'username' not in session:
        return jsonify({'error': 'Unauthorised'}), 401
    if request.content_length and request.content_length > 131072:
        return jsonify({'error': 'Sync payload is too large'}), 413
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({'error': 'Sync payload must be an object'}), 400
    queued = payload.get('assessments', [])
    if not isinstance(queued, list):
        return jsonify({'error': 'assessments must be a list'}), 400
    if len(queued) > 50:
        return jsonify({'error': 'Sync at most 50 assessments per request'}), 413

    synced_ids = []
    rejected_ids = []
    symptom_fields = {
        'fever', 'cough', 'difficulty_breathing', 'severe_fatigue',
        'chest_pain', 'diarrhea', 'vomiting', 'dehydration',
        'loss_of_appetite', 'body_weakness', 'stomach_pain',
        'intestinal_worms', 'cold_exposure', 'dense_fog',
        'smoke_exposure', 'chronic_cough', 'asthma',
    }
    for item in queued:
        if not isinstance(item, dict):
            continue
        client_id = item.get('client_id') or item.get('local_id')
        try:
            client_id = str(uuid.UUID(str(client_id)))
        except (ValueError, TypeError, AttributeError):
            rejected_ids.append(str(item.get('local_id') or item.get('client_id') or '')[:80])
            continue

        data = item.get('data', {})
        if not isinstance(data, dict):
            rejected_ids.append(client_id)
            continue
        if isinstance(data.get('checked_symptoms'), list):
            data = {**data, **{key: 'on' for key in data['checked_symptoms']}}
        safe_data = {
            key: str(data[key])[:500]
            for key in ('age', 'bisaya_symptoms', *symptom_fields)
            if key in data and isinstance(data[key], (str, int))
        }
        if 'checked_symptoms' in data:
            safe_data['checked_symptoms'] = [
                key for key in data['checked_symptoms']
                if key in symptom_fields
            ] if isinstance(data['checked_symptoms'], list) else []
        save_assessment(session['username'], safe_data, client_id=client_id)
        synced_ids.append(client_id)

    if synced_ids:
        log_activity(session['username'], 'offline_sync', f'{len(synced_ids)} assessments')
    return jsonify({
        'synced_count': len(synced_ids),
        'synced_ids': synced_ids,
        'rejected_ids': rejected_ids,
    })


@app.route('/api/hospitals')
def hospitals_api():
    query = request.args.get('q', 'hospital near Don Victoriano').strip()
    try:
        request_url = 'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=10&q=' + quote(query)
        network_request = Request(request_url, headers={'User-Agent': 'MalindangHealthWise/1.0'})
        with urlopen(network_request, timeout=5) as response:
            return jsonify(json.loads(response.read().decode('utf-8')))
    except (OSError, ValueError, json.JSONDecodeError):
        connection = get_db_connection()
        rows = connection.execute("SELECT name, municipality, barangay, description FROM facilities WHERE lower(name) LIKE '%hospital%' OR lower(description) LIKE '%hospital%'").fetchall()
        connection.close()
        return jsonify([dict(row) for row in rows])


@app.route('/api/facilities')
def facilities_api():
    connection = get_db_connection()
    rows = connection.execute(
        'SELECT id, name, municipality, barangay, description FROM facilities ORDER BY municipality, barangay'
    ).fetchall()
    connection.close()
    return jsonify([dict(row) for row in rows])


@app.route('/admin/retrain', methods=['POST'])
def retrain_ml_model():
    if not admin_required():
        return redirect(url_for('login'))
    retrain_model(model_path=MODEL_PATH)
    metrics = evaluate_model()
    accuracy_note = f"cv accuracy {metrics['cv_accuracy']}%" if metrics['cv_accuracy'] is not None else metrics['note']
    log_activity(session['username'], 'model_retrained', f"{MODEL_PATH.name} ({accuracy_note})")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/model/download')
def download_ml_model():
    if not admin_required():
        return redirect(url_for('login'))
    if not MODEL_PATH.exists():
        retrain_model(model_path=MODEL_PATH)
    return send_file(MODEL_PATH, as_attachment=True, download_name='malindang-risk-model.pkl')


@app.route('/records')
def records():
    if 'username' not in session:
        return redirect(url_for('login'))
    own_records = load_records(username=session['username'])
    return render_template('records.html', username=session['username'], records=own_records)


@app.route('/assessments')
def assessments():
    if 'username' not in session:
        return redirect(url_for('login'))
    connection = get_db_connection()
    rows = connection.execute(
        'SELECT id, age, municipality, barangay, risk_level, priority, symptom_summary, created_at FROM assessments WHERE username = ? ORDER BY id DESC',
        (session['username'],),
    ).fetchall()
    connection.close()
    return render_template('assessments.html', username=session['username'], assessments=rows)


@app.route('/assessments/<int:assessment_id>')
def assessment_detail(assessment_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    assessment = load_assessment(assessment_id, username=session['username'], allow_any=admin_required())
    if not assessment:
        return redirect(url_for('assessments'))
    return render_template('assessment_detail.html', username=session['username'], assessment=assessment)


@app.route('/referral/<int:assessment_id>')
def referral_detail(assessment_id):
    if 'username' not in session:
        return redirect(url_for('login'))
    assessment = load_assessment(assessment_id, username=session['username'], allow_any=admin_required())
    if not assessment:
        return redirect(url_for('assessments'))
    return render_template('referral.html', username=session['username'], assessment=assessment)


@app.route('/admin')
def admin_dashboard():
    if not admin_required():
        return redirect(url_for('admin_login'))
    connection = get_db_connection()
    respondent_count = connection.execute(
        'SELECT COUNT(*) FROM questionnaire_responses'
    ).fetchone()[0]
    respondent_groups = connection.execute(
        'SELECT respondent_type, COUNT(*) AS response_count '
        'FROM questionnaire_responses GROUP BY respondent_type ORDER BY respondent_type'
    ).fetchall()
    rating_rows = connection.execute(
        'SELECT question_code, rating FROM questionnaire_answers'
    ).fetchall()
    connection.close()
    ratings_by_section = {}
    question_section = {
        code: section['title']
        for section in QUESTION_SECTIONS
        for code, _ in section['questions']
    }
    for row in rating_rows:
        section_title = question_section[row['question_code']]
        ratings_by_section.setdefault(section_title, []).append(row['rating'])
    survey_averages = [
        {
            'section': section['title'],
            'average': (
                round(sum(ratings_by_section[section['title']]) / len(ratings_by_section[section['title']]), 2)
                if ratings_by_section.get(section['title'])
                else None
            ),
        }
        for section in QUESTION_SECTIONS
    ]
    respondent_type_labels = dict(RESPONDENT_TYPES)
    respondent_groups = [
        {
            'label': respondent_type_labels[row['respondent_type']],
            'response_count': row['response_count'],
        }
        for row in respondent_groups
    ]
    return render_template(
        'admin.html',
        respondent_count=respondent_count,
        respondent_goal=RESPONDENT_GOAL,
        respondent_remaining=max(0, RESPONDENT_GOAL - respondent_count),
        respondent_progress=min(100, round(respondent_count * 100 / RESPONDENT_GOAL, 1)),
        respondent_groups=respondent_groups,
        survey_averages=survey_averages,
    )


@app.route('/admin/survey/export')
def export_survey_responses():
    if not admin_required():
        return redirect(url_for('admin_login'))

    connection = get_db_connection()
    responses = connection.execute(
        'SELECT id, respondent_type, barangay, sex, age, comments, created_at '
        'FROM questionnaire_responses ORDER BY id'
    ).fetchall()
    answers = connection.execute(
        'SELECT response_id, question_code, rating FROM questionnaire_answers '
        'ORDER BY response_id, question_code'
    ).fetchall()
    connection.close()

    answers_by_response = {}
    for answer in answers:
        answers_by_response.setdefault(answer['response_id'], {})[
            answer['question_code']
        ] = answer['rating']

    from openpyxl import Workbook

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = 'Questionnaire Responses'
    fieldnames = [
        'response_id', 'respondent_type', 'barangay', 'sex', 'age',
        *(code for code, _, _ in QUESTIONNAIRE),
        'comments', 'created_at',
    ]
    worksheet.append([_spreadsheet_safe(field) for field in fieldnames])

    for response in responses:
        row = [
            response['id'],
            _spreadsheet_safe(response['respondent_type']),
            _spreadsheet_safe(response['barangay']),
            _spreadsheet_safe(response['sex']),
            response['age'],
        ]
        answers = answers_by_response.get(response['id'], {})
        row.extend(_spreadsheet_safe(answers.get(code, '')) for code, _, _ in QUESTIONNAIRE)
        row.extend([
            _spreadsheet_safe(response['comments']),
            _spreadsheet_safe(response['created_at']),
        ])
        worksheet.append(row)

    output = io.BytesIO()
    workbook.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='malindang-questionnaire-responses.xlsx',
    )


@app.route('/admin/survey/responses')
def view_survey_responses():
    if not admin_required():
        return redirect(url_for('admin_login'))

    connection = get_db_connection()
    responses = connection.execute(
        'SELECT id, respondent_type, barangay, sex, age, comments, created_at '
        'FROM questionnaire_responses ORDER BY id DESC'
    ).fetchall()
    answer_rows = connection.execute(
        'SELECT response_id, question_code, rating FROM questionnaire_answers '
        'ORDER BY response_id, question_code'
    ).fetchall()
    connection.close()

    question_details = {
        code: {'statement': statement, 'section': section}
        for code, statement, section in QUESTIONNAIRE
    }
    answers_by_response = {}
    for answer in answer_rows:
        question = question_details[answer['question_code']]
        answers_by_response.setdefault(answer['response_id'], []).append({
            'statement': question['statement'],
            'section': question['section'],
            'rating': answer['rating'],
            'rating_label': next(
                label for value, label, _ in SCALE if value == answer['rating']
            ),
        })

    respondent_type_labels = dict(RESPONDENT_TYPES)
    questionnaire_responses = [
        {
            'id': response['id'],
            'respondent_type': respondent_type_labels.get(
                response['respondent_type'], response['respondent_type']
            ),
            'barangay': response['barangay'],
            'sex': response['sex'],
            'age': response['age'],
            'comments': response['comments'],
            'created_at': response['created_at'],
            'answers': answers_by_response.get(response['id'], []),
        }
        for response in responses
    ]
    return render_template(
        'survey_responses.html',
        responses=questionnaire_responses,
    )


@app.route('/admin/facilities', methods=['POST'])
def add_facility():
    if not admin_required():
        return redirect(url_for('login'))
    connection = get_db_connection()
    connection.execute(
        'INSERT INTO facilities (name, municipality, barangay, description) VALUES (?, ?, ?, ?)',
        (request.form.get('name', '').strip(), request.form.get('municipality', '').strip(), request.form.get('barangay', '').strip(), request.form.get('description', '').strip()),
    )
    connection.commit()
    connection.close()
    log_activity(session['username'], 'facility_update', request.form.get('name', '').strip())
    return redirect(url_for('admin_dashboard'))


@app.route('/assess', methods=['POST'])
def assess():
    if 'username' not in session:
        return redirect(url_for('login'))

    form_data = request.form
    age = form_data.get('age', '').strip()
    bisaya_input = form_data.get('bisaya_symptoms', '').strip()
    result = assessment_from_form(form_data)
    user_data = users.get(session.get('username', ''), {})
    result['referral_facility'] = referral_facility(
        user_data.get('municipality', ''), user_data.get('barangay', '')
    )

    client_id = form_data.get('client_id', '').strip()
    try:
        client_id = str(uuid.UUID(client_id)) if client_id else None
    except ValueError:
        abort(400, 'Invalid assessment submission identifier.')
    _, assessment_id = save_assessment(session['username'], form_data, client_id=client_id)
    result['assessment_id'] = assessment_id
    return render_template('processing.html', result=result, username=session['username'])


if __name__ == '__main__':
    app.run(
        host=os.environ.get('HOST', '0.0.0.0'),
        port=int(os.environ.get('PORT', '5000')),
        debug=False,
    )
