@echo off
cd /d E:\OpenIIT Data\backend
call .venv311\Scripts\activate
curl -X POST http://localhost:8000/api/geocode -H "Content-Type: application/json" -d "%1"