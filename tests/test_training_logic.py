"""
Tests for the pure training logic, with an explicit regression test for the
label-leakage bug.

feast/mlflow are stubbed so these run in CI without any infrastructure.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "feature_repo"))


def _stub(name: str, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


# --- Stub the heavy optional deps the training module imports at top level ---
_stub("feast", FeatureStore=object)
_mlflow = _stub(
    "mlflow",
    set_tracking_uri=lambda *a, **k: None,
    set_experiment=lambda *a, **k: None,
    start_run=lambda *a, **k: None,
    log_params=lambda *a, **k: None,
    log_metrics=lambda *a, **k: None,
    log_artifact=lambda *a, **k: None,
    register_model=lambda *a, **k: None,
)
_stub("mlflow.exceptions", MlflowException=Exception)
_stub("mlflow.sklearn", log_model=lambda *a, **k: None, load_model=lambda *a, **k: None)
_mlflow.exceptions = sys.modules["mlflow.exceptions"]
_mlflow.sklearn = sys.modules["mlflow.sklearn"]
_stub("minio_config")

from src.models.train_ranking_model import (
    acceptance_probability,
    haversine_distance,
    simulate_ride_requests,
    train_model,
)


# ----------------------------------------------------------------- haversine
def test_haversine_zero_distance():
    assert haversine_distance(37.77, -122.42, 37.77, -122.42) == pytest.approx(0.0, abs=1e-9)


def test_haversine_known_pair():
    # SF City Hall -> Oakland City Hall, ~13.4 km great-circle.
    d = haversine_distance(37.7793, -122.4193, 37.8044, -122.2712)
    assert 12.0 < d < 15.0


def test_haversine_is_vectorised():
    lats = np.array([37.77, 37.80, 37.75])
    lons = np.array([-122.42, -122.40, -122.45])
    out = haversine_distance(37.77, -122.42, lats, lons)
    assert out.shape == (3,)
    assert out[0] == pytest.approx(0.0, abs=1e-9)


# ------------------------------------------------------ acceptance model
def test_acceptance_probability_in_unit_interval():
    d = np.linspace(0, 40, 50)
    p = acceptance_probability(d, np.full(50, 0.8), np.full(50, 800.0))
    assert np.all((p >= 0) & (p <= 1))


def test_acceptance_decreases_with_distance():
    p = acceptance_probability(np.array([1.0, 20.0]), np.array([0.8, 0.8]), np.array([800.0, 800.0]))
    assert p[0] > p[1]


def test_acceptance_increases_with_accept_rate():
    p = acceptance_probability(np.array([5.0, 5.0]), np.array([0.2, 0.95]), np.array([800.0, 800.0]))
    assert p[1] > p[0]


# ------------------------------------------------------------- fixtures
def _fake_driver_features(n=60, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "driver_id": [f"driver_{i}" for i in range(n)],
        "event_timestamp": pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC"),
        "lat": 37.77 + rng.uniform(-0.08, 0.08, n),
        "lon": -122.42 + rng.uniform(-0.08, 0.08, n),
        "accept_rate_7d": rng.uniform(0.4, 0.99, n),
        "avg_response_ms": rng.uniform(200, 2500, n),
    })


# --------------------------------------------------------------- simulation
def test_simulation_shape_and_columns():
    df = simulate_ride_requests(_fake_driver_features(), num_requests=40, seed=1)
    assert set(df.columns) == {
        "request_id", "driver_id", "distance_km",
        "accept_rate_7d", "avg_response_ms", "label",
    }
    assert len(df) > 0
    assert df["request_id"].nunique() == 40


def test_simulation_is_reproducible():
    a = simulate_ride_requests(_fake_driver_features(), num_requests=20, seed=7)
    b = simulate_ride_requests(_fake_driver_features(), num_requests=20, seed=7)
    pd.testing.assert_frame_equal(a, b)


def test_simulation_produces_both_classes():
    df = simulate_ride_requests(_fake_driver_features(), num_requests=60, seed=3)
    assert df["label"].nunique() == 2
    rate = df["label"].mean()
    assert 0.05 < rate < 0.95, f"degenerate positive rate {rate}"


def test_label_is_not_a_deterministic_function_of_distance():
    """
    Regression test for the original label-leakage bug.

    Previously the positive label was `argmin(distance)` within each request,
    so the label was fully determined by an input feature. Assert that no such
    rule exists: within a request, the nearest driver must NOT always be the
    (only) positive.
    """
    df = simulate_ride_requests(_fake_driver_features(), num_requests=100, seed=5)

    nearest_is_positive = []
    for _, grp in df.groupby("request_id"):
        nearest_idx = grp["distance_km"].idxmin()
        nearest_is_positive.append(bool(grp.loc[nearest_idx, "label"]))

    frac = float(np.mean(nearest_is_positive))
    assert frac < 0.98, (
        f"nearest driver is positive in {frac:.1%} of requests — label leakage has returned"
    )

    # And there must be requests with more than one positive, which the old
    # one-hot-argmin labelling could never produce.
    positives_per_request = df.groupby("request_id")["label"].sum()
    assert (positives_per_request > 1).any()


def test_model_auc_is_realistic_not_perfect():
    """
    The whole point of removing leakage: AUC should be usefully above chance
    but nowhere near 1.0. A perfect score here means a feature encodes the label.
    """
    from sklearn.model_selection import train_test_split

    df = simulate_ride_requests(_fake_driver_features(n=120), num_requests=400, seed=11)
    X = df[["distance_km", "accept_rate_7d", "avg_response_ms"]]
    y = df["label"]
    X_tr, X_va, y_tr, y_va = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    _, metrics = train_model(X_tr, y_tr, X_va, y_va)

    assert 0.60 < metrics["val_auc"] < 0.97, f"suspicious AUC {metrics['val_auc']:.4f}"


def test_model_learns_expected_sign_on_distance():
    """Distance should push acceptance down -> negative coefficient."""
    from sklearn.model_selection import train_test_split

    df = simulate_ride_requests(_fake_driver_features(n=120), num_requests=400, seed=13)
    X = df[["distance_km", "accept_rate_7d", "avg_response_ms"]]
    y = df["label"]
    X_tr, X_va, y_tr, y_va = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    model, _ = train_model(X_tr, y_tr, X_va, y_va)
    coefs = dict(zip(X.columns, model.named_steps["clf"].coef_[0]))
    assert coefs["distance_km"] < 0
