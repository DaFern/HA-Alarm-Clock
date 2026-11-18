"""Run the real custom card in isolated headless Chromium with a fake HA server."""

import html
import json
from pathlib import Path
import re
import subprocess
import tempfile

fixture = Path(__file__).with_name("browser.html")
for width in (320, 390, 620, 1280):
    profile = tempfile.mkdtemp(prefix=f"household-alarms-browser-{width}-", dir="/data/v2/cache/opencode")
    args = ["/usr/bin/chromium", "--headless", "--no-sandbox", "--disable-gpu",
            "--disable-dev-shm-usage", "--allow-file-access-from-files", "--no-first-run",
            "--disable-background-networking", f"--user-data-dir={profile}",
            f"--window-size={width},1100", "--virtual-time-budget=5000", "--dump-dom", fixture.as_uri()]
    completed = subprocess.run(args, capture_output=True, text=True, timeout=45)
    match = re.search(r'<pre id="results">(.*?)</pre>', completed.stdout, re.S)
    if not match:
        raise SystemExit(f"Chromium did not report results at {width}px (exit {completed.returncode})")
    result = json.loads(html.unescape(match.group(1)))
    print(json.dumps({"width": width, **result}, indent=2))
    if result["status"] != "PASS":
        raise SystemExit(1)
