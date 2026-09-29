# Expert System Rule Base

This document is the audit trail for the rule-based classification engine in
[`health_system.py`](../health_system.py). Every rule the system can fire is
listed here with its ID, firing condition, score weight, and clinical
rationale, so a reviewer can trace any assessment result back to the specific
rules that produced it (`assess_patient()` returns the fired rules as
`rules_fired` alongside the final score).

## How a score becomes a risk level

1. Every rule below is evaluated independently against the patient's symptom
   flags and age. Each one that fires adds its weight to a running score and
   its finding to the case notes.
2. The score maps to a risk band:

   | Score | Risk level |
   |---|---|
   | 0–2 | Low |
   | 3–5 | Moderate |
   | 6+ | High |

3. **Emergency override.** A small subset of rules (marked *Emergency* below)
   force the risk level to **High** regardless of the accumulated score. This
   exists because a point total should never be allowed to soften a
   genuinely dangerous single finding -- e.g. chest pain alone (weight 3)
   plus nothing else totals a score of 3 ("Moderate" by the table above), but
   chest pain is never clinically appropriate to downgrade to "consult within
   24 hours." The override guarantees `risk_level` and the referral
   recommendation can never contradict each other.
4. `risk_level` deterministically maps to a referral action:
   - **High → "Emergency referral to nearest hospital or clinic"**
   - **Moderate → "Consult healthcare professional within 24 hours"**
   - **Low → "Routine consultation / monitoring"**

## Rule table

### Single-symptom rules

| ID | Finding | Weight | Emergency? |
|---|---|---|---|
| R01 | Fever | 1 | |
| R02 | Cough | 1 | |
| R03 | Difficulty Breathing | 2 | Yes |
| R04 | Severe Fatigue | 2 | |
| R05 | Chest Pain | 3 | Yes |
| R06 | Diarrhea | 1 | |
| R07 | Vomiting | 1 | |
| R08 | Dehydration | 3 | Yes |
| R09 | Loss Of Appetite | 1 | |
| R10 | Body Weakness | 1 | |
| R11 | Stomach Pain | 2 | |
| R12 | Intestinal Worms | 1 | |
| R13 | Cold Exposure | 1 | |
| R14 | Dense Fog | 1 | |
| R15 | Smoke Exposure | 1 | |
| R16 | Chronic Cough | 2 | |
| R17 | Asthma | 2 | |

### Compound rules (symptom combinations)

These fire on top of whichever single-symptom rules already matched, so a
combination is always weighted more than its parts considered separately.

| ID | Condition (all must be present) | Finding | Weight | Emergency? | Rationale |
|---|---|---|---|---|---|
| R18 | `difficulty_breathing` AND `chest_pain` | Possible acute respiratory distress | 2 | Yes | Combined cardiopulmonary warning signs |
| R19 | `diarrhea` AND `vomiting` AND `dehydration` | Acute gastrointestinal emergency pattern | 2 | Yes | Classic acute GI-emergency triad, relevant to the interior waterborne-risk barangays (Lake Duminagat, Napangan) named in the dataset dictionary |
| R20 | `chronic_cough` AND `smoke_exposure` | Chronic respiratory illness aggravated by smoke exposure | 1 | | Firewood-smoke exposure is a named high-elevation risk factor (Gandawan, Lalud, Petian) |
| R21 | `asthma` AND `cold_exposure` | Asthma exacerbation risk from cold/high-elevation exposure | 1 | | Cold-triggered bronchospasm in a known asthma case |
| R22 | `fever` AND `chronic_cough` | Persistent fever with chronic cough (TB-screening pattern; refer for evaluation) | 2 | | Standard TB-screening symptom pair; intentionally *not* an emergency override -- it should raise the score toward Moderate/High and prompt referral, not trigger the same response as an acute respiratory event |
| R23 | `dense_fog` AND `difficulty_breathing` | High-elevation respiratory risk factor present | 1 | | Environmental aggravating factor specific to the highland barangays |
| R24 | `intestinal_worms` AND `loss_of_appetite` AND `body_weakness` | Possible malnutrition risk from parasitic infection | 1 | | Recognized parasitic-infection symptom cluster |
| R25 | age ≥ 65 | Elderly (65+): increased vulnerability | 2 | | Age-based vulnerability adjustment |

## Design notes for the methodology chapter

- **Single-symptom weights are unchanged from the original prototype scoring**
  so results stay comparable to the initial curated dataset
  (`dataset/health_assessment_dataset.csv`); only the compound rules (R18–R25)
  and the emergency-override mechanism are new.
- **The emergency override was added to fix a real inconsistency**: prior to
  this rule base, `risk_level` and the referral recommendation were computed
  independently, so a case could be labeled `"Moderate"` while its referral
  text simultaneously read `"Emergency referral to nearest hospital or
  clinic"`. That is now structurally impossible -- any emergency-flagged rule
  forces `risk_level` to `"High"` before the referral is derived from it.
- **`rules_fired` is returned by `assess_patient()`** as a list of
  `{id, finding, weight}` objects, so downstream code (templates, exports, an
  evaluator's manual audit) can show exactly which rules produced a given
  case's classification rather than only the final number.
