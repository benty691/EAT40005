# download.py
# Download latest models from Hugging Face
import os, shutil, pathlib, sys
import json
from huggingface_hub import hf_hub_download, HfApi

def load_env_file():
    """Load environment variables from .env file if it exists"""
    env_path = pathlib.Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        return True
    return False

REPO_ID   = os.getenv("HF_MODEL_REPO", "BinKhoaLe1812/Driver_Behavior_OBD")
MODEL_DIR = pathlib.Path(os.getenv("MODEL_DIR", "/app/models/ul")).resolve()
FILES     = ["label_encoder_ul.pkl", "scaler_ul.pkl", "xgb_drivestyle_ul.pkl"]

MODEL_DIR.mkdir(parents=True, exist_ok=True)

def get_latest_version():
    """Get the latest model version from Hugging Face repo"""
    try:
        # Load .env file first
        load_env_file()
        
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            print("⚠️ HF_TOKEN not set, using default model files")
            return None
        
        api = HfApi(token=hf_token)
        repo_files = api.list_repo_files(
            repo_id=REPO_ID,
            repo_type="model"
        )
        
        print(f"🔍 Checking repository files...")
        print(f"📁 Found {len(repo_files)} files in repository")
        
        # Find version directories (v1.0, v1.1, etc.)
        version_dirs = [f for f in repo_files if f.startswith('v') and '/' not in f]
        print(f"📦 Found version directories: {version_dirs}")
        
        # Also check for version directories with files inside
        version_dirs_with_files = []
        for f in repo_files:
            if f.startswith('v') and '/' in f:
                version_dir = f.split('/')[0]
                if version_dir not in version_dirs_with_files:
                    version_dirs_with_files.append(version_dir)
        
        if version_dirs_with_files:
            print(f"📦 Found version directories with files: {version_dirs_with_files}")
            version_dirs.extend(version_dirs_with_files)
        
        versions = []
        
        for v_dir in version_dirs:
            try:
                version_str = v_dir[1:]  # Remove 'v' prefix
                if '.' in version_str:
                    major, minor = version_str.split('.')
                    versions.append((int(major), int(minor), v_dir))
                    print(f"✅ Found version: {v_dir} (major={major}, minor={minor})")
            except (ValueError, IndexError):
                print(f"⚠️ Could not parse version: {v_dir}")
                continue
        
        if not versions:
            print("📦 No versioned models found, checking for root files...")
            # Check if files exist in root
            root_files = [f for f in repo_files if f in FILES]
            if root_files:
                print(f"📁 Found root files: {root_files}")
                return None  # Use root files
            else:
                print("❌ No model files found in repository")
                print("💡 Available files in repository:")
                for f in sorted(repo_files):
                    print(f"   - {f}")
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
        # Load .env file first
        load_env_file()
        
        if version_dir:
            # Download from versioned directory
            versioned_path = f"{version_dir}/{fname}"
            print(f"📥 Downloading {fname} from {versioned_path}...")
            src = hf_hub_download(repo_id=REPO_ID, filename=versioned_path, repo_type="model")
        else:
            # Download from root directory (fallback)
            print(f"📥 Downloading {fname} from root directory...")
            src = hf_hub_download(repo_id=REPO_ID, filename=fname, repo_type="model")
        
        dst = MODEL_DIR / fname
        shutil.copy2(src, dst)
        print(f"✅ Downloaded {fname} → {dst}")
        return True
    except Exception as e:
        print(f"❌ Failed to fetch {fname}: {e}")
        if version_dir:
            print(f"   Tried path: {version_dir}/{fname}")
        else:
            print(f"   Tried path: {fname}")
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
    # Load .env file first
    load_env_file()
    
    success = download_latest_models()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
