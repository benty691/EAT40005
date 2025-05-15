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

# ── Pre-mount GDrive (no-op if creds not found) ──
COPY --chown=user mount_drive.py .
RUN python mount_drive.py || true

# ── Copy application source ──
COPY --chown=user . .

# ── Make sure cache/log folders are owned by the user ──
RUN mkdir -p $HOME/app/logs $HOME/app/cache $HOME/app/cache/obd_data

# ── Default port ──
EXPOSE 7860

# ── Start app ──
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
