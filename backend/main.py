"""CLI entry point — launches the FastAPI application via uvicorn.

This is the outermost layer — it simply starts the server.
All application wiring happens in api/app.py (Composition Root).
"""

from presentation.app import create_app

# Create the app instance (used by uvicorn for import string)
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
