# start_server.py
# Serve both frontend HTML and backend API together

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
from pathlib import Path

# Import your backend app
from backend.main import app as backend_app

# Create the main app that will serve everything
app = FastAPI(title="Expense Tracker 3.0 - Full Stack")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the backend API under /api prefix
app.mount("/api", backend_app)

# Serve static files (CSS, JS, images) if you have them
frontend_dir = Path("frontend")
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Serve the main HTML file at the root
@app.get("/")
async def serve_frontend():
    """Serve the main frontend HTML file."""
    html_file = Path("frontend/index.html")
    if html_file.exists():
        return FileResponse(html_file)
    else:
        # Fallback if no frontend file exists yet
        return {
            "message": "Expense Tracker 3.0 - Frontend file not found",
            "instructions": "Create frontend/index.html with the new UI",
            "backend_api": "/api/docs",
            "features": [
                "ML-powered categorization",
                "Smart duplicate detection", 
                "Real-time progress tracking",
                "Advanced analytics",
                "User-defined categories"
            ]
        }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "3.0.0"}

if __name__ == "__main__":
    print("🚀 Starting Expense Tracker 3.0...")
    print("📱 Frontend: http://localhost:8000/")
    print("🔧 Backend API: http://localhost:8000/api/")
    print("📚 API Docs: http://localhost:8000/api/docs")
    
    uvicorn.run(
        "start_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )