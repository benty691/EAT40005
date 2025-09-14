# ul_label.py
# Load UL models and predict driving style
import os, logging, pickle
import joblib
import numpy as np
import pandas as pd

log = logging.getLogger("ul-labeler")
log.setLevel(logging.INFO)

MODEL_DIR = os.getenv("MODEL_DIR", "/app/models/ul")
LE_PATH   = os.path.join(MODEL_DIR, "label_encoder_ul.pkl")
SC_PATH   = os.path.join(MODEL_DIR, "scaler_ul.pkl")
XGB_PATH  = os.path.join(MODEL_DIR, "xgb_drivestyle_ul.pkl")

SAFE_DROP = {
    "timestamp","driving_style","ul_drivestyle","gt_drivestyle",
    "session_id","imported_at","record_index"
}

def _load_any(path):
    try:
        return joblib.load(path)
    except Exception:
        with open(path, "rb") as f:
            return pickle.load(f)

class ULLabeler:
    _instance = None

    def __init__(self):
        if not (os.path.exists(LE_PATH) and os.path.exists(SC_PATH) and os.path.exists(XGB_PATH)):
            raise FileNotFoundError("Model files not found. Ensure download.py ran successfully.")
        self.le   = _load_any(LE_PATH)
        self.scal = _load_any(SC_PATH)
        self.clf  = _load_any(XGB_PATH)

        # Try to discover expected feature names from scaler or model
        self.expected = None
        if hasattr(self.scal, "feature_names_in_"):
            self.expected = list(self.scal.feature_names_in_)
        elif hasattr(self.clf, "feature_names_in_"):
            self.expected = list(self.clf.feature_names_in_)

        log.info(f"ULLabeler ready | expected_features={len(self.expected) if self.expected else 'unknown'}")

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = ULLabeler()
        return cls._instance

    def _prepare(self, df: pd.DataFrame):
        # numeric only + drop non-feature columns
        cols = [c for c in df.columns if c not in SAFE_DROP and pd.api.types.is_numeric_dtype(df[c])]
        X = df[cols].copy()

        # ensure required features
        if self.expected:
            for c in self.expected:
                if c not in X.columns:
                    X[c] = 0.0
            X = X[self.expected]  # align order
        X = X.fillna(0)

        # scale
        try:
            Xs = self.scal.transform(X if hasattr(self.scal, "feature_names_in_") else X.values)
        except Exception as e:
            log.warning(f"Scaler transform failed ({e}); using raw features.")
            Xs = X.values
        return Xs

    def predict_df(self, df: pd.DataFrame) -> np.ndarray:
        Xs = self._prepare(df)
        yhat = self.clf.predict(Xs)
        try:
            return self.le.inverse_transform(yhat)
        except Exception:
            return yhat

    def predict_csv(self, csv_path: str) -> pd.DataFrame:
        df = pd.read_csv(csv_path)
        y = self.predict_df(df)
        out = df.copy()
        out["driving_style"] = y
        return out
