"""Generate a synthetic, rule-engine-labeled augmentation of the curated
health assessment dataset, for training/validating the supplementary ML
classifier in `ml_module.py`.

Why this exists: the curated dataset (`dataset/health_assessment_dataset.csv`)
has 16 hand-written case narratives, which is far too small a sample to
support any claim about a trained classifier's accuracy. Rather than
hand-authoring more narrative cases (slow, and still small), this script
procedurally samples symptom/age/location combinations and labels each one
using the project's OWN rule-based engine (`health_system.assess_patient`) --
the same engine the paper already documents and defends as the "safety
authority." That makes every synthetic label internally consistent with the
system's own logic by construction, and the provenance is explicit: every row
this script writes is tagged `source=synthetic` in the output CSV, clearly
distinguishing it from the 16 `source=curated` narrative cases.

This is *not* a substitute for real patient encounters, and the resulting
dataset should be described in the paper exactly as that: a synthetic,
rule-engine-labeled augmentation used to give the classifier evaluation a
larger, class-balanced sample than 16 records can provide, not a claim about
real-world disease prevalence.

Usage:
    python scripts/generate_synthetic_dataset.py

Output:
    dataset/health_assessment_dataset_augmented.csv
    (curated rows copied through unchanged, plus generated synthetic rows)
"""

import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from health_system import assess_patient, normalize_symptom_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CURATED_PATH = ROOT / "dataset" / "health_assessment_dataset.csv"
AUGMENTED_PATH = ROOT / "dataset" / "health_assessment_dataset_augmented.csv"

SEED = 42
TARGET_PER_CLASS = 50  # synthetic rows per risk level; total synthetic = 3x this
MAX_ATTEMPTS = 200_000

SYMPTOM_KEYS = (
    "fever", "cough", "difficulty_breathing", "severe_fatigue", "chest_pain",
    "diarrhea", "vomiting", "dehydration", "loss_of_appetite", "body_weakness",
    "stomach_pain", "intestinal_worms", "cold_exposure", "dense_fog",
    "smoke_exposure", "chronic_cough", "asthma",
)

# One representative Bisaya/English phrase per symptom key, used to assemble
# a plausible (if generic) symptom_text field for each synthetic row -- kept
# from the same vocabulary `normalize_symptom_text` already recognizes, so a
# generated row is internally consistent end-to-end.
SYMPTOM_PHRASE = {
    "fever": "hilanat",
    "cough": "ubo",
    "difficulty_breathing": "lisod ug ginhawa",
    "severe_fatigue": "kapoy",
    "chest_pain": "sakit sa dughan",
    "diarrhea": "kalibanga",
    "vomiting": "pagsuka",
    "dehydration": "dehydration",
    "loss_of_appetite": "wala gyuy gana mokaon",
    "body_weakness": "kaluya sa lawas",
    "stomach_pain": "sakit sa tiyan",
    "intestinal_worms": "bitok",
    "cold_exposure": "pirteng bugnawa",
    "dense_fog": "gabun",
    "smoke_exposure": "aso sa dabu-dabu",
    "chronic_cough": "sigeg ubo nga nagdugay",
    "asthma": "hika",
}

# Mirrors app.py's BARANGAYS_BY_MUNICIPALITY. Duplicated here (rather than
# imported from app.py) so this script has no Flask/DB side effects -- if
# app.py's barangay list changes, update this to match.
LOCATIONS = [
    ("Don Victoriano", b) for b in (
        "Bagumbang", "Gandawan", "Lake Duminagat", "Lalud", "Lampasan",
        "Liboron", "Maramat", "Napangan", "Nueva Vista", "Petian", "Siloy",
    )
] + [("Tangub City", b) for b in ("Owayan", "Hoyohoy")]


def _sample_symptoms(rng, target_class):
    """Sample a symptom set biased toward producing `target_class`.

    Rejection sampling is used rather than hand-tuning per-class probabilities
    exactly -- simpler to reason about and keeps the generator honest (every
    accepted row is genuinely classified that way by assess_patient, not
    forced).
    """
    if target_class == "Low":
        active_count_range = (0, 2)
        pool = SYMPTOM_KEYS
    elif target_class == "Moderate":
        active_count_range = (1, 4)
        pool = SYMPTOM_KEYS
    else:  # High
        active_count_range = (2, 6)
        # Bias toward emergency-capable / high-weight symptoms so High-risk
        # cases are reachable in reasonable time, not just by rare chance.
        pool = SYMPTOM_KEYS + (
            "chest_pain", "difficulty_breathing", "dehydration",
            "chest_pain", "difficulty_breathing", "dehydration",
        )

    n = rng.randint(*active_count_range)
    chosen = set(rng.sample(pool, k=min(n, len(set(pool)))))
    return {key: (key in chosen) for key in SYMPTOM_KEYS}


def generate_rows(count_per_class, seed):
    rng = random.Random(seed)
    buckets = {"Low": [], "Moderate": [], "High": []}
    attempts = 0

    while any(len(rows) < count_per_class for rows in buckets.values()) and attempts < MAX_ATTEMPTS:
        attempts += 1
        target_class = min(buckets, key=lambda k: len(buckets[k]))
        age = rng.randint(18, 85)
        symptoms = _sample_symptoms(rng, target_class)
        result = assess_patient(symptoms, age=age)

        risk = result["risk_level"]
        if len(buckets[risk]) >= count_per_class:
            continue

        municipality, barangay = rng.choice(LOCATIONS)
        active_phrases = [SYMPTOM_PHRASE[k] for k in SYMPTOM_KEYS if symptoms[k]]
        symptom_text = ", ".join(active_phrases) if active_phrases else "walay simtoma"

        row = {
            "patient_id": None,  # assigned after generation, in class order
            "full_name": "Synthetic Case",
            "age": age,
            "municipality": municipality,
            "barangay": barangay,
            "address": f"{barangay}, {municipality}",
            **{k: (1 if symptoms[k] else 0) for k in SYMPTOM_KEYS},
            "symptom_text": symptom_text,
            "notes": "Synthetic training case (rule-engine generated; see scripts/generate_synthetic_dataset.py)",
            "risk_level": result["risk_level"],
            "referral_recommendation": result["referral"],
            "priority": result["priority"],
            "source": "synthetic",
        }
        buckets[risk].append(row)

    if attempts >= MAX_ATTEMPTS:
        counts = {k: len(v) for k, v in buckets.items()}
        raise RuntimeError(f"Hit MAX_ATTEMPTS before reaching target class balance: {counts}")

    all_rows = buckets["Low"] + buckets["Moderate"] + buckets["High"]
    for index, row in enumerate(all_rows, start=1):
        row["patient_id"] = f"SYN{index:03d}"
    return all_rows, {k: len(v) for k, v in buckets.items()}


def load_curated_rows():
    with CURATED_PATH.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["source"] = "curated"
    return rows


def main():
    curated_rows = load_curated_rows()
    synthetic_rows, counts = generate_rows(TARGET_PER_CLASS, SEED)

    fieldnames = list(curated_rows[0].keys())  # curated rows already end with 'source'

    with AUGMENTED_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(curated_rows)
        writer.writerows(synthetic_rows)

    total = len(curated_rows) + len(synthetic_rows)
    print(f"Wrote {AUGMENTED_PATH.relative_to(ROOT)}")
    print(f"  curated:   {len(curated_rows)}")
    print(f"  synthetic: {len(synthetic_rows)}  {counts}")
    print(f"  total:     {total}")


if __name__ == "__main__":
    main()
