# download.py
# Download latest models from Hugging Face
import os, shutil, pathlib, sys
import json
from huggingface_hub import hf_hub_download, HfApi

REPO_ID   = os.getenv("HF_MODEL_REPO", "BinKhoaLe1812/Driver_Behavior_OBD")
MODEL_DIR = pathlib.Path(os.getenv("MODEL_DIR", "/app/models/ul")).resolve()
FILES     = ["label_encoder_ul.pkl", "scaler_ul.pkl", "xgb_drivestyle_ul.pkl"]

MODEL_DIR.mkdir(parents=True, exist_ok=True)

def get_latest_version():
    """Get the latest model version from Hugging Face repo"""
    try:
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            print("⚠️ HF_TOKEN not set, using default model files")
            return None
        
        api = HfApi(token=hf_token)
        repo_files = api.list_repo_files(
            repo_id=REPO_ID,
            repo_type="model"
        )
        
        # Find version directories (v1.0, v1.1, etc.)
        version_dirs = [f for f in repo_files if f.startswith('v') and '/' not in f]
        versions = []
        
        for v_dir in version_dirs:
            try:
                version_str = v_dir[1:]  # Remove 'v' prefix
                if '.' in version_str:
                    major, minor = version_str.split('.')
                    versions.append((int(major), int(minor), v_dir))
            except (ValueError, IndexError):
                continue
        
        if not versions:
            print("📦 No versioned models found, using default files")
            return None
        
        # Sort versions and get the latest
        versions.sort()
        latest_version = versions[-1][2]  # Get the directory name
        print(f"📦 Latest model version: {latest_version}")
        return latest_version
        
    except Exception as e:
        print(f"⚠️ Failed to get latest version: {e}")
        return None

def fetch_latest(fname: str, version_dir: str = None):
    """Download the latest version of a model file"""
    try:
        if version_dir:
            # Download from versioned directory
            versioned_path = f"{version_dir}/{fname}"
            src = hf_hub_download(repo_id=REPO_ID, filename=versioned_path, repo_type="model")
        else:
            # Download from root directory (fallback)
            src = hf_hub_download(repo_id=REPO_ID, filename=fname, repo_type="model")
        
        dst = MODEL_DIR / fname
        shutil.copy2(src, dst)
        print(f"✅ Downloaded {fname} → {dst}")
        return True
    except Exception as e:
        print(f"❌ Failed to fetch {fname}: {e}")
        return False

def download_latest_models():
    """Download the latest version of all model files"""
    print("🔄 Checking for latest model version...")
    latest_version = get_latest_version()
    
    success_count = 0
    for f in FILES:
        if fetch_latest(f, latest_version):
            success_count += 1
    
    if success_count == len(FILES):
        print(f"✅ Successfully downloaded all {len(FILES)} model files")
        if latest_version:
            print(f"📦 Using version: {latest_version}")
        return True
    else:
        print(f"⚠️ Only {success_count}/{len(FILES)} files downloaded successfully")
        return False

def fetch(fname: str):
    """Legacy function for backward compatibility"""
    return fetch_latest(fname)

def main():
    """Download latest models"""
    success = download_latest_models()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
