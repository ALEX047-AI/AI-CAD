@echo off
cd /d "%~dp0"
python run.py
if errorlevel 1 (
 echo.
 echo Launch failed. Check README.md and Python environment.
 pause
)
