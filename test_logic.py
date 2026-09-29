from health_system import assess_patient, health_risk_level, normalize_symptom_text, referral_priority
from app import app, LOGIN_MAX_ATTEMPTS, get_db_connection


def test_assess_patient_high_risk_for_severe_symptoms():
    result = assess_patient({
        "fever": True,
        "cough": True,
        "difficulty_breathing": True,
        "severe_fatigue": True,
        "chest_pain": True,
        "diarrhea": False,
        "vomiting": False,
        "dehydration": False,
    })

    assert result["risk_level"] == "High"
    assert "Emergency" in result["referral"]


def test_risk_level_uses_severity():
    assert health_risk_level(0) == "Low"
    assert health_risk_level(3) == "Moderate"
    assert health_risk_level(6) == "High"


def test_referral_priority_matches_alertness():
    assert referral_priority("Severe dehydration") == "Immediate referral"
    assert referral_priority("Routine follow-up") == "Scheduled visit"


def test_bisaya_symptom_parsing_works():
    symptoms = normalize_symptom_text("kalibanga ug pagsuka, hubak, lisod ug ginhawa")
    assert "diarrhea" in symptoms
    assert "vomiting" in symptoms
    assert "cough" in symptoms
    assert "difficulty_breathing" in symptoms

    english_symptoms = normalize_symptom_text("difficulty breathing and chest pain")
    assert "difficulty_breathing" in english_symptoms
    assert "chest_pain" in english_symptoms


def test_bisaya_symptom_parsing_does_not_match_inside_unrelated_words():
    # "ubo" (cough) must not fire just because it appears as a substring of
    # another word -- matching has to respect word boundaries.
    symptoms = normalize_symptom_text("nagtrabaho sa uboson nga bukid")
    assert "cough" not in symptoms


def test_community_primary_health_concerns_are_available_on_dashboard():
    from community_health_concerns import COMMUNITY_HEALTH_CONCERNS

    assert len(COMMUNITY_HEALTH_CONCERNS) == 13
    assert any(
        concern['bisaya'] == 'taas nga presyon / pagkalipong'
        and 'Bagong Clarin' in concern['locations']
        for concern in COMMUNITY_HEALTH_CONCERNS
    )

    client = app.test_client()
    client.post('/register', data={
        'full_name': 'Concern List User', 'age': '30', 'username': 'concernlistuser',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 1',
        'password': 'concernlistpass1', 'confirm_password': 'concernlistpass1',
    })
    client.post('/login', data={
        'username': 'concernlistuser',
        'password': 'concernlistpass1',
    })
    dashboard = client.get('/dashboard')

    assert dashboard.status_code == 200
    assert 'Community-Reported Primary Health Concerns'.encode() in dashboard.data
    assert 'samad sa yuta'.encode() in dashboard.data
    assert 'Occupational injury'.encode() in dashboard.data
    assert 'not diagnoses'.encode() in dashboard.data
    assert b'Nearest configured healthcare referral' in dashboard.data
    assert b'Owayan Barangay Health Station' in dashboard.data
    assert b'not a live distance or route calculation' in dashboard.data


def test_location_referral_prefers_exact_barangay_and_falls_back_to_local_health_office():
    from app import (
        FACILITY_TYPE_BARANGAY,
        FACILITY_TYPE_HEALTH_OFFICE,
        FACILITY_TYPE_HOSPITAL,
        get_location_referral,
    )

    facilities = [
        {
            'name': 'Tangub District Hospital',
            'municipality': 'Tangub City',
            'barangay': '',
            'description': 'Hospital',
            'facility_type': FACILITY_TYPE_HOSPITAL,
        },
        {
            'name': 'Owayan Barangay Health Station',
            'municipality': 'Tangub City',
            'barangay': 'Owayan',
            'description': 'First-contact facility',
            'facility_type': FACILITY_TYPE_BARANGAY,
        },
        {
            'name': 'Tangub City Health Office',
            'municipality': 'Tangub City',
            'barangay': '',
            'description': 'City-level health office',
            'facility_type': FACILITY_TYPE_HEALTH_OFFICE,
        },
        {
            'name': 'Don Victoriano Health Infirmary',
            'municipality': 'Don Victoriano',
            'barangay': '',
            'description': 'Municipal facility',
            'facility_type': FACILITY_TYPE_HEALTH_OFFICE,
        },
    ]

    owayan = get_location_referral(facilities, 'Tangub City', 'Owayan')
    assert owayan['facility']['name'] == 'Owayan Barangay Health Station'
    assert owayan['hospital']['name'] == 'Tangub District Hospital'
    assert owayan['matched_barangay'] is True

    donor = get_location_referral(facilities, 'Don Victoriano', 'Lake Duminagat')
    assert donor['facility']['name'] == 'Don Victoriano Health Infirmary'
    assert donor['matched_barangay'] is False
    assert donor['hospital'] is None


def _valid_questionnaire_payload(client, **overrides):
    from survey_questionnaire import QUESTION_CODES

    with client.session_transaction() as stored_session:
        csrf_token = stored_session['_survey_csrf_token']
    payload = {
        'csrf_token': csrf_token,
        'respondent_type': 'resident',
        'barangay': 'Lake Duminagat',
        'sex': 'Female',
        'age': '34',
        'consent': 'yes',
        'comments': '',
    }
    payload.update({f'answer_{code}': '5' for code in QUESTION_CODES})
    payload.update(overrides)
    return payload


def test_research_questionnaire_requires_consent_and_all_ratings():
    client = app.test_client()

    survey_page = client.get('/survey')
    assert survey_page.status_code == 200
    assert b'Research Questionnaire' in survey_page.data
    assert b'Healthcare Professional' in survey_page.data
    assert b'answer_U1' in survey_page.data
    assert b'answer_C8' in survey_page.data

    missing_consent = _valid_questionnaire_payload(client)
    missing_consent.pop('consent')
    rejected = client.post('/survey', data=missing_consent)
    assert rejected.status_code == 400
    assert b'voluntary consent' in rejected.data

    missing_answer = _valid_questionnaire_payload(client)
    missing_answer.pop('answer_A4')
    rejected = client.post('/survey', data=missing_answer)
    assert rejected.status_code == 400
    assert b'answer every statement' in rejected.data

    connection = get_db_connection()
    assert connection.execute('SELECT COUNT(*) FROM questionnaire_responses').fetchone()[0] == 0
    connection.close()


def test_consented_questionnaire_submission_is_saved_for_admin_export():
    client = app.test_client()
    client.get('/survey')
    payload = _valid_questionnaire_payload(
        client,
        respondent_type='bhw',
        barangay='Nueva Vista',
        sex='Male',
        comments='=formula text should not run',
    )
    response = client.post('/survey', data=payload)

    assert response.status_code == 200
    assert b'Thank you for participating' in response.data

    connection = get_db_connection()
    submission = connection.execute(
        'SELECT respondent_type, barangay, sex, age, comments FROM questionnaire_responses'
    ).fetchone()
    assert tuple(submission) == (
        'bhw', 'Nueva Vista', 'Male', 34, '=formula text should not run'
    )
    assert connection.execute('SELECT COUNT(*) FROM questionnaire_answers').fetchone()[0] == 24
    connection.close()

    denied_export = client.get('/admin/survey/export', follow_redirects=False)
    assert denied_export.status_code in (301, 302)
    assert '/login' in denied_export.headers.get('Location', '')

    with client.session_transaction() as stored_session:
        stored_session['username'] = 'research-admin'
        stored_session['role'] = 'admin'
    export = client.get('/admin/survey/export')

    assert export.status_code == 200
    assert export.mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    assert 'malindang-questionnaire-responses.xlsx' in export.headers.get('Content-Disposition', '')
    assert export.data.startswith(b'PK')
    assert b'healthcare_professional' not in export.data


def test_user_registration_persists_to_disk():
    import sqlite3
    from app import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()
    client = app.test_client()

    response = client.post('/register', data={
        'full_name': 'Persisted User',
        'age': '30',
        'username': 'persisteduser',
        'municipality': 'Tangub City',
        'barangay': 'Hoyohoy',
        'address': 'Barangay Hoyohoy',
        'password': 'persistpass123',
        'confirm_password': 'persistpass123'
    }, follow_redirects=True)

    assert response.status_code == 200
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT username, password_hash FROM users WHERE username = ?",
        ('persisteduser',)
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[1] != 'persistpass123'


def test_user_registration_and_login_flow():
    client = app.test_client()

    response = client.post('/register', data={
        'full_name': 'Test User',
        'age': '25',
        'username': 'testuser',
        'municipality': 'Don Victoriano',
        'barangay': 'Bagumbang',
        'address': 'Sample address',
        'password': 'securepass123',
        'confirm_password': 'securepass123'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Login' in response.data

    login_response = client.post('/login', data={
        'username': 'testuser',
        'password': 'securepass123'
    }, follow_redirects=True)

    assert login_response.status_code == 200
    assert b'Assessment' in login_response.data or b'health' in login_response.data.lower()


def test_admin_routes_reject_non_admin_users():
    client = app.test_client()
    client.post('/register', data={
        'full_name': 'Regular Resident', 'age': '40', 'username': 'residentonly',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 1',
        'password': 'residentpass1', 'confirm_password': 'residentpass1',
    }, follow_redirects=True)
    client.post('/login', data={'username': 'residentonly', 'password': 'residentpass1'})

    admin_page = client.get('/admin', follow_redirects=False)
    assert admin_page.status_code in (301, 302)
    assert '/login' in admin_page.headers.get('Location', '')

    retrain = client.post('/admin/retrain', follow_redirects=False)
    assert retrain.status_code in (301, 302)
    assert '/login' in retrain.headers.get('Location', '')


def test_login_locks_out_after_repeated_failures():
    client = app.test_client()
    client.post('/register', data={
        'full_name': 'Lockout Test', 'age': '33', 'username': 'lockouttest',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 1',
        'password': 'correctpass1', 'confirm_password': 'correctpass1',
    }, follow_redirects=True)
    connection = get_db_connection()
    connection.execute('DELETE FROM login_attempts WHERE username = ?', ('lockouttest',))
    connection.commit()
    connection.close()

    for _ in range(LOGIN_MAX_ATTEMPTS):
        client.post('/login', data={'username': 'lockouttest', 'password': 'wrongpass'})

    locked_response = client.post('/login', data={'username': 'lockouttest', 'password': 'correctpass1'})
    assert b'sayop nga pagsulay' in locked_response.data.lower()
    connection = get_db_connection()
    connection.execute('DELETE FROM login_attempts WHERE username = ?', ('lockouttest',))
    connection.commit()
    connection.close()


def test_password_reset_requires_matching_email():
    client = app.test_client()
    client.post('/register', data={
        'full_name': 'Reset Me', 'age': '29', 'username': 'resetflow',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 1',
        'email': 'resetflow@example.com',
        'password': 'oldpassword1', 'confirm_password': 'oldpassword1',
    }, follow_redirects=True)

    wrong_email = client.post('/reset-password', data={
        'username': 'resetflow', 'email': 'notmyemail@example.com', 'new_password': 'newpassword1',
    })
    assert b'Susiha' in wrong_email.data

    ok = client.post('/reset-password', data={
        'username': 'resetflow', 'email': 'resetflow@example.com', 'new_password': 'newpassword1',
    }, follow_redirects=True)
    assert ok.status_code == 200

    login_response = client.post('/login', data={'username': 'resetflow', 'password': 'newpassword1'}, follow_redirects=True)
    assert b'Assessment' in login_response.data or b'health' in login_response.data.lower()


def test_new_password_hashes_use_scrypt():
    from app import hash_password
    from werkzeug.security import check_password_hash

    encoded = hash_password('safe-example-password')

    assert encoded.startswith('scrypt:32768:8:1$')
    assert check_password_hash(encoded, 'safe-example-password')
    assert not check_password_hash(encoded, 'different-password')


def test_successful_login_upgrades_legacy_password_hash():
    from werkzeug.security import generate_password_hash

    client = app.test_client()
    client.post('/register', data={
        'full_name': 'Legacy Hash User', 'age': '30', 'username': 'legacyhashuser',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 1',
        'password': 'legacy-password1', 'confirm_password': 'legacy-password1',
    })
    connection = get_db_connection()
    connection.execute(
        'UPDATE users SET password_hash = ? WHERE username = ?',
        (generate_password_hash('legacy-password1', method='pbkdf2:sha256:600000'), 'legacyhashuser'),
    )
    connection.commit()
    connection.close()

    response = client.post('/login', data={
        'username': 'legacyhashuser',
        'password': 'legacy-password1',
    })

    assert response.status_code in (301, 302)
    connection = get_db_connection()
    password_hash = connection.execute(
        'SELECT password_hash FROM users WHERE username = ?', ('legacyhashuser',)
    ).fetchone()['password_hash']
    connection.close()
    assert password_hash.startswith('scrypt:32768:8:1$')


def test_mysql_sql_adapter_preserves_quoted_question_marks():
    from db import HybridRow, MySQLConnection

    statement = "SELECT '?' AS marker, column_name FROM table_name WHERE value = ?"
    assert MySQLConnection._convert_placeholders(statement) == (
        "SELECT '?' AS marker, column_name FROM table_name WHERE value = %s"
    )
    row = HybridRow({'username': 'resident', 'id': 7})
    assert row['username'] == 'resident'
    assert row[0] == 'resident'
    assert dict(row) == {'username': 'resident', 'id': 7}


def test_ml_evaluate_model_returns_cross_validated_accuracy():
    from ml_module import evaluate_model

    metrics = evaluate_model()
    # Trains against the augmented (curated + synthetic) dataset by default,
    # so this should reflect a class-balanced sample, not the 16-row curated set alone.
    assert metrics['sample_size'] >= 100
    assert metrics['cv_folds'] >= 5
    assert metrics['cv_accuracy'] is not None
    assert 0 <= metrics['cv_accuracy'] <= 100


def test_augmented_dataset_is_labeled_consistently_with_the_rule_engine():
    import csv
    from ml_module import AUGMENTED_DATASET_PATH

    symptom_keys = (
        'fever', 'cough', 'difficulty_breathing', 'severe_fatigue', 'chest_pain',
        'diarrhea', 'vomiting', 'dehydration', 'loss_of_appetite', 'body_weakness',
        'stomach_pain', 'intestinal_worms', 'cold_exposure', 'dense_fog',
        'smoke_exposure', 'chronic_cough', 'asthma',
    )
    curated_count = 0
    synthetic_count = 0
    with AUGMENTED_DATASET_PATH.open('r', encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            symptoms = {k: row.get(k) == '1' for k in symptom_keys}
            computed = assess_patient(symptoms, age=row.get('age'))['risk_level']
            assert computed == row['risk_level'], f"{row['patient_id']}: computed {computed}, labeled {row['risk_level']}"
            if row['source'] == 'curated':
                curated_count += 1
            elif row['source'] == 'synthetic':
                synthetic_count += 1

    assert curated_count == 16
    assert synthetic_count > 0


def test_residents_cannot_see_each_others_assessment_records():
    from app import DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()

    client_a = app.test_client()
    client_a.post('/register', data={
        'full_name': 'Resident A', 'age': '30', 'username': 'residenta',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 1',
        'password': 'residentapass', 'confirm_password': 'residentapass',
    }, follow_redirects=True)
    client_a.post('/login', data={'username': 'residenta', 'password': 'residentapass'})
    assess_response = client_a.post('/assess', data={
        'age': '30', 'fever': 'on', 'cough': 'on', 'bisaya_symptoms': '',
    }, follow_redirects=True)
    assert assess_response.status_code == 200

    client_b = app.test_client()
    client_b.post('/register', data={
        'full_name': 'Resident B', 'age': '40', 'username': 'residentb',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 2',
        'password': 'residentbpass', 'confirm_password': 'residentbpass',
    }, follow_redirects=True)
    client_b.post('/login', data={'username': 'residentb', 'password': 'residentbpass'})

    # B's own record lists must not contain A's assessment.
    dashboard_b = client_b.get('/dashboard')
    assert b'Resident A' not in dashboard_b.data
    records_b = client_b.get('/records')
    assert b'Resident A' not in records_b.data

    # B guessing A's assessment ID directly must not work either.
    detail_b_view_of_a = client_b.get('/assessments/1', follow_redirects=True)
    assert b'Resident A' not in detail_b_view_of_a.data
    referral_b_view_of_a = client_b.get('/referral/1', follow_redirects=True)
    assert b'Resident A' not in referral_b_view_of_a.data

    # A can still see their own record.
    records_a = client_a.get('/records')
    assert b'Resident A' in records_a.data


def test_offline_assessments_sync_idempotently_and_reject_invalid_ids():
    client = app.test_client()
    username = 'offline_sync_user'
    client.post('/register', data={
        'full_name': 'Offline Sync User', 'age': '30', 'username': username,
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 3',
        'password': 'offlinesyncpass', 'confirm_password': 'offlinesyncpass',
    }, follow_redirects=True)
    client.post('/login', data={'username': username, 'password': 'offlinesyncpass'})

    assessment = {
        'local_id': 'd9428888-122b-4f23-9a11-2b1b45f50399',
        'client_id': 'd9428888-122b-4f23-9a11-2b1b45f50399',
        'data': {
            'age': '30',
            'bisaya_symptoms': 'kalibanga',
            'checked_symptoms': ['diarrhea', 'not_a_symptom'],
        },
    }
    first = client.post('/sync', json={'assessments': [assessment]})
    second = client.post('/sync', json={'assessments': [assessment]})
    rejected = client.post('/sync', json={'assessments': [{
        'client_id': 'not-a-uuid', 'data': {'fever': 'on'},
    }]})

    assert first.status_code == 200
    assert first.json['synced_ids'] == [assessment['client_id']]
    assert second.status_code == 200
    assert second.json['synced_ids'] == [assessment['client_id']]
    assert rejected.status_code == 200
    assert rejected.json['rejected_ids'] == ['not-a-uuid']

    connection = get_db_connection()
    rows = connection.execute(
        'SELECT symptom_summary FROM assessments WHERE username = ? AND client_id = ?',
        (username, assessment['client_id']),
    ).fetchall()
    connection.close()
    assert len(rows) == 1
    assert 'diarrhea' in rows[0]['symptom_summary'].lower()
    assert 'not_a_symptom' not in rows[0]['symptom_summary']


def test_offline_endpoints_and_sync_payload_limits():
    client = app.test_client()
    assert client.get('/offline.html').status_code == 200
    worker = client.get('/service-worker.js')
    assert worker.status_code == 200
    assert worker.headers['Service-Worker-Allowed'] == '/'

    client.post('/register', data={
        'full_name': 'Offline Limit User', 'age': '30', 'username': 'offline_limit_user',
        'municipality': 'Tangub City', 'barangay': 'Owayan', 'address': 'Purok 4',
        'password': 'offlinelimitpass', 'confirm_password': 'offlinelimitpass',
    }, follow_redirects=True)
    client.post('/login', data={
        'username': 'offline_limit_user', 'password': 'offlinelimitpass',
    })
    too_many = client.post('/sync', json={'assessments': [{}] * 51})
    too_large = client.post('/sync', data=' ' * 131073, content_type='application/json')
    malformed = client.post('/sync', json=['not-an-object'])
    not_a_list = client.post('/sync', json={'assessments': {}})
    assert too_many.status_code == 413
    assert too_large.status_code == 413
    assert malformed.status_code == 400
    assert not_a_list.status_code == 400


def test_rule_engine_never_contradicts_itself_on_emergency_findings():
    # Chest pain + difficulty breathing must always read as High risk with an
    # Emergency referral together -- risk_level and the referral text must
    # never disagree (this was a real bug: see docs/rule_base.md).
    result = assess_patient({"difficulty_breathing": True, "chest_pain": True})
    assert result["risk_level"] == "High"
    assert "Emergency" in result["referral"]
