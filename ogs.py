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

import goban

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
            if "code" in q or "error" in q:      # niet /favicon.ico: dat overschreef de code
                got["code"] = q.get("code", [None])[0]
                got["error"] = q.get("error", [None])[0]
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
        raise SystemExit(f"OGS weigerde: {got['error']}" if got.get("error") else
                         "Geen authorization code ontvangen (timeout).")
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


def rank_label(ranking):
    """OGS ranking-veld -> '21k' / '2d'."""
    if ranking is None:
        return ""
    r = float(ranking)
    return f"{max(1, int(30 - r))}k" if r < 30 else f"{int(r - 29)}d"


def rating_to_rank(rating):
    """Echte rating -> kyu/dan, zonder de 25k-weergaveklem van OGS."""
    import math
    if not rating:
        return ""
    r = math.log(rating / 525) * 23.15
    return f"{round(30 - r)}k" if r < 30 else f"{round(r - 29)}d"


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
        exp = gd.get("clock", {}).get("expiration")
        out.append({
            "id": g.get("id"),
            "opp": opp.get("username", "?"),
            "my_turn": gd.get("clock", {}).get("current_player") == mid,
            "speed": speed_label(gd.get("time_control", {}).get("speed", "")),
            "left": max(0, exp / 1000 - time.time()) if exp else None,
        })
    return out


def my_history(n=10, page=1):
    """Afgeronde potten, nieuwste eerst. -> {id, opp, won, result, size, ended}"""
    mid = me().get("id")
    out = []
    for g in api(f"players/{mid}/games", ordering="-ended", page_size=n, page=page).get("results", []):
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
            "size": g.get("width"), "ended": g.get("ended"),
        })
    return out


# ---------- realtime socket (zetten; REST-move is dood op de server) ----------
def _game_command(gid, command, payload, confirm_tags):
    """Socket-transactie: connect, wacht op gamedata, stuur command, wacht op
    een van de bevestigings-events. Zo doet de webclient het ook."""
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
            elif sent and tag in confirm_tags:
                return m[1] if len(m) > 1 else {}
            elif sent and isinstance(tag, str) and (tag.endswith("error") or tag == "ERROR"):
                raise RuntimeError(f"server weigerde: {m[1] if len(m) > 1 else '?'}")
        raise RuntimeError("geen bevestiging van de server (timeout)")
    except Exception:
        _jwt = None      # bij twijfel verse JWT voor de volgende poging
        raise
    finally:
        ws.close()


def wait_for_move(gid, nmoves, timeout=90):
    """Luister op de socket tot er een zet (of fase-wissel) bij komt na `nmoves`
    zetten. Push i.p.v. pollen: de zet van de tegenstander is er meteen.
    -> True als er iets veranderde, False bij timeout."""
    global _jwt
    import websocket
    if _jwt is None:
        _jwt = api("ui/config")["user_jwt"]
    ws = websocket.create_connection("wss://online-go.com/socket", timeout=5,
                                     header=["User-Agent: flip-go/0.1"])
    try:
        ws.send(json.dumps(["authenticate", {"jwt": _jwt}, 1]))
        ws.send(json.dumps(["game/connect", {"game_id": gid, "chat": False}, 2]))
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                m = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if not (isinstance(m, list) and m and isinstance(m[0], str)):
                continue
            tag = m[0]
            if tag == f"game/{gid}/gamedata":      # stand bij verbinden: al gezet?
                if len(m[1].get("moves", [])) > nmoves or m[1].get("phase") != "play":
                    return True
            elif tag in (f"game/{gid}/move", f"game/{gid}/phase"):
                return True
        return False
    finally:
        ws.close()


def submit_move(gid, x, y):
    mv = ".." if x < 0 else chr(97 + x) + chr(97 + y)
    return _game_command(gid, "game/move",
                         {"game_id": gid, "player_id": me().get("id"), "move": mv},
                         (f"game/{gid}/move",))


def pass_move(gid):
    return submit_move(gid, -1, -1)


def accept_removal(gid):
    """Accepteer de telling (server-voorstel voor dode stenen)."""
    g = api(f"games/{gid}")
    removed = (g.get("gamedata") or {}).get("removed") or ""
    return _game_command(gid, "game/removed_stones/accept",
                         {"game_id": gid, "player_id": me().get("id"),
                          "stones": removed, "strict_seki_mode": False},
                         (f"game/{gid}/removed_stones_accepted",
                          f"game/{gid}/phase", f"game/{gid}/gamedata"))


def resign(gid):
    # de server stuurt bij resign geen apart phase-event maar verse gamedata
    return _game_command(gid, "game/resign", {"game_id": gid},
                         (f"game/{gid}/phase", f"game/{gid}/gamedata",
                          f"game/{gid}/conditional_moves"))


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



def _dur(sec):
    """Seconden -> '3d' / '2m' / '30s' (grootste hele eenheid)."""
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if sec % n == 0:
            return f"{sec // n}{unit}"
    return f"{sec}s"


def time_label(speed):
    """'3d + 1d per move' uit TIME_CONTROLS (voor NEW GAME)."""
    tc = TIME_CONTROLS[speed]
    return f"{_dur(tc['initial_time'])} + {_dur(tc['time_increment'])} per move"


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
            "name": "flip-go", "rules": goban.RULES, "ranked": ranked,
            "width": size, "height": size, "handicap": 0, "komi_auto": "automatic",
            "disable_analysis": False, "initial_state": None, "private": False,
            "time_control": "fischer",
            "time_control_parameters": TIME_CONTROLS[speed],
        },
    }


SEEK_RANGE = 3      # open challenge: alleen spelers tot zoveel rangen boven of onder jou


def create_challenge(speed="daily", size=9, ranked=True):
    """Open challenge (japanese, auto-komi) voor spelers rond je eigen rang (vers opgehaald).
    OGS geeft meteen het pot-nummer mee; dat bewaren we voor de zoeker."""
    body = _challenge_body(speed, size, ranked)
    mine = round(float(api("me").get("ranking") or 5))
    body.update(min_ranking=max(0, mine - SEEK_RANGE), max_ranking=min(36, mine + SEEK_RANGE))
    r = S.post(f"{BASE}/challenges/", json=body, headers=_auth(), timeout=15)
    r.raise_for_status()
    res = r.json()
    with _chall_lock:
        _chall_store(_chall_store() + [{"id": res.get("challenge"), "game": res.get("game"),
                                        "speed": speed, "size": size}])
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
    _chall_drop(cid)
    return True


_chall_lock = threading.RLock()     # de lijst wordt ook door de Seeker gelezen en geschreven


def _chall_store(data=None):
    with _chall_lock:
        if data is not None:
            tmp = CHALL_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(CHALL_FILE)           # atomisch: een andere thread leest nooit half
            return data
        if CHALL_FILE.exists():
            return json.loads(CHALL_FILE.read_text())
        return []


def _chall_drop(cid):
    with _chall_lock:
        _chall_store([c for c in _chall_store() if c.get("id") != cid])


def _challenge_open(cid):
    """True zolang OGS de challenge kent; alleen een 404 betekent weg (geen netwerkfout)."""
    r = S.get(f"{BASE}/challenges/{cid}", headers=_auth(), timeout=15)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    return True


def my_challenges():
    """Eigen openstaande challenges (lokaal bijgehouden — het me/challenges-
    endpoint toont uitgaande open challenges niet). Server-geverifieerd."""
    out = []
    for c in _chall_store():
        try:
            if not _challenge_open(c["id"]):
                _chall_drop(c["id"])        # aangenomen (pot staat in de lijst) of verlopen
                continue
        except Exception:
            pass                            # netwerk: niet vergeten
        out.append(c)
    return out


class Seeker:
    """Volgt de eigen open challenges op de achtergrond, ook tijdens een botpot.
    Live: elke seconde challenge/keepalive op een aangemelde socket; zonder verdwijnt een
    live-challenge binnen ~20 s (getest 27 okt). Aangenomen = de challenge is weg en de pot
    (nummer uit create_challenge) staat op 'play': dan staat found klaar voor de melding."""
    CHECK = {"live": 2, "daily": 30}       # seconden tussen controles

    def __init__(self):
        self.watch = {}                    # challenge-id -> regel uit challenges.json
        self.found = None                  # {"game", "opp", "speed"} tot je de pot opent of hij afloopt
        self.changes = 0                   # +1 als een zoekopdracht afloopt: YOUR GAMES laadt opnieuw
        self._ws, self._checked, self._err, self._started = None, {}, None, False

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True).start()

    def take(self):
        f, self.found = self.found, None
        return f

    def seen(self, gid):
        """De pot is open (via de melding of YOUR GAMES): melding weg."""
        if self.found and self.found["game"] == gid:
            self.found = None

    def _run(self):
        while True:
            try:
                self._tick()
                self._err = None
            except Exception as e:
                if str(e) != self._err:            # één regel per soort fout, niet elke seconde
                    print("seeker:", e, flush=True)
                    self._err = str(e)
                self._close()
                time.sleep(4)
            time.sleep(1)

    def _tick(self):
        for c in _chall_store():
            self.watch.setdefault(c.get("id"), c)
        live = [c for c in self.watch.values() if c.get("speed") == "live" and c.get("game")]
        if live:
            self._keepalive(live)
        else:
            self._close()
        now = time.time()
        for cid, c in list(self.watch.items()):
            if now - self._checked.get(cid, 0) < self.CHECK.get(c.get("speed"), 30):
                continue
            self._checked[cid] = now
            if _challenge_open(cid):
                continue
            self.watch.pop(cid, None)
            _chall_drop(cid)
            found = self._game(c.get("game"), c.get("speed"))
            print(f"seeker: challenge {cid} ({c.get('speed')}) "
                  + (f"aangenomen door {found['opp']}, pot {found['game']}" if found else "weg, geen pot"), flush=True)
            self.found = found or self.found
            self.changes += 1
        if self.found and now - self._checked.get("found", 0) > 5:      # nog speelbaar?
            self._checked["found"] = now
            if not self._game(self.found["game"], self.found["speed"]):
                self.found = None

    def _game(self, gid, speed):
        """-> found-dict als pot gid loopt, anders None (afgebroken, afgelopen, onbekend)."""
        if not gid:
            return None
        r = S.get(f"{BASE}/games/{gid}", headers=_auth(), timeout=15)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        g = r.json()
        if g.get("ended") or (g.get("gamedata") or {}).get("phase") != "play":
            return None
        pl = g.get("players") or {}
        opp = pl.get("white") if (pl.get("black") or {}).get("id") == me().get("id") else pl.get("black")
        return {"game": gid, "opp": (opp or {}).get("username", "?"), "speed": speed}

    def _keepalive(self, live):
        global _jwt
        import websocket
        if self._ws is None:
            if _jwt is None:
                _jwt = api("ui/config")["user_jwt"]
            self._ws = websocket.create_connection("wss://online-go.com/socket", timeout=5,
                                                   header=["User-Agent: flip-go/0.1"])
            self._ws.send(json.dumps(["authenticate", {"jwt": _jwt}, 1]))
        for c in live:
            self._ws.send(json.dumps(["challenge/keepalive", {"challenge_id": c["id"], "game_id": c["game"]}]))
        self._ws.settimeout(0.05)                 # wat de server stuurt leeg lezen, niet wachten
        try:
            for _ in range(20):
                self._ws.recv()
        except Exception:
            pass

    def _close(self):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None


seeker = Seeker()


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
