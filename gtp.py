"""Minimale GTP-client: lokale engine (GNU Go / KataGo) als subprocess.
Engines + netten staan in engines/ naast de code (via flip-scp, niet via OTA).
Coördinaten: x,y met y=0 boven (zoals goban.py); GTP-rij 1 = onder.
"""
import os
import subprocess
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, "engines")
LETTERS = "ABCDEFGHJKLMNOPQRST"

# Offline tegenstanders: (label, kind, arg). gnugo-arg = level, katago-arg = human-profiel.
# Bergnamen = MiniGo-bergenladder (humanlike-net speelt als een mens van die rank).
BOTS = (
    ("Vaalserberg", "katago", "preaz_25k"),
    ("Zugspitze", "katago", "preaz_20k"),
    ("Fuji", "katago", "preaz_18k"),
    ("Mont Blanc", "katago", "preaz_15k"),
    ("Kilimanjaro", "katago", "preaz_10k"),
    ("GNU Go 5", "gnugo", 5),
    ("GNU Go 10", "gnugo", 10),
)
HUMAN_NET = "b18c384nbt-humanv0.bin.gz"


def available():
    """Alleen bots waarvan de engine op dit apparaat staat."""
    have = {"gnugo": os.path.exists(os.path.join(ENG, "gnugo")),
            "katago": os.path.exists(os.path.join(ENG, "katago"))
                      and os.path.exists(os.path.join(ENG, HUMAN_NET))}
    return [b for b in BOTS if have[b[1]]]


def to_gtp(x, y, size):
    return "pass" if x < 0 else f"{LETTERS[x]}{size - y}"


def from_gtp(v, size):
    v = v.strip().upper()
    if v in ("PASS", "RESIGN"):
        return v.lower()
    return LETTERS.index(v[0]), size - int(v[1:])


class Engine:
    """Eén GTP-proces. KataGo laden kost ~30 s op de Flip: die blijft warm
    (zie get_engine) en krijgt per pot alleen een nieuw bord/profiel."""

    def __init__(self, kind, arg):
        if kind == "gnugo":
            cmd = [os.path.join(ENG, "gnugo"), "--mode", "gtp", "--level", str(arg),
                   "--chinese-rules"]
        else:   # humanlike-net als enig net, 1 visit = zet uit de menselijke policy
            cmd = [os.path.join(ENG, "katago"), "gtp",
                   "-config", os.path.join(ENG, "gtp_human1.cfg"),
                   "-model", os.path.join(ENG, HUMAN_NET),
                   "-override-config", f"humanSLProfile={arg}"]
        self.kind, self.arg = kind, arg
        self.lock = threading.Lock()
        err = open(os.path.join(ENG, "engine.log"), "a")    # waarom een engine stopt
        err.write(f"--- start {kind} {arg}\n")
        err.flush()
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=err, text=True, bufsize=1, cwd=ENG)
        self.size = 0

    def new_game(self, size, komi, arg=None):
        """-> False als het profiel niet om te zetten is (dan opnieuw starten)."""
        if arg is not None and arg != self.arg:
            if not self.cmd(f"kata-set-param humanSLProfile {arg}")[0]:
                return False
            self.arg = arg
        self.size = size
        self.cmd(f"boardsize {size}")
        self.cmd("clear_board")
        self.cmd(f"komi {komi}")
        return True

    def cmd(self, line):
        """-> (ok, antwoord) volgens GTP: '= ...' of '? ...', afgesloten met lege regel."""
        with self.lock:
            return self._cmd(line)

    def _cmd(self, line):
        if self.p.poll() is not None:
            raise OSError(f"engine stopped (exit {self.p.returncode})")
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        out = []
        while True:
            ln = self.p.stdout.readline()
            if not ln:
                raise OSError("engine stopped mid-reply")
            if ln.strip() == "" and out:
                break
            if ln.strip():
                out.append(ln.strip())
        resp = " ".join(out)
        return resp.startswith("="), resp[1:].strip()

    def play(self, color, x, y):
        return self.cmd(f"play {color} {to_gtp(x, y, self.size)}")[0]

    def genmove(self, color):
        ok, v = self.cmd(f"genmove {color}")
        return from_gtp(v, self.size) if ok else "resign"

    def score(self):
        """'B+3.5' / 'W+12.5' of None."""
        ok, v = self.cmd("final_score")
        return v if ok and v[:2] in ("B+", "W+") else None

    def close(self):
        try:
            self.cmd("quit")
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


_warm = None            # warme KataGo, gedeeld tussen potten
_warm_lock = threading.Lock()


def get_engine(kind, arg, size, komi):
    """GNU Go start in een flits: altijd vers. KataGo: hergebruik de warme."""
    global _warm
    if kind == "gnugo":
        e = Engine(kind, arg)
        e.new_game(size, komi)
        return e
    with _warm_lock:
        if _warm is None or _warm.p.poll() is not None:
            _warm = Engine(kind, arg)
        try:
            ok = _warm.new_game(size, komi, arg)
        except OSError:         # engine net gestorven (broken pipe): één keer opnieuw
            _warm = Engine(kind, arg)
            ok = _warm.new_game(size, komi)
        if not ok:
            _warm.close()
            _warm = Engine(kind, arg)
            _warm.new_game(size, komi)
        return _warm


def preload():
    """KataGo alvast laden (bij openen van OFFLINE), zodat de eerste zet niet wacht."""
    if not any(b[1] == "katago" for b in available()):
        return
    def go():
        global _warm
        with _warm_lock:
            if _warm is None or _warm.p.poll() is not None:
                _warm = Engine("katago", BOTS[1][2])
                _warm.cmd("name")       # blokkeert tot het net geladen is
    threading.Thread(target=go, daemon=True).start()


def is_warm():
    return _warm is not None and _warm.p.poll() is None and not _warm_lock.locked()
