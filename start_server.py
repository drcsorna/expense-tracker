# start_server.py
# Enhanced server with clean static file structure

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

# Mount the backend API under /api prefix
app.mount("/api", backend_app)

# Serve static files - 2025 standard approach
static_dir = Path("static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")
    logger.info("✅ Static files mounted: static/ → /static/")
else:
    logger.warning("⚠️ Static directory not found")

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
            "static_exists": static_dir.exists(),
            "api_mounted": True,
            "static_files_mounted": static_dir.exists(),
            "favicon_method": "HTML data URI",
            "static_files_debug": {
                "css_exists": (static_dir / "css" / "styles.css").exists(),
                "js_app_exists": (static_dir / "js" / "app.js").exists(),
                "js_auth_exists": (static_dir / "js" / "auth.js").exists(),
                "js_uploads_exists": (static_dir / "js" / "uploads.js").exists(),
                "index_html_exists": (static_dir / "index.html").exists()
            }
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
            "timestamp": "2025-07-11",
            "environment": "development",
            "database": "sqlite",
            "static_mounted": static_dir.exists(),
            "favicon_method": "HTML data URI"
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
    """Serve the main HTML file."""
    html_file = static_dir / "index.html"
    if html_file.exists():
        logger.info("✅ Serving static/index.html")
        return FileResponse(html_file)
    else:
        logger.error("❌ HTML file not found: static/index.html")
        return {
            "message": "💰 Expense Tracker 3.0 - HTML file not found",
            "instructions": "Create static/index.html",
            "backend_api": "/api/docs",
            "debug_endpoint": "/debug/routers",
            "health_check": "/health",
            "error": "HTML file missing"
        }

if __name__ == "__main__":
    print("🚀 Starting Expense Tracker 3.0...")
    print("💰 Favicon: ✅ HTML data URI")
    print("📁 Static Files: ✅ static/ → /static/")
    print("🔧 Auth Format: ✅ JSON-based login")
    print("📱 Frontend: http://localhost:8000/")
    print("🔧 Backend API: http://localhost:8000/api/")
    print("📚 API Docs: http://localhost:8000/api/docs")
    print("🐛 Debug: http://localhost:8000/debug/routers")
    print("🏥 Health: http://localhost:8000/health")
    print("🌐 Proxmox URL: http://192.168.10.160:8680/proxy/8000/")
    print("\n🎯 2025 STRUCTURE:")
    print("   • Clean static/ directory structure")
    print("   • URL paths match directory names")
    print("   • Industry standard approach")
    
    uvicorn.run(
        "start_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )