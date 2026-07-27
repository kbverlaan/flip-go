"""OGS-laag: REST (login, potten, challenges) + realtime-socket (zetten).

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
CLIENT_ID = "3SKcBAGtYW2QmKiiYiqy5Q72hzpIgXwohQ7ZpGrr"
REDIRECT = "http://localhost:8642/callback"
TOKEN_FILE = Path.home() / ".config" / "flip-go" / "token.json"
CHALL_FILE = TOKEN_FILE.parent / "challenges.json"

S = requests.Session()
S.headers["User-Agent"] = "flip-go/0.1 (personal client)"

_tok = None      # token in memory; disk alleen bij start en refresh
_me = None       # eigen speler-info is sessie-constant
_jwt = None      # socket-JWT; vernieuwd zodra een socket-commando faalt


# ---------- auth ----------
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
    r = S.post("https://online-go.com/oauth2/token/", data={
        "grant_type": "authorization_code", "code": got["code"],
        "redirect_uri": REDIRECT, "client_id": CLIENT_ID,
        "code_verifier": verifier}, timeout=15)
    r.raise_for_status()
    _save_token(r.json())
    return True


def _save_token(tok):
    global _tok
    tok["obtained_at"] = time.time()
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok))
    TOKEN_FILE.chmod(0o600)
    _tok = tok


def _token():
    global _tok
    if _tok is None:
        if not TOKEN_FILE.exists():
            return None
        _tok = json.loads(TOKEN_FILE.read_text())
    if time.time() - _tok["obtained_at"] > _tok.get("expires_in", 3600) - 120:
        r = S.post("https://online-go.com/oauth2/token/", data={
            "grant_type": "refresh_token", "refresh_token": _tok["refresh_token"],
            "client_id": CLIENT_ID}, timeout=15)
        r.raise_for_status()
        _save_token(r.json())
    return _tok


def _auth():
    return {"Authorization": f"Bearer {_token()['access_token']}"}


# ---------- REST ----------
def api(path, **params):
    h = _auth() if _token() else {}
    r = S.get(f"{BASE}/{path.lstrip('/')}", params=params, headers=h, timeout=10)
    r.raise_for_status()
    return r.json()


def me():
    global _me
    if _me is None:
        _me = api("me")
    return _me


def speed_label(sp):
    return "daily" if sp == "correspondence" else (sp or "?")


def format_outcome(winner_is_black, outcome):
    """'5.5 points' -> 'B+5.5'; 'Resignation' -> 'W+R'."""
    if not outcome:
        return "finished"
    wc = "B" if winner_is_black else "W"
    if outcome.endswith("points"):
        return f"{wc}+{outcome.split()[0]}"
    return f"{wc}+{outcome[0].upper()}"


def my_games():
    """Actieve potten uit het overview. -> lijst {id, opp, my_turn, speed}"""
    mid = me().get("id")
    out = []
    for g in api("ui/overview").get("active_games", []):
        gd = g.get("json", {})
        pl = gd.get("players", {})
        i_am_black = pl.get("black", {}).get("id") == mid
        opp = pl.get("white" if i_am_black else "black", {})
        out.append({
            "id": g.get("id"),
            "opp": opp.get("username", "?"),
            "my_turn": gd.get("clock", {}).get("current_player") == mid,
            "speed": speed_label(gd.get("time_control", {}).get("speed", "")),
        })
    return out


def my_history(n=10):
    """Laatste afgeronde potten. -> {id, opp, won, result} nieuwste eerst."""
    mid = me().get("id")
    out = []
    for g in api(f"players/{mid}/games", ordering="-ended", page_size=n).get("results", []):
        if not g.get("ended"):
            continue
        black = (g.get("players") or {}).get("black", {})
        white = (g.get("players") or {}).get("white", {})
        i_black = black.get("id") == mid
        out.append({
            "id": g["id"],
            "opp": (white if i_black else black).get("username", "?"),
            "won": bool(g.get("white_lost") if i_black else g.get("black_lost")),
            "result": format_outcome(g.get("white_lost"), g.get("outcome", "")),
        })
    return out


# ---------- realtime socket (zetten; REST-move is dood op de server) ----------
def _game_command(gid, command, payload, confirm_tag):
    """Socket-transactie: connect, wacht op gamedata, stuur command, wacht op
    bevestigings-event. Zo doet de webclient het ook."""
    global _jwt
    import websocket
    if _jwt is None:
        _jwt = api("ui/config")["user_jwt"]
    ws = websocket.create_connection("wss://online-go.com/socket", timeout=10,
                                     header=["User-Agent: flip-go/0.1"])
    try:
        ws.send(json.dumps(["authenticate", {"jwt": _jwt}, 1]))
        ws.send(json.dumps(["game/connect", {"game_id": gid, "chat": False}, 2]))
        sent = False
        t0 = time.time()
        while time.time() - t0 < 15:
            m = json.loads(ws.recv())
            if not (isinstance(m, list) and m):
                continue
            tag = m[0]
            if not sent and isinstance(tag, str) and tag.endswith("gamedata"):
                ws.send(json.dumps([command, payload]))
                sent = True
            elif sent and tag == confirm_tag:
                return m[1] if len(m) > 1 else {}
            elif sent and isinstance(tag, str) and (tag.endswith("error") or tag == "ERROR"):
                raise RuntimeError(f"server weigerde: {m[1] if len(m) > 1 else '?'}")
        raise RuntimeError("geen bevestiging van de server (timeout)")
    except Exception:
        _jwt = None      # bij twijfel verse JWT voor de volgende poging
        raise
    finally:
        ws.close()


def submit_move(gid, x, y):
    mv = ".." if x < 0 else chr(97 + x) + chr(97 + y)
    return _game_command(gid, "game/move",
                         {"game_id": gid, "player_id": me().get("id"), "move": mv},
                         f"game/{gid}/move")


def pass_move(gid):
    return submit_move(gid, -1, -1)


def accept_removal(gid):
    """Accepteer de telling (server-voorstel voor dode stenen)."""
    g = api(f"games/{gid}")
    removed = (g.get("gamedata") or {}).get("removed") or ""
    return _game_command(gid, "game/removed_stones/accept",
                         {"game_id": gid, "player_id": me().get("id"),
                          "stones": removed, "strict_seki_mode": False},
                         f"game/{gid}/removed_stones_accepted")


def resign(gid):
    return _game_command(gid, "game/resign", {"game_id": gid}, f"game/{gid}/phase")


# ---------- challenges ----------
TIME_CONTROLS = {
    # fischer: daily = 3d + 1d/zet (cap 7d); live = 2m + 30s/zet (cap 5m)
    "daily": {"system": "fischer", "time_control": "fischer", "speed": "correspondence",
              "initial_time": 259200, "time_increment": 86400, "max_time": 604800,
              "pause_on_weekends": True},
    "live": {"system": "fischer", "time_control": "fischer", "speed": "live",
             "initial_time": 120, "time_increment": 30, "max_time": 300,
             "pause_on_weekends": False},
}

# De OGS-bloemenladder (alfabetisch = oplopend in sterkte), ids via active-bots
FLOWERS = [
    ("Agapanthus", 1195515),
    ("Amaranthus", 1200334),
    ("Bergamot", 1195517),
    ("Bouvardia", 1278465),
    ("Carnation", 1195518),
    ("Deutzia", 1195519),
    ("Echinops", 1195520),
]


def _challenge_body(speed, size, ranked):
    return {
        "challenger_color": "automatic",
        "game": {
            "name": "flip-go", "rules": "japanese", "ranked": ranked,
            "width": size, "height": size, "handicap": 0, "komi_auto": "automatic",
            "disable_analysis": False, "initial_state": None, "private": False,
            "time_control": "fischer",
            "time_control_parameters": TIME_CONTROLS[speed],
        },
    }


def create_challenge(speed="daily", size=9, ranked=True):
    """Open challenge (japanese, auto-komi)."""
    body = _challenge_body(speed, size, ranked)
    body.update(min_ranking=0, max_ranking=36)
    r = S.post(f"{BASE}/challenges/", json=body, headers=_auth(), timeout=15)
    r.raise_for_status()
    res = r.json()
    _chall_store(_chall_store() + [{"id": res.get("challenge"), "speed": speed, "size": size}])
    return res


def challenge_player(pid, speed="live", size=9, ranked=True):
    """Directe challenge naar een speler/bot."""
    r = S.post(f"{BASE}/players/{pid}/challenge/",
               json=_challenge_body(speed, size, ranked), headers=_auth(), timeout=15)
    r.raise_for_status()
    return r.json()


def cancel_challenge(cid):
    r = S.delete(f"{BASE}/challenges/{cid}/", headers=_auth(), timeout=15)
    if r.status_code not in (200, 204):
        r.raise_for_status()
    _chall_store([c for c in _chall_store() if c.get("id") != cid])
    return True


def _chall_store(data=None):
    if data is not None:
        CHALL_FILE.write_text(json.dumps(data))
        return data
    if CHALL_FILE.exists():
        return json.loads(CHALL_FILE.read_text())
    return []


def my_challenges():
    """Eigen openstaande challenges (lokaal bijgehouden — het me/challenges-
    endpoint toont uitgaande open challenges niet). Server-geverifieerd."""
    out = []
    for c in _chall_store():
        try:
            api(f"challenges/{c['id']}")
            out.append(c)
        except Exception:
            pass     # geaccepteerd (pot staat dan in de lijst) of verlopen
    _chall_store(out)
    return out


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
