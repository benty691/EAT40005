# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure logs folder exists and is writable
RUN mkdir -p /app/logs /app/logs/cleaned

# Expose default Hugging Face Spaces port
EXPOSE 7860

# Start the FastAPI app with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
