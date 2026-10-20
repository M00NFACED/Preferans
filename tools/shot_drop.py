"""Скриншот этапа сноса: прикуп раскрыт, у заказчика 10 карт."""

import asyncio
import base64
import json
import subprocess
import time
from pathlib import Path

import requests
import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9777
OUT = Path("shots_drop")
OUT.mkdir(exist_ok=True)
URL = "http://127.0.0.1:8090"


async def main():
    profile = Path.home() / "AppData" / "Local" / "Temp" / "pref_chrome_drop"
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
        "--window-size=1500,950", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    target = None
    for _ in range(40):
        time.sleep(0.5)
        try:
            items = requests.get(f"http://127.0.0.1:{PORT}/json", timeout=3).json()
            pages = [t for t in items if t.get("type") == "page"]
            if pages:
                target = pages[0]
                break
        except Exception:
            continue
    if not target:
        print("нет chrome")
        proc.terminate()
        return

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=40 * 1024 * 1024) as ws:
        n = {"i": 0}

        async def call(method, params=None):
            n["i"] += 1
            mid = n["i"]
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == mid:
                    return m.get("result", {})

        async def ev(expr):
            r = await call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
            if r.get("exceptionDetails"):
                return "EXC " + json.dumps(r["exceptionDetails"])[:200]
            return r.get("result", {}).get("value")

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Emulation.setDeviceMetricsOverride",
                   {"width": 1500, "height": 950, "deviceScaleFactor": 1, "mobile": False})
        await call("Page.navigate", {"url": URL})
        for _ in range(60):
            if await ev("!!window.__pref"):
                break
            await asyncio.sleep(0.3)
        await asyncio.sleep(0.8)
        await ev("document.getElementById('btn-quick').click()")
        await asyncio.sleep(2.0)
        print("экран:", await ev("window.__pref.screen"))
        print("комната:", await ev("JSON.stringify(window.__pref.room)"))
        print("тост:", await ev("document.getElementById('toast').textContent"))

        # ждём, пока фаза станет «drop» (сброс), подыгрывая за человека
        phase = ""
        for _ in range(160):
            await asyncio.sleep(0.4)
            await ev("""(() => {
                const s = window.__pref, g = s && s.game;
                if (!g || g.turn !== s.seat) return;
                const byText = t => Array.from(document.querySelectorAll('#actions .btn'))
                    .find(b => b.textContent.trim() === t);
                if (g.phase === 'auction') {
                  const o = byText('Открыть карты'); if (o) { o.click(); return; }
                  const p = byText('Пас'); if (p) { p.click(); return; }
                }
            })()""")
            phase = await ev(
                "(window.__pref && window.__pref.game) ? window.__pref.game.phase : ''")
            if phase == "drop":
                break
        print("фаза:", phase)
        print("карт в руке:", await ev(
            "(window.__pref && window.__pref.game) ? (window.__pref.game.hand||[]).length : -1"))
        print("прикуп на столе:", await ev(
            "document.querySelectorAll('#talon .card').length"))
        data = await call("Page.captureScreenshot", {"format": "png"})
        (OUT / "drop.png").write_bytes(base64.b64decode(data["data"]))
        print("сохранено shots_drop/drop.png")
    proc.terminate()


asyncio.run(main())
