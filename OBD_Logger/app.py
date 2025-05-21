from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
import pandas as pd
import numpy as np
import os, datetime, json, logging
from sklearn.preprocessing import MinMaxScaler
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import matplotlib.pyplot as plt
import seaborn as sns


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
PLOT_DIR = os.path.join(BASE_DIR, "plots")
RAW_CSV = os.path.join(BASE_DIR, "raw_logs.csv")
os.makedirs(CLEANED_DIR, exist_ok=True)
os.makedirs(PLOT_DIR, exist_ok=True)
os.makedirs(BASE_DIR, exist_ok=True)
# Init temp empty file
if not os.path.exists(RAW_CSV):
    pd.DataFrame(columns=["timestamp", "driving_style"]).to_csv(RAW_CSV, index=False)

PIPELINE_EVENTS = {}

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
# Point to specific Drive path
def upload_to_folder(service, file_path, folder_id):
    file_name = os.path.basename(file_path)
    media = MediaFileUpload(file_path, mimetype='text/csv')
    metadata = {"name": file_name, "parents": [folder_id]}
    return service.files().create(body=metadata, media_body=media, fields="id").execute()


# ───────────── Render Dashboard UI ──────────────
app.mount("/statics", StaticFiles(directory="statics"), name="statics")
templates = Jinja2Templates(directory="statics")
# Endpoint
@app.get("/ui", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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


# ───────────── Bulk CSV Upload ───────────────────
@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    path = os.path.join(BASE_DIR, file.filename)
    with open(path, "wb") as f:
        f.write(await file.read())
    logger.info(f"CSV uploaded: {path}")
    ts = datetime.datetime.now().isoformat()
    background_tasks.add_task(process_uploaded_csv, path, ts)
    return {"status": "processing started", "file": file.filename}


# ───────────── Data Processing ──────────────────
# Bulk CSV
def process_uploaded_csv(path, timestamp_str):
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        _process_and_save(df, timestamp_str)
    except Exception as e:
        logger.error(f"CSV processing failed: {e}")

# Process streaming
def process_data(timestamp_str):
    try:
        df = pd.read_csv(RAW_CSV, parse_dates=["timestamp"])
        _process_and_save(df, timestamp_str)
    except Exception as e:
        logger.error(f"Streamed data processing failed: {e}")

# All processing pipeline
def _process_and_save(df, timestamp_str):
    PIPELINE_EVENTS[timestamp_str]["status"] = "processed"
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
    # Prepare filename
    ts = timestamp_str.replace(":", "-").replace(" ", "T").replace("/", "-")
    out_path = os.path.join(CLEANED_DIR, f"cleaned_{ts}.csv")
    df.to_csv(out_path, index=False)
    logger.info(f"✅ Cleaned saved: {out_path}")

    # Save Heatmap
    try:
        plt.figure(figsize=(12, 10))
        sns.heatmap(df.select_dtypes(include=[np.number]).corr(), annot=True, fmt=".2f", cmap="coolwarm")
        plt.title("Correlation Between Numeric OBD-II Variables")
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, f"heatmap_{ts}.png"))
        plt.close()
    except Exception as e:
        logger.error(f"Heatmap generation failed: {e}")
    # Save Sensor Trend Chart
    try:
        plt.figure(figsize=(15, 6))
        for col in ['RPM', 'ENGINE_LOAD', 'ABSOLUTE_LOAD', 'COOLANT_TEMP',
                    'INTAKE_TEMP', 'OIL_TEMP', 'INTAKE_PRESSURE', 'BAROMETRIC_PRESSURE',
                    'CONTROL_MODULE_VOLTAGE']:
            if col in df.columns:
                plt.plot(df.index, df[col], label=col)
        plt.title("Sensor Trends (Index-Based, No Time Gaps)")
        plt.xlabel("Sample Index")
        plt.ylabel("Sensor Value")
        plt.legend()
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(os.path.join(PLOT_DIR, f"trend_{ts}.png"))
        plt.close()
    except Exception as e:
        logger.error(f"Trend plot failed: {e}")
    # Update event
    PIPELINE_EVENTS[timestamp_str]["status"] = "done"
    # Point to Drive service
    service = get_drive_service()
    if service:
        folder_id = "1r-wefqKbK9k9BeYDW1hXRbx4B-0Fvj5P"
        try:
            upload_to_folder(service, out_path, folder_id)
            logger.info("✅ Uploaded to Drive")
        except Exception as e:
            logger.error(f"❌ Drive upload error: {e}")


# ───────────── Health Check ──────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ─────── Send status to frontend ─────────────────
@app.get("/events")
def get_events():
    return PIPELINE_EVENTS


# ───────────── Download Cleaned ──────────────────
@app.get("/download/{filename}")
def download_file(filename: str):
    path = os.path.join(CLEANED_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type='text/csv', filename=filename)
