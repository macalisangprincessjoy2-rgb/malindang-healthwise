import re
from functools import lru_cache


BISAYA_SYMPTOM_MAP = {
    "kalibanga": "diarrhea",
    "pagsuka": "vomiting",
    "hubak": "cough",
    "ubo": "cough",
    "trangkaso": "fever",
    "hilanat": "fever",
    "sakit sa tiyan": "stomach_pain",
    "bitok": "intestinal_worms",
    "asam": "fever",
    "lisod ug ginhawa": "difficulty_breathing",
    "ginhawa": "difficulty_breathing",
    "sakit sa hawak": "body_weakness",
    "sakit sa lawas": "body_weakness",
    "samad sa yuta": "body_weakness",
    "taas nga presyon": "body_weakness",
    "pagkalipong": "body_weakness",
    "losing gana": "loss_of_appetite",
    "kapoy": "severe_fatigue",
    "ginakapoy": "severe_fatigue",
    "hangos": "difficulty_breathing",
    "sakit sa dughan": "chest_pain",
    "dughan": "chest_pain",
    "sakit sa ulo": "fever",
    "hangin": "difficulty_breathing",
    "panahon": "fever",
    "diyeta": "loss_of_appetite",
    "wala gyuy gana mokaon": "loss_of_appetite",
    "kulba": "body_weakness",
    "kaguyod": "body_weakness",
    "sakit kaayo": "body_weakness",
    "pirteng bugnawa": "cold_exposure",
    "bugnaw": "cold_exposure",
    "gabun": "dense_fog",
    "aso sa dabu-dabu": "smoke_exposure",
    "sigeg ubo nga nagdugay": "chronic_cough",
    "bronchitis": "chronic_cough",
    "hika": "asthma",
}


ENGLISH_PHRASE_MAP = {
    "difficulty breathing": "difficulty_breathing",
    "chest pain": "chest_pain",
    "loss of appetite": "loss_of_appetite",
    "severe fatigue": "severe_fatigue",
    "body weakness": "body_weakness",
    "stomach pain": "stomach_pain",
    "intestinal worms": "intestinal_worms",
    "cold exposure": "cold_exposure",
    "dense fog": "dense_fog",
    "smoke exposure": "smoke_exposure",
    "chronic cough": "chronic_cough",
    "asthma": "asthma",
    "high fever": "fever",
    "dry cough": "cough",
    "fever and cough": "fever",
    "cough and fever": "cough",
}

# The full default lexicon (Bisaya + English phrases) used when no explicit
# phrase_map is supplied -- e.g. a phrase set loaded from
# rule_repository.load_phrase_map() for the live, database-driven app.
DEFAULT_PHRASE_MAP = {**BISAYA_SYMPTOM_MAP, **ENGLISH_PHRASE_MAP}

# A fallback for bare English root words typed without a full phrase (e.g.
# just "fatigue" rather than "severe fatigue"). Maps the word to the actual
# canonical symptom key -- NOT the word itself. (This used to be a plain set
# that appended the bare word as if it were the key; "fatigue", "weakness",
# "appetite", and "bronchitis" never matched anything downstream because no
# such symptom keys exist -- only fever/cough/diarrhea/vomiting/dehydration/
# asthma happened to already equal their own key, silently masking the bug.)
_SINGLE_WORD_MAP = {
    "fever": "fever",
    "cough": "cough",
    "fatigue": "severe_fatigue",
    "diarrhea": "diarrhea",
    "vomiting": "vomiting",
    "dehydration": "dehydration",
    "weakness": "body_weakness",
    "appetite": "loss_of_appetite",
    "asthma": "asthma",
    "bronchitis": "chronic_cough",
}


@lru_cache(maxsize=16)
def _compiled_patterns_for(phrase_items):
    """Compile (and cache) word-boundary patterns for a phrase map.

    `phrase_items` must be a hashable tuple of (phrase, key) pairs -- callers
    pass `tuple(sorted(phrase_map.items()))`. Caching means a phrase map
    loaded from the database (via rule_repository) is compiled once per
    distinct map, not on every call, same as the old module-level constants.
    """
    return [
        (re.compile(r"\b" + re.escape(phrase) + r"\b"), key)
        for phrase, key in phrase_items
    ]


def normalize_symptom_text(text, phrase_map=None):
    """Convert Bisaya symptom descriptions into canonical symptom keys.

    `phrase_map` defaults to `DEFAULT_PHRASE_MAP` (the built-in Bisaya +
    English lexicon); pass an explicit map (e.g. from
    `rule_repository.load_phrase_map()`) to match against a database-driven
    lexicon instead. Matching is done on word boundaries so a short phrase
    (e.g. "ubo") can't accidentally match inside an unrelated longer word.
    """
    if not text:
        return []

    active_map = phrase_map if phrase_map is not None else DEFAULT_PHRASE_MAP
    patterns = _compiled_patterns_for(tuple(sorted(active_map.items())))

    normalized = []
    lowered = text.lower()

    for pattern, key in patterns:
        if pattern.search(lowered):
            normalized.append(key)

    text_words = re.findall(r"[a-zA-Z]+", lowered)
    for word in text_words:
        if word in _SINGLE_WORD_MAP:
            normalized.append(_SINGLE_WORD_MAP[word])

    unique_list = []
    for key in normalized:
        if key not in unique_list:
            unique_list.append(key)
    return unique_list


def _all_present(symptoms, *keys):
    return all(symptoms.get(key, False) for key in keys)


def _is_elderly(symptoms, age):
    try:
        return age is not None and int(age) >= 65
    except (TypeError, ValueError):
        return False


# The rule base. Each rule is independently traceable: an evaluator can point
# at a specific ID and its firing condition and see exactly why it contributed
# to a case's score. `emergency` marks findings that force an emergency
# referral outright, regardless of the accumulated score -- these encode
# clinical judgment calls that a point total alone shouldn't be allowed to
# soften (e.g. chest pain should never be waved through as merely "Moderate"
# because the rest of the symptom list was mild).
#
# Weights mirror the single-symptom scoring used in the original prototype
# (kept for continuity with `dataset/health_assessment_dataset.csv`); the
# compound rules (R18+) are new and encode symptom *combinations* that carry
# more clinical significance together than any of their parts do alone.
#
# This is the DEFAULT/fallback rule set -- used whenever `assess_patient()`
# isn't given an explicit `rules` argument, which is what every existing
# caller (tests, scripts/generate_synthetic_dataset.py) still does, so this
# list has to keep meaning exactly what it always has. The live app instead
# loads rules from the database (see rule_repository.load_rules()) and passes
# them in explicitly; docs/database/erd.md's EXPERT_RULES/RULE_SYMPTOMS
# tables are hand-kept in sync with this list by
# rule_repository.seed_from_defaults(), and a parity test
# (tests/test_rule_repository.py) checks the two never drift apart.
DEFAULT_RULES = [
    {"id": "R01", "when": lambda s, a: s.get("fever", False), "weight": 1, "finding": "Fever"},
    {"id": "R02", "when": lambda s, a: s.get("cough", False), "weight": 1, "finding": "Cough"},
    {"id": "R03", "when": lambda s, a: s.get("difficulty_breathing", False), "weight": 2, "finding": "Difficulty Breathing", "emergency": True},
    {"id": "R04", "when": lambda s, a: s.get("severe_fatigue", False), "weight": 2, "finding": "Severe Fatigue"},
    {"id": "R05", "when": lambda s, a: s.get("chest_pain", False), "weight": 3, "finding": "Chest Pain", "emergency": True},
    {"id": "R06", "when": lambda s, a: s.get("diarrhea", False), "weight": 1, "finding": "Diarrhea"},
    {"id": "R07", "when": lambda s, a: s.get("vomiting", False), "weight": 1, "finding": "Vomiting"},
    {"id": "R08", "when": lambda s, a: s.get("dehydration", False), "weight": 3, "finding": "Dehydration", "emergency": True, "emergency_label": "Severe dehydration"},
    {"id": "R09", "when": lambda s, a: s.get("loss_of_appetite", False), "weight": 1, "finding": "Loss Of Appetite"},
    {"id": "R10", "when": lambda s, a: s.get("body_weakness", False), "weight": 1, "finding": "Body Weakness"},
    {"id": "R11", "when": lambda s, a: s.get("stomach_pain", False), "weight": 2, "finding": "Stomach Pain"},
    {"id": "R12", "when": lambda s, a: s.get("intestinal_worms", False), "weight": 1, "finding": "Intestinal Worms"},
    {"id": "R13", "when": lambda s, a: s.get("cold_exposure", False), "weight": 1, "finding": "Cold Exposure"},
    {"id": "R14", "when": lambda s, a: s.get("dense_fog", False), "weight": 1, "finding": "Dense Fog"},
    {"id": "R15", "when": lambda s, a: s.get("smoke_exposure", False), "weight": 1, "finding": "Smoke Exposure"},
    {"id": "R16", "when": lambda s, a: s.get("chronic_cough", False), "weight": 2, "finding": "Chronic Cough"},
    {"id": "R17", "when": lambda s, a: s.get("asthma", False), "weight": 2, "finding": "Asthma"},
    # Compound rules: a symptom combination that reads as a recognizable
    # clinical pattern, worth more than the sum of its parts.
    {
        "id": "R18", "weight": 2, "emergency": True,
        "when": lambda s, a: _all_present(s, "difficulty_breathing", "chest_pain"),
        "finding": "Possible acute respiratory distress",
    },
    {
        "id": "R19", "weight": 2, "emergency": True,
        "when": lambda s, a: _all_present(s, "diarrhea", "vomiting", "dehydration"),
        "finding": "Acute gastrointestinal emergency pattern",
    },
    {
        "id": "R20", "weight": 1,
        "when": lambda s, a: _all_present(s, "chronic_cough", "smoke_exposure"),
        "finding": "Chronic respiratory illness aggravated by smoke exposure",
    },
    {
        "id": "R21", "weight": 1,
        "when": lambda s, a: _all_present(s, "asthma", "cold_exposure"),
        "finding": "Asthma exacerbation risk from cold/high-elevation exposure",
    },
    {
        "id": "R22", "weight": 2,
        "when": lambda s, a: _all_present(s, "fever", "chronic_cough"),
        "finding": "Persistent fever with chronic cough (TB-screening pattern; refer for evaluation)",
    },
    {
        "id": "R23", "weight": 1,
        "when": lambda s, a: _all_present(s, "dense_fog", "difficulty_breathing"),
        "finding": "High-elevation respiratory risk factor present",
    },
    {
        "id": "R24", "weight": 1,
        "when": lambda s, a: _all_present(s, "intestinal_worms", "loss_of_appetite", "body_weakness"),
        "finding": "Possible malnutrition risk from parasitic infection",
    },
    {
        "id": "R25", "weight": 2,
        "when": lambda s, a: _is_elderly(s, a),
        "finding": "Elderly (65+): increased vulnerability",
    },
]

# Kept as a plain alias -- `RULES` was the original public name.
RULES = DEFAULT_RULES


def assess_patient(symptoms, age=None, rules=None):
    """Return a preliminary health assessment and healthcare referral recommendation.

    `rules` defaults to `DEFAULT_RULES`; pass an explicit list (e.g. from
    `rule_repository.load_rules()`) to run against a database-driven rule set
    instead. Every rule is evaluated against `symptoms`/`age`; the ones that
    fire are accumulated into a score and returned as an auditable list
    (`rules_fired`), so a reviewer can see exactly which findings produced a
    given risk level rather than trusting an opaque number.
    """
    active_rules = rules if rules is not None else DEFAULT_RULES
    score = 0
    symptom_notes = []
    rules_fired = []
    emergency = False

    for rule in active_rules:
        if not rule["when"](symptoms, age):
            continue
        score += rule["weight"]
        symptom_notes.append(rule["finding"])
        rules_fired.append({"id": rule["id"], "finding": rule["finding"], "weight": rule["weight"]})
        if rule.get("emergency"):
            emergency = True
            emergency_label = rule.get("emergency_label", rule["finding"])
            if emergency_label not in symptom_notes:
                symptom_notes.append(emergency_label)

    risk_level = health_risk_level(score)
    # An emergency-flagged finding (chest pain, difficulty breathing, dehydration,
    # or the compound patterns above) must never be reported as merely
    # "Moderate" -- the score-based band is a floor here, not the final word,
    # so risk_level and the referral text can never contradict each other.
    if emergency and risk_level != "High":
        risk_level = "High"

    referral = suggest_referral(risk_level, symptom_notes)
    priority = referral_priority(referral)

    return {
        "score": score,
        "risk_level": risk_level,
        "symptoms": symptom_notes,
        "rules_fired": rules_fired,
        "referral": referral,
        "priority": priority,
        "age": age,
    }


def health_risk_level(score):
    if score >= 6:
        return "High"
    if score >= 3:
        return "Moderate"
    return "Low"


def suggest_referral(risk_level, symptom_notes):
    if risk_level == "High":
        return "Emergency referral to nearest hospital or clinic"
    if risk_level == "Moderate":
        return "Consult healthcare professional within 24 hours"
    return "Routine consultation / monitoring"


def referral_priority(note):
    lower_note = str(note).lower()

    if "severe dehydration" in lower_note or "emergency" in lower_note or "acute" in lower_note:
        return "Immediate referral"
    if "follow-up" in lower_note or "monitoring" in lower_note or "routine" in lower_note:
        return "Scheduled visit"
    if "24 hours" in lower_note or "urgent" in lower_note:
        return "Urgent evaluation"
    return "Priority assessment"
