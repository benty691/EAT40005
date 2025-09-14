# firebase_saver.py
import os
import io
import json
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger("firebase-saver")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s"))
    logger.addHandler(_h)

def _parse_gs_uri(uri: Optional[str]):
    if not uri or not uri.startswith("gs://"):
        return None, None
    path = uri[len("gs://"):]
    parts = path.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix

def _maybe_default_firebase_bucket(name: Optional[str]) -> Optional[str]:
    # If user passed a project ID (no dot), convert to <project>.appspot.com
    if name and "." not in name:
        return f"{name}.appspot.com"
    return name

class _AdminClient:
    def __init__(self, bucket: str):
        import firebase_admin
        from firebase_admin import credentials, storage as fb_storage

        raw = os.getenv("FIREBASE_ADMIN_JSON")
        if not raw:
            raise RuntimeError("FIREBASE_ADMIN_JSON not set")
        info = json.loads(raw)
        client_email = info.get("client_email")
        cred = credentials.Certificate(info)

        # If app already initialized, reuse it
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred, {"storageBucket": bucket})
        else:
            # if already initialized without a bucket, set default bucket here
            pass

        self.bucket = fb_storage.bucket(bucket)
        logger.info(f"✅ Firebase Admin initialized | bucket={bucket} as {client_email}")

    def upload_from_filename(self, local_path: str, dest_path: str, content_type: str):
        blob = self.bucket.blob(dest_path)
        blob.cache_control = "no-store"
        blob.upload_from_filename(local_path, content_type=content_type)

    def upload_from_bytes(self, data: bytes, dest_path: str, content_type: str):
        blob = self.bucket.blob(dest_path)
        blob.cache_control = "no-store"
        blob.upload_from_string(data, content_type=content_type)

class _GCSClient:
    def __init__(self, bucket: str):
        from google.cloud import storage
        from google.oauth2 import service_account

        raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
        if not raw:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON not set")
        info = json.loads(raw)
        client_email = info.get("client_email")
        creds = service_account.Credentials.from_service_account_info(info)
        project_id = info.get("project_id")
        self.client = storage.Client(credentials=creds, project=project_id)
        self.bucket = self.client.bucket(bucket)
        logger.info(f"✅ GCS client initialized | bucket={bucket} as {client_email}")

    def upload_from_filename(self, local_path: str, dest_path: str, content_type: str):
        blob = self.bucket.blob(dest_path)
        blob.cache_control = "no-store"
        blob.upload_from_filename(local_path, content_type=content_type)

    def upload_from_bytes(self, data: bytes, dest_path: str, content_type: str):
        blob = self.bucket.blob(dest_path)
        blob.cache_control = "no-store"
        blob.upload_from_string(data, content_type=content_type)

class FirebaseSaver:
    """
    Priority:
      1) Firebase Admin SDK via FIREBASE_ADMIN_JSON (recommended on Blaze)
      2) google-cloud-storage via FIREBASE_SERVICE_ACCOUNT_JSON (fallback)

    Config (any of):
      - FIREBASE_GS_URI=gs://<bucket>/<prefix>
      - FIREBASE_BUCKET and FIREBASE_PREFIX
    """
    def __init__(self, gs_uri: Optional[str] = None, bucket_name: Optional[str] = None, prefix: Optional[str] = None):
        env_gs = gs_uri or os.getenv("FIREBASE_GS_URI")
        if env_gs:
            b, p = _parse_gs_uri(env_gs)
            if b:
                bucket_name = b
                if prefix is None:
                    prefix = p

        bucket_name = bucket_name or os.getenv("FIREBASE_BUCKET")
        prefix = prefix if prefix is not None else os.getenv("FIREBASE_PREFIX", "skyledge/processed")

        # Normalize bucket (auto map project-id to <project-id>.appspot.com)
        bucket_name = _maybe_default_firebase_bucket(bucket_name)

        if not bucket_name:
            # As a last resort, try to infer from Admin JSON project_id
            raw_admin = os.getenv("FIREBASE_ADMIN_JSON")
            if raw_admin:
                try:
                    pj = json.loads(raw_admin).get("project_id")
                    bucket_name = f"{pj}.appspot.com" if pj else None
                except Exception:
                    pass

        if not bucket_name:
            raise RuntimeError("No Firebase bucket resolved. Set FIREBASE_GS_URI or FIREBASE_BUCKET.")

        self.bucket_name = bucket_name
        self.prefix = (prefix or "").strip("/") or None

        # Choose client
        self.client = None
        self.mode = None
        # Try Admin SDK first
        try:
            if os.getenv("FIREBASE_ADMIN_JSON"):
                self.client = _AdminClient(self.bucket_name)
                self.mode = "admin"
        except Exception as e:
            logger.warning(f"⚠️ Admin SDK init failed: {e}")

        # Fallback to GCS
        if self.client is None:
            try:
                self.client = _GCSClient(self.bucket_name)
                self.mode = "gcs"
            except Exception as e:
                logger.error(f"❌ GCS client init failed: {e}")
                raise

        logger.info(f"📦 FirebaseSaver ready | mode={self.mode} bucket={self.bucket_name} prefix={self.prefix or '(root)'}")

    def _dest_path(self, filename: str, subdir: Optional[str] = None) -> str:
        parts = []
        if self.prefix:
            parts.append(self.prefix)
        if subdir:
            parts.append(subdir.strip("/"))
        parts.append(os.path.basename(filename))
        return "/".join(parts)

    def is_available(self) -> bool:
        return self.client is not None

    def upload_file(self, local_path: str, dest_name: Optional[str] = None, subdir: Optional[str] = None, content_type: str = "text/csv") -> bool:
        if not self.is_available():
            logger.warning("⚠️ Firebase saver unavailable")
            return False
        try:
            dest = self._dest_path(dest_name or os.path.basename(local_path), subdir=subdir)
            self.client.upload_from_filename(local_path, dest, content_type)
            logger.info(f"✅ Uploaded file to gs://{self.bucket_name}/{dest}")
            return True
        except Exception as e:
            logger.error(f"❌ Firebase upload failed: {e}")
            return False

    def upload_dataframe(self, df: pd.DataFrame, dest_name: str, subdir: Optional[str] = None, content_type: str = "text/csv") -> bool:
        if not self.is_available():
            logger.warning("⚠️ Firebase saver unavailable")
            return False
        try:
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            data = buf.getvalue().encode("utf-8")
            dest = self._dest_path(dest_name, subdir=subdir)
            self.client.upload_from_bytes(data, dest, content_type)
            logger.info(f"✅ Uploaded DataFrame to gs://{self.bucket_name}/{dest}")
            return True
        except Exception as e:
            logger.error(f"❌ Firebase DF upload failed: {e}")
            return False

# Convenience
def save_csv_to_firebase(csv_path: str, dest_name: Optional[str] = None, subdir: Optional[str] = None) -> bool:
    saver = FirebaseSaver()
    return saver.upload_file(csv_path, dest_name=dest_name, subdir=subdir)

def save_dataframe_to_firebase(df: pd.DataFrame, dest_name: str, subdir: Optional[str] = None) -> bool:
    saver = FirebaseSaver()
    return saver.upload_dataframe(df, dest_name=dest_name, subdir=subdir)
