"""Reproducible dashboard screenshots of SIMULATED scenarios (headless Chromium via Playwright).

    uv run python scripts/screenshot.py                       # every shot below -> docs/screenshots/v1/
    uv run python scripts/screenshot.py --only registration   # shots whose file name contains the text
    uv run python scripts/screenshot.py --live                # also a Live-mode shot of a paced run

Needs a one-time ``uv run playwright install chromium``. A scenario without a finished batch run in the outputs
directory is simulated first (``--rerun`` simulates them all again). The map loads geography data from Plotly's CDN,
so network access may be required.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots" / "v1"
VIEWPORT = {"width": 1600, "height": 2300}
# (scenario id, simulated HH:MM, node to open in the detail panel or None)
SHOTS = [
    ("baseline_weekday", "02:00", None),
    ("baseline_weekday", "10:00", None),
    ("semester_registration_monday", "06:55", None),
    ("semester_registration_monday", "07:10", "uvu-orem"),
    ("semester_registration_monday", "09:30", None),
    ("weekend_dorm_streaming", "20:00", None),
    ("ai_training_campaign", "12:00", None),
    ("statewide_k12_testing", "09:30", None),
]
LIVE_SCENARIO, LIVE_SPEED, LIVE_WALL_S = "semester_registration_monday", 600, 20  # 20 s at 600x: 06:00 -> about 09:20


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def has_finished_run(out_dir: Path, scenario: str) -> bool:
    for p in out_dir.glob(f"run_{scenario}_*"):
        try:
            if json.loads((p / "run_meta.json").read_text()).get("finished"):
                return True
        except (OSError, json.JSONDecodeError):
            pass
    return False


def ensure_runs(out_dir: Path, scenarios: list[str], rerun: bool) -> None:
    from uetn_twin.sim.runner import SimRun
    from uetn_twin.sim.scenario import load_scenario

    for sc in dict.fromkeys(scenarios):
        if rerun or not has_finished_run(out_dir, sc):
            print("simulating", sc)
            SimRun(load_scenario(sc), out_base=out_dir).run()


def start_streamlit(out_dir: Path) -> tuple[subprocess.Popen, int]:
    port = free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py"), "--server.headless", "true",
         "--server.port", str(port), "--browser.gatherUsageStats", "false"],
        cwd=ROOT, env={**os.environ, "UETN_OUT_DIR": str(out_dir)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)
            return server, port
        except OSError:
            time.sleep(0.5)
    server.terminate()
    raise RuntimeError("Streamlit did not start")


def snap(page, url: str, dest: Path) -> None:
    page.goto(url)
    page.wait_for_selector("text=link utilization", timeout=60000)
    page.wait_for_selector(".js-plotly-plot .geo path", state="attached", timeout=60000)
    page.wait_for_timeout(3000)  # let tables, charts and markers settle
    page.screenshot(path=str(dest), full_page=True)
    print("wrote", dest.relative_to(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="only shots whose file name contains this text")
    ap.add_argument("--live", action="store_true", help="also capture Live mode while a paced run is in progress")
    ap.add_argument("--rerun", action="store_true", help="simulate every scenario again before the shots")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    from uetn_twin.engine import DEFAULT_OUT

    shots = [s for s in SHOTS if not args.only or args.only in f"{s[0]}_{s[1].replace(':', '')}"]
    OUT.mkdir(parents=True, exist_ok=True)
    out_dir = Path(DEFAULT_OUT)
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_runs(out_dir, [s[0] for s in shots], args.rerun)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2)
        if shots:
            server, port = start_streamlit(out_dir)
            try:
                for scenario, hhmm, node in shots:
                    url = f"http://127.0.0.1:{port}/?run={scenario}&t={hhmm}" + (f"&node={node}" if node else "")
                    snap(page, url, OUT / f"{scenario}_{hhmm.replace(':', '')}{'_' + node if node else ''}.png")
            finally:
                server.terminate()
        if args.live:
            with tempfile.TemporaryDirectory() as tmp:
                sim = subprocess.Popen([sys.executable, "-m", "uetn_twin.cli", "live", LIVE_SCENARIO, "--speed", str(LIVE_SPEED),
                                        "--out", tmp], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                server, port = start_streamlit(Path(tmp))
                try:
                    time.sleep(LIVE_WALL_S)
                    snap(page, f"http://127.0.0.1:{port}/?mode=live", OUT / f"{LIVE_SCENARIO}_live.png")
                finally:
                    server.terminate()
                    sim.terminate()
                    sim.wait(timeout=30)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
