"""Скриншот карт: туз, фигурные, раскладка пипсов — на белом фоне."""

import base64
import asyncio
import json
import subprocess
import time
from pathlib import Path

import requests
import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9666
OUT = Path("shots_cards")
OUT.mkdir(exist_ok=True)

HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="http://127.0.0.1:8090/css/style.css">
<style>
body{background:#0d1f15;padding:26px;font-family:sans-serif}
.row{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:22px}
h3{color:#f2c14e;font-family:Georgia,serif;margin:14px 0 8px}
</style></head><body>
<h3>Туз и фигурные</h3><div class="row" id="r1"></div>
<h3>Раскладка пипсов 7–10</h3><div class="row" id="r2"></div>
<script src="http://127.0.0.1:8090/js/cards.js"></script>
<script>
const mk=(s,r,size)=>Cards.makeCard({id:1,suit:s,rank:r},{size:size||'lg'});
r1.innerHTML = [0,1,2,3].map(s=>mk(s,14)).join('')
  + [0,1,2,3].map(s=>mk(s,13)).join('')
  + [0,1,2,3].map(s=>mk(s,12)).join('')
  + [0,1,2,3].map(s=>mk(s,11)).join('');
r2.innerHTML = [7,8,9,10].map(r=>mk(0,r)).join('')
  + [0,1,2,3].map(s=>mk(s,10)).join('');
</script></body></html>"""


async def main():
    profile = Path.home() / "AppData" / "Local" / "Temp" / "pref_chrome_cards"
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run",
        f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
        "--window-size=1000,700", "about:blank",
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

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Emulation.setDeviceMetricsOverride",
                   {"width": 1000, "height": 700, "deviceScaleFactor": 2, "mobile": False})
        await call("Page.navigate", {"url": "http://127.0.0.1:8090/cardtest.html"})
        await asyncio.sleep(2.5)
        data = await call("Page.captureScreenshot", {"format": "png"})
        (OUT / "cards.png").write_bytes(base64.b64decode(data["data"]))
        print("сохранено shots_cards/cards.png")
    proc.terminate()


asyncio.run(main())
