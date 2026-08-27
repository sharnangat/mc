@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment with Python 3.13...
    py -3.13 -m venv .venv
    if errorlevel 1 (
        echo Failed to create venv. Is Python 3.13 installed? Try: py -0p
        exit /b 1
    )
    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --no-cache-dir -r requirements.txt
)

if not exist ".env" (
    echo Creating .env from .env.example...
    copy ".env.example" ".env" >nul
)

echo Starting API at http://127.0.0.1:8000  (docs at /docs)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

endlocal
