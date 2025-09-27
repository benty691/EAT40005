# Git Workflow for OBD Logger

This document explains how to properly manage the OBD Logger repository with both Hugging Face Space and GitHub.

## 🏗️ Repository Structure

- **Hugging Face Space**: `https://huggingface.co/spaces/BinKhoaLe1812/OBD_Logger`
- **GitHub Repository**: `https://github.com/benty691/EAT40005.git` (obd-logger branch)

## 📋 Setup (One-time)

The repository is already configured with the correct remotes:

```bash
# Check remotes
git remote -v

# Should show:
# hf      https://huggingface.co/spaces/BinKhoaLe1812/OBD_Logger (fetch)
# hf      https://huggingface.co/spaces/BinKhoaLe1812/OBD_Logger (push)
# origin  https://github.com/benty691/EAT40005.git (fetch)
# origin  https://github.com/benty691/EAT40005.git (push)
```

## 🚀 Daily Workflow

### Option 1: Using the Script (Recommended)

```bash
# Make changes to your code
# ... edit files ...

# Stage and commit changes
git add .
git commit -m "Your commit message"

# Push to Hugging Face Space
./push_workflow.sh hf

# Push to GitHub
./push_workflow.sh github

# Or push to both at once
./push_workflow.sh both
```

### Option 2: Manual Commands

```bash
# Make changes to your code
# ... edit files ...

# Stage and commit changes
git add .
git commit -m "Your commit message"

# Push to Hugging Face Space (for deployment)
git push hf main

# Push to GitHub (for backup/collaboration)
git push origin obd-logger
```

## 📁 Directory Structure

```
OBD_Logger/
├── app.py                 # FastAPI application
├── Dockerfile            # Docker configuration
├── requirements.txt      # Python dependencies
├── train/                # RLHF training system
│   ├── rlhf.py          # Main RLHF trainer
│   ├── loader.py        # Data loader
│   └── saver.py         # Model saver
├── utils/                # Utilities
│   └── download.py      # Model downloader
├── data/                 # Data handlers
├── static/              # Web interface
└── push_workflow.sh     # Push workflow script
```

## 🔄 Workflow Summary

1. **Development**: Make changes in the OBD_Logger directory
2. **Commit**: `git add . && git commit -m "message"`
3. **Deploy**: `git push hf main` (pushes to Hugging Face Space)
4. **Backup**: `git push origin obd-logger` (pushes to GitHub)

## 🛡️ Security Features

- ✅ No hardcoded tokens in code
- ✅ Models download at runtime
- ✅ Environment variables loaded from `.env`
- ✅ Large files excluded from repository
- ✅ Clean git history

## 📊 Monitoring

- **Hugging Face Space**: Check deployment status at the HF Space URL
- **Model Status**: Use `GET /models/status` endpoint to check if models are loaded
- **Health Check**: Use `GET /health` endpoint for basic health check

## 🚨 Troubleshooting

### Large File Errors
If you get large file errors:
```bash
# Check for large files
find . -type f -size +10M

# Remove large files from git history
git filter-branch --tree-filter 'rm -f path/to/large/file' HEAD
```

### Push Failures
If push fails:
```bash
# Check remote configuration
git remote -v

# Force push if needed (be careful!)
git push hf main --force
```

## 📝 Notes

- The OBD_Logger directory is now a clean, independent git repository
- No large files in the git history
- Models are downloaded at runtime, not during build
- Both Hugging Face Space and GitHub are properly configured
