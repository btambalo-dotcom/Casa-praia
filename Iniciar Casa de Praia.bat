@echo off
cd /d "%~dp0"

IF EXIST venv (
    call venv\Scripts\activate
)

pip install -r requirements.txt

python app.py

echo.
echo Se aparecer erro acima, tire print e envie para correção.
pause
