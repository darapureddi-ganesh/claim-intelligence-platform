"""
XGBoost/scikit-learn scoring engine.

For the pilot, models are trained on synthetic data at first import if no
serialised model files exist. Real models are loaded from disk when present.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import numpy as np
import structlog
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.claimiq.scoring.features import extract_features, feature_names
from src.core.domain.models import Claim, ScoringResult
from src.core.domain.ports import IScoringEngine

logger = structlog.get_logger(__name__)

_MODEL_DIR = Path(__file__).parent / "models"
_SEVERITY_MODEL_PATH = _MODEL_DIR / "severity_model.pkl"
_COMPLEXITY_MODEL_PATH = _MODEL_DIR / "complexity_model.pkl"
_FRAUD_MODEL_PATH = _MODEL_DIR / "fraud_model.pkl"

MODEL_VERSION = "v0.1.0-synthetic"


def _build_synthetic_training_data(n: int = 500) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic training data for the pilot. Replace with real data."""
    rng = np.random.default_rng(42)
    X = rng.random((n, len(feature_names())))
    # Severity: high amount + late report → higher severity
    y_severity = ((X[:, 2] > 0.5) | (X[:, 4] > 0.5)).astype(int)
    # Complexity: non-English + high value + late → complex
    y_complexity = ((X[:, 6] > 0.5) | (X[:, 9] > 0.5) | (X[:, 4] > 0.5)).astype(int)
    # Fraud: weekend + late report + high amount → higher fraud signal
    y_fraud = ((X[:, 8] > 0.5) & (X[:, 4] > 0.5) & (X[:, 2] > 0.6)).astype(int)
    return X, y_severity, y_complexity, y_fraud


def _train_model(X: np.ndarray, y: np.ndarray) -> Pipeline:
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)),
    ])
    pipe.fit(X, y)
    return pipe


def _load_or_train_models() -> tuple[Pipeline, Pipeline, Pipeline]:
    _MODEL_DIR.mkdir(parents=True, exist_ok=True)
    paths = (_SEVERITY_MODEL_PATH, _COMPLEXITY_MODEL_PATH, _FRAUD_MODEL_PATH)

    if all(p.exists() for p in paths):
        logger.info("loading_scoring_models_from_disk")
        models = []
        for p in paths:
            with open(p, "rb") as f:
                models.append(pickle.load(f))
        return tuple(models)

    logger.warning("scoring_models_not_found_training_on_synthetic_data")
    X, y_sev, y_cplx, y_fraud = _build_synthetic_training_data()
    severity = _train_model(X, y_sev)
    complexity = _train_model(X, y_cplx)
    fraud = _train_model(X, y_fraud)

    for model, path in zip((severity, complexity, fraud), paths):
        with open(path, "wb") as f:
            pickle.dump(model, f)

    return severity, complexity, fraud


class XGBoostScoringEngine(IScoringEngine):
    """
    Scores a claim on severity, complexity, and fraud propensity.
    Uses GradientBoosting (scikit-learn) for the pilot; swap for XGBoost
    by replacing the pipeline estimator and re-serialising.
    """

    def __init__(self) -> None:
        self._severity_model, self._complexity_model, self._fraud_model = _load_or_train_models()

    def score(self, claim: Claim) -> ScoringResult:
        features = extract_features(claim).reshape(1, -1)

        severity = float(self._severity_model.predict_proba(features)[0][1])
        complexity = float(self._complexity_model.predict_proba(features)[0][1])
        fraud = float(self._fraud_model.predict_proba(features)[0][1])

        result = ScoringResult(
            claim_id=claim.id,
            severity_score=round(severity, 4),
            complexity_score=round(complexity, 4),
            fraud_propensity_score=round(fraud, 4),
            features_used={name: float(val) for name, val in zip(feature_names(), features[0])},
            model_version=MODEL_VERSION,
        )
        logger.info(
            "claim_scored",
            claim_id=str(claim.id),
            severity=result.severity_score,
            complexity=result.complexity_score,
            fraud=result.fraud_propensity_score,
        )
        return result
