@echo off
setlocal

cd /d "%~dp0"

echo Starting backend (http://127.0.0.1:8001) and frontend (http://localhost:4200)...
start "MC Backend" cmd /k "%~dp0backend\start.bat"
start "MC Frontend" cmd /k "%~dp0frontend\start.bat"

endlocal
