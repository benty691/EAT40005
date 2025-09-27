#!/usr/bin/env python3
"""
Script to reorganize existing models in HF repo to versioned structure.
This will move the current 3 .pkl files from root to v1.0 folder.
"""

import os
import sys
import tempfile
import json
from pathlib import Path

# Load environment variables from .env file
def load_env():
    """Load environment variables from .env file"""
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value
        print(f"✅ Loaded environment variables from {env_path}")
    else:
        print("⚠️ No .env file found")

# Load environment variables
load_env()

# Add train directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'train'))

def main():
    """Main function to reorganize models"""
    print("🔄 Reorganizing models in Hugging Face repository...")
    print("=" * 60)
    
    # Check if HF_TOKEN is set
    if not os.getenv("HF_TOKEN"):
        print("❌ Error: HF_TOKEN environment variable not set")
        print("Please set your Hugging Face token:")
        print("export HF_TOKEN=your_token_here")
        return 1
    
    # Check if we're in the right directory
    if not os.path.exists("train/rlhf.py"):
        print("❌ Error: Please run this script from the OBD_Logger root directory")
        return 1
    
    try:
        # Import and run the reorganization
        from train.move_models_to_v1 import move_models_to_v1
        
        print("📥 Starting model reorganization...")
        move_models_to_v1()
        
        print("\n✅ Model reorganization completed successfully!")
        print("📁 Your models are now organized in the v1.0 folder")
        print("🔄 Future RLHF training will create v1.1, v1.2, etc.")
        print("\nNext steps:")
        print("1. Verify the models are in the v1.0 folder on Hugging Face")
        print("2. Test the RLHF training with: curl -X POST 'http://localhost:8000/rlhf/train'")
        
        return 0
        
    except Exception as e:
        print(f"❌ Reorganization failed: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure HF_TOKEN is set correctly")
        print("2. Check that you have write access to the repository")
        print("3. Verify the repository name is correct")
        return 1

if __name__ == "__main__":
    exit(main())
