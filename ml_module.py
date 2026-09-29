import csv
import pickle
from functools import lru_cache
from pathlib import Path

from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.tree import DecisionTreeClassifier

from health_system import normalize_symptom_text


FEATURES = (
    'fever', 'cough', 'difficulty_breathing', 'severe_fatigue',
    'chest_pain', 'diarrhea', 'vomiting', 'dehydration',
    'loss_of_appetite', 'body_weakness', 'stomach_pain',
    'intestinal_worms', 'cold_exposure', 'dense_fog',
    'smoke_exposure', 'chronic_cough', 'asthma',
)
CURATED_DATASET_PATH = Path(__file__).with_name('dataset').joinpath('health_assessment_dataset.csv')
# The classifier trains on the augmented (curated + rule-engine-labeled
# synthetic) dataset -- 16 records is too small a sample to support any
# accuracy claim. See scripts/generate_synthetic_dataset.py for provenance;
# every synthetic row is tagged source=synthetic in the CSV itself.
AUGMENTED_DATASET_PATH = Path(__file__).with_name('dataset').joinpath('health_assessment_dataset_augmented.csv')
DEFAULT_DATASET_PATH = AUGMENTED_DATASET_PATH if AUGMENTED_DATASET_PATH.exists() else CURATED_DATASET_PATH
MODEL_PATH = Path(__file__).with_name('risk_model.pkl')


def _feature_vector(row):
    detected = set(normalize_symptom_text(row.get('symptom_text', '')))
    values = []
    for feature in FEATURES:
        explicit_value = row.get(feature, '')
        values.append(int(explicit_value == '1' or feature in detected))
    return values


def _load_features_labels(dataset_path):
    features = []
    labels = []
    with Path(dataset_path).open('r', encoding='utf-8', newline='') as csvfile:
        for row in csv.DictReader(csvfile):
            if row.get('risk_level'):
                features.append(_feature_vector(row))
                labels.append(row['risk_level'])
    return features, labels


@lru_cache(maxsize=4)
def _trained_model(dataset_path):
    features, labels = _load_features_labels(dataset_path)

    if len(features) < 3 or len(set(labels)) < 2:
        raise ValueError('The dataset needs at least two risk classes and three records.')

    model = DecisionTreeClassifier(max_depth=8, random_state=42)
    model.fit(features, labels)
    return model


def evaluate_model(dataset_path=DEFAULT_DATASET_PATH):
    """Return a cross-validated accuracy estimate for the classifier.

    The model deployed by `_trained_model`/`retrain_model` is fit on the full
    dataset (best use of the available sample for the deployed model), so its
    training accuracy alone would be meaningless -- a decision tree can simply
    memorize the data it was fit on. Stratified k-fold cross-validation
    instead holds out a rotating slice of records per fold and reports how
    well the model generalizes to data it did not see, which is the honest
    number to report. The number of folds is capped by the smallest risk
    class so every fold still sees every class.
    """
    features, labels = _load_features_labels(str(dataset_path))

    if len(features) < 6 or len(set(labels)) < 2:
        return {
            'cv_accuracy': None,
            'cv_folds': 0,
            'sample_size': len(features),
            'note': 'Not enough records yet for a meaningful cross-validated estimate.',
        }

    smallest_class_size = min(labels.count(label) for label in set(labels))
    folds = max(2, min(5, smallest_class_size))
    if smallest_class_size < 2:
        return {
            'cv_accuracy': None,
            'cv_folds': 0,
            'sample_size': len(features),
            'note': 'A risk class has fewer than two records; cross-validation is not meaningful yet.',
        }

    model = DecisionTreeClassifier(max_depth=8, random_state=42)
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    scores = cross_val_score(model, features, labels, cv=splitter)

    return {
        'cv_accuracy': round(float(scores.mean()) * 100, 1),
        'cv_folds': folds,
        'sample_size': len(features),
        'note': f'{folds}-fold cross-validated accuracy across {len(features)} records.',
    }


def retrain_model(dataset_path=DEFAULT_DATASET_PATH, model_path=MODEL_PATH):
    model = _trained_model.__wrapped__(str(dataset_path))
    with Path(model_path).open('wb') as model_file:
        pickle.dump(model, model_file)
    _trained_model.cache_clear()
    return model


def load_saved_model(model_path=MODEL_PATH):
    if not Path(model_path).exists():
        retrain_model(model_path=model_path)
    with Path(model_path).open('rb') as model_file:
        return pickle.load(model_file)


def predict_risk(symptoms, age=None, dataset_path=DEFAULT_DATASET_PATH):
    """Return an ML risk prediction; rule-based results remain the safety authority."""
    try:
        model = load_saved_model() if str(dataset_path) == str(DEFAULT_DATASET_PATH) else _trained_model(str(dataset_path))
        vector = [[int(bool(symptoms.get(feature, False))) for feature in FEATURES]]
        prediction = model.predict(vector)[0]
        probabilities = model.predict_proba(vector)[0]
        confidence = round(float(max(probabilities)) * 100, 1)
        return {
            'ml_risk_level': prediction,
            'ml_confidence': confidence,
            'ml_status': 'trained',
        }
    except (OSError, ValueError, RuntimeError):
        return {
            'ml_risk_level': None,
            'ml_confidence': None,
            'ml_status': 'unavailable',
        }
