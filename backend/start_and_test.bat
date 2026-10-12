@echo off
cd /d E:\OpenIIT Data\backend
call .venv311\Scripts\Activate.bat
timeout /t 3 >nul
echo Starting server...
python -m app.main > server.log 2>&1 &
timeout /t 8 >nul
echo Testing /api/real/towns...
curl http://localhost:8000/api/real/towns