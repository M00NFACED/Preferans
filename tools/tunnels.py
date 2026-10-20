"""Публичные адреса для игры с друзьями — несколько туннелей сразу.

Запуск:  python tools/tunnels.py [--port 8000]

Каждый туннель сам переподключается, если связь отвалилась. Если провайдер
выдаёт новый адрес — печатаем его крупно: игроки просто открывают новую
ссылку, комната и счёт сохраняются (клиент сам переподключится к той же партии).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"https://[a-zA-Z0-9._-]+")

# по каждому провайдеру берём только его собственные домены
ACCEPT = {
    "localhost.run": re.compile(r"https://[a-z0-9-]+\.lhr\.life$"),
    "pinggy": re.compile(r"https://[a-z0-9-]+\.(free\.pinggy\.net|run\.pinggy-free\.link)$"),
    "cloudflared": re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com$"),
}

HINTS = {
    "pinggy": "pinggy режет анонимные туннели при частых переподключениях — попробуйте позже",
    "cloudflared": "адреса Cloudflare в РФ недоступны без VPN",
    "localhost.run": "если адрес перестал открываться — он сменится, ждите новый",
}

STATE: dict[str, dict] = {}
LOCK = threading.Lock()
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def say(text: str) -> None:
    print(text, flush=True)


def cleaner(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)


def pick(name: str, text: str) -> list[str]:
    pattern = ACCEPT.get(name)
    if pattern is None:
        return []
    return [url for url in URL_RE.findall(cleaner(text)) if pattern.match(url)]


def announce(name: str, url: str) -> None:
    with LOCK:
        entry = STATE.setdefault(name, {"urls": [], "seen": {}, "status": ""})
        if url in entry["urls"]:
            return
        old = entry["urls"][-1] if entry["urls"] else None
        entry["urls"].append(url)
        if old:
            say("")
            say(f"{YELLOW}{BOLD}  ⚠  {name}: адрес сменился!{RESET}")
            say(f"     старый: {old}  (больше не работает)")
            say(f"     новый:  {GREEN}{BOLD}{url}{RESET}")
            say("     отправьте друзьям новую ссылку — партия продолжится с того же места.")
            say("")
        else:
            say(f"  [{name}] {url}")


def report_failure(name: str, reason: str) -> None:
    with LOCK:
        entry = STATE.setdefault(name, {"urls": [], "seen": {}, "status": ""})
        if entry.get("status") != reason:
            entry["status"] = reason
            say(f"  [{name}] не подключился: {reason}")


def run_cloudflared(port: int) -> None:
    exe = ROOT / "tools" / "cloudflared.exe"
    if not exe.exists():
        report_failure("cloudflared", "нет бинарника в tools/")
        return
    while True:
        cmd = [str(exe), "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate", "--protocol", "http2"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace")
        except Exception as exc:
            report_failure("cloudflared", str(exc))
            return
        for line in proc.stderr:
            for url in pick("cloudflared", line):
                announce("cloudflared", url)
        proc.wait()
        say("  [cloudflared] переподключаюсь...")
        time.sleep(3)


def run_ssh(name: str, args: list[str]) -> None:
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ServerAliveInterval=20",
           "-o", "ServerAliveCountMax=100", "-o", "TCPKeepAlive=yes",
           "-o", "ConnectTimeout=25", "-o", "ExitOnForwardFailure=yes"] + args
    attempt = 0
    while True:
        attempt += 1
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    encoding="utf-8", errors="replace")
        except FileNotFoundError:
            report_failure(name, "нет ssh в системе")
            return
        reason = "соединение не установлено"
        for line in proc.stdout:
            for url in pick(name, line):
                announce(name, url)
            clean = cleaner(line).strip()
            if "timed out" in clean.lower() or "Connection refused" in clean:
                reason = "сервис не отвечает (таймаут)"
            elif "Permission denied" in clean:
                reason = "отказано в доступе"
        proc.wait()
        if attempt == 1 and not STATE.get(name, {}).get("urls"):
            report_failure(name, reason)
        say(f"  [{name}] переподключаюсь (попытка {attempt + 1})…")
        time.sleep(3)


def check_urls() -> None:
    """Раз в 15 секунд проверяем, какие адреса реально отвечают."""
    misses: dict[str, int] = {}
    while True:
        time.sleep(15)
        with LOCK:
            targets = [(name, list(entry.get("urls", []))) for name, entry in STATE.items()]
        for name, urls in targets:
            for url in urls:
                state = "ok"
                for _attempt in range(2):
                    try:
                        request = urllib.request.Request(url + "/api/health",
                                                         headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(request, timeout=20) as response:
                            body = response.read(40).decode("utf-8", "replace")
                        state = "ok" if body.startswith("{") else "заглушка (кнопка Enter site)"
                        break
                    except urllib.error.HTTPError as exc:
                        state = f"HTTP {exc.code}"
                        break
                    except Exception:
                        state = "не отвечает"
                key = f"{name} {url}"
                if state != "ok":
                    misses[key] = misses.get(key, 0) + 1
                    if misses[key] < 2:
                        state = "нестабильно"
                else:
                    misses[key] = 0
                with LOCK:
                    entry = STATE.setdefault(name, {"urls": [], "seen": {}, "status": ""})
                    seen = entry.setdefault("seen", {})
                    if seen.get(url) != state:
                        seen[url] = state
                        say(f"  [{name}] {url} — {state}")
                        if state not in ("ok", "нестабильно"):
                            say(f"           подсказка: {HINTS.get(name, '')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--only", default="", help="только этот провайдер (localhost.run|pinggy|cloudflared)")
    args = parser.parse_args()

    say("")
    say("  Публичные адреса преферанса (сервер должен быть запущен).")
    say("  Проверяйте адреса с телефона БЕЗ VPN и отправляйте друзьям рабочий.")
    say("  Если адрес сменится — придёт уведомление, партия продолжится по новой ссылке.")
    say("  Остановить: Ctrl+C")
    say("")

    providers = []
    if not args.only or args.only == "localhost.run":
        providers.append(("localhost.run", ["-R", f"80:localhost:{args.port}", "nokey@localhost.run"]))
    if not args.only or args.only == "pinggy":
        providers.append(("pinggy", ["-p", "443", "-R0:localhost:" + str(args.port), "a.pinggy.io"]))
    if not args.only or args.only == "cloudflared":
        providers.append(("cloudflared", None))

    for name, ssh_args in providers:
        if ssh_args is None:
            threading.Thread(target=run_cloudflared, args=(args.port,), daemon=True).start()
        else:
            threading.Thread(target=run_ssh, args=(name, ssh_args), daemon=True).start()
    threading.Thread(target=check_urls, daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        say("\n  Останавливаю туннели...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
