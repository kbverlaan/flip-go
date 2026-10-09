"""Scheidsrechter voor de humanlike-bots (offline).

Het humanlike-net (1 netwerk-evaluatie, `kata-raw-nn 0`) levert de menselijke
kansverdeling; daaruit trekken we een zet. Een klein net (b6) als KataGo-analyse-engine
beslist over passen en opgeven en keurt zetten af die meer dan `max_loss` punten
weggeven (de sterkteknop per berg). Zo blijft de zet menselijk, maar speelt de bot een
pot netjes uit en verdwijnen de grofste blunders.
"""
import json
import os
import random
import subprocess
import threading
import time

ENG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engines")
JUDGE_NET = "b6c96.bin.gz"
JUDGE_CFG = "judge_analysis.cfg"
LETTERS = "ABCDEFGHJKLMNOPQRST"
VISITS = 8           # genoeg voor pass/opgave/grove blunders; ~0,7 s op 13x13 (Flip)
TEMPERATURE = 0.8      # trekken uit de menselijke policy (lager = vaker de topzet)
TRIES = 4              # max. aantal menselijke kandidaten dat we laten keuren


def available():
    return (os.path.exists(os.path.join(ENG, JUDGE_NET))
            and os.path.exists(os.path.join(ENG, JUDGE_CFG)))


class Judge:
    """b6-net als KataGo-analyse-engine (JSON over stdin/stdout)."""

    def __init__(self):
        err = open(os.path.join(ENG, "engine.log"), "a")
        err.write("--- start judge\n")
        err.flush()
        self.p = subprocess.Popen(
            [os.path.join(ENG, "katago"), "analysis", "-config", os.path.join(ENG, JUDGE_CFG),
             "-model", os.path.join(ENG, JUDGE_NET)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1,
            cwd=ENG)
        self.qid = 0
        self.lock = threading.Lock()

    def analyze(self, moves, size, komi, extra=None):
        """-> response-dict (rootInfo/moveInfos) voor de stand na `moves`."""
        with self.lock:
            if self.p.poll() is not None:
                raise OSError("judge stopped")
            self.qid += 1
            q = dict(id=str(self.qid), moves=moves, rules="japanese", komi=komi,
                     boardXSize=size, boardYSize=size, maxVisits=VISITS,
                     analyzeTurns=[len(moves)])
            q.update(extra or {})
            self.p.stdin.write(json.dumps(q) + "\n")
            self.p.stdin.flush()
            while True:
                ln = self.p.stdout.readline()
                if not ln:
                    raise OSError("judge stopped mid-reply")
                r = json.loads(ln)
                if r.get("id") == q["id"] and ("rootInfo" in r or "error" in r):
                    if "error" in r:
                        raise OSError(f"judge: {r['error']}")
                    return r

    def close(self):
        try:
            self.p.kill()
        except Exception:
            pass


class JudgedEngine:
    """Zelfde interface als gtp.Engine (play/genmove/score/new_game/close)."""
    kind = "katago"

    def __init__(self, human, judge, max_loss):
        self.human, self.judge, self.max_loss = human, judge, max_loss
        self.p = human.p           # voor warm-checks in gtp.py
        self.arg = human.arg
        self.size, self.komi, self.moves, self.behind = 9, 6.5, [], 0
        self.rng = random.Random()

    def new_game(self, size, komi, arg=None):
        ok = self.human.new_game(size, komi, arg)
        self.arg = self.human.arg
        self.size, self.komi, self.moves, self.behind = size, komi, [], 0
        return ok

    def _gtp(self, x, y):
        return "pass" if x < 0 else f"{LETTERS[x]}{self.size - y}"

    def play(self, color, x, y):
        if not self.human.play(color, x, y):
            return False
        self.moves.append([color, self._gtp(x, y)])
        return True

    def _lead(self, r, col):
        s = r["rootInfo"]["scoreLead"]          # zwart-perspectief (judge-config)
        return s if col == "B" else -s

    def _policy(self):
        ok, txt = self.human.cmd("kata-raw-nn 0")
        tok = txt.split()
        i = tok.index("policy") + 1
        probs = {}
        for k in range(self.size * self.size):
            v = tok[i + k]
            if v != "NAN" and float(v) > 0:
                y, x = divmod(k, self.size)
                probs[(x, y)] = float(v)
        return probs

    def _draw(self, probs):
        items = [(m, p ** (1.0 / TEMPERATURE)) for m, p in probs.items()]
        tot = sum(w for _, w in items)
        r = self.rng.random() * tot
        for m, w in items:
            r -= w
            if r <= 0:
                return m
        return items[-1][0] if items else None

    def genmove(self, color):
        t0 = time.monotonic()
        # scheidsrechter en humanlike-net zijn aparte processen: tegelijk laten rekenen
        pol = {}
        th = threading.Thread(target=lambda: pol.update(p=self._policy()))
        th.start()
        root = self.judge.analyze(self.moves, self.size, self.komi)
        t_root = time.monotonic() - t0
        t_pol, checks = 0.0, 0
        known = {m["move"].upper(): self._lead({"rootInfo": m}, color)
                 for m in root.get("moveInfos", [])}
        lead = self._lead(root, color)
        best = (root.get("moveInfos") or [{"move": "pass"}])[0]["move"].lower()
        area = self.size * self.size
        if best == "pass":                     # pot is af (of passen is echt het beste)
            mv = "pass"
        else:
            if len(self.moves) > 0.4 * area:   # opgeven: 3 eigen beurten ruim achter
                self.behind = self.behind + 1 if lead < -(20 if self.size <= 9 else 30) else 0
                if self.behind >= 3:
                    return "resign"
            th.join()
            probs = pol["p"]
            t_pol = time.monotonic() - t0
            mv, best_loss = None, None
            for _ in range(TRIES):
                if not probs:
                    break
                c = self._draw(probs)
                if self.max_loss is None:
                    mv = c
                    break
                g = self._gtp(*c)
                if g.upper() in known:             # al door de scheidsrechter bekeken
                    loss = lead - known[g.upper()]
                else:
                    checks += 1
                    r = self.judge.analyze(self.moves, self.size, self.komi, {
                        "allowMoves": [{"player": color, "moves": [g], "untilDepth": 1}]})
                    loss = lead - self._lead(r, color)
                if loss <= self.max_loss:
                    mv = c
                    break
                if best_loss is None or loss < best_loss[0]:
                    best_loss = (loss, c)
                probs.pop(c)
            if mv is None:
                mv = best_loss[1] if best_loss else "pass"
        print(f"judge: zet {len(self.moves)+1} root {t_root:.2f}s policy {t_pol:.2f}s "
              f"checks {checks} totaal {time.monotonic()-t0:.2f}s", flush=True)
        th.join()                              # policy-thread nooit laten hangen
        if mv == "pass":
            self.human.cmd(f"play {color} pass")
            self.moves.append([color, "pass"])
            return "pass"
        x, y = mv
        self.human.cmd(f"play {color} {self._gtp(x, y)}")
        self.moves.append([color, self._gtp(x, y)])
        return x, y

    def score(self):
        r = self.judge.analyze(self.moves, self.size, self.komi)
        s = r["rootInfo"]["scoreLead"]
        pts = max(0.5, round(abs(s) * 2) / 2)
        if pts == int(pts):                    # komi .5 -> altijd halve punten
            pts += 0.5
        return f"{'B' if s > 0 else 'W'}+{pts:g}"

    def close(self):
        pass                                   # human en judge blijven warm (gtp.py)
