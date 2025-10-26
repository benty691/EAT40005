"""
Fuel Efficiency Model Downloader
Downloads the latest fuel efficiency model from Hugging Face Hub
Similar to utils/download.py but for fuel efficiency models
"""

import os
import pathlib
import logging
from typing import Optional, List
from huggingface_hub import HfApi, hf_hub_download
import joblib

logger = logging.getLogger("efficiency-downloader")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s"))
    logger.addHandler(handler)

def load_env_file():
    """Load .env file if it exists"""
    env_path = pathlib.Path(".env")
    if env_path.exists():
        logger.info("📄 Loading .env file...")
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        return True
    return False

# Load .env file first before setting any environment variables
load_env_file()

# Configuration
EFFICIENCY_REPO_ID = os.getenv("HF_EFFICIENCY_MODEL_REPO", "BinKhoaLe1812/Fuel_Efficiency_OBD")
EFFICIENCY_MODEL_DIR = pathlib.Path(os.getenv("EFFICIENCY_MODEL_DIR", "/app/models/efficiency")).resolve()
EFFICIENCY_FILES = ["efficiency_model.joblib", "efficiency_meta.json"]

EFFICIENCY_MODEL_DIR.mkdir(parents=True, exist_ok=True)

def get_latest_efficiency_version():
    """Get the latest fuel efficiency model version from Hugging Face repo"""
    try:
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            logger.warning("⚠️ HF_TOKEN not set, using default efficiency model files")
            return None
        
        api = HfApi(token=hf_token)
        repo_files = api.list_repo_files(
            repo_id=EFFICIENCY_REPO_ID,
            repo_type="model"
        )
        
        logger.info(f"🔍 Checking efficiency repository files...")
        logger.info(f"📁 Found {len(repo_files)} files in efficiency repository")
        
        # Find version directories (v1.0, v1.1, etc.)
        version_dirs = [f for f in repo_files if f.startswith('v') and '/' not in f]
        logger.info(f"📦 Found efficiency version directories: {version_dirs}")
        
        # Also check for version directories with files inside
        version_dirs_with_files = []
        for f in repo_files:
            if f.startswith('v') and '/' in f:
                version_dir = f.split('/')[0]
                if version_dir not in version_dirs_with_files:
                    version_dirs_with_files.append(version_dir)
        
        if version_dirs_with_files:
            logger.info(f"📦 Found efficiency version directories with files: {version_dirs_with_files}")
            version_dirs.extend(version_dirs_with_files)
        
        versions = []
        
        for v_dir in version_dirs:
            try:
                # Extract version number (e.g., "v1.0" -> 1.0)
                version_str = v_dir[1:]  # Remove 'v' prefix
                major, minor = map(int, version_str.split('.'))
                versions.append((major, minor, v_dir))
            except ValueError:
                logger.warning(f"⚠️ Could not parse version: {v_dir}")
                continue
        
        if not versions:
            logger.warning("⚠️ No valid efficiency versions found")
            return None
        
        # Sort by major.minor version
        versions.sort(key=lambda x: (x[0], x[1]))
        latest_version = versions[-1][2]  # Get the version string
        
        logger.info(f"✅ Latest efficiency model version: {latest_version}")
        return latest_version
        
    except Exception as e:
        logger.error(f"❌ Error getting latest efficiency version: {e}")
        return None

def download_efficiency_model(version: Optional[str] = None) -> bool:
    """Download the specified version of the fuel efficiency model"""
    try:
        hf_token = os.getenv("HF_TOKEN")
        if not hf_token:
            logger.error("❌ HF_TOKEN not set")
            return False
        
        if version is None:
            version = get_latest_efficiency_version()
            if version is None:
                logger.error("❌ Could not determine latest efficiency version")
                return False
        
        logger.info(f"📥 Downloading efficiency model version: {version}")
        
        # Download each required file
        for filename in EFFICIENCY_FILES:
            try:
                file_path = hf_hub_download(
                    repo_id=EFFICIENCY_REPO_ID,
                    filename=f"{version}/{filename}",
                    token=hf_token,
                    local_dir=EFFICIENCY_MODEL_DIR,
                    local_dir_use_symlinks=False
                )
                logger.info(f"✅ Downloaded: {filename}")
                
            except Exception as e:
                logger.error(f"❌ Failed to download {filename}: {e}")
                return False
        
        logger.info(f"✅ Efficiency model {version} downloaded successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error downloading efficiency model: {e}")
        return False

def download_latest_efficiency_models() -> bool:
    """Download the latest fuel efficiency model files"""
    try:
        logger.info("🚀 Starting efficiency model download...")
        
        # Get latest version
        latest_version = get_latest_efficiency_version()
        if latest_version is None:
            logger.error("❌ Could not determine latest efficiency version")
            return False
        
        # Download the model
        success = download_efficiency_model(latest_version)
        if success:
            logger.info("✅ Latest efficiency model downloaded successfully")
        else:
            logger.error("❌ Failed to download latest efficiency model")
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Error in download_latest_efficiency_models: {e}")
        return False

def load_efficiency_model():
    """Load the efficiency model from local storage"""
    try:
        model_path = EFFICIENCY_MODEL_DIR / "efficiency_model.joblib"
        meta_path = EFFICIENCY_MODEL_DIR / "efficiency_meta.json"
        
        if not model_path.exists():
            logger.error(f"❌ Efficiency model not found at {model_path}")
            return None, None
        
        # Load model
        model_artifacts = joblib.load(model_path)
        
        # Load metadata if available
        metadata = None
        if meta_path.exists():
            import json
            with open(meta_path, 'r') as f:
                metadata = json.load(f)
        
        logger.info("✅ Efficiency model loaded successfully")
        return model_artifacts, metadata
        
    except Exception as e:
        logger.error(f"❌ Error loading efficiency model: {e}")
        return None, None

def check_efficiency_model_exists() -> bool:
    """Check if efficiency model files exist locally"""
    model_path = EFFICIENCY_MODEL_DIR / "efficiency_model.joblib"
    return model_path.exists()

if __name__ == "__main__":
    # Test the download functionality
    success = download_latest_efficiency_models()
    if success:
        print("✅ Efficiency model download test successful")
    else:
        print("❌ Efficiency model download test failed")
