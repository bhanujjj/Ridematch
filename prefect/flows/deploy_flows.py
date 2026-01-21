#!/usr/bin/env python3
"""
Deploy Prefect Flows
====================

This script deploys Prefect flows to the Prefect server so they appear in the UI
and can be scheduled/triggered.

For Prefect 3.x, we use `flow.deploy()` instead of the old Deployment API.

Usage:
    python deploy_flows.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Set Prefect API URL if not already set
if "PREFECT_API_URL" not in os.environ:
    os.environ["PREFECT_API_URL"] = "http://127.0.0.1:4200/api"

# Import flows
# Change to the flows directory to import correctly
flows_dir = Path(__file__).parent
sys.path.insert(0, str(flows_dir))

from etl_flow import ridematch_ingest_flow
from train_flow import train_flow


def deploy_flows():
    """Deploy all flows to Prefect server using Prefect 3.x API."""
    
    print("🚀 Deploying Prefect flows...")
    print(f"   API URL: {os.environ.get('PREFECT_API_URL')}")
    print()
    
    # Deploy ETL flow
    print("📦 Deploying ridematch_ingest_flow...")
    try:
        ridematch_ingest_flow.deploy(
            name="ridematch-ingest-deployment",
            work_pool_name="ridematch-pool",
            work_queue_name="ridematch-queue",
            tags=["etl", "ingestion"],
            push=False,  # Use local flow code
        )
        print("   ✅ ETL flow deployed!")
    except Exception as e:
        print(f"   ❌ Error deploying ETL flow: {e}")
        import traceback
        traceback.print_exc()
    print()
    
    # Deploy training flow
    print("📦 Deploying train_and_register_model flow...")
    try:
        train_flow.deploy(
            name="train-model-deployment",
            work_pool_name="ridematch-pool",
            work_queue_name="ridematch-queue",
            tags=["training", "mlflow"],
            push=False,  # Use local flow code
        )
        print("   ✅ Training flow deployed!")
    except Exception as e:
        print(f"   ❌ Error deploying training flow: {e}")
        import traceback
        traceback.print_exc()
    print()
    
    print("✅ Deployment process completed!")
    print()
    print("📋 Next steps:")
    print("   1. Open Prefect UI: http://localhost:4200")
    print("   2. Go to 'Deployments' to see your deployed flows")
    print("   3. Trigger a flow run from the UI or CLI")
    print()
    print("   To trigger a flow run via CLI:")
    print("   prefect deployment run 'ridematch-ingest-deployment/ridematch_ingest'")
    print("   prefect deployment run 'train-model-deployment/train_and_register_model'")


if __name__ == "__main__":
    deploy_flows()

