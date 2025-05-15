from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import pandas as pd
import numpy as np
import os, datetime, json, logging
from sklearn.preprocessing import MinMaxScaler
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ───────────── Logging Setup ─────────────
logger = logging.getLogger("obd-logger")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(fmt)
logger.addHandler(handler)

# ───────────── FastAPI Init ─────────────
app = FastAPI(title="OBD-II Logging & Processing API")

# ───────────── Directory Paths ─────────────
BASE_DIR = './cache/obd_data'
CLEANED_DIR = os.path.join(BASE_DIR, "cleaned")
RAW_CSV = os.path.join(BASE_DIR, "raw_logs.csv")
os.makedirs(CLEANED_DIR, exist_ok=True)
os.makedirs(BASE_DIR, exist_ok=True)

if not os.path.exists(RAW_CSV):
    pd.DataFrame(columns=["timestamp", "driving_style"]).to_csv(RAW_CSV, index=False)

# ───────────── Drive Auth ─────────────
def get_drive_service():
    try:
        creds_dict = json.loads(os.getenv("GDRIVE_CREDENTIALS_JSON"))
        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/drive"]
        )
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Drive init failed: {e}")
        return None

def upload_to_folder(service, file_path, folder_id):
    file_name = os.path.basename(file_path)
    media = MediaFileUpload(file_path, mimetype='text/csv')
    metadata = {"name": file_name, "parents": [folder_id]}
    return service.files().create(body=metadata, media_body=media, fields="id").execute()

# ───────────── Streamed Entry Ingest ─────────────
class OBDEntry(BaseModel):
    timestamp: str
    driving_style: str
    data: dict

# Real time endpoint
@app.post("/ingest")
def ingest(entry: OBDEntry, background_tasks: BackgroundTasks):
    logger.info(f"Ingest: {entry.timestamp} / {entry.driving_style}")
    try:
        df = pd.read_csv(RAW_CSV)
        row = {"timestamp": entry.timestamp, "driving_style": entry.driving_style}
        row.update(entry.data)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(RAW_CSV, index=False)
        background_tasks.add_task(process_data)
        return {"status": "ingested"}
    except Exception as e:
        logger.error(f"Streaming ingest failed: {e}")
        raise HTTPException(status_code=500, detail="Ingest error")

# ───────────── Bulk CSV Upload ─────────────
@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    path = os.path.join(BASE_DIR, file.filename)
    with open(path, "wb") as f:
        f.write(await file.read())
    logger.info(f"CSV uploaded: {path}")
    background_tasks.add_task(process_uploaded_csv, path)
    return {"status": "processing started", "file": file.filename}

# ───────────── Data Processing ─────────────
def process_uploaded_csv(path):
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        _process_and_save(df)
    except Exception as e:
        logger.error(f"CSV processing failed: {e}")

# Process streaming
def process_data():
    try:
        df = pd.read_csv(RAW_CSV, parse_dates=["timestamp"])
        _process_and_save(df)
    except Exception as e:
        logger.error(f"Streamed data processing failed: {e}")

# All processing pipeline
def _process_and_save(df):
    logger.info("🔧 Cleaning started")
    protected_cols = {"timestamp", "driving_style"}
    df.drop(columns=[c for c in df if c not in protected_cols and (df[c].nunique() <= 1 or df[c].isna().all())], inplace=True)
    df = df.loc[:, ~df.T.duplicated()]
    df.drop_duplicates(inplace=True)
    df.replace([-22, -40, 255], np.nan, inplace=True)
    df = df[df.drop(columns=["timestamp"]).isna().sum(axis=1) <= int(0.8 * (df.shape[1] - 1))]
    df.drop(columns=df.isna().mean()[lambda x: x > 0.8].index, inplace=True)
    df = df[df.drop(columns=["timestamp"]).notna().sum(axis=1) > 1]
    if "RPM" in df.columns:
        df.loc[(df["RPM"] < 100) | (df["RPM"] > 6000), "RPM"] = np.nan
    for c in df.select_dtypes(include=["number"]).columns:
        df[c].fillna(df[c].median(), inplace=True)
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    if not df.select_dtypes(include=["number"]).empty:
        df[df.select_dtypes(include=["number"]).columns] = MinMaxScaler().fit_transform(df.select_dtypes(include=["number"]))
    if {"ENGINE_LOAD", "ABSOLUTE_LOAD"}.issubset(df.columns):
        df["AVG_ENGINE_LOAD"] = df[["ENGINE_LOAD", "ABSOLUTE_LOAD"]].mean(axis=1)
    if {"INTAKE_TEMP", "OIL_TEMP", "COOLANT_TEMP"}.issubset(df.columns):
        df["TEMP_MEAN"] = df[["INTAKE_TEMP", "OIL_TEMP", "COOLANT_TEMP"]].mean(axis=1)
    if {"MAF", "RPM"}.issubset(df.columns):
        df["AIRFLOW_PER_RPM"] = df["MAF"] / df["RPM"].replace(0, np.nan)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(CLEANED_DIR, f"cleaned_{ts}.csv")
    df.to_csv(out_path, index=False)
    logger.info(f"✅ Cleaned saved: {out_path}")

    service = get_drive_service()
    if service:
        folder_id = "1r-wefqKbK9k9BeYDW1hXRbx4B-0Fvj5P"
        try:
            upload_to_folder(service, out_path, folder_id)
            logger.info("✅ Uploaded to Drive")
        except Exception as e:
            logger.error(f"❌ Drive upload error: {e}")

# ───────────── Health Check ─────────────
@app.get("/health")
def health():
    return {"status": "ok"}

# ───────────── Download Cleaned ─────────────
@app.get("/download/{filename}")
def download_file(filename: str):
    path = os.path.join(CLEANED_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type='text/csv', filename=filename)
