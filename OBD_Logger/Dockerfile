FROM python:3.11-slim

# ── Create and switch to non-root user ──
RUN useradd -m -u 1000 user
USER user

# ── Set environment and working directory ──
ENV HOME=/home/user
WORKDIR $HOME/app

# ── Upgrade pip and install dependencies ──
COPY --chown=user requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Install specific versions for UL model inference
RUN pip install --no-cache-dir huggingface_hub==0.25.2 xgboost==2.0.3 joblib

# ── Pre-mount GDrive (no-op if creds not found) ──
COPY --chown=user utils/mount_drive.py .
RUN python mount_drive.py || true

# ── Copy application source ──
COPY --chown=user . .

# ── Create required folders ──
RUN mkdir -p $HOME/app/logs \
    $HOME/app/cache \
    $HOME/app/cache/obd_data \
    $HOME/app/cache/obd_data/plots \
    $HOME/app/models/ul

# ── Environment variables for HuggingFace model ──
ENV MODEL_DIR=$HOME/app/models/ul
ENV HF_MODEL_REPO=BinKhoaLe1812/Driver_Behavior_OBD

# ── Download UL model files on build ──
RUN python utils/download.py

# ── Default port ──
EXPOSE 7860

# ── Start app ──
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
