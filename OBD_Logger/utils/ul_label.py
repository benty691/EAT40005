# ul_label.py
# Load UL models and predict driving style
import os, logging, pickle
import warnings
import joblib
import numpy as np
import pandas as pd

log = logging.getLogger("ul-labeler")
log.setLevel(logging.INFO)

# Suppress version compatibility warnings in production
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn.base")
warnings.filterwarnings("ignore", category=UserWarning, module="xgboost.core")

MODEL_DIR = os.getenv("MODEL_DIR", "/app/models/ul")
LE_PATH   = os.path.join(MODEL_DIR, "label_encoder_ul.pkl")
SC_PATH   = os.path.join(MODEL_DIR, "scaler_ul.pkl")
XGB_PATH  = os.path.join(MODEL_DIR, "xgb_drivestyle_ul.pkl")

SAFE_DROP = {
    "timestamp","driving_style","ul_drivestyle","gt_drivestyle",
    "session_id","imported_at","record_index"
}

def _load_any(path):
    # Suppress version compatibility warnings for production
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
        warnings.filterwarnings("ignore", category=UserWarning, module="xgboost")
        try:
            model = joblib.load(path)
        except Exception:
            with open(path, "rb") as f:
                model = pickle.load(f)
    
    # Handle XGBoost compatibility issues
    if hasattr(model, 'use_label_encoder'):
        # Remove deprecated use_label_encoder attribute for newer XGBoost versions
        if hasattr(model, '__dict__'):
            model.__dict__.pop('use_label_encoder', None)
    
    return model

class ULLabeler:
    _instance = None

    def __init__(self):
        if not (os.path.exists(LE_PATH) and os.path.exists(SC_PATH) and os.path.exists(XGB_PATH)):
            raise FileNotFoundError("Model files not found. Ensure download.py ran successfully.")
        self.le   = _load_any(LE_PATH)
        self.scal = _load_any(SC_PATH)
        self.clf  = _load_any(XGB_PATH)
        
        # Additional XGBoost compatibility fixes
        self._fix_xgb_compatibility()

        # Try to discover expected feature names from scaler or model
        self.expected = None
        if hasattr(self.scal, "feature_names_in_"):
            self.expected = list(self.scal.feature_names_in_)
        elif hasattr(self.clf, "feature_names_in_"):
            self.expected = list(self.clf.feature_names_in_)

        log.info(f"ULLabeler ready | expected_features={len(self.expected) if self.expected else 'unknown'}")

    def _fix_xgb_compatibility(self):
        """Fix XGBoost compatibility issues with older trained models."""
        try:
            # Check if this is an XGBoost classifier
            if hasattr(self.clf, 'get_booster'):
                # Remove deprecated attributes that cause issues in newer XGBoost versions
                deprecated_attrs = ['use_label_encoder', '_le', '_label_encoder']
                for attr in deprecated_attrs:
                    if hasattr(self.clf, attr):
                        try:
                            delattr(self.clf, attr)
                        except (AttributeError, TypeError):
                            pass
                
                # Ensure the model is properly configured for prediction
                if hasattr(self.clf, 'n_classes_') and self.clf.n_classes_ is None:
                    # Try to infer number of classes from the label encoder
                    if hasattr(self.le, 'classes_'):
                        self.clf.n_classes_ = len(self.le.classes_)
                
                log.info("XGBoost compatibility fixes applied successfully")
        except Exception as e:
            log.warning(f"XGBoost compatibility fix failed: {e}")

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
        try:
            yhat = self.clf.predict(Xs)
        except AttributeError as e:
            if 'use_label_encoder' in str(e):
                # Last resort: try to fix the model and retry
                log.warning("XGBoost compatibility issue detected, attempting fix...")
                self._fix_xgb_compatibility()
                yhat = self.clf.predict(Xs)
            else:
                raise e
        
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
