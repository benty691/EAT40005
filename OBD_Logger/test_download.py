#!/usr/bin/env python3
"""
Test script to check model download functionality
"""
import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.append(os.path.dirname(__file__))

def load_env_file():
    """Load environment variables from .env file"""
    env_path = Path(".env")
    if env_path.exists():
        print("📄 Loading .env file...")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
                    print(f"✅ Loaded {key}")
        return True
    else:
        print("⚠️ No .env file found")
        return False

def test_download():
    """Test the download functionality"""
    print("🧪 Testing model download functionality")
    print("=" * 50)
    
    # Load .env file
    load_env_file()
    
    # Check HF_TOKEN
    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        print(f"✅ HF_TOKEN found: {hf_token[:10]}...")
    else:
        print("❌ HF_TOKEN not found")
        return False
    
    # Check other environment variables
    repo_id = os.getenv("HF_MODEL_REPO", "BinKhoaLe1812/Driver_Behavior_OBD")
    model_dir = os.getenv("MODEL_DIR", "/app/models/ul")
    
    print(f"📦 Repository: {repo_id}")
    print(f"📁 Model directory: {model_dir}")
    
    # Test the download
    try:
        from utils.download import download_latest_models
        success = download_latest_models()
        return success
    except Exception as e:
        print(f"❌ Download test failed: {e}")
        return False

def main():
    """Main test function"""
    print("🚀 Starting download test...")
    
    success = test_download()
    
    if success:
        print("\n✅ Download test passed!")
        print("📦 Models should be available in the model directory")
    else:
        print("\n❌ Download test failed!")
        print("🔧 Check the error messages above for troubleshooting")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
