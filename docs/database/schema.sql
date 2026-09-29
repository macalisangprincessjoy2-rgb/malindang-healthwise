-- Corrected database design for the Malindang Highlands expert system.
-- See docs/database/erd.md for the diagram and the rationale behind every
-- change relative to the original ERD.
--
-- This is a DESIGN document (Chapter 3 deliverable), not something app.py
-- currently runs -- see the note at the bottom of erd.md for how it relates
-- to the simplified schema actually implemented in app.py's init_db().
--
-- SQLite dialect, consistent with the project's existing database engine.

PRAGMA foreign_keys = ON;

-- ============================================================
-- People & access
-- ============================================================

CREATE TABLE IF NOT EXISTS USERS (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name       TEXT NOT NULL,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    gender          TEXT,
    age             TEXT,
    role            TEXT NOT NULL DEFAULT 'resident'
                    CHECK (role IN ('resident', 'health_worker', 'admin')),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- Healthcare facilities
-- ============================================================

CREATE TABLE IF NOT EXISTS FACILITY_TYPES (
    facility_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_name         TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS HEALTHCARE_FACILITIES (
    facility_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user_id     INTEGER NOT NULL REFERENCES USERS(user_id),
    facility_type_id  INTEGER NOT NULL REFERENCES FACILITY_TYPES(facility_type_id),
    facility_name     TEXT NOT NULL,
    address           TEXT,
    latitude          REAL,
    longitude         REAL,
    contact_number    TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS SERVICES (
    service_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    service_name  TEXT NOT NULL UNIQUE
);

-- Replaces the original flat HEALTHCARE_FACILITIES.service_available column
-- -- a facility can offer more than one service.
CREATE TABLE IF NOT EXISTS FACILITY_SERVICES (
    facility_service_id INTEGER PRIMARY KEY AUTOINCREMENT,
    facility_id          INTEGER NOT NULL REFERENCES HEALTHCARE_FACILITIES(facility_id),
    service_id           INTEGER NOT NULL REFERENCES SERVICES(service_id),
    UNIQUE (facility_id, service_id)
);

-- ============================================================
-- Clinical knowledge base (admin-editable)
-- ============================================================

CREATE TABLE IF NOT EXISTS CONDITIONS (
    condition_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_name  TEXT NOT NULL,
    condition_type  TEXT,
    description     TEXT
);

CREATE TABLE IF NOT EXISTS RISK_LEVELS (
    risk_level_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    level_name      TEXT NOT NULL UNIQUE,       -- 'Low' | 'Moderate' | 'High'
    description     TEXT,
    severity_rank   INTEGER NOT NULL UNIQUE     -- lets code do MAX(severity_rank) instead of string comparison
);

CREATE TABLE IF NOT EXISTS SYMPTOMS (
    symptom_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    symptom_key   TEXT NOT NULL UNIQUE,   -- machine key, e.g. 'difficulty_breathing' -- mirrors ml_module.FEATURES
    symptom_name  TEXT NOT NULL,          -- display label, e.g. 'Difficulty Breathing'
    description   TEXT
);

CREATE TABLE IF NOT EXISTS SYMPTOM_TERMS (
    term_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    symptom_id   INTEGER NOT NULL REFERENCES SYMPTOMS(symptom_id),
    bisaya_term  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS EXPERT_RULES (
    rule_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user_id         INTEGER NOT NULL REFERENCES USERS(user_id),
    condition_id          INTEGER NOT NULL REFERENCES CONDITIONS(condition_id),
    risk_level_id         INTEGER NOT NULL REFERENCES RISK_LEVELS(risk_level_id),
    rule_name             TEXT NOT NULL,
    rule_description      TEXT,
    weight                INTEGER NOT NULL DEFAULT 0,   -- score contribution when this rule fires
    is_emergency_override BOOLEAN NOT NULL DEFAULT 0,   -- forces ASSESSMENTS.final_risk_level_id to High regardless of score
    is_active             BOOLEAN NOT NULL DEFAULT 1,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS RULE_SYMPTOMS (
    rule_symptom_id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id         INTEGER NOT NULL REFERENCES EXPERT_RULES(rule_id),
    symptom_id      INTEGER NOT NULL REFERENCES SYMPTOMS(symptom_id),
    is_required     BOOLEAN NOT NULL DEFAULT 1,
    UNIQUE (rule_id, symptom_id)
);

CREATE TABLE IF NOT EXISTS HEALTH_GUIDELINES (
    guideline_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user_id     INTEGER NOT NULL REFERENCES USERS(user_id),
    condition_id      INTEGER REFERENCES CONDITIONS(condition_id),
    guideline_title   TEXT NOT NULL,
    guideline_content TEXT NOT NULL,
    source            TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS RECOMMENDATIONS (
    recommendation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user_id      INTEGER NOT NULL REFERENCES USERS(user_id),
    condition_id       INTEGER NOT NULL REFERENCES CONDITIONS(condition_id),
    risk_level_id      INTEGER NOT NULL REFERENCES RISK_LEVELS(risk_level_id),
    guideline_id       INTEGER REFERENCES HEALTH_GUIDELINES(guideline_id),
    recommendation_text TEXT NOT NULL,
    action_type        TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- ML component
-- ============================================================

CREATE TABLE IF NOT EXISTS ML_MODELS (
    model_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_user_id INTEGER NOT NULL REFERENCES USERS(user_id),
    model_name    TEXT NOT NULL,
    version       TEXT NOT NULL,
    algorithm     TEXT NOT NULL,
    trained_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sample_size   INTEGER,        -- ml_module.evaluate_model()['sample_size']
    cv_folds      INTEGER,        -- ml_module.evaluate_model()['cv_folds']
    cv_accuracy   REAL,           -- ml_module.evaluate_model()['cv_accuracy'] -- cross-validated, never training accuracy
    is_active     BOOLEAN NOT NULL DEFAULT 1
);

-- ============================================================
-- Assessment pipeline
-- ============================================================

CREATE TABLE IF NOT EXISTS ASSESSMENTS (
    assessment_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES USERS(user_id),
    raw_symptom_input  TEXT,
    language           TEXT,
    location_text      TEXT,
    latitude           REAL,
    longitude          REAL,
    age_snapshot       INTEGER,
    gender_snapshot    TEXT,
    final_risk_level_id INTEGER REFERENCES RISK_LEVELS(risk_level_id),
        -- Aggregated rule-engine verdict = MAX(severity_rank) across this
        -- assessment's ASSESSMENT_RESULTS rows. NULL until processing
        -- completes. The rule engine is the safety authority: this field is
        -- never overwritten by RISK_CLASSIFICATIONS (the ML opinion).
    assessment_date    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status             TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS ASSESSMENT_SYMPTOMS (
    assessment_symptom_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id         INTEGER NOT NULL REFERENCES ASSESSMENTS(assessment_id),
    symptom_id            INTEGER NOT NULL REFERENCES SYMPTOMS(symptom_id),
    extracted_text        TEXT,     -- the raw phrase that matched, e.g. "lisod ug ginhawa"
    confidence_score      REAL,
    UNIQUE (assessment_id, symptom_id)
);

CREATE TABLE IF NOT EXISTS ASSESSMENT_RESULTS (
    result_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id      INTEGER NOT NULL REFERENCES ASSESSMENTS(assessment_id),
    condition_id       INTEGER NOT NULL REFERENCES CONDITIONS(condition_id),
        -- Snapshot of EXPERT_RULES.condition_id at match time -- deliberately
        -- denormalized so a later admin edit to the rule doesn't rewrite history.
    risk_level_id       INTEGER NOT NULL REFERENCES RISK_LEVELS(risk_level_id),
        -- Snapshot of EXPERT_RULES.risk_level_id at match time, same rationale.
    rule_id             INTEGER NOT NULL REFERENCES EXPERT_RULES(rule_id),
    explanation          TEXT,
    confidence_score     REAL,
    generated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    -- One row per matched rule -- an assessment can have several. The single
    -- number shown to the patient is ASSESSMENTS.final_risk_level_id, derived
    -- from all of this assessment's rows, not any single one.
);

CREATE TABLE IF NOT EXISTS RESULT_RECOMMENDATIONS (
    result_recommendation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id                 INTEGER NOT NULL REFERENCES ASSESSMENT_RESULTS(result_id),
    recommendation_id         INTEGER NOT NULL REFERENCES RECOMMENDATIONS(recommendation_id),
        -- Junction, not a direct condition+risk_level lookup, so that if a
        -- RECOMMENDATIONS row's text is edited later, this table still
        -- records exactly which recommendation the patient was actually shown.
    UNIQUE (result_id, recommendation_id)
);

CREATE TABLE IF NOT EXISTS RISK_CLASSIFICATIONS (
    classification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id       INTEGER NOT NULL REFERENCES ASSESSMENTS(assessment_id),
    model_id             INTEGER NOT NULL REFERENCES ML_MODELS(model_id),
    risk_level_id         INTEGER NOT NULL REFERENCES RISK_LEVELS(risk_level_id),
        -- The ML model's own opinion. Supplementary only -- never written
        -- into ASSESSMENTS.final_risk_level_id.
    confidence_score      REAL,
    classified_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS REFERRALS (
    referral_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id      INTEGER NOT NULL UNIQUE REFERENCES ASSESSMENTS(assessment_id),
        -- UNIQUE: exactly one referral per assessment, generated from the
        -- aggregated final_risk_level_id -- not one per matched rule, which
        -- would risk duplicate "go to the ER now" rows for one visit.
    facility_id         INTEGER NOT NULL REFERENCES HEALTHCARE_FACILITIES(facility_id),
    referral_reason      TEXT,
    referral_priority    TEXT,
    referral_status      TEXT NOT NULL DEFAULT 'pending',
    referral_date        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS FEEDBACKS (
    feedback_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES USERS(user_id),
    assessment_id      INTEGER NOT NULL REFERENCES ASSESSMENTS(assessment_id),
    usability_score     INTEGER CHECK (usability_score BETWEEN 1 AND 5),
    accuracy_score       INTEGER CHECK (accuracy_score BETWEEN 1 AND 5),
    accessibility_score  INTEGER CHECK (accessibility_score BETWEEN 1 AND 5),
    comments             TEXT,
    submitted_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- Seed data for RISK_LEVELS -- severity_rank is what lets
-- MAX(severity_rank) work for ASSESSMENTS.final_risk_level_id.
-- ============================================================

INSERT OR IGNORE INTO RISK_LEVELS (level_name, description, severity_rank) VALUES
    ('Low',      'Mild symptoms; routine monitoring.', 1),
    ('Moderate', 'Moderate symptoms; consult a health professional within 24 hours.', 2),
    ('High',     'Severe symptoms or emergency signs; immediate referral.', 3);
