# Reliability Evaluation Checklist (SOP 5.4)

The system's reliability story is the offline-first design named in the
README: a service worker, an IndexedDB assessment queue, and automatic
synchronization. This is exactly the kind of behavior that's impractical to
verify with a stdlib script — it depends on the browser's network state and
storage, so this is a manual walkthrough. Run it in a real browser with dev
tools open, record pass/fail per step, and note the browser/OS used (results
can differ across browsers' service worker implementations).

## Setup

1. Serve the app (`python app.py`) and open it in Chrome or Firefox.
2. Open DevTools → Application tab (Chrome) or Storage tab (Firefox) so you
   can inspect the service worker registration and IndexedDB contents
   directly, not just observe the UI.
3. Log in as a registered resident account.

## Test cases

| # | Steps | Expected result | Pass/Fail |
|---|---|---|---|
| R1 | Load the dashboard once while online. | Page loads normally; DevTools → Application → Service Workers shows `service-worker.js` registered and activated. | |
| R2 | With DevTools open, go to Network tab → set throttling to "Offline". Reload the dashboard. | The page still loads (served from the service worker cache) rather than showing the browser's default offline error page. | |
| R3 | While still offline, complete a symptom assessment and submit it. | The app should not hang or show a raw network-error page; the assessment should be visibly queued (check IndexedDB in DevTools for a pending-assessment entry, or an on-screen "queued for sync" indicator if the UI shows one). | |
| R4 | Submit 2–3 more assessments while still offline. | Each one queues; none are silently dropped (IndexedDB entry count matches the number submitted). | |
| R5 | Set Network throttling back to "Online" (or "No throttling"). | The queued assessments sync automatically within a reasonable time, without requiring a manual page reload — confirm by checking `/assessments` afterward for the records, or by inspecting `POST /sync` in the Network tab firing on its own. | |
| R6 | After sync, check IndexedDB again. | The synced entries are cleared from the local queue (no duplicate re-submission on the next sync attempt). | |
| R7 | Repeat R2–R5 with a mid-air interruption: go offline, submit one assessment, go online, then go offline again *before* confirming sync completed, then online again. | No duplicate assessments are created server-side, and no assessment is permanently lost — check `/assessments` count matches what was actually submitted. | |
| R8 | Force-quit and reopen the browser tab while offline data is still queued (before R5). | On reopening (still offline), the queued data is still present in IndexedDB — a tab close/reopen must not silently drop unsynced data. | |

## Reporting

For each failed case, record: what actually happened, the browser/version,
and whether it's a UI-visibility issue (sync happened but wasn't shown) or a
data-loss issue (an assessment was genuinely dropped) — these are very
different severities and should be reported as such. A UI-visibility gap is a
minor finding; a data-loss finding on R7/R8 specifically is a legitimate
"future work" item worth naming explicitly, since it directly affects the
reliability claim in your abstract.
