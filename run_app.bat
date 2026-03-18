@echo off
start "Backend" /D "%~dp0backend" cmd /k "call .venv\Scripts\activate && uvicorn app.main:app --reload"
start "Frontend" /D "%~dp0frontend" cmd /k "npm run dev"