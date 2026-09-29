"""Database-backed storage for the expert-system rule base.

This is the "core migration" piece of docs/database/erd.md: CONDITIONS,
RISK_LEVELS, SYMPTOMS, SYMPTOM_TERMS, EXPERT_RULES, and RULE_SYMPTOMS now
live as real tables, and the live app loads its rules and its Bisaya/English
lexicon from them at request time instead of only from the hardcoded
`health_system.DEFAULT_RULES`/`DEFAULT_PHRASE_MAP` constants.

Those constants haven't gone away -- they're still the fallback every
existing caller (tests, scripts/generate_synthetic_dataset.py) uses when it
doesn't pass an explicit `rules`/`phrase_map` argument, and they're also
exactly what this module seeds the database with on first run, via
`seed_from_defaults()`. `tests/test_rule_repository.py` checks the two never
drift apart.

Deliberate scope note: this phase does NOT add admin CRUD screens for
editing rules/symptoms/conditions through the UI -- the tables exist and are
what the app actually reads from, but they're currently only written by the
one-time seed. Admin editing is a separate, later phase.
"""

from functools import lru_cache

from db import DB_PATH, get_db_connection, is_mysql_connection
from health_system import (
    BISAYA_SYMPTOM_MAP,
    DEFAULT_RULES,
    ENGLISH_PHRASE_MAP,
    health_risk_level,
)

# The canonical symptom vocabulary -- matches ml_module.FEATURES exactly.
SYMPTOM_KEYS = (
    'fever', 'cough', 'difficulty_breathing', 'severe_fatigue', 'chest_pain',
    'diarrhea', 'vomiting', 'dehydration', 'loss_of_appetite', 'body_weakness',
    'stomach_pain', 'intestinal_worms', 'cold_exposure', 'dense_fog',
    'smoke_exposure', 'chronic_cough', 'asthma',
)

RISK_LEVEL_SEED = (
    ('Low', 'Mild symptoms; routine monitoring.', 1),
    ('Moderate', 'Moderate symptoms; consult a health professional within 24 hours.', 2),
    ('High', 'Severe symptoms or emergency signs; immediate referral.', 3),
)

# Explicit seed data for the 25 default rules, hand-kept in sync with
# health_system.DEFAULT_RULES (lambdas can't be introspected to derive this
# automatically). `tests/test_rule_repository.py` is the safety net: it runs
# every rule scenario through both DEFAULT_RULES and the DB-loaded rules and
# asserts identical results.
#
# Each entry: (rule_id, symptom_keys (AND, all required), min_age,
#              weight, is_emergency_override, emergency_label, finding,
#              condition_type)
_SEED_RULE_DATA = [
    ('R01', ('fever',), None, 1, False, None, 'Fever', 'symptom'),
    ('R02', ('cough',), None, 1, False, None, 'Cough', 'symptom'),
    ('R03', ('difficulty_breathing',), None, 2, True, None, 'Difficulty Breathing', 'symptom'),
    ('R04', ('severe_fatigue',), None, 2, False, None, 'Severe Fatigue', 'symptom'),
    ('R05', ('chest_pain',), None, 3, True, None, 'Chest Pain', 'symptom'),
    ('R06', ('diarrhea',), None, 1, False, None, 'Diarrhea', 'symptom'),
    ('R07', ('vomiting',), None, 1, False, None, 'Vomiting', 'symptom'),
    ('R08', ('dehydration',), None, 3, True, 'Severe dehydration', 'Dehydration', 'symptom'),
    ('R09', ('loss_of_appetite',), None, 1, False, None, 'Loss Of Appetite', 'symptom'),
    ('R10', ('body_weakness',), None, 1, False, None, 'Body Weakness', 'symptom'),
    ('R11', ('stomach_pain',), None, 2, False, None, 'Stomach Pain', 'symptom'),
    ('R12', ('intestinal_worms',), None, 1, False, None, 'Intestinal Worms', 'symptom'),
    ('R13', ('cold_exposure',), None, 1, False, None, 'Cold Exposure', 'symptom'),
    ('R14', ('dense_fog',), None, 1, False, None, 'Dense Fog', 'symptom'),
    ('R15', ('smoke_exposure',), None, 1, False, None, 'Smoke Exposure', 'symptom'),
    ('R16', ('chronic_cough',), None, 2, False, None, 'Chronic Cough', 'symptom'),
    ('R17', ('asthma',), None, 2, False, None, 'Asthma', 'symptom'),
    ('R18', ('difficulty_breathing', 'chest_pain'), None, 2, True, None,
     'Possible acute respiratory distress', 'compound_pattern'),
    ('R19', ('diarrhea', 'vomiting', 'dehydration'), None, 2, True, None,
     'Acute gastrointestinal emergency pattern', 'compound_pattern'),
    ('R20', ('chronic_cough', 'smoke_exposure'), None, 1, False, None,
     'Chronic respiratory illness aggravated by smoke exposure', 'compound_pattern'),
    ('R21', ('asthma', 'cold_exposure'), None, 1, False, None,
     'Asthma exacerbation risk from cold/high-elevation exposure', 'compound_pattern'),
    ('R22', ('fever', 'chronic_cough'), None, 2, False, None,
     'Persistent fever with chronic cough (TB-screening pattern; refer for evaluation)', 'compound_pattern'),
    ('R23', ('dense_fog', 'difficulty_breathing'), None, 1, False, None,
     'High-elevation respiratory risk factor present', 'compound_pattern'),
    ('R24', ('intestinal_worms', 'loss_of_appetite', 'body_weakness'), None, 1, False, None,
     'Possible malnutrition risk from parasitic infection', 'compound_pattern'),
    ('R25', (), 65, 2, False, None,
     'Elderly (65+): increased vulnerability', 'demographic_risk'),
]


def ensure_schema(connection):
    """Create the rule-base tables if they don't already exist."""
    primary_key = (
        'INTEGER PRIMARY KEY AUTO_INCREMENT'
        if is_mysql_connection(connection)
        else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    )
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS RISK_LEVELS (
            risk_level_id {primary_key},
            level_name    VARCHAR(50) NOT NULL UNIQUE,
            description   TEXT,
            severity_rank INTEGER NOT NULL UNIQUE
        )
    """)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS CONDITIONS (
            condition_id   {primary_key},
            condition_name TEXT NOT NULL,
            condition_type TEXT,
            description    TEXT
        )
    """)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS SYMPTOMS (
            symptom_id   {primary_key},
            symptom_key  VARCHAR(100) NOT NULL UNIQUE,
            symptom_name VARCHAR(150) NOT NULL,
            description  TEXT
        )
    """)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS SYMPTOM_TERMS (
            term_id     {primary_key},
            symptom_id  INTEGER NOT NULL,
            bisaya_term VARCHAR(255) NOT NULL,
            CONSTRAINT fk_symptom_terms_symptom
                FOREIGN KEY (symptom_id) REFERENCES SYMPTOMS(symptom_id)
        )
    """)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS EXPERT_RULES (
            rule_id               {primary_key},
            rule_code              VARCHAR(20) NOT NULL UNIQUE,   -- 'R01'..'R25', matches docs/rule_base.md
            condition_id           INTEGER NOT NULL,
            risk_level_id          INTEGER NOT NULL,
            rule_name               TEXT NOT NULL,
            rule_description        TEXT,
            weight                  INTEGER NOT NULL DEFAULT 0,
            min_age                 INTEGER,   -- NULL unless the rule is age-gated (see R25)
            is_emergency_override   BOOLEAN NOT NULL DEFAULT 0,
            emergency_label         TEXT,      -- overrides the finding text shown when the emergency flag fires (see R08)
            is_active                BOOLEAN NOT NULL DEFAULT 1,
            created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_expert_rules_condition
                FOREIGN KEY (condition_id) REFERENCES CONDITIONS(condition_id),
            CONSTRAINT fk_expert_rules_risk_level
                FOREIGN KEY (risk_level_id) REFERENCES RISK_LEVELS(risk_level_id)
        )
    """)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS RULE_SYMPTOMS (
            rule_symptom_id {primary_key},
            rule_id         INTEGER NOT NULL,
            symptom_id      INTEGER NOT NULL,
            is_required     BOOLEAN NOT NULL DEFAULT 1,
            UNIQUE (rule_id, symptom_id),
            CONSTRAINT fk_rule_symptoms_rule
                FOREIGN KEY (rule_id) REFERENCES EXPERT_RULES(rule_id),
            CONSTRAINT fk_rule_symptoms_symptom
                FOREIGN KEY (symptom_id) REFERENCES SYMPTOMS(symptom_id)
        )
    """)
    connection.commit()


def _symptom_display_name(symptom_key):
    return symptom_key.replace('_', ' ').title()


def seed_from_defaults(connection):
    """Populate the rule-base tables from health_system's hardcoded defaults.

    Idempotent -- does nothing if EXPERT_RULES already has rows, so it's safe
    to call on every app startup alongside ensure_schema().
    """
    already_seeded = connection.execute('SELECT COUNT(*) FROM EXPERT_RULES').fetchone()[0]
    if already_seeded:
        return

    ignore_prefix = 'INSERT IGNORE' if is_mysql_connection(connection) else 'INSERT OR IGNORE'
    connection.executemany(
        f'{ignore_prefix} INTO RISK_LEVELS (level_name, description, severity_rank) VALUES (?, ?, ?)',
        RISK_LEVEL_SEED,
    )

    symptom_id_by_key = {}
    for key in SYMPTOM_KEYS:
        cursor = connection.execute(
            f'{ignore_prefix} INTO SYMPTOMS (symptom_key, symptom_name) VALUES (?, ?)',
            (key, _symptom_display_name(key)),
        )
        row = connection.execute('SELECT symptom_id FROM SYMPTOMS WHERE symptom_key = ?', (key,)).fetchone()
        symptom_id_by_key[key] = row[0]

    # All recognized phrases -- Bisaya and English alike -- go into
    # SYMPTOM_TERMS; the column is named after the ERD's `bisaya_term`, but
    # holds every recognized phrase regardless of language, same as
    # health_system.DEFAULT_PHRASE_MAP does in code.
    for phrase, key in {**BISAYA_SYMPTOM_MAP, **ENGLISH_PHRASE_MAP}.items():
        symptom_id = symptom_id_by_key.get(key)
        if symptom_id is None:
            continue  # phrase maps to a key outside SYMPTOM_KEYS; nothing to link to
        connection.execute(
            'INSERT INTO SYMPTOM_TERMS (symptom_id, bisaya_term) VALUES (?, ?)',
            (symptom_id, phrase),
        )

    risk_level_id_by_name = {
        row['level_name']: row['risk_level_id']
        for row in connection.execute('SELECT level_name, risk_level_id FROM RISK_LEVELS').fetchall()
    }

    for rule_code, required_keys, min_age, weight, is_emergency, emergency_label, finding, condition_type in _SEED_RULE_DATA:
        condition_insert = connection.execute(
            'INSERT INTO CONDITIONS (condition_name, condition_type, description) VALUES (?, ?, ?)',
            (finding, condition_type, f'Auto-migrated from health_system.DEFAULT_RULES rule {rule_code}.'),
        )
        condition_id = condition_insert.lastrowid

        # A rule's own weight alone -- via the same health_risk_level()
        # thresholds used for the aggregate score -- never reaches "High" on
        # any single rule (max weight is 3). That's expected and consistent:
        # is_emergency_override is the separate mechanism that actually
        # forces a High outcome (e.g. chest pain alone). risk_level_id here
        # is informational ("what this finding alone would suggest"), not
        # what drives the real aggregate result.
        risk_level_name = health_risk_level(weight)
        risk_level_id = risk_level_id_by_name[risk_level_name]

        rule_insert = connection.execute(
            """
            INSERT INTO EXPERT_RULES
                (rule_code, condition_id, risk_level_id, rule_name, rule_description,
                 weight, min_age, is_emergency_override, emergency_label, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (rule_code, condition_id, risk_level_id, finding, finding,
             weight, min_age, int(is_emergency), emergency_label),
        )
        rule_id = rule_insert.lastrowid

        for symptom_key in required_keys:
            connection.execute(
                'INSERT INTO RULE_SYMPTOMS (rule_id, symptom_id, is_required) VALUES (?, ?, 1)',
                (rule_id, symptom_id_by_key[symptom_key]),
            )

    connection.commit()


def _row_to_rule(row, required_keys):
    required_keys = tuple(required_keys)

    def when(symptoms, age):
        if not all(symptoms.get(key, False) for key in required_keys):
            return False
        if row['min_age'] is not None:
            try:
                if age is None or int(age) < row['min_age']:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    rule = {
        'id': row['rule_code'],
        'when': when,
        'weight': row['weight'],
        'finding': row['rule_name'],
    }
    if row['is_emergency_override']:
        rule['emergency'] = True
        if row['emergency_label']:
            rule['emergency_label'] = row['emergency_label']
    return rule


def load_rules(connection=None):
    """Load the active rule set from the database, in the same shape as
    `health_system.DEFAULT_RULES`, ready to pass as `assess_patient(..., rules=...)`.
    """
    owns_connection = connection is None
    if owns_connection:
        connection = get_db_connection()

    try:
        rule_rows = connection.execute(
            'SELECT * FROM EXPERT_RULES WHERE is_active = 1 ORDER BY rule_id ASC'
        ).fetchall()
        symptom_rows = connection.execute(
            """
            SELECT RULE_SYMPTOMS.rule_id, SYMPTOMS.symptom_key
            FROM RULE_SYMPTOMS
            JOIN SYMPTOMS ON SYMPTOMS.symptom_id = RULE_SYMPTOMS.symptom_id
            WHERE RULE_SYMPTOMS.is_required = 1
            """
        ).fetchall()
    finally:
        if owns_connection:
            connection.close()

    required_by_rule = {}
    for symptom_row in symptom_rows:
        required_by_rule.setdefault(symptom_row['rule_id'], []).append(symptom_row['symptom_key'])

    return [_row_to_rule(row, required_by_rule.get(row['rule_id'], [])) for row in rule_rows]


def load_phrase_map(connection=None):
    """Load the Bisaya/English phrase lexicon from the database, in the same
    shape as `health_system.DEFAULT_PHRASE_MAP`.
    """
    owns_connection = connection is None
    if owns_connection:
        connection = get_db_connection()

    try:
        rows = connection.execute(
            """
            SELECT SYMPTOM_TERMS.bisaya_term, SYMPTOMS.symptom_key
            FROM SYMPTOM_TERMS
            JOIN SYMPTOMS ON SYMPTOMS.symptom_id = SYMPTOM_TERMS.symptom_id
            """
        ).fetchall()
    finally:
        if owns_connection:
            connection.close()

    return {row['bisaya_term']: row['symptom_key'] for row in rows}


@lru_cache(maxsize=1)
def _cached_rules_and_phrase_map():
    connection = get_db_connection()
    try:
        return load_rules(connection), load_phrase_map(connection)
    finally:
        connection.close()


def get_active_rules_and_phrase_map():
    """Cached accessor for the live app's request path -- avoids re-querying
    the small rule/lexicon tables on every single assessment. Call
    `clear_cache()` after any future admin edit to the rule base.
    """
    return _cached_rules_and_phrase_map()


def clear_cache():
    _cached_rules_and_phrase_map.cache_clear()
