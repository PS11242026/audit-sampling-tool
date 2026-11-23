@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Run:  python -m venv .venv ^&^& .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo Starting the Kestrel Transmission Audit Tool - your browser will open at http://localhost:8501
".venv\Scripts\python.exe" -m streamlit run app.py --server.address localhost
pause
