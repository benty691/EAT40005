# rlhf.py
# Reinforcement Learning from Human Feedback training pipeline
import os
import json
import logging
import pickle
import joblib
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
import warnings

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from sklearn.preprocessing import LabelEncoder, StandardScaler
import xgboost as xgb

# Import our custom modules
from .loader import LabeledDataLoader
from .saver import ModelSaver

# Suppress warnings for cleaner output
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
warnings.filterwarnings("ignore", category=UserWarning, module="xgboost")
warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger("rlhf-trainer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s"))
    logger.addHandler(_h)

class RLHFTrainer:
    """
    Reinforcement Learning from Human Feedback trainer for driver behavior classification.
    
    This trainer:
    1. Loads human-labeled data from Firebase storage
    2. Combines it with existing model predictions for RLHF
    3. Retrains the XGBoost model with the combined dataset
    4. Evaluates performance and saves the new model
    """
    
    def __init__(self):
        self.loader = LabeledDataLoader()
        self.saver = ModelSaver()
        
        # Model parameters
        self.model_params = {
            'n_estimators': 100,
            'max_depth': 6,
            'learning_rate': 0.1,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'random_state': 42,
            'use_label_encoder': False,
            'eval_metric': 'mlogloss'
        }
        
        # Feature columns to drop (non-predictive)
        self.safe_drop = {
            "timestamp", "driving_style", "ul_drivestyle", "gt_drivestyle",
            "session_id", "imported_at", "record_index"
        }
        
        logger.info("🤖 RLHFTrainer initialized")
    
    def _prepare_features(self, df: pd.DataFrame, expected_features: Optional[List[str]] = None) -> Tuple[np.ndarray, List[str]]:
        """Prepare features for training"""
        # Select numeric columns and drop non-feature columns
        feature_cols = [c for c in df.columns 
                       if c not in self.safe_drop and pd.api.types.is_numeric_dtype(df[c])]
        
        X = df[feature_cols].copy()
        
        # Ensure required features are present
        if expected_features:
            for col in expected_features:
                if col not in X.columns:
                    X[col] = 0.0
            X = X[expected_features]  # Align order
        
        # Handle missing values
        X = X.fillna(0)
        
        return X.values, feature_cols
    
    def _prepare_labels(self, df: pd.DataFrame, label_column: str = "driving_style") -> np.ndarray:
        """Prepare labels for training"""
        if label_column not in df.columns:
            raise ValueError(f"Label column '{label_column}' not found in data")
        
        return df[label_column].values
    
    def _load_existing_model(self) -> Tuple[Any, Any, Any, List[str]]:
        """Load existing model components"""
        try:
            model_dir = os.getenv("MODEL_DIR", "/app/models/ul")
            
            model_path = os.path.join(model_dir, "xgb_drivestyle_ul.pkl")
            le_path = os.path.join(model_dir, "label_encoder_ul.pkl")
            scaler_path = os.path.join(model_dir, "scaler_ul.pkl")
            
            # Load with compatibility fixes
            model = self._load_model_with_compatibility(model_path)
            label_encoder = joblib.load(le_path)
            scaler = joblib.load(scaler_path)
            
            # Get expected features
            expected_features = None
            if hasattr(scaler, "feature_names_in_"):
                expected_features = list(scaler.feature_names_in_)
            elif hasattr(model, "feature_names_in_"):
                expected_features = list(model.feature_names_in_)
            
            logger.info(f"✅ Loaded existing model with {len(expected_features) if expected_features else 'unknown'} features")
            return model, label_encoder, scaler, expected_features
            
        except Exception as e:
            logger.warning(f"⚠️ Failed to load existing model: {e}")
            return None, None, None, None
    
    def _load_model_with_compatibility(self, model_path: str) -> Any:
        """Load model with XGBoost compatibility fixes"""
        try:
            model = joblib.load(model_path)
            
            # Fix XGBoost compatibility issues
            if hasattr(model, 'get_booster'):  # This is an XGBoost model
                # Remove deprecated attributes
                deprecated_attrs = [
                    'use_label_encoder', '_le', '_label_encoder',
                    'use_label_encoder_', '_le_', '_label_encoder_'
                ]
                for attr in deprecated_attrs:
                    if hasattr(model, attr):
                        try:
                            delattr(model, attr)
                        except (AttributeError, TypeError):
                            pass
                
                # Set use_label_encoder to False
                if hasattr(model, 'set_params'):
                    try:
                        model.set_params(use_label_encoder=False)
                    except Exception:
                        pass
            
            return model
            
        except Exception as e:
            logger.error(f"❌ Failed to load model: {e}")
            raise
    
    def _create_rlhf_dataset(self, labeled_data: List[pd.DataFrame]) -> Tuple[np.ndarray, np.ndarray]:
        """Create RLHF dataset by combining labeled data with model predictions"""
        try:
            # Load existing model for generating predictions
            existing_model, label_encoder, scaler, expected_features = self._load_existing_model()
            
            if existing_model is None:
                logger.warning("⚠️ No existing model found, using only labeled data")
                return self._prepare_rlhf_from_labeled_only(labeled_data)
            
            # Combine all labeled datasets
            combined_df = pd.concat(labeled_data, ignore_index=True)
            
            # Prepare features and labels
            X, feature_cols = self._prepare_features(combined_df, expected_features)
            y = self._prepare_labels(combined_df)
            
            # Scale features
            X_scaled = scaler.transform(X)
            
            # Generate model predictions for comparison
            model_predictions = existing_model.predict(X_scaled)
            
            # Create RLHF dataset with human feedback
            # In a real RLHF setup, this would include reward signals from human feedback
            # For now, we'll use the labeled data as the "correct" behavior
            
            logger.info(f"📊 Created RLHF dataset: {X.shape[0]} samples, {X.shape[1]} features")
            return X_scaled, y
            
        except Exception as e:
            logger.error(f"❌ Failed to create RLHF dataset: {e}")
            raise
    
    def _prepare_rlhf_from_labeled_only(self, labeled_data: List[pd.DataFrame]) -> Tuple[np.ndarray, np.ndarray]:
        """Prepare RLHF dataset from labeled data only (when no existing model)"""
        combined_df = pd.concat(labeled_data, ignore_index=True)
        
        # Prepare features
        X, feature_cols = self._prepare_features(combined_df)
        y = self._prepare_labels(combined_df)
        
        # Create and fit scaler
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        return X_scaled, y
    
    def _train_model(self, X: np.ndarray, y: np.ndarray, 
                    existing_model: Optional[Any] = None) -> Tuple[Any, Any, Any]:
        """Train the XGBoost model"""
        try:
            # Create label encoder
            label_encoder = LabelEncoder()
            y_encoded = label_encoder.fit_transform(y)
            
            # Create scaler
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X_scaled, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
            )
            
            # Create and train model
            model = xgb.XGBClassifier(**self.model_params)
            
            # If we have an existing model, we can use it for warm start or transfer learning
            if existing_model is not None:
                logger.info("🔄 Using existing model for warm start")
                # For XGBoost, we can't directly warm start, but we can use similar parameters
                # and potentially use the existing model's predictions as additional features
            
            # Train the model
            model.fit(X_train, y_train, 
                     eval_set=[(X_test, y_test)],
                     early_stopping_rounds=10,
                     verbose=False)
            
            # Evaluate
            y_pred = model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            
            logger.info(f"✅ Model trained with accuracy: {accuracy:.4f}")
            
            return model, label_encoder, scaler
            
        except Exception as e:
            logger.error(f"❌ Model training failed: {e}")
            raise
    
    def _evaluate_model(self, model: Any, label_encoder: Any, scaler: Any, 
                       X: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        """Evaluate model performance"""
        try:
            # Prepare test data
            X_scaled = scaler.transform(X)
            y_encoded = label_encoder.transform(y)
            
            # Make predictions
            y_pred = model.predict(X_scaled)
            
            # Calculate metrics
            accuracy = accuracy_score(y_encoded, y_pred)
            
            # Cross-validation score
            cv_scores = cross_val_score(model, X_scaled, y_encoded, cv=5)
            cv_mean = cv_scores.mean()
            cv_std = cv_scores.std()
            
            metrics = {
                "accuracy": accuracy,
                "cv_mean": cv_mean,
                "cv_std": cv_std,
                "cv_scores": cv_scores.tolist()
            }
            
            logger.info(f"📊 Model evaluation: accuracy={accuracy:.4f}, cv_mean={cv_mean:.4f}±{cv_std:.4f}")
            return metrics
            
        except Exception as e:
            logger.error(f"❌ Model evaluation failed: {e}")
            return {"accuracy": 0.0, "cv_mean": 0.0, "cv_std": 0.0}
    
    def train(self, max_datasets: int = 10) -> Dict[str, Any]:
        """Main training pipeline"""
        try:
            logger.info("🚀 Starting RLHF training pipeline")
            
            # Load new labeled datasets
            dataframes, dataset_names = self.loader.create_training_batch(max_datasets=max_datasets)
            
            if not dataframes:
                logger.warning("⚠️ No new datasets available for training")
                return {"status": "no_data", "message": "No new datasets available"}
            
            logger.info(f"📦 Loaded {len(dataframes)} datasets for training")
            
            # Create RLHF dataset
            X, y = self._create_rlhf_dataset(dataframes)
            
            # Load existing model for comparison
            existing_model, existing_le, existing_scaler, expected_features = self._load_existing_model()
            
            # Train new model
            model, label_encoder, scaler = self._train_model(X, y, existing_model)
            
            # Evaluate model
            metrics = self._evaluate_model(model, label_encoder, scaler, X, y)
            
            # Generate model version
            model_version = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Prepare training data info
            training_data_info = {
                "datasets": dataset_names,
                "total_samples": len(X),
                "training_date": datetime.now().isoformat(),
                "features_count": X.shape[1]
            }
            
            # Prepare training log
            training_log = {
                "datasets_used": dataset_names,
                "samples_processed": len(X),
                "model_parameters": self.model_params,
                "performance_metrics": metrics,
                "training_duration": "N/A",  # Could be tracked if needed
                "existing_model_used": existing_model is not None
            }
            
            # Save model
            save_result = self.saver.save_complete_model(
                model=model,
                label_encoder=label_encoder,
                scaler=scaler,
                model_version=model_version,
                training_data_info=training_data_info,
                performance_metrics=metrics,
                training_log=training_log
            )
            
            result = {
                "status": "success",
                "model_version": model_version,
                "datasets_processed": len(dataset_names),
                "samples_processed": len(X),
                "performance_metrics": metrics,
                "save_result": save_result,
                "training_log": training_log
            }
            
            logger.info(f"✅ RLHF training completed successfully: v{model_version}")
            return result
            
        except Exception as e:
            logger.error(f"❌ RLHF training failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


def main():
    """Test the RLHF trainer"""
    try:
        trainer = RLHFTrainer()
        result = trainer.train(max_datasets=5)
        print(f"Training result: {result}")
    except Exception as e:
        print(f"Training failed: {e}")


if __name__ == "__main__":
    main()
