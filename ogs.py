"""OGS REST-laag: publieke endpoints + OAuth2/PKCE-login.
De realtime socket komt hierna.

CLI:  python ogs.py login   (opent browser, vangt callback op :8642)
      python ogs.py me      (test: wie ben ik?)
"""
import base64
import hashlib
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

BASE = "https://online-go.com/api/v1"
UA = {"User-Agent": "flip-go/0.1 (personal client)"}
CLIENT_ID = "3SKcBAGtYW2QmKiiYiqy5Q72hzpIgXwohQ7ZpGrr"
REDIRECT = "http://localhost:8642/callback"
TOKEN_FILE = Path.home() / ".config" / "flip-go" / "token.json"


def login(timeout=180):
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = q.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>flip-go: logged in. You can close this tab.</h2>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 8642), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = "https://online-go.com/oauth2/authorize?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    webbrowser.open(url)
    print("Browser geopend - klik Authorize op online-go.com ...")
    t0 = time.time()
    while "code" not in got and time.time() - t0 < timeout:
        time.sleep(0.5)
    srv.shutdown()
    if not got.get("code"):
        raise SystemExit("Geen authorization code ontvangen (timeout).")
    r = requests.post("https://online-go.com/oauth2/token/", data={
        "grant_type": "authorization_code", "code": got["code"],
        "redirect_uri": REDIRECT, "client_id": CLIENT_ID,
        "code_verifier": verifier}, headers=UA, timeout=15)
    r.raise_for_status()
    _save_token(r.json())
    return True


def _save_token(tok):
    tok["obtained_at"] = time.time()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok))
    TOKEN_FILE.chmod(0o600)


def _token():
    if not TOKEN_FILE.exists():
        return None
    tok = json.loads(TOKEN_FILE.read_text())
    if time.time() - tok["obtained_at"] > tok.get("expires_in", 3600) - 120:
        r = requests.post("https://online-go.com/oauth2/token/", data={
            "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
            "client_id": CLIENT_ID}, headers=UA, timeout=15)
        r.raise_for_status()
        tok = r.json()
        _save_token(tok)
    return tok


def api(path, **params):
    tok = _token()
    h = dict(UA)
    if tok:
        h["Authorization"] = f"Bearer {tok['access_token']}"
    r = requests.get(f"{BASE}/{path.lstrip('/')}", params=params, headers=h, timeout=10)
    r.raise_for_status()
    return r.json()


def me():
    return api("me")


def my_games():
    """Actieve potten uit het overview. -> lijst {id, black, white, my_turn, size}"""
    m = me()
    out = []
    for g in api("ui/overview").get("active_games", []):
        gd = g.get("json", {})
        pl = gd.get("players", {})
        out.append({
            "id": g.get("id"),
            "black": pl.get("black", {}).get("username", "?"),
            "white": pl.get("white", {}).get("username", "?"),
            "my_id": m.get("id"),
            "my_turn": gd.get("clock", {}).get("current_player") == m.get("id"),
            "size": gd.get("width", 9),
        })
    return out


def game(gid):
    return api(f"games/{gid}")


def submit_move(gid, x, y, size=9):
    """Zet insturen via de realtime socket (zoals de webclient; REST is dood).
    Wacht op het move-event van de server als bevestiging."""
    import websocket
    jwt = api("ui/config")["user_jwt"]
    my_id = me().get("id")
    mv = chr(97 + x) + chr(97 + y)
    ws = websocket.create_connection("wss://online-go.com/socket", timeout=10,
                                     header=["User-Agent: flip-go/0.1"])
    try:
        ws.send(json.dumps(["authenticate", {"jwt": jwt}, 1]))
        ws.send(json.dumps(["game/connect", {"game_id": gid, "chat": False}, 2]))
        sent = False
        t0 = time.time()
        while time.time() - t0 < 15:
            m = json.loads(ws.recv())
            if not (isinstance(m, list) and m):
                continue
            tag = m[0]
            if not sent and isinstance(tag, str) and tag.endswith("gamedata"):
                ws.send(json.dumps(["game/move",
                                    {"game_id": gid, "player_id": my_id, "move": mv}]))
                sent = True
            elif sent and tag == f"game/{gid}/move":
                return m[1]                       # server bevestigt onze zet
            elif sent and isinstance(tag, str) and tag.endswith("error"):
                raise RuntimeError(f"server weigerde zet: {m[1]}")
            elif isinstance(tag, str) and tag == "ERROR":
                raise RuntimeError(f"socket error: {m[1] if len(m) > 1 else '?'}")
        raise RuntimeError("geen bevestiging van de server (timeout)")
    finally:
        ws.close()


def get_player(username):
    r = requests.get(f"{BASE}/players", params={"username": username},
                     headers=UA, timeout=10)
    r.raise_for_status()
    res = r.json().get("results", [])
    return res[0] if res else None


def rating_to_rank(rating):
    """OGS: rank = ln(rating/525) * 23.15; <30k afkappen."""
    import math
    if not rating:
        return "?"
    r = math.log(rating / 525) * 23.15
    return f"{int(30 - r)}k" if r < 30 else f"{int(r - 29)}d"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "me"
    if cmd == "login":
        login()
        print("Token opgeslagen.")
        m = me()
        print("Ingelogd als:", m.get("username"), "| id:", m.get("id"))
    elif cmd == "me":
        m = me()
        print(json.dumps({k: m.get(k) for k in ("id", "username", "ranking")}, indent=1))
