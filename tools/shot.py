"""Скриншоты интерфейса через headless Chrome (CDP).

Использование:  python tools/shot.py [http://127.0.0.1:8000] [папка]
"""

from __future__ import annotations

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
PORT = 9222


class Cdp:
    def __init__(self, ws):
        self.ws = ws
        self.counter = 0

    async def call(self, method: str, params: dict | None = None):
        self.counter += 1
        msg_id = self.counter
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        while True:
            raw = await self.ws.recv()
            message = json.loads(raw)
            if message.get("id") == msg_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    async def eval(self, expression: str):
        result = await self.call("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True
        })
        if result.get("exceptionDetails"):
            raise RuntimeError(result["exceptionDetails"])
        return result.get("result", {}).get("value")

    async def shot(self, path: str, full: bool = True):
        await asyncio.sleep(0.4)
        params = {"format": "png"}
        if full:
            params["captureBeyondViewport"] = True
        data = await self.call("Page.captureScreenshot", params)
        Path(path).write_bytes(base64.b64decode(data["data"]))
        print("сохранено:", path)


AUTOPLAY = """
(() => {
  const s = window.__pref;
  const g = s && s.game;
  if (!g) return 'no-game';
  if (g.turn !== s.seat) return 'wait';
  const byText = (t) => Array.from(document.querySelectorAll('#actions .btn'))
      .find(b => b.textContent.trim() === t);
  switch (g.phase) {
    case 'auction': {
      const open = byText('Открыть карты');
      if (open) { open.click(); return 'open'; }
      const b = byText('Пас');
      if (b) { b.click(); return 'pass'; }
      return 'no-btn';
    }
    case 'drop': {
      const cards = Array.from(document.querySelectorAll('#hand .card'));
      const selected = cards.filter(c => c.classList.contains('selected'));
      if (selected.length < 2) {
        const next = cards.find(c => !c.classList.contains('selected'));
        if (next) { next.click(); return 'select'; }
        return 'no-cards';
      }
      const b = byText('Сбросить две карты'); if (b) { b.click(); return 'drop'; } return 'no-btn';
    }
    case 'declare': { const b = byText('ОК'); if (b) { b.click(); return 'declare'; } return 'no-btn'; }
    case 'whist': { const b = byText('Пас'); if (b) { b.click(); return 'whist'; } return 'no-btn'; }
    case 'catch_mizer': { const b = byText('Не ловить'); if (b) { b.click(); return 'catch'; } return 'no-btn'; }
    case 'playing': {
      const legal = new Set(g.legal || []);
      const card = Array.from(document.querySelectorAll('#hand .card'))
          .find(c => legal.has(parseInt(c.dataset.cid)));
      if (card) { card.click(); return 'play'; }
      return 'no-card';
    }
  }
  return 'phase-' + g.phase;
})()
"""


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "shots")
    mobile = "--mobile" in sys.argv
    out.mkdir(exist_ok=True)

    profile = Path.home() / "AppData" / "Local" / "Temp" / "pref_chrome"
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
        f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}",
        "--window-size=900,1250", "about:blank",
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
    if target is None:
        print("Chrome не запустился")
        proc.terminate()
        return 1

    async with websockets.connect(target["webSocketDebuggerUrl"], max_size=40 * 1024 * 1024) as ws:
        cdp = Cdp(ws)
        await cdp.call("Page.enable")
        await cdp.call("Runtime.enable")
        await cdp.call("Network.enable")
        await cdp.call("Network.setCacheDisabled", {"cacheDisabled": True})
        await cdp.call("Emulation.setDeviceMetricsOverride", {
            "width": 390 if mobile else 900,
            "height": 844 if mobile else 1250,
            "deviceScaleFactor": 2 if mobile else 1,
            "mobile": mobile,
        })
        if mobile:
            await cdp.call("Emulation.setUserAgentOverride", {
                "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
            })
            await cdp.call("Emulation.setTouchEmulationEnabled", {"enabled": True})
        await cdp.call("Page.navigate", {"url": url})
        # страница-заглушка pinggy: один раз нажать «Enter site»
        await asyncio.sleep(2.0)
        await cdp.eval(
            "(() => { const b = document.querySelector('button[onclick*=\"access\"]');"
            " if (b) { b.click(); return 'clicked'; } return 'no-interstitial'; })()")
        # ждём, пока страница реально отрисовалась (через туннель это медленно)
        for _ in range(60):
            ready = await cdp.eval(
                "document.readyState === 'complete' && !!document.getElementById('input-name')")
            if ready:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(1.0)
        await cdp.shot(str(out / "01-home.png"))

        # лобби: создаём комнату
        await cdp.eval("document.getElementById('input-name').value = 'Аня';")
        await cdp.eval("document.getElementById('btn-create').click();")
        await asyncio.sleep(1.5)
        await cdp.shot(str(out / "02-lobby.png"))

        # добавляем бота и стартуем
        await cdp.eval("document.getElementById('btn-add-bot').click();")
        await asyncio.sleep(0.6)
        await cdp.eval("document.getElementById('btn-add-bot').click();")
        await asyncio.sleep(0.6)
        await cdp.shot(str(out / "03-lobby-bots.png"))
        await cdp.eval("document.getElementById('btn-start').click();")
        await asyncio.sleep(2.0)
        await cdp.shot(str(out / "04-auction.png"))

        # ходим в торге: пасуем, пока не начнётся игра
        for _ in range(10):
            phase = await cdp.eval(
                "(window.__pref && window.__pref.state && window.__pref.game) "
                "? window.__pref.game.phase : null"
            )
            if phase and phase != "auction":
                break
            await cdp.eval(
                "(() => { const bs = Array.from(document.querySelectorAll('#actions .btn'));"
                " const p = bs.find(b => b.textContent.trim() === 'Пас');"
                " if (p) p.click(); })()"
            )
            await asyncio.sleep(1.3)
        await cdp.shot(str(out / "05-table.png"))

        # автоигра: доигрываем раунд кнопками интерфейса
        for _ in range(200):
            result = await cdp.eval(AUTOPLAY)
            phase = await cdp.eval(
                "(window.__pref && window.__pref.game) ? window.__pref.game.phase : null"
            )
            if phase in ("round_end", "match_end"):
                break
            await asyncio.sleep(0.4)

        # ждём, пока появится экран итогов
        for _ in range(60):
            visible = await cdp.eval(
                "document.getElementById('screen-result').classList.contains('active')")
            if visible:
                break
            await asyncio.sleep(0.5)
        await cdp.shot(str(out / "05b-result.png"))

        # правила
        await cdp.eval("document.getElementById('btn-menu').click();")
        await asyncio.sleep(0.5)
        await cdp.eval("document.getElementById('btn-menu-rules').click();")
        await asyncio.sleep(0.5)
        await cdp.shot(str(out / "06-rules.png"))

    proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
