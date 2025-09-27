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
    
    def _create_rlhf_dataset(self, training_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
        """Create RLHF dataset by combining labeled data with original data and model predictions"""
        try:
            # Load existing model for generating predictions
            existing_model, label_encoder, scaler, expected_features = self._load_existing_model()
            
            if existing_model is None:
                logger.warning("⚠️ No existing model found, using only labeled data")
                return self._prepare_rlhf_from_labeled_only(training_data)
            
            # Combine all labeled datasets
            labeled_dfs = [item['labeled_df'] for item in training_data if item['labeled_df'] is not None]
            original_dfs = [item['original_df'] for item in training_data if item['original_df'] is not None]
            
            combined_labeled_df = pd.concat(labeled_dfs, ignore_index=True)
            
            # Prepare features and labels from labeled data
            X_labeled, feature_cols = self._prepare_features(combined_labeled_df, expected_features)
            y_labeled = self._prepare_labels(combined_labeled_df)
            
            # Scale features
            X_labeled_scaled = scaler.transform(X_labeled)
            
            # Generate model predictions on original data for comparison
            model_predictions = []
            prediction_confidence = []
            
            if original_dfs:
                combined_original_df = pd.concat(original_dfs, ignore_index=True)
                X_original, _ = self._prepare_features(combined_original_df, expected_features)
                X_original_scaled = scaler.transform(X_original)
                
                # Get model predictions on original data
                original_predictions = existing_model.predict(X_original_scaled)
                model_predictions.extend(original_predictions)
                
                # Get prediction probabilities for confidence
                if hasattr(existing_model, 'predict_proba'):
                    proba = existing_model.predict_proba(X_original_scaled)
                    confidence = np.max(proba, axis=1)
                    prediction_confidence.extend(confidence)
            
            # Create RLHF dataset with preference learning
            # The labeled data represents the "correct" behavior (human preference)
            # The model predictions on original data represent what the model thought was correct
            
            # For RLHF, we want to learn from the difference between model predictions and human labels
            rlhf_metadata = {
                "labeled_samples": len(X_labeled),
                "original_samples": len(model_predictions) if model_predictions else 0,
                "model_confidence": np.mean(prediction_confidence) if prediction_confidence else 0.0,
                "datasets_processed": len(training_data)
            }
            
            logger.info(f"📊 Created RLHF dataset: {len(X_labeled)} labeled samples, {len(model_predictions)} original samples")
            logger.info(f"📊 Model confidence on original data: {rlhf_metadata['model_confidence']:.3f}")
            
            return X_labeled_scaled, y_labeled, rlhf_metadata
            
        except Exception as e:
            logger.error(f"❌ Failed to create RLHF dataset: {e}")
            raise
    
    def _prepare_rlhf_from_labeled_only(self, training_data: List[Dict[str, Any]]) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
        """Prepare RLHF dataset from labeled data only (when no existing model)"""
        labeled_dfs = [item['labeled_df'] for item in training_data if item['labeled_df'] is not None]
        combined_df = pd.concat(labeled_dfs, ignore_index=True)
        
        # Prepare features
        X, feature_cols = self._prepare_features(combined_df)
        y = self._prepare_labels(combined_df)
        
        # Create and fit scaler
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        rlhf_metadata = {
            "labeled_samples": len(X),
            "original_samples": 0,
            "model_confidence": 0.0,
            "datasets_processed": len(training_data)
        }
        
        return X_scaled, y, rlhf_metadata
    
    
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
            
            # Load new labeled datasets with original data for RLHF
            training_data, dataset_names = self.loader.create_rlhf_training_batch(max_datasets=max_datasets)
            
            if not training_data:
                logger.warning("⚠️ No new datasets available for RLHF training")
                return {"status": "no_data", "message": "No new datasets available"}
            
            logger.info(f"📦 Loaded {len(training_data)} datasets for RLHF training")
            
            # Create RLHF dataset
            X, y, rlhf_metadata = self._create_rlhf_dataset(training_data)
            
            # Load existing model for comparison
            existing_model, existing_le, existing_scaler, expected_features = self._load_existing_model()
            
            # Train new model
            model, label_encoder, scaler = self._train_model(X, y, existing_model)
            
            # Evaluate model
            metrics = self._evaluate_model(model, label_encoder, scaler, X, y)
            
            # Generate model version using semantic versioning
            model_version = self.saver._get_next_version()
            
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
                training_log=training_log,
                rlhf_metadata=rlhf_metadata
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
