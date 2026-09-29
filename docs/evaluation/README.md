# Evaluation Instruments

Item 5 of the Statement of the Problem asks how the system is evaluated
across five ISO/IEC 25010 quality characteristics. None of these are
something code can satisfy by itself — they need an instrument administered
to real people, real load, or a real audit. This folder holds a ready-to-use
instrument for each one; running/administering them and reporting the results
is the remaining work for the evaluation chapter.

| SOP item | Characteristic | Instrument | Status |
|---|---|---|---|
| 5.1 | Usability | [`usability_sus_questionnaire.md`](usability_sus_questionnaire.md) | Ready to administer |
| 5.2 | Functional Suitability | [`functional_suitability_traceability.md`](functional_suitability_traceability.md) | Ready — backed by the pytest suite |
| 5.3 | Performance Efficiency | [`performance_test.py`](performance_test.py) | Runnable now |
| 5.4 | Reliability | [`reliability_test_checklist.md`](reliability_test_checklist.md) | Ready to walk through |
| 5.5 | Security | [`security_test_checklist.md`](security_test_checklist.md) | Ready — several items pre-checked from this session's fixes |

## How to use each one

- **Usability (5.1):** Administer the SUS questionnaire to a sample of actual
  barangay health workers and/or residents after they complete a real
  assessment in the app. SUS produces a single 0–100 score per respondent;
  average across respondents and report against the standard SUS benchmark
  (a mean score ≥ 68 is "above average" industry-wide — cite Brooke, 1996,
  the original SUS paper, in your related-literature section).
- **Functional Suitability (5.2):** The traceability doc maps each numbered
  SOP requirement to the specific automated test(s) that verify it. Run
  `pytest -v` and paste the pass/fail output next to the mapping as your
  evidence table.
- **Performance Efficiency (5.3):** Run the script against a running instance
  of the app (locally or deployed) with `python docs/evaluation/performance_test.py`.
  It hits the key routes under configurable concurrency and reports response
  time percentiles — no external load-testing tool required.
- **Reliability (5.4):** This one is a manual walkthrough (it exercises the
  browser's offline queue and service worker, which isn't practical to fully
  automate without a browser-automation dependency this project doesn't
  have). Follow the checklist with dev tools open and record pass/fail per
  step.
- **Security (5.5):** A checklist mapping to common OWASP-style concerns,
  marked against what's already in place versus what's still open. Anything
  left unchecked is either a deliberate scope limitation (state it as one in
  the paper) or a next fix.

## A note on honesty in reporting

Every instrument here is designed to produce a number or a pass/fail you can
report even if the result isn't flattering — a low SUS score, a slow p95
response time, or a failed security check are all legitimate, citable
findings for a thesis (they become "Recommendations for future work"). Don't
adjust the instrument to get a better number; adjust the system, or report
the limitation honestly. A panel trusts an evaluation chapter more, not less,
when it includes at least one finding that isn't purely positive.
