---
title: OBD Logger
emoji: 🚗
colorFrom: gray
colorTo: purple
sdk: docker
pinned: false
license: apache-2.0
short_description: OBD-logging FastAPI server with data processing pipelines
---

# OBD Logger

A comprehensive OBD-II data logging and processing system built with FastAPI, featuring advanced data cleaning, Google Drive integration, and MongoDB storage capabilities.

## Features

- **Real-time OBD-II Data Ingestion**: Stream and process OBD sensor data in real-time
- **Advanced Data Cleaning**: Intelligent gap detection, KNN imputation, and outlier handling
- **Dual Storage Options**: 
  - Google Drive integration for CSV storage
  - MongoDB Atlas for structured data storage and querying
- **Data Visualization**: Automatic generation of correlation heatmaps and trend plots
- **RESTful API**: Comprehensive endpoints for data management and retrieval
- **Web Dashboard**: User-friendly interface for monitoring and control

## Architecture

The application is structured into modular components:

- **`app.py`**: Main FastAPI application with data processing pipeline
- **`drive_saver.py`**: Google Drive operations and file management
- **`mongo_saver.py`**: MongoDB operations and data persistence
- **`OBD/`**: OBD-specific modules for data analysis and logging

## Quick Start

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set Environment Variables**:
   - `GDRIVE_CREDENTIALS_JSON`: Google Service Account credentials
   - `MONGO_URI`: MongoDB Atlas connection string

3. **Run the Application**:
   ```bash
   uvicorn app:app --reload
   ```

4. **Access the Dashboard**:
   - Web UI: `http://localhost:8000/ui`
   - API Docs: `http://localhost:8000/docs`

## Data Processing Pipeline

1. **Ingestion**: Real-time streaming or bulk CSV upload
2. **Cleaning**: Automatic gap detection and KNN imputation
3. **Feature Engineering**: Derived metrics and sensor combinations
4. **Storage**: Simultaneous save to Google Drive and MongoDB
5. **Visualization**: Correlation analysis and trend plots

## API Endpoints

### Data Ingestion
- `POST /ingest`: Stream OBD data
- `POST /upload-csv/`: Bulk CSV upload

### Data Retrieval
- `GET /download/{filename}`: Download cleaned CSV
- `GET /events`: Get processing status

### MongoDB Operations
- `GET /mongo/status`: Check MongoDB connection
- `GET /mongo/sessions`: Get data session summaries
- `GET /mongo/query`: Query data with filters
- `POST /mongo/save-csv`: Direct CSV to MongoDB

## Storage Options

### Google Drive
- Automatic CSV upload after processing
- Configurable folder destinations
- Service account authentication

### MongoDB Atlas
- Structured JSON storage
- Advanced querying capabilities
- Session-based organization
- Automatic indexing for performance

## Documentation

- **MongoDB Setup**: See `MONGODB_SETUP.md` for detailed configuration
- **API Reference**: Interactive docs at `/docs` endpoint
- **Code Structure**: Modular design for easy maintenance

## Development

The codebase follows clean architecture principles:
- Separation of concerns between storage, processing, and API layers
- Comprehensive error handling and logging
- Type hints and documentation
- Graceful fallbacks for service unavailability

## License

Apache 2.0 License
