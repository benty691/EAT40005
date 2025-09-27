# check_latest_model.py
# Script to check and download the latest model version

import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from utils.download import get_latest_version, download_latest_models
from utils.ul_label import ULLabeler

def check_latest_model():
    """Check and demonstrate latest model loading"""
    print("🔍 Checking Latest Model Version")
    print("=" * 50)
    
    # Check latest version
    print("\n1. Checking latest version from Hugging Face...")
    latest_version = get_latest_version()
    if latest_version:
        print(f"✅ Latest version found: {latest_version}")
    else:
        print("⚠️ No versioned models found, using default files")
    
    # Download latest models
    print("\n2. Downloading latest models...")
    success = download_latest_models()
    if success:
        print("✅ Successfully downloaded latest models")
    else:
        print("❌ Failed to download latest models")
        return False
    
    # Test model loading
    print("\n3. Testing model loading...")
    try:
        # This will auto-download latest models
        labeler = ULLabeler(auto_download=True)
        print("✅ Model loaded successfully with latest version")
        
        # Test prediction on dummy data
        import pandas as pd
        import numpy as np
        
        # Create dummy data for testing
        dummy_data = pd.DataFrame({
            'speed': [50, 60, 70],
            'rpm': [2000, 2500, 3000],
            'throttle': [0.3, 0.5, 0.7],
            'brake': [0.0, 0.1, 0.0]
        })
        
        predictions = labeler.predict_df(dummy_data)
        print(f"✅ Test predictions: {predictions}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return False

def main():
    """Main function"""
    success = check_latest_model()
    if success:
        print("\n🎉 Latest model loading test completed successfully!")
    else:
        print("\n❌ Latest model loading test failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()
