#!/usr/bin/env python3
"""
Serve Prefect Flows
===================

This script serves Prefect flows so they appear in the UI and can be triggered.
For Prefect 3.x, `flow.serve()` is the recommended way for local development.

Usage:
    python serve_flows.py
"""

import os
import sys
from pathlib import Path

# Set Prefect API URL if not already set
if "PREFECT_API_URL" not in os.environ:
    os.environ["PREFECT_API_URL"] = "http://127.0.0.1:4200/api"

# Import flows
flows_dir = Path(__file__).parent
sys.path.insert(0, str(flows_dir))

from etl_flow import ridematch_ingest_flow
from train_flow import train_flow


def serve_flows():
    """Serve all flows so they appear in Prefect UI."""
    
    print("🚀 Serving Prefect flows...")
    print(f"   API URL: {os.environ.get('PREFECT_API_URL')}")
    print()
    print("📋 Flows will be available in Prefect UI at http://localhost:4200")
    print("   You can trigger them from the UI or CLI")
    print()
    print("   Press Ctrl+C to stop serving flows")
    print()
    
    # Serve both flows
    # This makes them available in the Prefect UI and allows them to be triggered
    ridematch_ingest_flow.serve(
        name="ridematch-ingest",
        tags=["etl", "ingestion"],
    )
    
    # Note: flow.serve() blocks, so we can only serve one at a time
    # To serve multiple flows, run them in separate processes or use the UI
    
    # Alternative: Serve both flows (this would require running in separate terminals)
    # train_flow.serve(
    #     name="train-and-register-model",
    #     tags=["training", "mlflow"],
    # )


if __name__ == "__main__":
    serve_flows()

