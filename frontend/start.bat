@echo off
setlocal

cd /d "%~dp0"

if not exist "node_modules" (
    echo Installing dependencies...
    call npm install
    if errorlevel 1 (
        echo npm install failed.
        exit /b 1
    )
)

echo Starting Angular dev server at http://localhost:4200
call npx ng serve --port 4200

endlocal
