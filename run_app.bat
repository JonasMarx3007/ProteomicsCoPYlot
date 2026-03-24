@echo off
start "Backend" /D "%~dp0backend" cmd /k ""%~dp0backend\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
start "Frontend" /D "%~dp0frontend" cmd /k "npm run dev"
timeout /t 3 /nobreak >nul
start "" "http://localhost:5173"
