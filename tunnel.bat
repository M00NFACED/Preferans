@echo off
REM Публичные адреса для игры с друзьями: несколько бесплатных туннелей сразу,
REM без регистрации. Сервер преферанса должен быть уже запущен (run.bat).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Нужно сначала запустить run.bat, чтобы создалось окружение.
  pause
  exit /b 1
)

call .venv\Scripts\activate.bat
python tools\tunnels.py %*
