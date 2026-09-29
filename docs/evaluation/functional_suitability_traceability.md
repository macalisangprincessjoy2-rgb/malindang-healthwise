# Functional Suitability Traceability (SOP 5.2)

Maps each numbered requirement from the Statement of the Problem to the
specific automated test(s) that verify it. Run `pytest -v` from the project
root and paste the output as the evidence column in your evaluation chapter —
this table is the mapping, the test run is the proof.

| SOP requirement | Implementation | Verifying test(s) |
|---|---|---|
| 1.1 User-centered symptoms in Bisaya | `bisaya_symptoms` form field → `normalize_symptom_text()` | `test_bisaya_symptom_parsing_works`, `test_bisaya_symptom_parsing_does_not_match_inside_unrelated_words` |
| 1.2 Medical knowledge base / IF-THEN rules | `health_system.RULES` (see `docs/rule_base.md`) | `test_assess_patient_high_risk_for_severe_symptoms`, `test_risk_level_uses_severity`, `test_rule_engine_never_contradicts_itself_on_emergency_findings` |
| 1.3 Healthcare facility & referral info | `referral_facility()`, `/api/facilities`, `/api/hospitals` | *(not yet covered — see gap below)* |
| 2. NLP for Bisaya symptoms | `normalize_symptom_text()` | `test_bisaya_symptom_parsing_works`, `test_bisaya_symptom_parsing_does_not_match_inside_unrelated_words` |
| 3. Rule-based + ML risk classification | `assess_patient()` (rule-based) + `ml_module.predict_risk()` (ML) | `test_ml_evaluate_model_returns_cross_validated_accuracy`, `test_augmented_dataset_is_labeled_consistently_with_the_rule_engine` |
| 4. Decision support recommendations & referral | `suggest_referral()`, `referral_priority()` | `test_referral_priority_matches_alertness`, `test_rule_engine_never_contradicts_itself_on_emergency_findings` |
| User registration & authentication | `/register`, `/login`, password hashing | `test_user_registration_persists_to_disk`, `test_user_registration_and_login_flow` |
| Access control (admin vs resident) | `admin_required()` guard on `/admin*` routes | `test_admin_routes_reject_non_admin_users` |
| Account recovery | `/reset-password` | `test_password_reset_requires_matching_email` |
| Brute-force login protection | In-memory login throttle | `test_login_locks_out_after_repeated_failures` |

## Coverage gaps (report these honestly, don't hide them)

These routes/behaviors exist in the running system but currently have no
automated test. Either add tests for them before your defense, or list them
explicitly in the evaluation chapter as scope not yet covered by automated
testing (a defensible, honest statement — "manually verified but not yet
under automated test" is a legitimate limitation to name):

- `/api/hospitals` (external Nominatim lookup + DB fallback)
- `/api/facilities`, `/admin/facilities` (facility CRUD)
- `/sync` (offline assessment queue sync)
- `/admin/model/download` (model export)
- `/records`, `/assessments`, `/assessments/<id>`, `/referral/<id>` (record browsing/detail views)

## Running the evidence

```bash
pytest -v
```

Paste the full pass/fail output (13 tests as of this writing) into your
evaluation chapter as the evidence artifact backing this table.
