# ul_label.py
# Load UL models and predict driving style
import os, logging, pickle
import warnings
import joblib
import numpy as np
import pandas as pd

# Import download functionality
import sys
sys.path.append(os.path.dirname(__file__))
from download import download_latest_models

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
        warnings.filterwarnings("ignore", category=FutureWarning, module="sklearn")
        warnings.filterwarnings("ignore", category=FutureWarning, module="xgboost")
        try:
            model = joblib.load(path)
        except Exception:
            with open(path, "rb") as f:
                model = pickle.load(f)
    
    # Fix XGBoost compatibility issues for older trained models
    if hasattr(model, 'get_booster'):  # This is an XGBoost model
        # Remove deprecated use_label_encoder attribute that causes issues in newer XGBoost versions
        if hasattr(model, '__dict__'):
            # Remove all deprecated attributes that cause issues
            deprecated_attrs = [
                'use_label_encoder', '_le', '_label_encoder', 
                'use_label_encoder_', '_le_', '_label_encoder_'
            ]
            for attr in deprecated_attrs:
                model.__dict__.pop(attr, None)
            
            # Set use_label_encoder to False for newer XGBoost versions
            if hasattr(model, 'set_params'):
                try:
                    model.set_params(use_label_encoder=False)
                except Exception:
                    pass
    
    return model

class ULLabeler:
    _instance = None

    def __init__(self, auto_download: bool = True):
        # Auto-download latest models if enabled
        if auto_download:
            log.info("🔄 Checking for latest model version...")
            try:
                download_latest_models()
            except Exception as e:
                log.warning(f"⚠️ Failed to download latest models: {e}")
        
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
                deprecated_attrs = [
                    'use_label_encoder', '_le', '_label_encoder',
                    'use_label_encoder_', '_le_', '_label_encoder_'
                ]
                for attr in deprecated_attrs:
                    if hasattr(self.clf, attr):
                        try:
                            delattr(self.clf, attr)
                        except (AttributeError, TypeError):
                            pass
                
                # Set use_label_encoder to False for newer XGBoost versions
                if hasattr(self.clf, 'set_params'):
                    try:
                        self.clf.set_params(use_label_encoder=False)
                    except Exception:
                        pass
                
                # Ensure the model is properly configured for prediction
                if hasattr(self.clf, 'n_classes_') and self.clf.n_classes_ is None:
                    # Try to infer number of classes from the label encoder
                    if hasattr(self.le, 'classes_'):
                        self.clf.n_classes_ = len(self.le.classes_)
                
                # For newer XGBoost versions, ensure the model is properly initialized
                if hasattr(self.clf, '_le') and self.clf._le is None:
                    self.clf._le = None
                
                log.info("XGBoost compatibility fixes applied successfully")
        except Exception as e:
            log.warning(f"XGBoost compatibility fix failed: {e}")

    @classmethod
    def get(cls, auto_download: bool = True):
        if cls._instance is None:
            cls._instance = ULLabeler(auto_download=auto_download)
        return cls._instance

    def _prepare(self, df: pd.DataFrame):
        # Match training preprocessing exactly
        # Drop non-feature columns (same as training)
        drop_cols = {"timestamp","ul_drivestyle","gt_drivestyle","driving_style","session_id","imported_at","record_index"}
        X = df.drop(columns=[c for c in drop_cols if c in df.columns])
        
        # Keep only numeric columns (same as training)
        X = X.select_dtypes(include=[np.number]).fillna(0)
        
        # ensure required features match training
        if self.expected:
            for c in self.expected:
                if c not in X.columns:
                    X[c] = 0.0
            X = X[self.expected]  # align order
        
        # Data should already be scaled by main pipeline, but apply scaler if needed
        # This handles cases where the main pipeline scaling might not match exactly
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
        except (AttributeError, TypeError) as e:
            if 'use_label_encoder' in str(e) or 'label_encoder' in str(e):
                # Last resort: try to fix the model and retry
                log.warning("XGBoost compatibility issue detected, attempting fix...")
                try:
                    # Remove all problematic attributes
                    deprecated_attrs = [
                        'use_label_encoder', '_le', '_label_encoder',
                        'use_label_encoder_', '_le_', '_label_encoder_'
                    ]
                    for attr in deprecated_attrs:
                        if hasattr(self.clf, attr):
                            try:
                                delattr(self.clf, attr)
                            except (AttributeError, TypeError):
                                pass
                    
                    # Set use_label_encoder to False
                    if hasattr(self.clf, 'set_params'):
                        try:
                            self.clf.set_params(use_label_encoder=False)
                        except Exception:
                            pass
                    
                    # Retry prediction
                    yhat = self.clf.predict(Xs)
                except Exception as retry_e:
                    log.error(f"Failed to fix XGBoost compatibility: {retry_e}")
                    raise e
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
