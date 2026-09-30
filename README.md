# MALINDANG HIGHLANDS WEB-BASED EXPERT SYSTEM

This project implements a preliminary health assessment and referral expert system for geographically isolated and disadvantaged communities in the Mount Malindang Highlands of Misamis Occidental.

## Scope of the system
The system is designed for mountain communities in Don Victoriano Chiongbian and the elevated interior areas of Tangub City, especially Barangay Owayan and Barangay Hoyohoy/Fertig Hills. It targets barangay health workers and local community members as primary users.

The system supports preliminary screening of common local symptoms and generates risk-based recommendations and referral suggestions. It is intended for preliminary assessment only and does not replace clinical judgment from licensed physicians.

## Features
- Symptom-based local health screening
- Bisaya symptom parsing and term normalization
- Rule-based IF-THEN expert system for preliminary risk assessment
- Decision-support referral and priority recommendations
- Risk level classification for mild, moderate, and severe cases
- Community-aware user registration for residents of target highland barangays
- Interactive Mount Malindang community map
- Community-reported primary health-concern reference list by Bisaya phrase and location
- Voluntary system-evaluation questionnaire for residents, BHWs, and healthcare professionals
- Secure SQLite storage with hashed passwords and saved assessment records
- Supplementary machine-learning risk classifier trained from the sample dataset
- Admin monitoring dashboard with facility, guideline, and activity-log management
- Offline app-shell caching, account-scoped IndexedDB assessment queue, and automatic synchronization while the app is open
- Password reset, hospital lookup proxy, persisted ML model, and admin retraining
- Web interface using Flask

## System architecture

The application follows a rule-based expert-system workflow:

1. The resident or barangay health worker logs in and enters age, location, and symptoms.
2. The Bisaya NLP module normalizes phrases such as `kalibanga`, `bitok`, `pirteng bugnawa`, and `aso sa dabu-dabu` into symptom keys.
3. The expert-system engine applies weighted IF-THEN rules from `health_system.py`.
4. The decision-support module classifies risk and recommends monitoring, consultation, or referral.
5. The result is displayed and the assessment is saved in the configured database.

The rule-based engine remains the safety authority for emergency referral. The supplementary machine-learning classifier provides a risk prediction and confidence score from the sample dataset; it does not provide a medical diagnosis. All results require validation by a licensed healthcare professional.

### Offline use

Open the app and sign in while online at least once on the device/browser.
After the service worker has installed, an offline fallback page can be opened
without connectivity. Assessments entered offline are stored in that browser's
IndexedDB queue and associated with the last signed-in account on that device;
they are uploaded when the app is open and connectivity returns. If a session
has expired, sign in again with the same account. The queue is not encrypted by
the browser, is not shared across devices, and can be lost if site data is
cleared. Avoid shared devices for sensitive information and sign out after use.

An offline result is only a preliminary rule-based estimate generated in the
browser. It is not a diagnosis or server-recorded assessment; the server
reassesses the submission during synchronization, so its result may differ.
The app does not cache authenticated dashboard or health-record pages. Do not
delay urgent in-person care because internet access is unavailable.

Community-reported phrases and associated concern labels/locations are shown
as reference information on the dashboard. They do not independently establish
a diagnosis or alter automated risk scores.

## Research questionnaire

Respondents can submit the supplied system-evaluation questionnaire at
`/survey` without creating an account. The questionnaire requires affirmative
consent, records respondent type, barangay/location, sex, optional age, all 24
Likert ratings, and optional comments. It does not request a name or account
identifier. Only real submitted responses count toward the 386-person target;
the application does not generate respondents. An administrator can review
group totals and section means and download responses from the admin dashboard.
The respondent-facing questionnaire, prompts, ratings, consent text, and
validation messages are presented in Cebuano (Binisaya). Follow institutional
ethics approval, consent, data access, and retention requirements before
collecting or analyzing responses.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 on the host computer. The local Flask
development server binds to all network interfaces (debug mode is disabled),
so other devices on the same trusted Wi-Fi/LAN can open
`http://<host-computer-LAN-IP>:5000` (for example,
`http://10.20.20.208:5000`). The host computer must stay on and connected to
the same network. If Windows Firewall prompts, allow Python on **Private
networks only**; do not expose this development server to the public internet.

For a larger group or use beyond a trusted local network, deploy behind a
production WSGI server over HTTPS and use a managed MySQL database rather than
sharing the local development database.

## Administrator access

Set an administrator password before starting the app. The first startup creates the `admin` account automatically:

```powershell
$env:MALINDANG_ADMIN_PASSWORD="change-this-password"
python app.py
```

On the login page, choose **Admin login** and sign in with username `admin` and
the password set in `MALINDANG_ADMIN_PASSWORD`. The admin dashboard includes
**View submitted questionnaires** to inspect each response and its ratings, and
**Download Excel responses** to export them. On a hosted deployment, configure
a persistent MySQL `DATABASE_URL` so submissions remain available after
restarts and redeploys.

Administrator accounts are limited to research questionnaire monitoring.
Residents should register or sign in with regular accounts to use the health
assessment, history, and referral features.

To reset an existing administrator password, temporarily set
`MALINDANG_ADMIN_RESET_PASSWORD` in the hosting provider's environment settings.
The app applies it to the `admin` account during startup. After the deployment
succeeds, remove that variable immediately; while it remains set, each restart
resets the password again.

## Database configuration

SQLite (`health_app.db`) is used for local development when `DATABASE_URL` is
unset. Set `DATABASE_URL` to a MySQL connection URL to use MySQL instead:

```powershell
$env:DATABASE_URL="mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE?charset=utf8mb4"
python app.py
```

Create the MySQL database before starting the application and keep the URL in
an environment variable or secret manager; do not commit credentials. For
existing SQLite installations, stop the app, back up `health_app.db`, set
`DATABASE_URL`, and run the migration once:

```powershell
python scripts\migrate_sqlite_to_mysql.py
```

The migration refuses to copy into a non-empty MySQL database. Verify the
record counts and log in before deploying the app against the migrated data.
Password hashes are generated with Werkzeug's scrypt implementation
(`scrypt:32768:8:1`). Existing Werkzeug hashes remain usable and are upgraded
to scrypt after a successful login.

## Deploy publicly with Railway

The repository's `Procfile` defines the Gunicorn web server command for
Railway. To create a public HTTPS link for Messenger:

1. Push this project to a private GitHub repository. Do not include a real
   database URL, password, `SECRET_KEY`, or respondent export in the repository.
2. In Railway, create a project from that repository and add a **MySQL**
   database service. Wait for the database to finish provisioning.
3. Set the web service's start command to
   `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`.
   In the web service's Variables, add:
   - `DATABASE_URL`: reference the MySQL service's `MYSQL_URL` variable (use
     Railway's variable-reference picker so the database URL is not copied
     into source code).
   - `SECRET_KEY`: a new unpredictable secret, generated locally, for example
     with `python -c "import secrets; print(secrets.token_hex(32))"`.
   - `MALINDANG_ADMIN_PASSWORD`: a strong, unique initial admin password.
   - `SESSION_COOKIE_SECURE`: `true`.
4. Deploy the web service. Confirm its health check succeeds at `/login`, then
   use Railway's **Generate Domain** action to create a public HTTPS domain.
5. Test registration, login, admin access, MySQL persistence across a redeploy,
   and offline-queue synchronization before sharing the URL.

The app creates the database tables on startup. `DATABASE_URL` must point to the
Railway MySQL service; do not use the default SQLite database for a public
deployment because Railway's local filesystem is ephemeral. Existing local
SQLite users, assessments, and questionnaire submissions are not automatically
copied into Railway. Back up and migrate any data you intend to retain before
switching users to the hosted site; do not upload personal health or survey
data to an unsecured repository.

The Railway domain uses HTTPS, so enable `SESSION_COOKIE_SECURE=true`. Keep
the database private and internal to the Railway project, restrict project
access, rotate secrets if exposed, and arrange appropriate consent, retention,
and access controls before collecting real health or research data. The app
provides preliminary decision support only; it is not a substitute for
professional medical care.

`Procfile` and `render.yaml` remain available for other supported deployment
options. If `SECRET_KEY` is left unset, the app falls back to a random key
generated per process; this invalidates sessions on restart and can break
sessions across workers, so always configure a stable secret for deployment.

## Testing

```bash
pytest
```
