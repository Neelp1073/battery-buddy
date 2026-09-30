"""Shared settings for the Mac scripts, read from environment variables.

    BACKEND_URL  Base URL of the Flask backend (default http://127.0.0.1:5001)
    DEVICE_ID    Name this Mac reports as     (default neels-macbook)
"""
import os

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:5001").rstrip("/")
DEVICE_ID = os.environ.get("DEVICE_ID", "neels-macbook")
