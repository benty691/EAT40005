# Use official Python slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create writable cache directory for OBD data
ENV OBD_CACHE=/.cache/obd_data
RUN mkdir -p ${OBD_CACHE}

# OPTIONAL: move it to ./ relative to /app if not root-level
ENV OBD_CACHE=./.cache/obd_data
RUN mkdir -p .cache/obd_data


# Expose default Hugging Face Spaces port
EXPOSE 7860

# Start the FastAPI app with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
