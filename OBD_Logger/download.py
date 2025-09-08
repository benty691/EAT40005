# download.py
# Download models from Hugging Face
import os, shutil, pathlib, sys
from huggingface_hub import hf_hub_download

REPO_ID   = os.getenv("HF_MODEL_REPO", "BinKhoaLe1812/Driver_Behavior_OBD")
MODEL_DIR = pathlib.Path(os.getenv("MODEL_DIR", "/app/models/ul")).resolve()
FILES     = ["label_encoder_ul.pkl", "scaler_ul.pkl", "xgb_drivestyle_ul.pkl"]

MODEL_DIR.mkdir(parents=True, exist_ok=True)

def fetch(fname: str):
    src = hf_hub_download(repo_id=REPO_ID, filename=fname, repo_type="model")
    dst = MODEL_DIR / fname
    shutil.copy2(src, dst)
    print(f"✅ Downloaded {fname} → {dst}")

def main():
    for f in FILES:
        try:
            fetch(f)
        except Exception as e:
            print(f"❌ Failed to fetch {f}: {e}", file=sys.stderr)
            raise

if __name__ == "__main__":
    main()
