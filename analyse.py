"""Oude potten analyseren (OGS + offline) en volledige reviews bewaren.

Eén eigen b6-analyse-engine met 4 analysethreads: KataGo rekent dan 4 stellingen tegelijk,
~3-4x sneller dan stelling voor stelling. Een wachtrij werkt potten af op de achtergrond;
de History-schermen tonen de voortgang. Volledige review per pot (met zetten, voor WALK) in
conf/reviews/<sleutel>.json, de samenvatting voor STATS in conf/reviews.jsonl.
"""
import calendar
import json
import os
import subprocess
import threading
import time

import judge
import ogs
import review

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "conf")
REVIEWS = os.path.join(CONF, "reviews.jsonl")
FULL = os.path.join(CONF, "reviews")
LETTERS = "ABCDEFGHJKLMNOPQRST"
THREADS = 4
DEEP = 3            # werk van een stelling op 30 visits t.o.v. 8 visits (voortgangsbalk)
RULES = {"nz": "new-zealand", "ing": "chinese"}


# ---------- volledige reviews ----------
def _tuples(r):
    """JSON maakt van (x,y) een lijst; WALK vergelijkt met tuples."""
    for row in r.get("rows", []):
        for k in ("played", "answer", "reply"):
            if row.get(k) is not None:
                row[k] = tuple(row[k])
        row["pv"] = [tuple(p) if p else None for p in row.get("pv") or []]
    return r


def store(key, r, moves):
    """Volledige review (+ zetten) apart; samenvatting in reviews.jsonl voor STATS."""
    os.makedirs(FULL, exist_ok=True)
    r = dict(r, key=key)
    tmp = os.path.join(FULL, key + ".json.tmp")
    with open(tmp, "w") as f:
        json.dump(dict(r, game_moves=moves), f, separators=(",", ":"))
    os.replace(tmp, os.path.join(FULL, key + ".json"))
    review.save(REVIEWS, r)


def load(key):
    try:
        with open(os.path.join(FULL, key + ".json")) as f:
            return _tuples(json.load(f))
    except (OSError, ValueError):
        return None


def done_keys():
    try:
        return {n[:-5] for n in os.listdir(FULL) if n.endswith(".json")}
    except OSError:
        return set()


def local_games():
    """Offline potten met volledige review, nieuwste eerst (voor de History-lijst)."""
    out = []
    for key in done_keys():
        if key.startswith("off-"):
            r = load(key)
            if r:
                out.append({"key": key, "src": "off", "opp": r.get("bot", "?"), "won": r.get("won"),
                            "size": r.get("size"), "ts": r.get("ts", 0),
                            "result": f"{r.get('loss_per_move', 0):.1f}/mv"})
    return out


# ---------- engine ----------
class BatchJudge(judge.Judge):
    """b6-analyse met THREADS stellingen tegelijk (één query met analyzeTurns)."""

    def __init__(self):
        err = open(os.path.join(judge.ENG, "engine.log"), "a")
        err.write("--- start batch-judge\n")
        err.flush()
        self.p = subprocess.Popen(
            [os.path.join(judge.ENG, "katago"), "analysis", "-config", os.path.join(judge.ENG, judge.JUDGE_CFG),
             "-model", os.path.join(judge.ENG, judge.JUDGE_NET),
             "-override-config", f"numAnalysisThreads={THREADS},numSearchThreadsPerAnalysisThread=1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1, cwd=judge.ENG)
        self.qid = 0
        self.lock = threading.Lock()

    def turns(self, moves, size, komi, rules, turns, visits, out, step, stop):
        """Stand na moves[:t] voor elke t in turns -> out[t] (zoals JudgedEngine._remember)."""
        if not turns:
            return
        with self.lock:
            self.qid += 1
            qid = str(self.qid)
            self.p.stdin.write(json.dumps(dict(
                id=qid, moves=moves, rules=rules, komi=komi, boardXSize=size, boardYSize=size,
                maxVisits=visits, analyzeTurns=sorted(turns))) + "\n")
            self.p.stdin.flush()
            left = set(turns)
            while left:
                if stop():
                    raise InterruptedError
                ln = self.p.stdout.readline()
                if not ln:
                    raise OSError("judge stopped mid-reply")
                r = json.loads(ln)
                if r.get("id") != qid:
                    continue
                if "error" in r:
                    raise OSError(f"judge: {r['error']}")
                if "rootInfo" in r:
                    t = r["turnNumber"]
                    judge.JudgedEngine._remember(out, t, r)
                    left.discard(t)
                    step()


def analyse(size, moves, komi, rules, human, eng, progress, stop):
    """Volledige review van een pot. moves: [(x,y)] (x<0 = pass). progress(0..1)."""
    gm = [["B" if i % 2 == 0 else "W", "pass" if x < 0 else f"{LETTERS[x]}{size - y}"]
          for i, (x, y) in enumerate(moves)]
    n_mine = sum(1 for i in range(len(moves)) if (i % 2 == 0) == (human == 1))
    est = min(20, max(2, n_mine // 5))          # schatting eigen mistakes/blunders; zie rebase
    work = {"base": 0.0, "done": 0, "total": len(moves) + 1 + 2 * DEEP * est}

    def step(w=1):                              # nooit teruglopen (zelfde idee als in main.py)
        work["done"] += w
        progress(min(0.99, work["base"] + (1 - work["base"]) * work["done"] / work["total"]))
    ev = {}
    eng.turns(gm, size, komi, rules, range(len(moves) + 1), judge.VISITS, ev, step, stop)
    r = review.compute(size, moves, ev, human=human)
    if not r:
        return None
    todo = review.recheck(r["rows"])
    work.update(base=min(0.99, work["base"] + (1 - work["base"]) * work["done"] / work["total"]),
                done=0, total=max(1, 2 * DEEP * len(todo)))
    evd = {}
    eng.turns(gm, size, komi, rules, {u for t in todo for u in (t, t + 1)}, 30, evd,
              lambda: step(DEEP), stop)
    return review.compute(size, moves, ev, human=human, deep=evd)


def _iso_ts(s):
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return 0


def analyse_ogs(gid, eng, progress, stop):
    """-> (sleutel, review) of (None, foutmelding)."""
    g = ogs.api(f"games/{gid}")
    gd = g.get("gamedata") or {}
    size = gd.get("width")
    if size != gd.get("height") or size not in (9, 13, 19):
        return None, "odd board"
    if gd.get("handicap") or any((gd.get("initial_state") or {}).values()) \
            or gd.get("initial_player", "black") != "black":
        return None, "handicap"
    mid = ogs.me().get("id")
    human = 1 if gd["players"]["black"]["id"] == mid else 2
    moves = [(m[0], m[1]) for m in gd.get("moves", [])]
    rules = RULES.get(gd.get("rules"), gd.get("rules") or "japanese")
    r = analyse(size, moves, gd.get("komi", 6.5), rules, human, eng, progress, stop)
    if not r:
        return None, "too short"
    won = bool(g.get("white_lost") if human == 1 else g.get("black_lost"))
    opp = gd["players"]["white" if human == 1 else "black"].get("username", "?")
    ts = _iso_ts(g.get("ended"))
    r.update(size=size, bot=opp, won=won, human=human, src="ogs", gid=gid, ts=ts,
             date=time.strftime("%Y-%m-%d", time.gmtime(ts)))
    key = f"ogs-{gid}"
    store(key, r, [list(m) for m in moves])
    return key, r


# ---------- wachtrij ----------
class Worker:
    """Analyseert OGS-potten op de achtergrond, één tegelijk. status[gid] = 0..1 | 'done' | fout."""

    def __init__(self):
        self.queue, self.status, self.cur = [], {}, None
        self._stop = False
        self._thread = None
        self._eng = None

    def add(self, gids):
        for gid in gids:
            if gid not in self.queue and self.status.get(gid) != "done" and gid != self.cur:
                self.queue.append(gid)
                self.status[gid] = "queued"
        self._stop = False
        if not (self._thread and self._thread.is_alive()):
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def busy(self):
        return bool(self.queue) or self.cur is not None

    def stop(self):
        """Wachtrij leeg en lopende analyse afbreken (bijv. bij een offline pot: CPU vrij)."""
        self._stop = True
        for gid in self.queue:
            self.status.pop(gid, None)
        self.queue = []

    def _run(self):
        while self.queue and not self._stop:
            gid = self.cur = self.queue.pop(0)
            try:
                if self._eng is None or self._eng.p.poll() is not None:
                    self._eng = BatchJudge()
                self.status[gid] = 0.0
                key, res = analyse_ogs(gid, self._eng, lambda p: self.status.__setitem__(gid, p),
                                       lambda: self._stop)
                self.status[gid] = "done" if key else res
            except InterruptedError:
                self.status.pop(gid, None)
                self._close()                    # half beantwoorde query: engine weggooien
            except Exception as e:
                print("analyse:", gid, e)
                self.status[gid] = "failed"
            self.cur = None
        self._close()                            # klaar: geheugen en CPU vrij

    def _close(self):
        if self._eng is not None:
            self._eng.close()
            self._eng = None


worker = Worker()
