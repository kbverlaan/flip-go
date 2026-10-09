"""Minimale GTP-client: lokale engine (GNU Go / KataGo) als subprocess.
Engines + netten staan in engines/ naast de code (via flip-scp, niet via OTA).
Coördinaten: x,y met y=0 boven (zoals goban.py); GTP-rij 1 = onder.
"""
import json
import math
import os
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.join(HERE, "engines")
LETTERS = "ABCDEFGHJKLMNOPQRST"

# Offline tegenstanders: (label, kind, arg). gnugo-arg = level, katago-arg = human-profiel.
# Bergnamen = MiniGo-bergenladder (humanlike-net speelt als een mens van die rank).
# Laagste geldige profiel is 20k: een onbekend profiel (preaz_25k) laat KataGo crashen.
# katago-arg = (profiel, max_loss): de scheidsrechter keurt zetten af die meer dan
# max_loss punten weggeven (None = alleen pass/opgave bewaken).
# Volgorde = gemeten sterkte (testharnas 9 okt 2026, go-beginnerbot): het filter is een
# veel grotere sterkteknop dan het profiel. Zonder filter ~ Bouvardia-niveau (OGS ~24k).
BOTS = (
    ("Vaalserberg", "katago", ("preaz_25k", None)),   # vereist gepatchte KataGo (21k-30k)
    ("Zugspitze", "katago", ("preaz_20k", None)),
    ("Mont Blanc", "katago", ("preaz_15k", None)),
    ("Kilimanjaro", "katago", ("preaz_10k", None)),
    ("Denali", "katago", ("preaz_15k", 6)),
    ("Aconcagua", "katago", ("preaz_10k", 6)),
    ("Everest", "katago", ("preaz_10k", 3)),
    ("GNU Go 5", "gnugo", 5),
    ("GNU Go 10", "gnugo", 10),
)
HUMAN_NET = "b18c384nbt-humanv0.bin.gz"


def _weak_ok():
    """Profielen onder 20k bestaan alleen in de gepatchte KataGo (engines/katago.weak-ok)."""
    return os.path.exists(os.path.join(ENG, "katago.weak-ok"))


def _needs_patch(b):
    return b[1] == "katago" and int(_profile(b[2]).split("_")[1].rstrip("k")) > 20


def available():
    """Alleen bots waarvan de engine (en het profiel) op dit apparaat bestaan."""
    have = {"gnugo": os.path.exists(os.path.join(ENG, "gnugo")),
            "katago": os.path.exists(os.path.join(ENG, "katago"))
                      and os.path.exists(os.path.join(ENG, HUMAN_NET))}
    return [b for b in BOTS if have[b[1]] and (not _needs_patch(b) or _weak_ok())]


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

    def __init__(self, kind, arg, size=19):
        self.gpu = False
        if kind == "gnugo":
            cmd = [os.path.join(ENG, "gnugo"), "--mode", "gtp", "--level", str(arg),
                   "--japanese-rules"]
        else:   # humanlike-net als enig net, 1 visit = zet uit de menselijke policy
            # GPU (OpenCL FP16, Mali): 13x13 1,1 s i.p.v. 1,8 s en ~120 MB minder RAM.
            # Direct op de bordmaat starten: omschakelen kost 13 s (CPU) tot 27 s (GPU).
            self.gpu = _gpu_ok()
            d = os.path.join(ENG, "opencl") if self.gpu else ENG
            cmd = [os.path.join(d, "katago"), "gtp",
                   "-config", os.path.join(d, "gtp_human1.cfg"),
                   "-model", os.path.join(ENG, HUMAN_NET),
                   "-override-config", f"humanSLProfile={arg},defaultBoardSize={size}"]
        self.kind, self.arg = kind, arg
        self.lock = threading.Lock()
        err = open(os.path.join(ENG, "engine.log"), "a")    # waarom een engine stopt
        err.write(f"--- start {kind} {arg} {'gpu' if self.gpu else 'cpu'}\n")
        err.flush()
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=err, text=True, bufsize=1, cwd=ENG)
        self.size = size if kind == "katago" else 0     # KataGo start al op deze maat

    def new_game(self, size, komi, arg=None):
        """-> False als het profiel niet om te zetten is (dan opnieuw starten)."""
        if arg is not None and arg != self.arg:
            if not self.cmd(f"kata-set-param humanSLProfile {arg}")[0]:
                return False
            self.arg = arg
        if self.kind == "katago" and size != self.size:
            with _timed(("gpu" if self.gpu else "cpu") + f"-switch{size}"):
                self.cmd(f"boardsize {size}")       # nieuwe NN-context: 13 s (CPU) tot 27 s (GPU)
        self.size = size
        self.cmd(f"boardsize {size}")
        self.cmd("clear_board")
        if self.kind == "katago":
            self.cmd("kata-set-rules japanese")     # zoals de OGS-potten
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


_gpu_broken = False     # OpenCL faalde deze sessie: verder op de CPU


def _gpu_ok():
    d = os.path.join(ENG, "opencl")
    return (not _gpu_broken and os.path.exists(os.path.join(d, "katago"))
            and os.path.exists(os.path.join(d, "gtp_human1.cfg")))


# ---------- laadbalk ----------
# KataGo meldt in GTP-modus geen voortgang. Op hetzelfde apparaat is de laadtijd per
# (GPU/CPU, start/wissel, bordmaat) wel vrij constant: de balk loopt op de vorige meting.
# Stappen die op elkaar volgen (opstarten, afbreken, opnieuw) vormen één balk die nooit
# terugloopt: duurt het langer dan verwacht, dan blijft hij staan.
LOADTIMES = os.path.join(HERE, "conf", "loadtimes.json")
_bar = None             # {"t0", "exp", "phase": t0 lopende stap of None, "end", "shown"}


def _loadtimes():
    try:
        with open(LOADTIMES) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class _timed:
    def __init__(self, key):
        self.key = key

    def __enter__(self):
        global _bar
        now = time.monotonic()
        exp = _loadtimes().get(self.key, 30.0 if "start" in self.key else 20.0)
        if _bar and (_bar["phase"] or now - _bar["end"] < 2):     # vervolgstap: zelfde balk
            _bar.update(exp=(now - _bar["t0"]) + exp, phase=now)
        else:
            _bar = {"t0": now, "exp": exp, "phase": now, "end": 0, "shown": 0.0}

    def __exit__(self, exc, *_):
        now = time.monotonic()
        dt = now - _bar["phase"]
        _bar.update(phase=None, end=now)
        if exc is None:
            d = _loadtimes()
            d[self.key] = round(dt if self.key not in d else (d[self.key] + dt) / 2, 1)
            try:
                os.makedirs(os.path.dirname(LOADTIMES), exist_ok=True)
                with open(LOADTIMES, "w") as f:
                    json.dump(d, f)
            except OSError:
                pass


def load_progress():
    """-> 0..1 terwijl KataGo laadt of van bordmaat wisselt, anders None. Tot 90% lineair
    op de verwachte duur; daarna kruipt hij naar 99% en pas 'klaar' sluit hem af."""
    b = _bar
    if b is None or b["phase"] is None:
        return None
    el, exp = time.monotonic() - b["t0"], max(1.0, b["exp"])
    p = el / exp if el < 0.9 * exp else 0.9 + 0.09 * (1 - math.exp(-(el - 0.9 * exp) / (0.15 * exp)))
    b["shown"] = max(b["shown"], p)
    return b["shown"]


_loading = None         # KataGo die nu opstart (om af te breken bij een andere bordmaat)


def _start_human(prof, size, abortable=False):
    """Start + wacht tot geladen; valt bij een GPU-fout één keer terug op de CPU."""
    global _gpu_broken, _loading
    e = Engine("katago", prof, size)
    if abortable:
        _loading = e
    try:
        with _timed(("gpu" if e.gpu else "cpu") + f"-start{size}"):
            e.cmd("name")
        return e
    except OSError:
        if not e.gpu or getattr(e, "aborted", False):
            raise
        _gpu_broken = True
        return _start_human(prof, size, abortable)
    finally:
        if _loading is e:
            _loading = None


_warm = None            # warme KataGo, gedeeld tussen potten
_warm_lock = threading.Lock()
_judge = None           # warme b6-scheidsrechter (zie judge.py)


def _profile(arg):
    return arg[0] if isinstance(arg, (tuple, list)) else arg


def get_engine(kind, arg, size, komi):
    """GNU Go start in een flits: altijd vers. KataGo: hergebruik de warme."""
    global _warm
    if kind == "gnugo":
        e = Engine(kind, arg)
        e.new_game(size, komi)
        return e
    global _judge
    prof = _profile(arg)
    with _warm_lock:
        if _warm is None or _warm.p.poll() is not None:
            _warm = _start_human(prof, size)
        try:
            ok = _warm.new_game(size, komi, prof)
        except OSError:         # engine net gestorven (broken pipe): één keer opnieuw
            _warm = _start_human(prof, size)
            ok = _warm.new_game(size, komi)
        if not ok:
            _warm.close()
            _warm = _start_human(prof, size)
            _warm.new_game(size, komi)
        try:
            import judge
        except ImportError:
            return _warm
        if not judge.available():
            return _warm
        if _judge is None or _judge.p.poll() is not None:
            _judge = judge.Judge()
        e = judge.JudgedEngine(_warm, _judge, arg[1] if isinstance(arg, (tuple, list)) else None)
        e.size, e.komi = size, komi
        return e


_want = None            # bordmaat waarop de warme KataGo klaar moet staan


def preload(size=9):
    """KataGo alvast laden (bij openen van OFFLINE) of op de achtergrond naar de gekozen
    bordmaat omschakelen, zodat de eerste zet niet wacht. Wacht even: snel door de maten
    bladeren start niet elke maat."""
    global _want
    if not any(b[1] == "katago" for b in available()):
        return
    first = _want is None
    _want = size

    def go():
        global _warm
        if not first:
            time.sleep(0.8)
            if _want != size:
                return
            ld = _loading
            if ld is not None and ld.size != size and ld.p.poll() is None:
                ld.aborted = True       # nog aan het opstarten op een andere maat: opnieuw
                ld.p.kill()             # beginnen is sneller dan afmaken + omschakelen
        with _warm_lock:
            if _want != size:
                return
            try:
                if _warm is None or _warm.p.poll() is not None:
                    prof = _profile(next(b for b in available() if b[1] == "katago")[2])
                    _warm = _start_human(prof, size, abortable=True)   # blokkeert tot geladen
                elif _warm.size != size and size in (9, 13):    # 19x19 niet getuned: niet vooraf
                    _warm.new_game(size, 6.5)
            except OSError:
                _warm = None
    threading.Thread(target=go, daemon=True).start()


def is_warm():
    return _warm is not None and _warm.p.poll() is None and not _warm_lock.locked()
