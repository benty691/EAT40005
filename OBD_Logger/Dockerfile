FROM python:3.11-slim

# ── Create and switch to non-root user ──
RUN useradd -m -u 1000 user
USER user

# ── Set home and working directory ──
ENV HOME=/home/user
WORKDIR $HOME/app

# ── Copy requirements and install ──
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Create writeable cache/log directories ──
RUN mkdir -p $HOME/app/cache $HOME/app/logs $HOME/app/outputs

# ── Copy application source ──
COPY --chown=user . .

# ── Default FastAPI port ──
EXPOSE 7860

# ── Run app ──
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
