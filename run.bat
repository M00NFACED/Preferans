@echo off
REM Запуск преферанса локально. Открыть http://127.0.0.1:8000
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Установите Python 3.10+ и повторите.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Создаю виртуальное окружение...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

python -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Устанавливаю зависимости...
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
)

echo.
echo Преферанс запущен: http://127.0.0.1:8000
echo Остановить: Ctrl+C
echo.

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 75
