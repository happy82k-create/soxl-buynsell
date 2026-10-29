@echo off
chcp 65001 > nul
cd /d "%~dp0"
netstat -ano | findstr ":8502" | findstr "LISTENING" > nul
if errorlevel 1 (
  start "SOXL" ".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port 8502 --browser.gatherUsageStats false
  timeout /t 3 /nobreak > nul
)
start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --new-window http://127.0.0.1:8502
