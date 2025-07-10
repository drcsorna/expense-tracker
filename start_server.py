#!/usr/bin/env python3
"""
Simple startup script for the Expense Tracker 2.0
Handles database initialization and server startup
"""

import uvicorn
import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Import after path setup
from backend.models import engine, Base

def create_tables():
    """Create database tables if they don't exist."""
    print("🔧 Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ Database tables created successfully!")

def main():
    """Main startup function."""
    print("🚀 Starting Expense Tracker 2.0...")
    
    # Create database tables
    create_tables()
    
    # Get configuration from environment
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("DEBUG", "true").lower() == "true"
    
    print(f"🌐 Server will start at http://{host}:{port}")
    print(f"📊 Admin interface: http://{host}:{port}/docs")
    print(f"🎯 Application: http://{host}:{port}/app")
    
    # Start the server
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["backend"] if reload else None,
        log_level="info"
    )

if __name__ == "__main__":
    main()