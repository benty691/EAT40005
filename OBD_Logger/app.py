#  https://binkhoale1812-obd-logger.hf.space/
import logging
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import pandas as pd
import numpy as np
from sklearn.preprocessing import MinMaxScaler
import datetime
import os

# ─────────────────────────────────────
# Debug Logging Setup
# ─────────────────────────────────────
logger = logging.getLogger("obd-logger")
logger.setLevel(logging.INFO)
fmt = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s")
handler = logging.StreamHandler()
handler.setFormatter(fmt)
logger.addHandler(handler)
# suppress noisy libs
for lib in ("pymongo", "urllib3", "httpx", "uvicorn"):
    logging.getLogger(lib).setLevel(logging.WARNING)

# ─────────────────────────────────────
# FastAPI App Initialization
# ─────────────────────────────────────
app = FastAPI(title="OBD-II Logging & Processing API")

# ─────────────────────────────────────
# Model for Incoming Data
# ─────────────────────────────────────
class OBDEntry(BaseModel):
    timestamp: str
    driving_style: str
    road_type: str
    data: dict  # PID name -> value


# ─────────────────────────────────────
# Access Drive
# ─────────────────────────────────────
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def get_gdrive_client():
    """Initialize gspread client using mounted GDRIVE_CREDENTIALS_JSON."""
    creds_json = os.getenv("GDRIVE_CREDENTIALS_JSON")
    if not creds_json:
        logger.warning("GDRIVE_CREDENTIALS_JSON is not set; skipping upload.")
        return None
    try:
        creds_dict = json.loads(creds_json)
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        logger.error(f"Failed to reinitialize Google Drive client: {e}")
        return None


# ─────────────────────────────────────
# Paths and Directories
# ─────────────────────────────────────
os.environ['OBD_CACHE'] = './cache/obd_data'
os.makedirs(os.environ['OBD_CACHE'], exist_ok=True)
BASE_DIR = os.environ['OBD_CACHE']
RAW_CSV = os.path.join(BASE_DIR, "raw_logs.csv")
CLEANED_DIR = os.path.join(BASE_DIR, "cleaned")
os.makedirs(CLEANED_DIR, exist_ok=True)

# Initialize raw CSV if not exists
if not os.path.isfile(RAW_CSV):
    try:
        pd.DataFrame(columns=["timestamp", "driving_style", "road_type"]).to_csv(RAW_CSV, index=False)
        logger.info(f"Initialized raw log CSV at {RAW_CSV}")
    except Exception as e:
        logger.error(f"Failed to initialize raw CSV: {e}")
        raise HTTPException(status_code=500, detail="Init write error")


# ─────────────────────────────────────
# Endpoint: Ingest streamed OBD data
# ─────────────────────────────────────
@app.post("/ingest")
def ingest(entry: OBDEntry, background_tasks: BackgroundTasks):
    logger.info(f"Ingesting entry at {entry.timestamp}, style={entry.driving_style}, road={entry.road_type}")
    try:
        df = pd.read_csv(RAW_CSV)
    except Exception as e:
        logger.error(f"Failed to read raw CSV: {e}")
        raise HTTPException(status_code=500, detail="Read error")

    # Build row dictionary
    row = {
        "timestamp": entry.timestamp,
        "driving_style": entry.driving_style,
        "road_type": entry.road_type
    }
    row.update(entry.data)

    # Append and save
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(RAW_CSV, index=False)
    logger.info("Appended new row to raw CSV")

    # Schedule background processing
    background_tasks.add_task(process_data)
    return {"status": "ingested"}

# ─────────────────────────────────────
# Processing & Cleaning Pipeline
# ─────────────────────────────────────
def process_data():
    logger.info("Starting data processing pipeline")
    try:
        df = pd.read_csv(RAW_CSV, parse_dates=["timestamp"])
        logger.info(f"Loaded raw data with shape {df.shape}")

        # Drop constant/empty columns
        protected_cols = {"timestamp", "driving_style", "road_type"} # Protect manual features from being cleaned
        drop_cols = [c for c in df.columns if c not in protected_cols and (df[c].nunique() <= 1 or df[c].isna().all())]
        df.drop(columns=drop_cols, inplace=True)
        logger.info(f"Dropped constant/empty columns: {drop_cols}")

        # Remove duplicate columns & rows
        df = df.loc[:, ~df.T.duplicated()]
        df.drop_duplicates(inplace=True)
        logger.info("Removed duplicate columns and rows")

        # Replace placeholder errors
        df.replace([-22, -40, 255], np.nan, inplace=True)
        logger.info("Replaced placeholder error codes with NaN")

        # Drop rows with >80% missing
        thresh = int(0.2 * (df.shape[1] - 1))
        before = df.shape[0]
        df = df[df.drop(columns=["timestamp"]).isna().sum(axis=1) <= (df.shape[1] - 1 - thresh)]
        logger.info(f"Dropped {before - df.shape[0]} rows with too many missing values")

        # Drop high-missing columns
        miss_ratio = df.isna().mean()
        high_miss = miss_ratio[miss_ratio > 0.8].index.tolist()
        df.drop(columns=high_miss, inplace=True)
        logger.info(f"Dropped high-missing columns: {high_miss}")

        # Enforce >1 non-null feature
        df = df[df.drop(columns=["timestamp"]).notna().sum(axis=1) > 1]
        logger.info("Filtered rows with <=1 non-null feature")

        # Clip RPM extremes
        if "RPM" in df.columns:
            df.loc[(df.RPM < 100)|(df.RPM>6000), "RPM"] = np.nan
            logger.info("Clipped RPM extremes")

        # Fill numeric NaNs with median
        for c in df.select_dtypes(include=[np.number]).columns:
            df[c].fillna(df[c].median(), inplace=True)
        logger.info("Filled NaNs with median values")

        # Sort & reset index
        df.sort_values(by="timestamp", inplace=True)
        df.reset_index(drop=True, inplace=True)
        logger.info("Sorted by timestamp and reset index")

        # Normalize numeric features (only if numeric columns remain)
        num_cols = df.select_dtypes(include=[np.number]).columns
        if not num_cols.empty:
            scaler = MinMaxScaler()
            df[num_cols] = scaler.fit_transform(df[num_cols])
            logger.info("Applied MinMax normalization")
        else:
            logger.warning("Skipped normalization: no numeric columns found")

        # Feature engineering
        if {"ENGINE_LOAD","ABSOLUTE_LOAD"}.issubset(df.columns):
            df['AVG_ENGINE_LOAD'] = df[['ENGINE_LOAD','ABSOLUTE_LOAD']].mean(axis=1)
        if {"INTAKE_TEMP","OIL_TEMP","COOLANT_TEMP"}.issubset(df.columns):
            df['TEMP_MEAN'] = df[['INTAKE_TEMP','OIL_TEMP','COOLANT_TEMP']].mean(axis=1)
        if {"MAF","RPM"}.issubset(df.columns):
            df['AIRFLOW_PER_RPM'] = df['MAF']/df['RPM'].replace(0, np.nan)
        logger.info("Completed feature engineering")

        # Save cleaned output
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"cleaned_{ts}.csv"
        df.to_csv(filename, index=False)
        logger.info(f"Temporarily saved {filename}")

        # Upload to Google Drive
        gdrive = get_gdrive_client()
        if gdrive:
            try:
                logger.info("Uploading cleaned data to Google Drive...")
                with open(filename, "rb") as f:
                    gdrive.import_csv(gdrive.create(filename).id, f.read())
                logger.info(f"Uploaded {filename} successfully.")
            except Exception as e:
                logger.error(f"Failed uploading {filename}: {e}")
        else:
            logger.warning("Google Drive upload skipped: No credentials found.")

    except Exception as e:
        logger.error(f"Error in processing pipeline: {e}")


# ─────────────────────────────────────
# Health Check Endpoint
# ─────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


# ─────────────────────────────────────
# Download Endpoint
# ─────────────────────────────────────
from fastapi.responses import FileResponse
@app.get("/download/{filename}")
def download_file(filename: str):
    file_path = os.path.join(CLEANED_DIR, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, media_type='text/csv', filename=filename)
