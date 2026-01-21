import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import sys
import os
import pandas as pd
import json

import numpy as np

# Mock dependencies before importing main
sys.modules["feast"] = MagicMock()
sys.modules["mlflow"] = MagicMock()
sys.modules["mlflow.sklearn"] = MagicMock()

# Import app after mocking
from src.match_api.main import app, resources, DriftDetector

client = TestClient(app)

@pytest.fixture
def mock_resources():
    """Mock Feast store and MLflow model/stats"""
    resources.clear()
    
    # Mock Feature Store
    mock_store = MagicMock()
    # Mock get_online_features response
    mock_store.get_online_features.return_value.to_dict.return_value = {
        "driver_id": ["driver_0"],
        "lat": [40.73],
        "lon": [-73.93],
        "accept_rate_7d": [0.8],
        "avg_response_ms": [500]
    }
    resources["feature_store"] = mock_store
    
    # Mock Model
    mock_model = MagicMock()
    # Mock predict_proba: return [prob_0, prob_1]
    mock_model.predict_proba.return_value = np.array([[0.2, 0.8]])
    resources["model"] = mock_model
    
    # Mock Drift Detector stats
    stats = {
        "distance_km": {"p95": 5.0},
        "accept_rate_7d": {"p95": 0.9},
        "avg_response_ms": {"p95": 1000}
    }
    resources["drift_detector"] = DriftDetector(stats)
    
    yield
    resources.clear()

def test_metrics_endpoint_exists():
    """Verify /metrics endpoint is reachable even without startup event"""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "match_request_latency_seconds" in response.text

def test_drift_metrics_exposed(mock_resources):
    """Verify feature_drift_score is present in metrics"""
    # Simulate a request to populate metrics (though gauges might exist at init)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "feature_drift_score" in response.text

def test_match_endpoint_drift_update(mock_resources):
    """Verify calling match endpoint updates drift detector"""
    payload = {
        "rider_id": "test_rider",
        "rider_lat": 40.7,
        "rider_lon": -74.0,
        "top_k": 1
    }
    
    with patch.object(resources["drift_detector"], "observe") as mock_observe:
        response = client.post("/match", json=payload)
        if response.status_code != 200:
            print(f"Server Error: {response.text}")
        assert response.status_code == 200
        
        # Verify observe was called for features
        # We expect observe call for distance_km, accept_rate_7d, avg_response_ms
        assert mock_observe.call_count >= 3
        calls = [args[0] for args, _ in mock_observe.call_args_list]
        assert "distance_km" in calls
        assert "accept_rate_7d" in calls

def test_feature_stats_file_exists():
    """Validates that training stats are checked into the repo"""
    # Assuming run from root
    import pathlib
    stats_path = pathlib.Path("models/feature_stats.json")
    assert stats_path.exists(), "Feature statistics file missing! Run training to generate."
