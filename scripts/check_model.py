#!/usr/bin/env python3
import sys
import pickle
import glob
import os
from pathlib import Path

def main():
    print("🔍 Checking model artifacts...")
    project_root = Path(__file__).parent.parent
    models_dir = project_root / "models" / "saved"
    
    if not models_dir.exists():
        print(f"❌ Models directory not found: {models_dir}")
        sys.exit(1)
        
    pkl_files = list(models_dir.glob("*.pkl"))
    if not pkl_files:
        print(f"❌ No .pkl model files found in {models_dir}")
        sys.exit(1)
        
    # Get latest model
    latest_model_path = max(pkl_files, key=os.path.getmtime)
    print(f"✅ Found latest model: {latest_model_path.name}")
    
    try:
        with open(latest_model_path, "rb") as f:
            model = pickle.load(f)
            
        print("✅ Model loaded successfully")
        
        # Check API
        if not hasattr(model, "predict_proba"):
            print("❌ Model missing 'predict_proba' method!")
            sys.exit(1)
        
        print("✅ Model has 'predict_proba' method")
            
        if not hasattr(model, "predict"):
            print("❌ Model missing 'predict' method!")
            sys.exit(1)
            
        print("✅ Model compatible with Match API")
        
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
