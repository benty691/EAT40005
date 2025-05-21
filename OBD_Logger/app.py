# Access: https://binkhoale1812-obd-logger.hf.space/ui
import pathlib
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
import re

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
APP_ROOT = pathlib.Path(__file__).parent.resolve()  # Absolute base dir
BASE_DIR = os.path.join(APP_ROOT, './cache/obd_data')
CLEANED_DIR = os.path.join(BASE_DIR, "cleaned")
PLOT_DIR = os.path.join(BASE_DIR, "plots")
RAW_CSV = os.path.join(BASE_DIR, "raw_logs.csv")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(CLEANED_DIR, exist_ok=True)
os.makedirs(PLOT_DIR, exist_ok=True)
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
app.mount("/statics/plots", StaticFiles(directory=str(PLOT_DIR)), name="plots") # Graph
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
    status: str = None  # Optional for control signal (start/end streaming)

# Direct centralized timestamp format
def normalize_timestamp(ts):
    return ts.replace(":", "-").replace(".", "-").replace(" ", "T").replace("/", "-")

# Real time endpoint
@app.post("/ingest")
def ingest(entry: OBDEntry, background_tasks: BackgroundTasks):
    norm_ts = normalize_timestamp(entry.timestamp)
    logger.info(f"Ingest received: {norm_ts} | Status: {entry.status}")
    # Start logging
    if entry.status == "start":
        PIPELINE_EVENTS[norm_ts] = {"status": "started", "time": norm_ts}
        return {"status": "started"}
    # End logging, start processing
    if entry.status == "end":
        background_tasks.add_task(process_data, norm_ts)
        return {"status": "processed"}
    # Normal row append
    try:
        df = pd.read_csv(RAW_CSV)
        row = {"timestamp": norm_ts, "driving_style": entry.driving_style}
        row.update(entry.data)
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        df.to_csv(RAW_CSV, index=False)
        return {"status": "row appended"}
    except Exception as e:
        logger.error(f"Streaming ingest failed: {e}")
        raise HTTPException(status_code=500, detail="Ingest error")



# ───────────── Bulk CSV Upload ───────────────────
@app.post("/upload-csv/")
async def upload_csv(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    ts = datetime.datetime.now().isoformat()
    norm_ts = normalize_timestamp(ts)
    path = os.path.join(BASE_DIR, file.filename)
    PIPELINE_EVENTS[norm_ts] = {"status": "started", "time": norm_ts}
    with open(path, "wb") as f:
        f.write(await file.read())
    logger.info(f"CSV uploaded: {path}")
    background_tasks.add_task(process_uploaded_csv, path, norm_ts)
    return {"status": "processing started", "file": file.filename}


# ───────────── Data Processing ──────────────────
# Bulk CSV
def process_uploaded_csv(path, norm_ts):
    try:
        df = pd.read_csv(path, parse_dates=["timestamp"])
        PIPELINE_EVENTS[norm_ts] = {
            "status": "processed",
            "time": norm_ts
        }
        _process_and_save(df, norm_ts)
    except Exception as e:
        logger.error(f"CSV processing failed: {e}")

# Process streaming
def process_data(norm_ts):
    try:
        df = pd.read_csv(RAW_CSV, parse_dates=["timestamp"])
        PIPELINE_EVENTS[norm_ts] = {
            "status": "processed",
            "time": norm_ts
        }
        _process_and_save(df, norm_ts)
    except Exception as e:
        logger.error(f"Streamed data processing failed: {e}")


# All processing pipeline
def _process_and_save(df, norm_ts):
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
    out_path = os.path.join(CLEANED_DIR, f"cleaned_{norm_ts}.csv")
    df.to_csv(out_path, index=False)
    logger.info(f"✅ Cleaned saved: {out_path}")
    # Save Heatmap (timestamp as id)
    try:
        plt.figure(figsize=(12, 10))
        sns.heatmap(df.select_dtypes(include=[np.number]).corr(), annot=True, fmt=".2f", cmap="coolwarm")
        plt.title("Correlation Between Numeric OBD-II Variables")
        plt.tight_layout()
        logger.info(f"Saving heatmap to: {os.path.join(PLOT_DIR, f'heatmap_{norm_ts}.png')}")
        plt.savefig(os.path.join(PLOT_DIR, f"heatmap_{norm_ts}.png"))
        logger.info("✅ Heatmap saved successfully")
        plt.close()
    except Exception as e:
        logger.error(f"Heatmap generation failed: {e}")
    # Save Sensor Trend Chart (timestamp as id)
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
        logger.info(f"Saving sensor trend to: {os.path.join(PLOT_DIR, f'trend_{norm_ts}.png')}")
        plt.savefig(os.path.join(PLOT_DIR, f"trend_{norm_ts}.png"))
        logger.info("✅ Sensor trend logs saved successfully")
        plt.close()
    except Exception as e:
        logger.error(f"Trend plot failed: {e}")
    # Update event
    PIPELINE_EVENTS[norm_ts]["status"] = "done"
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


# ────── Delete event from dashboard ──────────────
@app.delete("/events/remove/{timestamp}")
def remove_event(timestamp: str):
    if timestamp in PIPELINE_EVENTS:
        del PIPELINE_EVENTS[timestamp]
    return {"status": "deleted"}


# ───────────── Download Cleaned ──────────────────
@app.get("/download/{filename}")
def download_file(filename: str):
    path = os.path.join(CLEANED_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type='text/csv', filename=filename)
