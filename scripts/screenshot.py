"""Reproducible dashboard screenshots (headless Chromium via Playwright).

    uv run python scripts/screenshot.py            # weekday 10:00 and 02:00 -> docs/screenshots/
    uv run python scripts/screenshot.py --times 10:00 14:30 --node uvu-orem

Needs a one-time ``uv run playwright install chromium``. Runs a simulation first if none exists.
The map may load geography data from the internet (Plotly's CDN), so network access may be required.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
VIEWPORT = {"width": 1600, "height": 1200}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ensure_run() -> None:
    if list((ROOT / "outputs").glob("run_*/snapshots.parquet")):
        return
    from uetn_twin import engine, topology

    topo = topology.load()
    engine.write_run(topo, engine.run_simulation(topo, 24), ROOT / "outputs")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", nargs="+", default=["10:00", "02:00"], help="HH:MM of the simulated day")
    ap.add_argument("--node", default=None, help="optionally open the detail panel of this node id")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    ensure_run()
    OUT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py"), "--server.headless", "true",
         "--server.port", str(port), "--browser.gatherUsageStats", "false"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            print("Streamlit did not start", file=sys.stderr)
            return 1
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
            for hhmm in args.times:
                page.goto(f"http://127.0.0.1:{port}/?t={hhmm}")
                page.wait_for_selector("text=link utilization", timeout=60000)
                page.wait_for_selector(".js-plotly-plot .geo path", state="attached", timeout=60000)
                if args.node:
                    box = page.locator('[data-testid="stSelectbox"]').filter(has_text="Inspect node").locator("input")
                    box.click()
                    box.fill(args.node)  # filter the list, then take the first match
                    page.keyboard.press("Enter")
                page.wait_for_timeout(2500)  # let tables and markers settle
                dest = OUT / f"weekday_{hhmm.replace(':', '')}{'_' + args.node if args.node else ''}.png"
                page.screenshot(path=str(dest))
                print("wrote", dest.relative_to(ROOT))
            browser.close()
    finally:
        server.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
