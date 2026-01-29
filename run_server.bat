@echo off
cd /d "C:\whatsapp_service"
 
echo Activating virtual environment...
call .venv\Scripts\activate
 
echo Starting FastAPI server...
python -m app.main