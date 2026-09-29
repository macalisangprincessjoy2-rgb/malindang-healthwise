"""Parity tests: the database-loaded rule base and lexicon must produce
IDENTICAL results to health_system's hardcoded defaults for every scenario
below. This is the safety net for the "core migration" -- it's what actually
lets us claim the migration preserves behavior rather than just hoping so.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

import rule_repository
from health_system import DEFAULT_PHRASE_MAP, assess_patient, normalize_symptom_text


@pytest.fixture(scope="module")
def db_connection():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "rule_repository_test.db"
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        rule_repository.ensure_schema(connection)
        rule_repository.seed_from_defaults(connection)
        yield connection
        connection.close()


@pytest.fixture(scope="module")
def db_rules(db_connection):
    return rule_repository.load_rules(db_connection)


@pytest.fixture(scope="module")
def db_phrase_map(db_connection):
    return rule_repository.load_phrase_map(db_connection)


def test_seeding_produces_all_25_rules(db_rules):
    assert len(db_rules) == 25
    assert {rule["id"] for rule in db_rules} == {f"R{n:02d}" for n in range(1, 26)}


ALL_SYMPTOM_KEYS = (
    'fever', 'cough', 'difficulty_breathing', 'severe_fatigue', 'chest_pain',
    'diarrhea', 'vomiting', 'dehydration', 'loss_of_appetite', 'body_weakness',
    'stomach_pain', 'intestinal_worms', 'cold_exposure', 'dense_fog',
    'smoke_exposure', 'chronic_cough', 'asthma',
)

SCENARIOS = (
    # (label, symptoms dict, age)
    ("no symptoms", {}, None),
    ("fever only", {"fever": True}, 30),
    ("chest pain alone (emergency override)", {"chest_pain": True}, 40),
    ("difficulty breathing alone (emergency override)", {"difficulty_breathing": True}, 25),
    ("dehydration alone (emergency override + custom label)", {"dehydration": True}, 50),
    ("acute respiratory distress compound", {"difficulty_breathing": True, "chest_pain": True}, 60),
    ("GI emergency triad", {"diarrhea": True, "vomiting": True, "dehydration": True}, 35),
    ("chronic cough + smoke exposure", {"chronic_cough": True, "smoke_exposure": True}, 45),
    ("asthma + cold exposure", {"asthma": True, "cold_exposure": True}, 28),
    ("fever + chronic cough (TB pattern)", {"fever": True, "chronic_cough": True}, 33),
    ("dense fog + difficulty breathing", {"dense_fog": True, "difficulty_breathing": True}, 41),
    ("malnutrition risk triad", {"intestinal_worms": True, "loss_of_appetite": True, "body_weakness": True}, 22),
    ("elderly alone", {}, 70),
    ("elderly with mild symptoms", {"fever": True, "cough": True}, 68),
    ("every symptom at once", {key: True for key in ALL_SYMPTOM_KEYS}, 80),
    ("moderate combo", {"fever": True, "diarrhea": True, "loss_of_appetite": True}, 26),
)


@pytest.mark.parametrize("label,symptoms,age", SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_db_rules_match_default_rules(db_rules, label, symptoms, age):
    default_result = assess_patient(symptoms, age=age)
    db_result = assess_patient(symptoms, age=age, rules=db_rules)

    assert db_result["score"] == default_result["score"], label
    assert db_result["risk_level"] == default_result["risk_level"], label
    assert db_result["referral"] == default_result["referral"], label
    assert db_result["priority"] == default_result["priority"], label
    assert db_result["symptoms"] == default_result["symptoms"], label
    assert [r["id"] for r in db_result["rules_fired"]] == [r["id"] for r in default_result["rules_fired"]], label


PHRASE_SAMPLES = (
    "hubak ug hilanat",
    "lisod ug ginhawa, kapoy, wala gyuy gana mokaon",
    "kalibanga ug pagsuka",
    "sakit sa dughan ug lisod ug ginhawa",
    "difficulty breathing and chest pain",
    "pirteng bugnawa ug gabun",
    "sigeg ubo nga nagdugay, aso sa dabu-dabu",
    "walay simtoma",
    "nagtrabaho sa uboson nga bukid",  # boundary-safety case: must NOT match "cough"
)


@pytest.mark.parametrize("text", PHRASE_SAMPLES)
def test_db_phrase_map_matches_default_phrase_map(db_phrase_map, text):
    assert normalize_symptom_text(text) == normalize_symptom_text(text, phrase_map=db_phrase_map)


def test_db_phrase_map_covers_every_default_entry(db_phrase_map):
    # Every phrase in the hardcoded default lexicon must survive the DB round-trip.
    missing = set(DEFAULT_PHRASE_MAP) - set(db_phrase_map)
    assert not missing, f"Phrases dropped during seeding: {missing}"


def test_seeding_is_idempotent(db_connection):
    before = db_connection.execute("SELECT COUNT(*) FROM EXPERT_RULES").fetchone()[0]
    rule_repository.seed_from_defaults(db_connection)  # calling again must no-op
    after = db_connection.execute("SELECT COUNT(*) FROM EXPERT_RULES").fetchone()[0]
    assert before == after == 25
