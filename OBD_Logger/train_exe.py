#!/usr/bin/env python3
"""
Consistent Training Script for XGBoost Driving Style Classification
This script ensures complete consistency between training and inference pipelines.
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns
import matplotlib.pyplot as plt
from xgboost import XGBClassifier
import joblib
import warnings

warnings.filterwarnings('ignore')

def add_feature_engineering(df):
    """Add the same feature engineering as inference pipeline"""
    df = df.copy()
    
    # Match the feature engineering from app.py
    if {"ENGINE_LOAD", "ABSOLUTE_LOAD"}.issubset(df.columns):
        df["AVG_ENGINE_LOAD"] = df[["ENGINE_LOAD", "ABSOLUTE_LOAD"]].mean(axis=1)
    if {"INTAKE_TEMP", "OIL_TEMP", "COOLANT_TEMP"}.issubset(df.columns):
        df["TEMP_MEAN"] = df[["INTAKE_TEMP", "OIL_TEMP", "COOLANT_TEMP"]].mean(axis=1)
    if {"MAF", "RPM"}.issubset(df.columns):
        df["AIRFLOW_PER_RPM"] = df["MAF"] / df["RPM"].replace(0, np.nan)
    
    return df

def train_consistent_model(csv_path="drivestyle_cpl.csv", use_ul=True, save_to_train_folder=True):
    """
    Train XGBoost model with complete consistency to inference pipeline
    """
    print("🚀 Starting consistent training...")
    
    # Load dataset
    df = pd.read_csv(csv_path)
    print(f"Dataset shape: {df.shape}")
    print(f"Columns: {df.columns[:15].tolist()}")
    print(f"Label columns: {df[['ul_drivestyle','gt_drivestyle']].head()}")
    
    # Apply feature engineering (same as inference)
    df = add_feature_engineering(df)
    print("✅ Applied feature engineering")
    
    # Drop non-feature columns (same as training original)
    drop_cols = {"timestamp","ul_drivestyle","gt_drivestyle"}
    X = df.drop(columns=[c for c in drop_cols if c in df.columns])
    
    # Keep only numeric columns (same as training original)
    X = X.select_dtypes(include=[np.number]).fillna(0)
    
    # Choose labels: UL or GT
    if use_ul and "ul_drivestyle" in df.columns:
        y_raw = df["ul_drivestyle"].fillna("(unknown)")
        print("Training on UL labels")
    else:
        y_raw = df["gt_drivestyle"].fillna("(unknown)")
        print("Training on GT labels")
    
    # Encode labels → integers
    le = LabelEncoder()
    y = le.fit_transform(y_raw)
    
    print(f"Classes: {le.classes_}")
    print(f"Class distribution: {np.bincount(y)}")
    print(f"Feature matrix shape: {X.shape}")
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )
    
    # Scale features with StandardScaler (same as inference)
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)
    
    print("✅ Applied StandardScaler preprocessing")
    
    # Train XGBoost
    xgb = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        objective="multi:softprob",
        num_class=len(le.classes_),
        eval_metric="mlogloss",
        random_state=42,
        n_jobs=-1,
        use_label_encoder=False  # Important for newer XGBoost versions
    )
    
    print("🤖 Training XGBoost model...")
    xgb.fit(X_train, y_train)
    
    # Predictions
    y_pred = xgb.predict(X_test)
    
    print("\n📊 Classification Report:")
    print(classification_report(y_test, y_pred, target_names=le.classes_))
    
    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred, labels=range(len(le.classes_)))
    plt.figure(figsize=(8,6))
    sns.heatmap(cm, annot=True, fmt="d", xticklabels=le.classes_, yticklabels=le.classes_, cmap="Blues")
    plt.xlabel("Predicted")
    plt.ylabel("True")
    plt.title("Confusion Matrix - Consistent Training")
    plt.tight_layout()
    plt.savefig("confusion_matrix_consistent.png", dpi=150, bbox_inches='tight')
    plt.show()
    
    # Save model components
    if save_to_train_folder:
        # Save to train folder with standard names for production use
        model_filename = "train/xgb_drivestyle_ul.pkl"
        scaler_filename = "train/scaler_ul.pkl"
        le_filename = "train/label_encoder_ul.pkl"
    else:
        # Save with consistent suffix for testing
        model_filename = "xgb_drivestyle_ul_consistent.pkl"
        scaler_filename = "scaler_ul_consistent.pkl"
        le_filename = "label_encoder_ul_consistent.pkl"
    
    joblib.dump(xgb, model_filename)
    joblib.dump(scaler, scaler_filename)
    joblib.dump(le, le_filename)
    
    print(f"\n✅ Model components saved:")
    print(f"   - Model: {model_filename}")
    print(f"   - Scaler: {scaler_filename}")
    print(f"   - Label Encoder: {le_filename}")
    
    # Test consistency with inference pipeline
    print("\n🧪 Testing consistency with inference pipeline...")
    test_df = df.head(10).copy()
    
    # Simulate inference preprocessing
    test_df = add_feature_engineering(test_df)
    test_X = test_df.drop(columns=[c for c in drop_cols if c in test_df.columns])
    test_X = test_X.select_dtypes(include=[np.number]).fillna(0)
    test_X_scaled = scaler.transform(test_X)
    
    # Predict
    test_pred = xgb.predict(test_X_scaled)
    test_labels = le.inverse_transform(test_pred)
    
    print(f"Sample predictions: {test_labels[:5]}")
    print("✅ Consistency test completed")
    
    return xgb, scaler, le

if __name__ == "__main__":
    # Train the model
    model, scaler, label_encoder = train_consistent_model()
    
    print("\n🎉 Training completed successfully!")
    print("This model should now work correctly with your inference pipeline.")
