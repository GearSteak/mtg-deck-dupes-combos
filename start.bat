@echo off
cd /d "%~dp0"
echo Starting Deck Dupes ^& Combos at http://localhost:8080
echo Close this window to stop the server.
echo.
python server.py
if errorlevel 1 (
  echo.
  echo Python not found. Trying py launcher...
  py server.py
)
pause
