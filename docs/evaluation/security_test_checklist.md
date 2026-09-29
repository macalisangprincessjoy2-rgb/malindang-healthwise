# Security Evaluation Checklist (SOP 5.5)

Organized loosely around OWASP Top 10 categories relevant to a small Flask +
SQLite app. Items already addressed in code are marked done, with the file
that does it; open items are marked with what running them or fixing them
would involve. Report both categories in the evaluation chapter — a security
section that only lists what's already fixed reads as incomplete, since it
implies nothing was checked and found lacking.

## Authentication & session management

- [x] **Passwords are hashed**, never stored or compared in plaintext —
  `werkzeug.security.generate_password_hash`/`check_password_hash`
  ([app.py](../../app.py)).
- [x] **No hardcoded secret key** — `SECRET_KEY` falls back to a random
  per-process value with a startup warning rather than a static string
  ([app.py](../../app.py)).
- [x] **Session cookies are `HttpOnly` and `SameSite=Lax`**; `Secure` is
  togglable via the `SESSION_COOKIE_SECURE` env var for HTTPS deployments
  ([app.py](../../app.py)).
- [x] **Login brute-force throttling** — 5 failed attempts per username locks
  that username for 5 minutes ([app.py](../../app.py)).
  - **Known limitation:** the throttle is in-memory and per-process. Under
    gunicorn with multiple workers (see `Procfile`), an attacker distributed
    across workers isn't fully throttled — each worker tracks its own
    counter. Adequate for this prototype's scale; a shared store (Redis, or a
    DB-backed counter) would be needed for a real multi-worker deployment.
    Report this as a named limitation, not a silent gap.
- [ ] **No CSRF token on state-changing forms.** `SameSite=Lax` cookies
  (already in place) block *most* cross-site POST-based CSRF, since the
  session cookie isn't sent on a cross-site POST — but this is a partial
  mitigation, not a substitute for per-form tokens. A determined attacker
  using a same-site or subdomain vector, or a browser predating `SameSite`
  support, isn't covered. **To close this fully:** add `Flask-WTF`'s CSRF
  protection (`CSRFProtect(app)` + `{{ csrf_token() }}` in each POST form) —
  this is the standard fix and is a reasonable "future work" item to name
  explicitly if not done before defense.
- [ ] **No password complexity/strength requirement** beyond an 8-character
  minimum on reset (`app.py`'s `/reset-password`); registration doesn't
  enforce even that. Consider whether your evaluation rubric expects a
  minimum-length check on `/register` too.

## Injection

- [x] **All SQL queries are parameterized** (`?` placeholders, never string
  interpolation) — verified by inspection of every `connection.execute(...)`
  call in `app.py`. No SQL injection surface found.
- [x] **Templates use Jinja2's default autoescaping** — Flask's
  `render_template` autoescapes HTML by default, so user-supplied fields
  (name, notes, symptom text) rendered into templates are not a reflected-XSS
  vector as long as no template uses `| safe` or `Markup()` on user input.
  **Verify:** grep the `templates/` directory for `| safe` or `{% autoescape
  false %}` and confirm none wrap user-controlled data.

## Dependency & supply chain

- [ ] **No automated dependency vulnerability scan has been run.** Run one as
  part of the evaluation:
  ```bash
  pip install pip-audit
  pip-audit -r requirements.txt
  ```
  Report the output (even "0 known vulnerabilities" is a citable, positive
  finding) and re-run it close to your defense date, since new CVEs are
  disclosed continuously.

## Access control

- [x] **Admin routes reject non-admin sessions** — `admin_required()` checks
  `session.get('role') == 'admin'` before any `/admin*` route proceeds;
  covered by `test_admin_routes_reject_non_admin_users`.
- [x] **Fixed: broken access control on assessment records (was the most
  severe finding of this evaluation).** Before this fix, `load_records()`
  had no `WHERE` clause at all — every logged-in resident's dashboard,
  `/records`, and `/assessments` pages showed **every other resident's**
  health records (name, symptoms, risk level), not just their own. This
  wasn't a narrow ID-guessing edge case; it was the default, unfiltered
  behavior of the main record-listing routes on a system handling personal
  health information. Fixed by adding a `username` column to `assessments`,
  recording it at save time, and scoping every resident-facing query
  (`load_records()`, `/assessments`, `/assessments/<id>`,
  `/referral/<id>`) to `WHERE username = ?`. Admins retain the ability to
  view any specific assessment's detail/referral page (`allow_any=True`,
  gated by `admin_required()`), but do not see other residents' records on
  their own personal dashboard. Regression-test this specifically before
  defense: register two accounts, save an assessment under each, and confirm
  neither can see the other's records anywhere in the UI.

## Transport & deployment

- [ ] **HTTPS is not enforced in code** — this is expected for local
  development, but confirm the actual deployment target (Render, per
  `render.yaml`) terminates TLS and that `SESSION_COOKIE_SECURE=true` is set
  there (see the note added to `README.md`).

## How to report this section

State plainly which items are done, which are open, and for each open item
whether you fixed it before defense or are naming it as a scope limitation.
The IDOR item above is the one I'd prioritize fixing if only one gets
addressed — it's a real data-exposure issue on a system that handles health
records, not just a hardening nice-to-have.
