# Access: https://binkhoale1812-obd-logger.hf.space/ui


# ───────────── Installation ─────────────
# Router
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
# ML/DL
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.preprocessing import MinMaxScaler
from sklearn.impute import KNNImputer
# Utils
import os, datetime, json, logging, re
from datetime import timedelta
import pathlib
# Driver
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
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/plots", StaticFiles(directory=str(PLOT_DIR)), name="plots")
templates = Jinja2Templates(directory="static")
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
    """
    Gap-aware, multi-sensor backfill for OBD-II streams with unknown cadence.
    - Infers sampling interval from data (robust).
    - Inserts placeholder rows for gaps using the inferred interval.
    - Flags only corrupted values (NaN/inf/sentinels); does NOT trim 'extreme but plausible' outliers.
    - Backfills ALL numeric sensors with KNNImputer (+ time as a feature).
    - Keeps your plotting, Drive upload, and PIPELINE_EVENTS wiring intact.
    """
    logger.info("🔧 Cleaning started (auto-interval, KNN for all sensors)")

    # ----------------------- helpers (scoped locally) -----------------------
    protected_cols = {"timestamp", "driving_style"}
    SENTINELS = {-22, -40, 255}

    def _to_dt(_df: pd.DataFrame) -> pd.DataFrame:
        _df = _df.copy()
        _df["timestamp"] = pd.to_datetime(_df["timestamp"], errors="coerce", utc=True)
        _df = _df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        # drop exact duplicate timestamps (keep first)
        _df = _df[~_df["timestamp"].duplicated(keep="first")].reset_index(drop=True)
        return _df

    def _drop_dead_weight(_df: pd.DataFrame) -> pd.DataFrame:
        _df = _df.copy()
        # drop all-NaN or constant columns (except protected)
        drop_cols = [c for c in _df.columns
                     if c not in protected_cols and (_df[c].nunique(dropna=True) <= 1 or _df[c].isna().all())]
        if drop_cols:
            _df.drop(columns=drop_cols, inplace=True, errors="ignore")
        # drop duplicate columns
        _df = _df.loc[:, ~_df.T.duplicated()]
        # drop duplicate rows
        _df.drop_duplicates(inplace=True)
        return _df

    def _normalize_corruption(_df: pd.DataFrame) -> pd.DataFrame:
        _df = _df.copy()
        # normalize obvious corruptions: NaN/inf/sentinels → NaN
        _df.replace(list(SENTINELS), np.nan, inplace=True)
        num_cols = _df.select_dtypes(include=[np.number]).columns
        for c in num_cols:
            s = _df[c]
            s = s.astype(float)
            s[~np.isfinite(s)] = np.nan
            _df[c] = s
        return _df

    def _light_row_col_filters(_df: pd.DataFrame) -> pd.DataFrame:
        _df = _df.copy()
        # keep rows with <=80% NaN (excluding timestamp)
        if "timestamp" in _df.columns and _df.shape[1] > 1:
            keep = _df.drop(columns=["timestamp"]).isna().mean(axis=1) <= 0.8
            _df = _df[keep]
        # prune columns with >80% NaN (except protected)
        na_frac = _df.isna().mean(numeric_only=False)
        high_na = [c for c in na_frac.index if na_frac[c] > 0.8 and c not in protected_cols]
        if high_na:
            _df.drop(columns=high_na, inplace=True, errors="ignore")
        # keep rows that have >1 observed value across non-timestamp columns
        if "timestamp" in _df.columns and _df.shape[1] > 1:
            valid = _df.drop(columns=["timestamp"]).notna().sum(axis=1) > 1
            _df = _df[valid]
        return _df

    def _infer_base_interval_seconds(ts: pd.Series) -> float:
        """
        Robustly infer base cadence from timestamp diffs.
        Strategy:
          - take positive diffs
          - winsorize to 5–95% to reduce impact of long gaps
          - compute a 'rounded mode' on 10ms grid; fall back to median if needed
        """
        if ts.size < 2:
            return 1.0  # fallback
        diffs = ts.sort_values().diff().dropna().dt.total_seconds()
        diffs = diffs[diffs > 0]
        if diffs.empty:
            return 1.0
        q05, q95 = diffs.quantile([0.05, 0.95])
        core = diffs[(diffs >= q05) & (diffs <= q95)]
        if core.empty:
            core = diffs
        # round to 10ms and take the most frequent bin
        rounded = (core / 0.01).round() * 0.01
        mode = rounded.mode()
        if not mode.empty:
            est = float(mode.iloc[0])
        else:
            est = float(core.median())
        # guardrails
        if est <= 0:
            est = float(core.median())
        logger.info(f"⏱️ Inferred base interval ≈ {est:.3f}s")
        return est

    def _insert_time_gaps(_df: pd.DataFrame, base_sec: float) -> pd.DataFrame:
        """
        Insert placeholder rows at multiples of inferred base_sec when gaps exceed ~1.5× base.
        All numeric columns are NaN in inserted rows; non-numeric are forward-filled (except protected).
        """
        if _df.empty:
            return _df
        _df = _df.copy()
        _df = _to_dt(_df)
        expected = timedelta(seconds=base_sec)
        # tolerance ~ half interval to avoid jittery inserts
        tol = timedelta(seconds=0.5 * base_sec)
        # Normalize data
        num_cols = _df.select_dtypes(include=[np.number]).columns.tolist()
        non_num_cols = [c for c in _df.columns if c not in num_cols]
        # Missing detection on interval expectation
        rows = [_df.iloc[0].copy()]
        for i in range(1, len(_df)):
            prev = _df.iloc[i - 1]
            curr = _df.iloc[i]
            dt = curr["timestamp"] - prev["timestamp"]
            if dt > expected * 1.5 + tol:
                n_missing = int(round(dt / expected)) - 1
                if n_missing > 0:
                    for j in range(1, n_missing + 1):
                        gap = prev.copy()
                        gap["timestamp"] = prev["timestamp"] + j * expected
                        # numeric sensors left as NaN to be imputed
                        for c in num_cols:
                            if c not in protected_cols:
                                gap[c] = np.nan
                        # for non-numeric, keep last known (except protected)
                        for c in non_num_cols:
                            if c not in protected_cols:
                                gap[c] = prev[c]
                        rows.append(gap)
            rows.append(curr.copy())
        # Sorting
        out = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
        return out

    def _knn_impute_all(_df: pd.DataFrame) -> pd.DataFrame:
        """
        Backfill ALL numeric sensors jointly with KNN, using time (ts_sec) as an additional feature.
        """
        _df = _df.copy()
        _df["ts_sec"] = (_df["timestamp"] - _df["timestamp"].min()).dt.total_seconds()
        # Normalize data
        num_cols = _df.select_dtypes(include=[np.number]).columns.tolist()
        # ensure ts_sec included
        if "ts_sec" not in num_cols:
            num_cols = num_cols + ["ts_sec"]
        # Build imputation frame and remember order
        X = _df[num_cols].copy()
        non_missing_rows = X.dropna().shape[0]
        k = min(5, max(1, non_missing_rows))
        logger.info(f"🤝 KNNImputer n_neighbors={k} on {len(num_cols)} features")
        # Impute and backfill data using KNN 
        imputer = KNNImputer(n_neighbors=k)
        X_imp = imputer.fit_transform(X)
        X_imp = pd.DataFrame(X_imp, columns=num_cols, index=_df.index)
        # Write back (excluding ts_sec)
        for c in num_cols:
            if c == "ts_sec":
                continue
            _df[c] = X_imp[c]

        _df.drop(columns=["ts_sec"], inplace=True)
        return _df

    # Copy data from selective sensor types for Feature Engineering
    def _feature_engineering(_df: pd.DataFrame) -> pd.DataFrame:
        _df = _df.copy()
        if {"ENGINE_LOAD", "ABSOLUTE_LOAD"}.issubset(_df.columns):
            _df["AVG_ENGINE_LOAD"] = _df[["ENGINE_LOAD", "ABSOLUTE_LOAD"]].mean(axis=1)
        if {"INTAKE_TEMP", "OIL_TEMP", "COOLANT_TEMP"}.issubset(_df.columns):
            _df["TEMP_MEAN"] = _df[["INTAKE_TEMP", "OIL_TEMP", "COOLANT_TEMP"]].mean(axis=1)
        if {"MAF", "RPM"}.issubset(_df.columns):
            _df["AIRFLOW_PER_RPM"] = _df["MAF"] / _df["RPM"].replace(0, np.nan)
        return _df

    # Apply MinMaxScaler to fit data frame
    def _scale_numeric(_df: pd.DataFrame) -> pd.DataFrame:
        _df = _df.copy()
        num_cols = _df.select_dtypes(include=[np.number]).columns.tolist()
        for c in list(protected_cols):
            if c in num_cols:
                num_cols.remove(c)
        if num_cols:
            scaler = MinMaxScaler()
            _df[num_cols] = scaler.fit_transform(_df[num_cols])
        return _df

    # Correlation heatmap plotter
    def _plot_corr(_df: pd.DataFrame, _id: str):
        try:
            num = _df.select_dtypes(include=[np.number])
            if num.shape[1] < 2:
                return
            plt.figure(figsize=(12, 10))
            sns.heatmap(num.corr(), annot=True, fmt=".2f", cmap="coolwarm")
            plt.title("Correlation Between Numeric OBD-II Variables")
            plt.tight_layout()
            plt.savefig(os.path.join(PLOT_DIR, f"heatmap_{_id}.png"))
            plt.close()
        except Exception as e:
            logger.error(f"Heatmap generation failed: {e}")

    # Sensor trend plotter
    def _plot_trend(_df: pd.DataFrame, _id: str):
        try:
            plt.figure(figsize=(15, 6))
            for col in ['RPM', 'ENGINE_LOAD', 'ABSOLUTE_LOAD', 'COOLANT_TEMP',
                        'INTAKE_TEMP', 'OIL_TEMP', 'INTAKE_PRESSURE', 'BAROMETRIC_PRESSURE',
                        'CONTROL_MODULE_VOLTAGE']:
                if col in _df.columns:
                    plt.plot(_df.index, _df[col], label=col)
            plt.title("Sensor Trends (Index-Based, No Time Gaps)")
            plt.xlabel("Sample Index")
            plt.ylabel("Sensor Value")
            plt.legend()
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(os.path.join(PLOT_DIR, f"trend_{_id}.png"))
            plt.close()
        except Exception as e:
            logger.error(f"Trend plot failed: {e}")

    # ----------------------- pipeline -----------------------
    df = df.copy()
    # 0) Basic tidy
    df = _drop_dead_weight(df)
    df = _to_dt(df)
    # 1) Corruption-only normalization (no outlier trimming)
    df = _normalize_corruption(df)
    # 2) Light row/column filtering for extreme sparsity
    df = _light_row_col_filters(df)
    # 3) Auto infer base interval & insert gap rows
    base_sec = _infer_base_interval_seconds(df["timestamp"])
    df = _insert_time_gaps(df, base_sec)
    # 4) KNN backfill all numeric sensors (time-aware)
    df = _knn_impute_all(df)
    # 5) Feature engineering AFTER imputation
    df = _feature_engineering(df)
    # 6) Final sort / index
    df.sort_values("timestamp", inplace=True)
    df.reset_index(drop=True, inplace=True)
    # 7) Scaling after impute (kept from original)
    if not df.select_dtypes(include=["number"]).empty:
        df = _scale_numeric(df)
    # 8) Save
    out_path = os.path.join(CLEANED_DIR, f"cleaned_{norm_ts}.csv")
    df.to_csv(out_path, index=False)
    logger.info(f"✅ Cleaned saved: {out_path}")
    # 9) Plots
    _plot_corr(df, norm_ts)
    _plot_trend(df, norm_ts)
    # 10) Update event
    try:
        PIPELINE_EVENTS[norm_ts]["status"] = "done"
    except Exception:
        pass
    # 11) Upload to Drive
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
