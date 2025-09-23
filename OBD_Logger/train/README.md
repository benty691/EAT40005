---
license: apache-2.0
language:
- en
pipeline_tag: tabular-classification
---

# RLHF Training System

This directory contains the Reinforcement Learning from Human Feedback (RLHF) training pipeline for the driver behavior classification model.

## Overview

The RLHF system enables continuous improvement of the driver behavior model by:
1. Loading human-labeled data from Firebase storage (`skyledge/labeled`)
2. Combining it with existing model predictions for reinforcement learning
3. Retraining the XGBoost model with the enhanced dataset
4. Saving new model checkpoints to Hugging Face Hub

## Files

### `loader.py`
- **Purpose**: Load labeled data from Firebase storage
- **Key Features**:
  - Lists available labeled datasets from `skyledge/labeled` path
  - Tracks already processed datasets in `trained.txt`
  - Downloads and loads datasets into pandas DataFrames
  - Prevents retraining on the same data

### `saver.py`
- **Purpose**: Save trained models to Hugging Face Hub and local storage
- **Key Features**:
  - Saves model components (XGBoost model, label encoder, scaler)
  - Creates model metadata and README files
  - Uploads to Hugging Face Hub with versioning
  - Maintains local model directory structure

### `rlhf.py`
- **Purpose**: Main RLHF training pipeline
- **Key Features**:
  - Loads new labeled datasets
  - Creates RLHF dataset by combining labeled data with model predictions
  - Trains XGBoost model with enhanced dataset
  - Evaluates model performance
  - Coordinates with loader and saver modules

## API Endpoints

The RLHF training system is integrated into the main FastAPI application with the following endpoints:

### `POST /rlhf/train`
Trigger RLHF training session.

**Request Body:**
```json
{
  "max_datasets": 10,
  "force_retrain": false
}
```

**Response:**
```json
{
  "status": "success",
  "model_version": "20241201_143022",
  "datasets_processed": 5,
  "samples_processed": 1250,
  "performance_metrics": {
    "accuracy": 0.892,
    "cv_mean": 0.885,
    "cv_std": 0.012
  },
  "timestamp": "2024-12-01T14:30:22"
}
```

### `GET /rlhf/status`
Get status of RLHF training system and available labeled data.

### `GET /rlhf/trained-datasets`
Get list of datasets that have already been used for training.

## Configuration

### Environment Variables
- `HF_TOKEN`: Hugging Face authentication token
- `HF_MODEL_REPO`: Hugging Face model repository (default: `BinKhoaLe1812/Driver_Behavior_OBD`)
- `MODEL_DIR`: Local model directory (default: `/app/models/ul`)
- `FIREBASE_ADMIN_JSON`: Firebase Admin SDK credentials
- `FIREBASE_SERVICE_ACCOUNT_JSON`: Firebase service account credentials

### Firebase Storage Structure
```
skyledge-36b56.firebasestorage.app/
├── skyledge/
│   ├── processed/          # Original processed data
│   ├── labeled/            # Human-labeled data for RLHF
│   │   ├── dataset1.csv
│   │   ├── dataset2.csv
│   │   └── trained.txt     # Tracks processed datasets
│   └── logs/               # Training logs (future)
```

## Usage

## Model Versioning

Each training session creates a new model version with timestamp format: `YYYYMMDD_HHMMSS`

Models are saved to:
- **Local**: `/app/models/ul/v{version}/`
- **Hugging Face**: `BinKhoaLe1812/Driver_Behavior_OBD`

## Data Flow

1. **Data Collection**: Human-labeled data stored in `skyledge/labeled/`
2. **Training Trigger**: API endpoint or manual trigger
3. **Data Loading**: Load new labeled datasets (skip already processed)
4. **RLHF Dataset**: Combine labeled data with model predictions
5. **Model Training**: Train XGBoost with enhanced dataset
6. **Evaluation**: Calculate performance metrics
7. **Model Saving**: Save to local storage and Hugging Face Hub
8. **Tracking**: Update `trained.txt` with processed datasets

## Performance Monitoring

The system tracks:
- Number of datasets processed
- Total samples processed
- Model accuracy and cross-validation scores
- Training timestamps and metadata

## Error Handling

- Graceful handling of missing datasets
- Firebase connection failures
- Model loading/saving errors
- XGBoost compatibility issues
- Comprehensive logging throughout the pipeline
