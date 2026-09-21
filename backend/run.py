"""Frozen-build entry point (PyInstaller .exe). Also runnable: python backend/run.py"""
import os
import sys

if getattr(sys, "frozen", False):
    here = os.path.dirname(sys.executable)
    os.environ.setdefault("STORAGE_DIR", os.path.join(here, "data"))
    os.chdir(here)
    import webbrowser
    webbrowser.open("http://localhost:8000/")

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
