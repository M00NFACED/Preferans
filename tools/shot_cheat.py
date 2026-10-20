"""Скриншоты шпаргалки и крупного экрана."""

import asyncio
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9555
OUT = Path("shots3")
URL = "http://127.0.0.1:8080"


async def main():
    OUT.mkdir(exist_ok=True)
    profile = Path.home() / "AppData" / "Local" / "Temp" / "pref_chrome_s3"
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
        "--window-size=1920,1080", "about:blank",
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

        async def shot(name):
            await asyncio.sleep(0.5)
            data = await call("Page.captureScreenshot", {"format": "png"})
            (OUT / name).write_bytes(base64.b64decode(data["data"]))
            print("сохранено", name)

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Emulation.setDeviceMetricsOverride",
                   {"width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False})
        await call("Page.navigate", {"url": URL})
        for _ in range(40):
            if await ev("!!document.getElementById('btn-create')"):
                break
            await asyncio.sleep(0.4)
        await asyncio.sleep(0.8)

        # шпаргалка
        await ev("document.getElementById('btn-cheat').click()")
        await asyncio.sleep(0.8)
        await shot("cheat-hand.png")
        # отмечаем карты: туз, король, дама пик + мелочь
        await ev("""(() => {
          const grid = document.querySelectorAll('.cheat-grid .card');
          const want = [14, 13, 12, 11, 7];
          grid.forEach(c => {
            const r = Number(c.dataset.cid) % 100;
            if (r === 14) c.click();
          });
        })()""")
        await asyncio.sleep(0.5)
        await shot("cheat-hand2.png")
        # таблица комбинаций
        await ev("document.querySelector('#cheat-tabs button[data-tab=\"combos\"]').click()")
        await asyncio.sleep(0.6)
        await shot("cheat-combos.png")
        await ev("document.querySelector('#cheat-tabs button[data-tab=\"holes\"]').click()")
        await asyncio.sleep(0.6)
        await shot("cheat-holes.png")

        # игра на большом экране
        await ev("document.getElementById('btn-cheat-back').click()")
        await ev("document.getElementById('btn-quick').click()")
        await asyncio.sleep(4)
        await shot("game-big.png")
    proc.terminate()


asyncio.run(main())
