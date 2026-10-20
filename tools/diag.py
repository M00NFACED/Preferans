"""Диагностика автоигры в интерфейсе: что видит бот-кликер и почему не ходит."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import requests
import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333


async def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8020"
    profile = Path.home() / "AppData" / "Local" / "Temp" / "pref_chrome_diag"
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
        counter = {"n": 0}

        async def call(method, params=None):
            counter["n"] += 1
            mid = counter["n"]
            await ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(f"{method}: {msg['error']}")
                    return msg.get("result", {})

        async def ev(expr):
            r = await call("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                                                "returnByValue": True})
            if r.get("exceptionDetails"):
                return "EXC: " + json.dumps(r["exceptionDetails"])[:300]
            return r.get("result", {}).get("value")

        await call("Page.enable")
        await call("Runtime.enable")
        await call("Network.enable")
        await call("Network.setCacheDisabled", {"cacheDisabled": True})
        await call("Page.navigate", {"url": url})
        await asyncio.sleep(2.5)

        print("версия app.js:", await ev(
            "fetch('/js/app.js', {cache:'no-store'}).then(r=>r.text()).then(t=>t.includes('dataset.cid') ? 'есть dataset.cid' : 'НЕТ dataset.cid')"))
        print("в странице:", await ev(
            "typeof window.__pref + ' / ' + (window.__pref ? Object.keys(window.__pref).join(',') : '')"))

        await ev("document.getElementById('input-name').value='Тест';")
        await ev("document.getElementById('btn-quick').click();")
        await asyncio.sleep(3)
        print("фаза:", await ev("window.__pref.game ? window.__pref.game.phase : '?'"))
        print("мой стул:", await ev("window.__pref.seat"))

        for i in range(40):
            phase = await ev("window.__pref.game ? window.__pref.game.phase : '?'")
            if phase in ("round_end", "match_end"):
                break
            info = await ev("""(() => {
                const s = window.__pref, g = s.game;
                if (g.turn !== s.seat) return 'ждём ход, фаза=' + g.phase;
                const btns = Array.from(document.querySelectorAll('#actions .btn')).map(b=>b.textContent.trim());
                const cards = Array.from(document.querySelectorAll('#hand .card')).map(c=>c.dataset.cid);
                return JSON.stringify({phase: g.phase, btns, cards, legal: g.legal, can_play: g.can_play});
            })()""")
            print(f"  [{i}] {phase} :: {info}")
            if phase == "playing":
                print("     клик:", await ev("""(() => {
                    const s = window.__pref, g = s.game;
                    const legal = new Set(g.legal || []);
                    const card = Array.from(document.querySelectorAll('#hand .card')).find(c => legal.has(parseInt(c.dataset.cid)));
                    if (!card) return 'нет карты';
                    card.click();
                    return 'клик по ' + card.dataset.cid;
                })()"""))
            else:
                await ev("""(() => {
                    const s = window.__pref, g = s.game;
                    const byText = t => Array.from(document.querySelectorAll('#actions .btn')).find(b => b.textContent.trim() === t);
                    if (g.phase === 'auction') { const b = byText('Пас'); if (b) b.click(); }
                    else if (g.phase === 'drop') {
                        const cards = Array.from(document.querySelectorAll('#hand .card'));
                        const sel = cards.filter(c => c.classList.contains('selected'));
                        if (sel.length < 2) { const n = cards.find(c => !c.classList.contains('selected')); if (n) n.click(); }
                        else { const b = byText('Сбросить две карты'); if (b) b.click(); }
                    }
                    else if (g.phase === 'declare') { const b = byText('ОК'); if (b) b.click(); }
                    else if (g.phase === 'whist') { const b = byText('Пас'); if (b) b.click(); }
                    else if (g.phase === 'catch_mizer') { const b = byText('Не ловить'); if (b) b.click(); }
                })()""")
            await asyncio.sleep(1.0)

    proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
