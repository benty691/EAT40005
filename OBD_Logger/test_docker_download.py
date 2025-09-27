#!/usr/bin/env python3
"""
Test script to verify Docker download will work
This simulates the Docker environment conditions
"""
import os
import sys
import tempfile
from pathlib import Path

def test_docker_download():
    """Test download in Docker-like conditions"""
    print("🐳 Testing Docker download conditions...")
    print("=" * 50)
    
    # Load .env file
    env_path = Path(".env")
    if env_path.exists():
        print("📄 Loading .env file...")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print("✅ Environment variables loaded")
    else:
        print("❌ No .env file found")
        return False
    
    # Check HF_TOKEN
    hf_token = os.getenv("HF_TOKEN")
    if not hf_token:
        print("❌ HF_TOKEN not found in environment")
        return False
    print(f"✅ HF_TOKEN found: {hf_token[:10]}...")
    
    # Create temporary directory (simulating Docker /app/models/ul)
    with tempfile.TemporaryDirectory() as temp_dir:
        model_dir = Path(temp_dir) / "models" / "ul"
        model_dir.mkdir(parents=True, exist_ok=True)
        
        # Set environment variables for the test
        os.environ["MODEL_DIR"] = str(model_dir)
        
        print(f"📁 Model directory: {model_dir}")
        print(f"📦 Repository: {os.getenv('HF_MODEL_REPO', 'BinKhoaLe1812/Driver_Behavior_OBD')}")
        
        # Test the download
        try:
            from utils.download import download_latest_models
            success = download_latest_models()
            
            if success:
                # Check if files were downloaded
                files = list(model_dir.glob("*.pkl"))
                print(f"📦 Downloaded {len(files)} files:")
                for f in files:
                    print(f"   - {f.name} ({f.stat().st_size} bytes)")
                
                return len(files) == 3
            else:
                print("❌ Download failed")
                return False
                
        except Exception as e:
            print(f"❌ Download test failed: {e}")
            return False

def main():
    """Main test function"""
    print("🚀 Testing Docker download functionality...")
    
    success = test_docker_download()
    
    if success:
        print("\n✅ Docker download test passed!")
        print("🐳 Your Docker build should work correctly")
        print("📦 Models will be downloaded from v1.0 folder")
    else:
        print("\n❌ Docker download test failed!")
        print("🔧 Check the error messages above for troubleshooting")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
