# start_server.py
# Enhanced server with favicon and better error handling

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import os
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import your backend app
try:
    from backend.main import app as backend_app
    logger.info("✅ Backend app imported successfully")
except Exception as e:
    logger.error(f"❌ Failed to import backend app: {e}")
    raise

# Create the main app that will serve everything
app = FastAPI(title="Expense Tracker 3.0 - Full Stack")

# Enhanced CORS middleware for your Proxmox setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000", 
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://192.168.10.160:8680",
        "http://192.168.10.160:8000",
        "*"  # For development only
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 💰 Favicon endpoint - serving the money emoji as favicon
@app.get("/favicon.ico")
async def favicon():
    """Serve 💰 emoji as favicon."""
    # Create SVG favicon with money emoji
    svg_content = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
        <text y="80" font-size="80">💰</text>
    </svg>'''
    
    return Response(
        content=svg_content,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=31536000",  # Cache for 1 year
            "Content-Type": "image/svg+xml"
        }
    )

# Mount the backend API under /api prefix
app.mount("/api", backend_app)

# Serve static files (CSS, JS, images) if you have them
frontend_dir = Path("frontend")
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory="frontend"), name="static")

# Debug endpoint to check router status
@app.get("/debug/routers")
async def debug_routers():
    """Debug endpoint to check router status."""
    try:
        from backend.main import ROUTERS_AVAILABLE
        from backend import models
        
        # Check database
        try:
            models.create_tables()
            db_status = "✅ Database tables created"
        except Exception as e:
            db_status = f"❌ Database error: {e}"
        
        return {
            "routers_available": ROUTERS_AVAILABLE,
            "database_status": db_status,
            "backend_routes": [{"path": route.path, "methods": route.methods} for route in backend_app.routes if hasattr(route, 'path')],
            "frontend_exists": frontend_dir.exists(),
            "api_mounted": True
        }
    except Exception as e:
        return {"error": str(e)}

# Enhanced health check
@app.get("/health")
async def health_check():
    """Enhanced health check with detailed status."""
    try:
        from backend.main import ROUTERS_AVAILABLE
        return {
            "status": "healthy",
            "version": "3.0.0",
            "routers_loaded": ROUTERS_AVAILABLE,
            "timestamp": "2025-07-10",
            "environment": "development",
            "database": "sqlite"
        }
    except Exception as e:
        return {
            "status": "degraded", 
            "error": str(e),
            "version": "3.0.0"
        }

# Serve the main HTML file at the root
@app.get("/")
async def serve_frontend():
    """Serve the main frontend HTML file."""
    html_file = Path("frontend/index.html")
    if html_file.exists():
        return FileResponse(html_file)
    else:
        # Enhanced fallback with better instructions
        return {
            "message": "💰 Expense Tracker 3.0 - Frontend file not found",
            "instructions": "Create frontend/index.html with the new UI",
            "backend_api": "/api/docs",
            "debug_endpoint": "/debug/routers",
            "health_check": "/health",
            "features": [
                "ML-powered categorization",
                "Smart duplicate detection", 
                "Real-time progress tracking",
                "Advanced analytics",
                "User-defined categories",
                "💰 Favicon support"
            ],
            "development_urls": {
                "frontend": "http://192.168.10.160:8680/proxy/8000/",
                "api_docs": "http://192.168.10.160:8680/proxy/8000/api/docs",
                "debug": "http://192.168.10.160:8680/proxy/8000/debug/routers"
            }
        }

if __name__ == "__main__":
    print("🚀 Starting Expense Tracker 3.0...")
    print("💰 Favicon: Enabled")
    print("📱 Frontend: http://localhost:8000/")
    print("🔧 Backend API: http://localhost:8000/api/")
    print("📚 API Docs: http://localhost:8000/api/docs")
    print("🐛 Debug: http://localhost:8000/debug/routers")
    print("🌐 Proxmox URL: http://192.168.10.160:8680/proxy/8000/")
    
    uvicorn.run(
        "start_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )