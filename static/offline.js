const OFFLINE_DB = 'malindang-offline';
const QUEUE_STORE = 'assessment_queue';
const CACHE_ONLY_KEYS = new Set(['facilities-cache']);
const ACTIVE_ACCOUNT_KEY = 'malindang-active-account';
const SYMPTOM_KEYS = [
    'fever', 'cough', 'difficulty_breathing', 'severe_fatigue', 'chest_pain',
    'diarrhea', 'vomiting', 'dehydration', 'loss_of_appetite', 'body_weakness',
    'stomach_pain', 'intestinal_worms', 'cold_exposure', 'dense_fog',
    'smoke_exposure', 'chronic_cough', 'asthma',
];

const PHRASE_MAP = {
    'kalibanga': 'diarrhea',
    'pagsuka': 'vomiting',
    'hubak': 'cough',
    'ubo': 'cough',
    'trangkaso': 'fever',
    'hilanat': 'fever',
    'sakit sa tiyan': 'stomach_pain',
    'bitok': 'intestinal_worms',
    'asam': 'fever',
    'lisod ug ginhawa': 'difficulty_breathing',
    'ginhawa': 'difficulty_breathing',
    'sakit sa hawak': 'body_weakness',
    'sakit sa lawas': 'body_weakness',
    'samad sa yuta': 'body_weakness',
    'taas nga presyon': 'body_weakness',
    'pagkalipong': 'body_weakness',
    'losing gana': 'loss_of_appetite',
    'kapoy': 'severe_fatigue',
    'ginakapoy': 'severe_fatigue',
    'hangos': 'difficulty_breathing',
    'sakit sa dughan': 'chest_pain',
    'dughan': 'chest_pain',
    'sakit sa ulo': 'fever',
    'hangin': 'difficulty_breathing',
    'panahon': 'fever',
    'diyeta': 'loss_of_appetite',
    'wala gyuy gana mokaon': 'loss_of_appetite',
    'kulba': 'body_weakness',
    'kaguyod': 'body_weakness',
    'sakit kaayo': 'body_weakness',
    'pirteng bugnawa': 'cold_exposure',
    'bugnaw': 'cold_exposure',
    'gabun': 'dense_fog',
    'aso sa dabu-dabu': 'smoke_exposure',
    'sigeg ubo nga nagdugay': 'chronic_cough',
    'bronchitis': 'chronic_cough',
    'hika': 'asthma',
    'difficulty breathing': 'difficulty_breathing',
    'chest pain': 'chest_pain',
    'loss of appetite': 'loss_of_appetite',
    'severe fatigue': 'severe_fatigue',
    'body weakness': 'body_weakness',
    'stomach pain': 'stomach_pain',
    'intestinal worms': 'intestinal_worms',
    'cold exposure': 'cold_exposure',
    'dense fog': 'dense_fog',
    'smoke exposure': 'smoke_exposure',
    'chronic cough': 'chronic_cough',
    'asthma': 'asthma',
    'high fever': 'fever',
    'dry cough': 'cough',
    'fever and cough': 'fever',
    'cough and fever': 'cough',
};

const SINGLE_WORD_MAP = {
    fever: 'fever',
    cough: 'cough',
    fatigue: 'severe_fatigue',
    diarrhea: 'diarrhea',
    vomiting: 'vomiting',
    dehydration: 'dehydration',
    weakness: 'body_weakness',
    appetite: 'loss_of_appetite',
    asthma: 'asthma',
    bronchitis: 'chronic_cough',
};

const RULES = [
    ['R01', ['fever'], 1, 'Fever', false],
    ['R02', ['cough'], 1, 'Cough', false],
    ['R03', ['difficulty_breathing'], 2, 'Difficulty Breathing', true],
    ['R04', ['severe_fatigue'], 2, 'Severe Fatigue', false],
    ['R05', ['chest_pain'], 3, 'Chest Pain', true],
    ['R06', ['diarrhea'], 1, 'Diarrhea', false],
    ['R07', ['vomiting'], 1, 'Vomiting', false],
    ['R08', ['dehydration'], 3, 'Dehydration', true, 'Severe dehydration'],
    ['R09', ['loss_of_appetite'], 1, 'Loss Of Appetite', false],
    ['R10', ['body_weakness'], 1, 'Body Weakness', false],
    ['R11', ['stomach_pain'], 2, 'Stomach Pain', false],
    ['R12', ['intestinal_worms'], 1, 'Intestinal Worms', false],
    ['R13', ['cold_exposure'], 1, 'Cold Exposure', false],
    ['R14', ['dense_fog'], 1, 'Dense Fog', false],
    ['R15', ['smoke_exposure'], 1, 'Smoke Exposure', false],
    ['R16', ['chronic_cough'], 2, 'Chronic Cough', false],
    ['R17', ['asthma'], 2, 'Asthma', false],
    ['R18', ['difficulty_breathing', 'chest_pain'], 2, 'Possible acute respiratory distress', true],
    ['R19', ['diarrhea', 'vomiting', 'dehydration'], 2, 'Acute gastrointestinal emergency pattern', true],
    ['R20', ['chronic_cough', 'smoke_exposure'], 1, 'Chronic respiratory illness aggravated by smoke exposure', false],
    ['R21', ['asthma', 'cold_exposure'], 1, 'Asthma exacerbation risk from cold/high-elevation exposure', false],
    ['R22', ['fever', 'chronic_cough'], 2, 'Persistent fever with chronic cough (TB-screening pattern; refer for evaluation)', false],
    ['R23', ['dense_fog', 'difficulty_breathing'], 1, 'High-elevation respiratory risk factor present', false],
    ['R24', ['intestinal_worms', 'loss_of_appetite', 'body_weakness'], 1, 'Possible malnutrition risk from parasitic infection', false],
    ['R25', [], 2, 'Elderly (65+): increased vulnerability', false, null, 65],
];

function openOfflineDb() {
    return new Promise((resolve, reject) => {
        if (!('indexedDB' in window)) {
            reject(new Error('This browser does not support offline storage.'));
            return;
        }
        const request = indexedDB.open(OFFLINE_DB, 1);
        request.onupgradeneeded = () => {
            if (!request.result.objectStoreNames.contains(QUEUE_STORE)) {
                request.result.createObjectStore(QUEUE_STORE, {
                    keyPath: 'local_id',
                    autoIncrement: true,
                });
            }
        };
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error || new Error('Could not open offline storage.'));
    });
}

function currentOfflineAccount() {
    const pageAccount = document.body.dataset.offlineAccount;
    if (pageAccount) {
        try {
            localStorage.setItem(ACTIVE_ACCOUNT_KEY, pageAccount);
        } catch (error) {
            console.error('Could not retain the offline account on this device:', error);
            return pageAccount;
        }
        return pageAccount;
    }
    try {
        return localStorage.getItem(ACTIVE_ACCOUNT_KEY);
    } catch (error) {
        console.error('Could not identify the offline account on this device:', error);
        return null;
    }
}

function newClientId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

async function getQueue() {
    const db = await openOfflineDb();
    try {
        return await new Promise((resolve, reject) => {
            const request = db.transaction(QUEUE_STORE, 'readonly').objectStore(QUEUE_STORE).getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('Could not read offline assessments.'));
        });
    } finally {
        db.close();
    }
}

async function putQueueItem(item) {
    const db = await openOfflineDb();
    try {
        return await new Promise((resolve, reject) => {
            const transaction = db.transaction(QUEUE_STORE, 'readwrite');
            const request = transaction.objectStore(QUEUE_STORE).put(item);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error('Could not save offline assessment.'));
        });
    } finally {
        db.close();
    }
}

async function queueAssessment(form) {
    const account = currentOfflineAccount();
    if (!account) {
        throw new Error('Sign in while online before saving offline assessments on this device.');
    }
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());
    data.checked_symptoms = Array.from(
        form.querySelectorAll('input[type="checkbox"]:checked'),
        input => input.name,
    );
    const clientId = data.client_id || newClientId();
    data.client_id = clientId;
    await putQueueItem({
        local_id: clientId,
        client_id: clientId,
        username: account,
        data,
        queued_at: new Date().toISOString(),
    });
    return { clientId, data };
}

async function syncOfflineAssessments() {
    if (!navigator.onLine) return { synced: 0, pending: null };
    const account = currentOfflineAccount();
    if (!account) return { synced: 0, pending: 0 };
    const allItems = await getQueue();
    const pending = allItems.filter(item =>
        !CACHE_ONLY_KEYS.has(item.local_id) && item.username === account,
    );
    if (!pending.length) return { synced: 0, pending: 0 };

    const prepared = [];
    for (const item of pending.slice(0, 50)) {
        const clientId = item.client_id || item.data?.client_id || newClientId();
        const normalized = {
            ...item,
            client_id: clientId,
            data: { ...(item.data || {}), client_id: clientId },
        };
        if (item.client_id !== clientId) await putQueueItem(normalized);
        prepared.push(normalized);
    }

    const response = await fetch('/sync', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assessments: prepared }),
    });
    if (!response.ok) {
        if (response.status === 401) {
            throw new Error('Your session needs sign-in. Reconnect, sign in, and pending assessments will sync.');
        }
        throw new Error(`Sync failed (HTTP ${response.status}). Your queued assessments are still saved on this device.`);
    }

    const result = await response.json();
    const syncedIds = new Set(result.synced_ids || []);
    const db = await openOfflineDb();
    try {
        await new Promise((resolve, reject) => {
            const transaction = db.transaction(QUEUE_STORE, 'readwrite');
            const store = transaction.objectStore(QUEUE_STORE);
            prepared.forEach(item => {
                if (syncedIds.has(item.client_id)) store.delete(item.local_id);
            });
            transaction.oncomplete = resolve;
            transaction.onerror = () => reject(transaction.error || new Error('Could not update the local sync queue.'));
            transaction.onabort = () => reject(transaction.error || new Error('Local sync queue update was aborted.'));
        });
    } finally {
        db.close();
    }
    const remaining = (await getQueue()).filter(item =>
        !CACHE_ONLY_KEYS.has(item.local_id) && item.username === account,
    ).length;
    return { synced: syncedIds.size, pending: remaining };
}

function normalizeSymptoms(data) {
    const found = new Set((data.checked_symptoms || []).filter(key => SYMPTOM_KEYS.includes(key)));
    SYMPTOM_KEYS.forEach(key => {
        if (data[key]) found.add(key);
    });
    const text = (data.bisaya_symptoms || '').toLowerCase();
    Object.entries(PHRASE_MAP).forEach(([phrase, key]) => {
        const pattern = new RegExp(`\\b${phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
        if (pattern.test(text)) found.add(key);
    });
    (text.match(/[a-z]+/g) || []).forEach(word => {
        if (SINGLE_WORD_MAP[word]) found.add(SINGLE_WORD_MAP[word]);
    });
    return found;
}

function assessOffline(data) {
    const symptoms = normalizeSymptoms(data);
    const age = Number.parseInt(data.age, 10);
    let score = 0;
    let emergency = false;
    const findings = [];

    RULES.forEach(([id, keys, weight, finding, emergencyOverride, emergencyLabel, minAge]) => {
        const matches = keys.every(key => symptoms.has(key));
        const ageMatches = !minAge || (Number.isFinite(age) && age >= minAge);
        if (!matches || !ageMatches) return;
        score += weight;
        findings.push(finding);
        if (emergencyOverride) {
            emergency = true;
            if (emergencyLabel && !findings.includes(emergencyLabel)) findings.push(emergencyLabel);
        }
    });

    let riskLevel = score >= 6 ? 'High' : score >= 3 ? 'Moderate' : 'Low';
    if (emergency) riskLevel = 'High';
    const referral = riskLevel === 'High'
        ? 'Emergency referral to nearest hospital or clinic'
        : riskLevel === 'Moderate'
            ? 'Consult healthcare professional within 24 hours'
            : 'Routine consultation / monitoring';
    return { riskLevel, referral, findings, score };
}

function setStatus(message, state = 'info') {
    document.querySelectorAll('[data-offline-status]').forEach(element => {
        element.textContent = message;
        element.dataset.state = state;
    });
}

async function refreshQueueStatus() {
    try {
        const account = currentOfflineAccount();
        const pending = account
            ? (await getQueue()).filter(item =>
                !CACHE_ONLY_KEYS.has(item.local_id) && item.username === account,
            )
            : [];
        document.querySelectorAll('[data-pending-count]').forEach(element => {
            element.textContent = String(pending.length);
        });
        if (!navigator.onLine) {
            setStatus(`Offline. ${pending.length} assessment(s) saved on this device and waiting to sync.`, 'offline');
        } else if (pending.length) {
            setStatus(`${pending.length} assessment(s) waiting to sync.`, 'pending');
        } else {
            setStatus('Online. No assessments are waiting to sync.', 'online');
        }
    } catch (error) {
        setStatus(error.message, 'error');
    }
}

async function reportSyncFailure(error) {
    await refreshQueueStatus();
    if (error instanceof TypeError || !navigator.onLine) {
        setStatus('Could not reach the server. Queued assessments remain on this device and will retry when the connection is available.', 'offline');
    } else {
        setStatus(error.message, 'error');
    }
}

function showOfflineAssessment(data) {
    const result = assessOffline(data);
    const resultPanel = document.querySelector('[data-offline-result]');
    if (!resultPanel) {
        setStatus(`Saved offline. Preliminary rule-based risk: ${result.riskLevel}. ${result.referral}`, 'pending');
        return;
    }
    resultPanel.replaceChildren();
    const title = document.createElement('h2');
    title.textContent = 'Assessment saved on this device';
    const summary = document.createElement('p');
    summary.textContent = `Offline preliminary risk: ${result.riskLevel}. ${result.referral}`;
    const details = document.createElement('p');
    details.textContent = result.findings.length
        ? `Matched findings: ${result.findings.join(', ')}`
        : 'No recognized symptoms were selected or entered.';
    const caution = document.createElement('p');
    caution.textContent = 'This is a rule-only offline estimate, not a diagnosis. It has not yet been saved to your health record. The server will reassess it when synced. If symptoms are severe, seek urgent in-person care; do not wait for internet access.';
    resultPanel.append(title, summary, details, caution);
    resultPanel.hidden = false;
}

async function submitAssessment(form) {
    const submitButton = form.querySelector('[type="submit"]');
    if (submitButton) submitButton.disabled = true;
    try {
        if (navigator.onLine) {
            try {
                const response = await fetch(form.action, {
                    method: 'POST',
                    body: new FormData(form),
                    credentials: 'same-origin',
                    headers: { 'X-Requested-With': 'fetch' },
                });
                if (response.status === 401 || response.redirected) {
                    throw new Error('Your sign-in may have expired. Please sign in again; the assessment has not been submitted.');
                }
                if (!response.ok) {
                    const message = `The server could not save this assessment (HTTP ${response.status}). Your form remains available; please try again.`;
                    setStatus(message, 'error');
                    return;
                }
                document.open();
                document.write(await response.text());
                document.close();
                return;
            } catch (error) {
                if (error instanceof TypeError || !navigator.onLine) {
                    setStatus('Connection lost while submitting. Saving this assessment on the device for later sync.', 'offline');
                } else {
                    setStatus(error.message, 'error');
                    return;
                }
            }
        }

        const queued = await queueAssessment(form);
        showOfflineAssessment(queued.data);
        form.reset();
        const clientIdField = form.querySelector('[name="client_id"]');
        if (clientIdField) clientIdField.value = newClientId();
        await refreshQueueStatus();
        if (navigator.onLine) syncOfflineAssessments().then(refreshQueueStatus).catch(reportSyncFailure);
    } catch (error) {
        setStatus(`Could not save assessment offline: ${error.message}`, 'error');
    } finally {
        if (submitButton?.isConnected) submitButton.disabled = false;
    }
}

async function startOfflineSupport() {
    if ('serviceWorker' in navigator) {
        try {
            await navigator.serviceWorker.register('/service-worker.js');
        } catch (error) {
            setStatus(`Offline page caching could not start: ${error.message}`, 'error');
        }
    }

    document.querySelectorAll('.assessment-form').forEach(form => {
        const idField = form.querySelector('[name="client_id"]');
        if (idField && !idField.value) idField.value = newClientId();
        form.addEventListener('submit', event => {
            event.preventDefault();
            submitAssessment(form);
        });
    });

    window.addEventListener('online', () => {
        setStatus('Connection restored. Syncing saved assessments…', 'pending');
        syncOfflineAssessments().then(refreshQueueStatus).catch(reportSyncFailure);
    });
    window.addEventListener('offline', refreshQueueStatus);
    await refreshQueueStatus();
    if (navigator.onLine) {
        syncOfflineAssessments().then(refreshQueueStatus).catch(reportSyncFailure);
    }
    window.setInterval(() => {
        if (navigator.onLine) {
            syncOfflineAssessments().then(refreshQueueStatus).catch(reportSyncFailure);
        }
    }, 30000);
}

document.addEventListener('DOMContentLoaded', () => {
    startOfflineSupport();
});
