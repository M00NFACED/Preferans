#!/usr/bin/env bash
# Запуск преферанса локально. Открыть http://127.0.0.1:8000
set -e
cd "$(dirname "$0")"

command -v python3 >/dev/null 2>&1 || { echo "Нужен Python 3.10+"; exit 1; }

if [ ! -d ".venv" ]; then
  echo "Создаю виртуальное окружение..."
  python3 -m venv .venv
fi
source .venv/bin/activate

python -c "import fastapi, uvicorn" >/dev/null 2>&1 || {
  echo "Устанавливаю зависимости..."
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
}

echo "Преферанс запущен: http://127.0.0.1:8000"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 75
