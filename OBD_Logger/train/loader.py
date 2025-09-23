# loader.py
# Load labeled data from Firebase storage for RLHF training
import os
import json
import logging
import pandas as pd
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# Import Firebase client from the existing firebase_saver
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from data.firebase_saver import _AdminClient, _GCSClient

logger = logging.getLogger("rlhf-loader")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s"))
    logger.addHandler(_h)

# Firebase configuration
FIREBASE_BUCKET = "skyledge-36b56.firebasestorage.app"
LABELED_PREFIX = "skyledge/labeled"
TRAINED_FILE = "trained.txt"

class LabeledDataLoader:
    """
    Load labeled data from Firebase storage for RLHF training.
    Tracks already processed datasets to avoid retraining on the same data.
    """
    
    def __init__(self):
        self.bucket_name = FIREBASE_BUCKET
        self.prefix = LABELED_PREFIX
        self.trained_file = TRAINED_FILE
        
        # Initialize Firebase client
        self.client = None
        self.mode = None
        try:
            if os.getenv("FIREBASE_ADMIN_JSON"):
                self.client = _AdminClient(self.bucket_name)
                self.mode = "admin"
        except Exception as e:
            logger.warning(f"⚠️ Admin SDK init failed: {e}")
        
        if self.client is None:
            try:
                self.client = _GCSClient(self.bucket_name)
                self.mode = "gcs"
            except Exception as e:
                logger.error(f"❌ GCS client init failed: {e}")
                raise
        
        logger.info(f"📦 LabeledDataLoader ready | mode={self.mode} bucket={self.bucket_name} prefix={self.prefix}")
    
    def _get_trained_datasets(self) -> List[str]:
        """Load list of already trained datasets from trained.txt"""
        try:
            # Check if trained.txt exists in Firebase storage
            trained_path = f"{self.prefix}/{self.trained_file}"
            if self.client.blob_exists(trained_path):
                # Download and read the file
                blob = self.client.bucket.blob(trained_path)
                content = blob.download_as_text()
                trained_datasets = [line.strip() for line in content.split('\n') if line.strip()]
                logger.info(f"📋 Loaded {len(trained_datasets)} already trained datasets")
                return trained_datasets
            else:
                logger.info("📋 No trained.txt found, starting fresh")
                return []
        except Exception as e:
            logger.warning(f"⚠️ Failed to load trained datasets: {e}")
            return []
    
    def _update_trained_datasets(self, new_datasets: List[str]):
        """Update trained.txt with new dataset names"""
        try:
            # Get existing trained datasets
            existing = self._get_trained_datasets()
            
            # Add new datasets with timestamp
            timestamp = datetime.now().isoformat()
            new_entries = [f"{timestamp}:{dataset}" for dataset in new_datasets]
            all_entries = existing + new_entries
            
            # Upload updated file
            trained_path = f"{self.prefix}/{self.trained_file}"
            content = '\n'.join(all_entries)
            self.client.upload_from_bytes(
                content.encode('utf-8'), 
                trained_path, 
                "text/plain"
            )
            logger.info(f"✅ Updated trained.txt with {len(new_datasets)} new datasets")
        except Exception as e:
            logger.error(f"❌ Failed to update trained datasets: {e}")
    
    def list_labeled_datasets(self) -> List[Dict[str, str]]:
        """List all available labeled datasets in Firebase storage"""
        try:
            # List all blobs under the labeled prefix
            blobs = self.client.bucket.list_blobs(prefix=f"{self.prefix}/")
            
            datasets = []
            trained_datasets = self._get_trained_datasets()
            
            for blob in blobs:
                # Skip the trained.txt file itself
                if blob.name.endswith(f"/{self.trained_file}"):
                    continue
                
                # Extract dataset name (relative to skyledge root)
                dataset_name = blob.name.replace("skyledge/", "")
                
                # Skip if already trained
                if any(dataset_name in entry for entry in trained_datasets):
                    continue
                
                # Get blob metadata
                blob.reload()
                datasets.append({
                    'name': dataset_name,
                    'path': blob.name,
                    'size': blob.size,
                    'created': blob.time_created.isoformat() if blob.time_created else None,
                    'updated': blob.updated.isoformat() if blob.updated else None,
                    'content_type': blob.content_type
                })
            
            logger.info(f"📊 Found {len(datasets)} new labeled datasets")
            return datasets
            
        except Exception as e:
            logger.error(f"❌ Failed to list labeled datasets: {e}")
            return []
    
    def download_dataset(self, dataset_path: str, local_path: str) -> bool:
        """Download a dataset from Firebase storage to local path"""
        try:
            blob = self.client.bucket.blob(dataset_path)
            blob.download_to_filename(local_path)
            logger.info(f"✅ Downloaded {dataset_path} to {local_path}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to download {dataset_path}: {e}")
            return False
    
    def load_dataset(self, dataset_path: str) -> Optional[pd.DataFrame]:
        """Load a dataset directly into a pandas DataFrame"""
        try:
            blob = self.client.bucket.blob(dataset_path)
            content = blob.download_as_text()
            
            # Try to determine file type and load accordingly
            if dataset_path.endswith('.csv'):
                df = pd.read_csv(pd.StringIO(content))
            elif dataset_path.endswith('.json'):
                df = pd.read_json(pd.StringIO(content))
            elif dataset_path.endswith('.parquet'):
                # For parquet, we need to download as bytes
                blob_bytes = blob.download_as_bytes()
                df = pd.read_parquet(pd.BytesIO(blob_bytes))
            else:
                # Default to CSV
                df = pd.read_csv(pd.StringIO(content))
            
            logger.info(f"✅ Loaded dataset {dataset_path} with shape {df.shape}")
            return df
            
        except Exception as e:
            logger.error(f"❌ Failed to load dataset {dataset_path}: {e}")
            return None
    
    def get_new_datasets_for_training(self) -> List[Dict[str, str]]:
        """Get list of new datasets that haven't been used for training yet"""
        return self.list_labeled_datasets()
    
    def mark_datasets_as_trained(self, dataset_names: List[str]):
        """Mark datasets as trained to avoid retraining"""
        self._update_trained_datasets(dataset_names)
    
    def create_training_batch(self, max_datasets: int = 10) -> Tuple[List[pd.DataFrame], List[str]]:
        """
        Create a training batch by loading new datasets.
        Returns tuple of (dataframes, dataset_names)
        """
        datasets = self.get_new_datasets_for_training()
        
        if not datasets:
            logger.info("📭 No new datasets available for training")
            return [], []
        
        # Limit the number of datasets
        datasets = datasets[:max_datasets]
        
        dataframes = []
        dataset_names = []
        
        for dataset in datasets:
            df = self.load_dataset(dataset['path'])
            if df is not None:
                dataframes.append(df)
                dataset_names.append(dataset['name'])
            else:
                logger.warning(f"⚠️ Skipping dataset {dataset['name']} due to load failure")
        
        if dataframes:
            logger.info(f"📦 Created training batch with {len(dataframes)} datasets")
            # Mark these datasets as trained
            self.mark_datasets_as_trained(dataset_names)
        
        return dataframes, dataset_names


def main():
    """Test the loader functionality"""
    loader = LabeledDataLoader()
    
    # List available datasets
    datasets = loader.list_labeled_datasets()
    print(f"Available datasets: {len(datasets)}")
    for dataset in datasets:
        print(f"  - {dataset['name']} ({dataset['size']} bytes)")
    
    # Create a training batch
    dataframes, names = loader.create_training_batch(max_datasets=5)
    print(f"Training batch: {len(dataframes)} datasets")
    for name in names:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
