@echo off
cd /d "%~dp0"
echo Starting LLM Discussion...
start /min python app.py
timeout /t 2 /nobreak >nul
start http://localhost:5000
exit
