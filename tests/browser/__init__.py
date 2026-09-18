"""Optional browser integration tests."""
import os


def browser_options():
    """Use installed Chrome on Windows and Playwright Chromium on Linux."""
    return {"headless": True, "executable_path": r"C:\Program Files\Google\Chrome\Application\chrome.exe" if os.name == "nt" else None}
