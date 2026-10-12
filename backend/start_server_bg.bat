@echo off
cd /d E:\OpenIIT Data\backend
start /B cmd /k "cd E:\OpenIIT Data\backend && .venv311\Scripts\activate && python -m app.main"
timeout /t 3 >NUL