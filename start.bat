@echo off
cd /d "%~dp0"
echo Starting LLM Discussion...
start /min python app.py

:waitloop
timeout /t 1 /nobreak >nul
curl -s http://localhost:5000 >nul 2>&1
if errorlevel 1 goto waitloop

start http://localhost:5000
exit
