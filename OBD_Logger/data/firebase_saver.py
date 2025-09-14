# firebase_saver.py
# Upload cleaned / labeled CSVs and DataFrames to Firebase Storage (GCS)
# Supports:
#   - FIREBASE_GS_URI="gs://<bucket>/<prefix>"
#   - or FIREBASE_BUCKET="..." and FIREBASE_PREFIX="..."
#   - Credentials via FIREBASE_SERVICE_ACCOUNT_JSON (secret env containing full JSON)

import os
import io
import json
import logging
import tempfile
from typing import Optional

import pandas as pd

# Optional dependency guard
FIREBASE_AVAILABLE = True
try:
    from google.cloud import storage
    from google.oauth2 import service_account
except Exception as e:
    FIREBASE_AVAILABLE = False

logger = logging.getLogger("firebase-saver")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("[%(levelname)s] %(asctime)s - %(message)s")
_h = logging.StreamHandler()
_h.setFormatter(_fmt)
if not logger.handlers:
    logger.addHandler(_h)


def _parse_gs_uri(uri: str):
    """
    Parse a gs://bucket/path style URI into (bucket, prefix).
    Examples:
      gs://my-bucket -> ("my-bucket", "")
      gs://my-bucket/some/prefix -> ("my-bucket", "some/prefix")
    """
    if not uri or not uri.startswith("gs://"):
        return None, None
    path = uri[len("gs://"):]  # strip scheme
    parts = path.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix


class FirebaseSaver:
    """
    Simple Firebase Storage (GCS) uploader with env-driven config.

    Env variables supported:
      - FIREBASE_GS_URI = "gs://skyledge-36b56.firebasestorage.app/skyledge/processed"
        (preferred: parses bucket & prefix)
      - FIREBASE_BUCKET = "skyledge-36b56.firebasestorage.app"
      - FIREBASE_PREFIX = "skyledge/processed"
      - FIREBASE_SERVICE_ACCOUNT_JSON = <entire service account JSON as a single env var>

    Notes:
      • This class never writes your JSON to disk unless absolutely needed.
      • Works on HF Spaces; provide credentials as a Secret.
      • Minimal permissions for uploads:
          roles/storage.objectCreator and roles/storage.objectViewer (or roles/storage.admin if easier).
    """

    def __init__(
        self,
        gs_uri: Optional[str] = None,
        bucket_name: Optional[str] = None,
        prefix: Optional[str] = None,
        creds_env: str = "FIREBASE_SERVICE_ACCOUNT_JSON",
    ):
        self.enabled = FIREBASE_AVAILABLE
        self.client = None
        self.bucket = None
        self.bucket_name = None
        self.prefix = None
        self.project_id = None
        self._creds_env = creds_env

        # Resolve location from env or args
        env_gs = gs_uri or os.getenv("FIREBASE_GS_URI")
        if env_gs:
            b, p = _parse_gs_uri(env_gs)
            if b:
                bucket_name = b
                # If caller provided explicit prefix parameter, prefer that
                prefix = p if prefix is None else prefix

        # Fall back to explicit envs
        self.bucket_name = bucket_name or os.getenv("FIREBASE_BUCKET") or "skyledge-36b56.firebasestorage.app"
        self.prefix = (prefix if prefix is not None else os.getenv("FIREBASE_PREFIX", "skyledge/processed")).strip("/")
        # Allow empty prefix
        if self.prefix == "":
            self.prefix = None

        if not self.enabled:
            logger.error("❌ google-cloud-storage not available. Add `google-cloud-storage` to requirements.")
            return

        try:
            creds_json = os.getenv(self._creds_env)
            if not creds_json:
                logger.error("❌ FIREBASE_SERVICE_ACCOUNT_JSON not set. Cannot authenticate to Firebase Storage.")
                self.enabled = False
                return

            # Load JSON directly from env (do not persist to disk)
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(info)
            self.project_id = info.get("project_id", None)

            self.client = storage.Client(credentials=creds, project=self.project_id)
            self.bucket = self.client.bucket(self.bucket_name)

            # Quick sanity check: not listing (which needs extra perms), but we can get a handle.
            _ = self.bucket.path
            logger.info(f"✅ FirebaseStorage ready | bucket={self.bucket_name} prefix={self.prefix or '(root)'}")

        except Exception as e:
            logger.error(f"❌ FirebaseSaver init failed: {e}")
            self.client = None
            self.bucket = None
            self.enabled = False

    # API parity-ish with Drive/Mongo helpers
    def is_available(self) -> bool:
        return bool(self.enabled and self.client and self.bucket)

    def _dest_path(self, filename: str, subdir: Optional[str] = None) -> str:
        parts = []
        if self.prefix:
            parts.append(self.prefix)
        if subdir:
            parts.append(subdir.strip("/"))
        parts.append(os.path.basename(filename))
        return "/".join(parts)

    def upload_file(
        self,
        local_path: str,
        dest_name: Optional[str] = None,
        subdir: Optional[str] = None,
        content_type: str = "text/csv"
    ) -> bool:
        """
        Upload a local file to gs://bucket/[prefix]/[subdir]/dest_name-or-basename
        """
        if not self.is_available():
            logger.warning("⚠️ FirebaseStorage unavailable; skipping upload.")
            return False
        try:
            fname = dest_name or os.path.basename(local_path)
            blob_path = self._dest_path(fname, subdir=subdir)
            blob = self.bucket.blob(blob_path)
            blob.cache_control = "no-store"
            blob.upload_from_filename(local_path, content_type=content_type)
            logger.info(f"✅ Uploaded to gs://{self.bucket_name}/{blob_path}")
            return True
        except Exception as e:
            logger.error(f"❌ Firebase upload failed: {e}")
            return False

    def upload_dataframe(
        self,
        df: pd.DataFrame,
        dest_name: str,
        subdir: Optional[str] = None,
        content_type: str = "text/csv"
    ) -> bool:
        """
        Upload a DataFrame as CSV directly (no need to persist file permanently).
        """
        if not self.is_available():
            logger.warning("⚠️ FirebaseStorage unavailable; skipping upload.")
            return False
        try:
            # Use in-memory buffer for minimal IO
            buf = io.StringIO()
            df.to_csv(buf, index=False)
            data = buf.getvalue().encode("utf-8")

            blob_path = self._dest_path(dest_name, subdir=subdir)
            blob = self.bucket.blob(blob_path)
            blob.cache_control = "no-store"
            blob.upload_from_string(data, content_type=content_type)
            logger.info(f"✅ Uploaded DataFrame to gs://{self.bucket_name}/{blob_path}")
            return True
        except Exception as e:
            logger.error(f"❌ Firebase DF upload failed: {e}")
            return False


# Convenience free functions (mirroring mongo_saver style)
def save_csv_to_firebase(csv_path: str, dest_name: Optional[str] = None, subdir: Optional[str] = None) -> bool:
    saver = FirebaseSaver()
    return saver.upload_file(csv_path, dest_name=dest_name, subdir=subdir)


def save_dataframe_to_firebase(df: pd.DataFrame, dest_name: str, subdir: Optional[str] = None) -> bool:
    saver = FirebaseSaver()
    return saver.upload_dataframe(df, dest_name=dest_name, subdir=subdir)
