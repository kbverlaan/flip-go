"""OTA-update: haalt bij start de nieuwste code op van GitHub (als er WiFi is).
Draait vóór de app (zie flip/FlipGo.sh). Faalt stil -> huidige versie start.

Private repo: zet een fine-grained PAT (alleen contents:read op deze repo)
in conf/github_token.txt. Public repo: geen token nodig.
Assets (geluid/font) reizen niet mee via OTA — die wijzigen zelden en
gaan via de SD-kaart.
"""
import ast
import sys
from pathlib import Path

REPO = "kbverlaan/flip-go"
FILES = ["main.py", "ogs.py", "goban.py", "retro.py", "gtp.py", "judge.py", "review.py", "analyse.py", "update.py"]
HERE = Path(__file__).parent
VERSION_FILE = HERE / "version.txt"


def _headers():
    h = {"User-Agent": "flip-go-updater"}
    p = HERE / "conf" / "github_token.txt"
    if p.exists():
        h["Authorization"] = f"Bearer {p.read_text().strip()}"
    return h


def main():
    import time
    import requests
    # Na slaap/boot staat de klok soms nog vóór 2025 tot NTP synct; dan faalt
    # de SSL-check ("certificate is not yet valid"). Wacht daar max 10s op.
    for _ in range(10):
        if time.time() > 1735689600:
            break
        time.sleep(1)
    h = _headers()
    r = requests.get(f"https://api.github.com/repos/{REPO}/commits/master",
                     headers=h, timeout=8)
    r.raise_for_status()
    sha = r.json()["sha"]
    cur = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else ""
    if sha == cur:
        print("flip-go up-to-date", sha[:8])
        return
    print("flip-go: updating to", sha[:8])
    def get(f):
        rr = requests.get(f"https://raw.githubusercontent.com/{REPO}/{sha}/{f}",
                          headers=h, timeout=10)
        rr.raise_for_status()
        return rr.content
    # De bestandslijst uit de NIEUWE update.py: anders komt een nieuw bestand pas één
    # update later mee, terwijl de nieuwe main.py het al importeert (crash bij start).
    new = {"update.py": get("update.py")}
    files = FILES
    for node in ast.parse(new["update.py"]).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "FILES" for t in node.targets):
            files = ast.literal_eval(node.value)
    for f in dict.fromkeys(list(files) + FILES):
        if f not in new:
            new[f] = get(f)
    for f, data in new.items():      # pas schrijven als alles compleet binnen is
        (HERE / f).write_bytes(data)
    VERSION_FILE.write_text(sha)
    print("flip-go: updated")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("update skipped:", e)
