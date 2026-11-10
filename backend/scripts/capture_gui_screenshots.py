"""Screenshots of the local GUI for PROJECT_DOCUMENTATION.docx, taken from a REAL run.

Drives headless Google Chrome over the DevTools protocol: opens the running GUI
(`python main.py --gui`), puts the given video into the page's file input (exactly as if
the user had chosen it), clicks "Analyze Video", and saves PNGs of each screen as the
real analysis progresses. Nothing on the page is edited or faked.

    python backend/scripts/capture_gui_screenshots.py --video evaluation/videos/x.mp4 \
        --out docs/screenshots [--url http://127.0.0.1:8765]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333


class Page:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def cmd(self, method: str, **params):
        self.n += 1
        my = self.n
        await self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == my:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def js(self, expr: str):
        r = await self.cmd("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value")

    async def until(self, expr: str, timeout: float = 180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if await self.js(expr):
                return
            await asyncio.sleep(0.25)
        raise TimeoutError(expr)

    async def goto(self, url: str):
        await self.cmd("Page.navigate", url=url)
        # page loaded and /api/config applied (it fills the threshold inputs)
        await self.until("document.readyState === 'complete' && document.getElementById('drop_ratio').value !== ''")
        await asyncio.sleep(0.8)

    async def set_file(self, path: Path):
        doc = await self.cmd("DOM.getDocument")
        node = await self.cmd("DOM.querySelector", nodeId=doc["root"]["nodeId"], selector="#file")
        await self.cmd("DOM.setFileInputFiles", nodeId=node["nodeId"], files=[str(path.resolve())])
        await asyncio.sleep(0.4)

    async def shot(self, out: Path, selectors: list[str] | None = None, pad: int = 12):
        """Screenshot of the viewport, or of the box enclosing the given elements."""
        params = {"format": "png"}
        if selectors:
            box = await self.js(
                "(() => { const r = " + json.dumps(selectors) + ".map(s => document.querySelector(s)"
                ".getBoundingClientRect()); return {x: Math.min(...r.map(b => b.left)), y: Math.min(...r.map(b => b.top"
                ")) + scrollY, r: Math.max(...r.map(b => b.right)), b: Math.max(...r.map(b => b.bottom)) + scrollY}; })()")
            params.update(captureBeyondViewport=True, clip={
                "x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad), "scale": 1,
                "width": box["r"] - box["x"] + 2 * pad, "height": box["b"] - box["y"] + 2 * pad})
        data = await self.cmd("Page.captureScreenshot", **params)
        out.write_bytes(base64.b64decode(data["data"]))
        print("  saved", out)


async def capture(url: str, video: Path, out: Path):
    tmp = Path(tempfile.mkdtemp(prefix="gui-shots-"))
    broken = tmp / "broken_recording.mp4"
    broken.write_text("this is a text file renamed to .mp4\n" * 50)
    unsupported = tmp / "gameplay_notes.txt"
    unsupported.write_text("not a video\n")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                               f"--user-data-dir={tmp / 'profile'}", "--hide-scrollbars", "--no-first-run",
                               "--force-color-profile=srgb", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001 - Chrome still starting
                time.sleep(0.2)
        else:
            raise RuntimeError("Chrome did not start")
        async with websockets.connect(ws_url, max_size=64 * 1024 * 1024) as ws:
            p = Page(ws)
            await p.cmd("Page.enable")
            await p.cmd("Emulation.setDeviceMetricsOverride", width=1280, height=860, deviceScaleFactor=2, mobile=False)
            await p.cmd("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])

            await p.goto(url + "/")
            await p.shot(out / "gui_1_upload.png", ["header", "#upload"], pad=0)
            await p.set_file(video)
            await p.js("document.querySelector('details').open = true")
            await p.shot(out / "gui_2_video_selected.png", ["#upload"])
            await p.js("document.querySelector('details').open = false")

            await p.js("document.getElementById('analyze').click()")
            await p.until("/analysing frame/.test(document.getElementById('progress-msg').textContent) && "
                          "parseInt(document.getElementById('progress-msg').textContent) >= 30")
            await p.shot(out / "gui_3_progress.png", ["#progress"])
            await p.until("!document.getElementById('results').classList.contains('hidden') && "
                          "[...document.images].every(i => i.complete && i.naturalWidth > 0)", timeout=600)
            await asyncio.sleep(0.5)
            job = await p.js("location.hash")
            await p.shot(out / "gui_4_results.png", [".verdict", "#r-stats", "#c-eff"])
            await p.shot(out / "gui_5_events.png", [".card:has(#r-events)"], pad=8)
            await p.shot(out / "gui_6_details.png", [".card:has(#c-int)", ".card:has(#c-chg)", ".card:has(#r-meta)", ".card:has(#r-lim)"], pad=8)

            await p.goto(url + "/")
            await p.set_file(unsupported)
            await p.shot(out / "gui_7_unsupported.png", ["#upload"])
            await p.set_file(broken)
            await p.js("document.getElementById('analyze').click()")
            await p.until("!document.getElementById('failed').classList.contains('hidden')")
            await p.shot(out / "gui_8_failed.png", ["#failed"])
            print("  results page job:", job)
    finally:
        chrome.terminate()
        chrome.wait(10)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/screenshots"))
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    asyncio.run(capture(a.url.rstrip("/"), a.video, a.out))


if __name__ == "__main__":
    main()
