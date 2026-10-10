"""Review na een offline pot: verlies per zet, blunders, de 3 duurste momenten en hun categorie.

evals: {beurt t: {"lead": scoreLead (zwart-perspectief) van de stelling na t zetten,
                   "best": beste zet (GTP, bv. "D4") in die stelling}}
Verlies van zet t = score vóór - score na, vanuit de speler aan zet. Categorieën volgen de
MiniGo-taxonomie (app.py _classify_mistake) plus 'Passed'. Puur Python: testbaar op de Mac.
"""
import calendar
import json
import math
import os
import time

import goban

LET = "ABCDEFGHJKLMNOPQRST"
BLUNDER = 6.0
CATS = {   # label + twee regels uitleg, elk <= 10 tekens (past in het zijpaneel bij 8px)
    "selfatari": ("Self-atari", "Own stones", "in atari"),
    "atari": ("Atari", "Capture or", "save group"),
    "ignored": ("Ignored", "Answer the", "threat"),
    "cut": ("Cut/link", "Groups got", "cut apart"),
    "endgame": ("Endgame", "Boundary", "move"),
    "bigpoint": ("Big point", "Bigger", "elsewhere"),
    "local": ("Local", "Better", "shape here"),
    "passed": ("Passed", "Passed", "too early"),
}
VERSION = 3       # opslagformaat reviews.jsonl (v3: per zet, beide kleuren)

# Zetklassen naar chess.com/ogs-review (verlies in punten): (sleutel, label, symbool, max-verlies)
CLASSES = (("best", "Best", "", 0.3), ("good", "Good", "", 1.5), ("inacc", "Inaccuracy", "?!", 3.0),
           ("mistake", "Mistake", "?", 6.0), ("blunder", "Blunder", "??", 1e9))


# Accuracy (zoals schaaksites; hoger = beter): per eigen zet 100 * e^(-verlies / ACC_K),
# gemiddeld over de pot. 0 pt = 100%, 1,5 (grens Good) ~74%, 3 ~55%, 6 (Blunder) ~30%.
ACC_K = 5.0


def move_acc(lost):
    return 100.0 * math.exp(-max(0.0, lost) / ACC_K)


def accuracy(entry):
    """Accuracy van een opgeslagen review; oude regels uit hun verlies per zet ('mine')."""
    if entry.get("accuracy") is not None:
        return entry["accuracy"]
    lost = [m[1] for m in entry.get("mine") or []] or \
           [r["lost"] for r in entry.get("rows") or [] if r["col"] == entry.get("human", 1)]
    return round(sum(move_acc(x) for x in lost) / len(lost), 1) if lost else None


def moves_of(entry):
    """Eigen zetten van een review als (verlies, klasse, fase): uit 'mine' of uit 'rows'."""
    if entry.get("mine"):
        return [(m[1], m[2], m[4]) for m in entry["mine"]]
    h = entry.get("human", 1)
    return [(r["lost"], r["cls"], r["phase"]) for r in entry.get("rows") or [] if r["col"] == h]


def phase_acc(entry, ph):
    lost = [x for x, _, p in moves_of(entry) if p == ph]
    return sum(move_acc(x) for x in lost) / len(lost) if lost else None


def move_class(lost, played_is_best=False):
    if played_is_best:
        return "best"
    for key, _, _, hi in CLASSES:
        if lost < hi:
            return key
    return "blunder"


def phase_of(t, board, size):
    """Fase per bord (niet als fractie van de pot): opening = eerste 10 (9x9) / 20 (13x13) zetten,
    eind = bord >= 55% bezet, anders midden."""
    if t < (10 if size <= 9 else 20):
        return "open"
    filled = sum(1 for r in board for v in r if v) / (size * size)
    return "end" if filled >= 0.55 else "mid"


def gtp_xy(m, size):
    if not m or m.lower() == "pass":
        return None
    return LET.index(m[0].upper()), size - int(m[1:])


def _libs(board, x, y):
    grp, _ = goban._group(board, x, y)
    size, libs = len(board), set()
    for gx, gy in grp:
        for nx, ny in goban._nbrs(gx, gy, size):
            if board[ny][nx] == 0:
                libs.add((nx, ny))
    return len(libs)


def _groups_adj(board, x, y, c):
    """Unieke groepen van kleur c naast (x,y): lijst (stenen, vrijheden)."""
    size, seen, out = len(board), set(), []
    for nx, ny in goban._nbrs(x, y, size):
        if board[ny][nx] == c and (nx, ny) not in seen:
            grp, _ = goban._group(board, nx, ny)
            seen |= grp
            out.append((grp, _libs(board, nx, ny)))
    return out


def classify(board, n, played, answer, lost, prev, col):
    """Soort fout (niet de grootte: die toont het getal al). Eerste regel die past wint.
    board = stand vóór de zet; played/answer/prev = (x,y) of None; col = speler aan zet (1/2)."""
    if played is None:
        return "passed"
    size, opp = len(board), 3 - col
    far = 3 if size <= 9 else 4
    dist = lambda a, b: max(abs(a[0] - b[0]), abs(a[1] - b[1])) if a and b else 99
    # 1. eigen stenen in atari gezet (zonder iets te slaan)
    after = [r[:] for r in board]
    caps = goban.apply_move(after, played[0], played[1], col)
    if caps == 0 and after[played[1]][played[0]] == col and _libs(after, played[0], played[1]) == 1:
        return "selfatari"
    if answer is None:
        return "local"
    bx, by = answer
    # 2. de betere zet slaat of redt stenen in atari
    if any(l == 1 for _, l in _groups_adj(board, bx, by, opp) + _groups_adj(board, bx, by, col)):
        return "atari"
    # 3. dreiging genegeerd: vorige zet bracht een eigen groep naar <= 2 vrijheden, het antwoord
    #    raakt die groep en jij speelde ver weg
    if prev:
        weak = [g for g, l in _groups_adj(board, prev[0], prev[1], col) if l <= 2]
        if weak and any(any((nx, ny) in g for g in weak) for nx, ny in goban._nbrs(bx, by, size)) \
                and dist(played, answer) >= far:
            return "ignored"
    # 4. eindspel: bord grotendeels vol, rand, klein verlies (vóór Cut: op een vol bord
    #    raakt bijna elk randpunt twee groepen)
    empty = sum(1 for r in board for v in r if v == 0) / (size * size)
    if empty <= 0.45 and min(bx, by, size - 1 - bx, size - 1 - by) <= 1 and lost < 6:
        return "endgame"
    # 5. snijden/verbinden: het antwoord grenst aan >= 2 groepen van één kleur, en minstens
    #    één daarvan is kwetsbaar (<= 3 vrijheden)
    for c in (col, opp):
        gs = _groups_adj(board, bx, by, c)
        if len(gs) >= 2 and any(l <= 3 for _, l in gs):
            return "cut"
    # 6. groot punt elders
    if dist(played, answer) >= far and dist(prev, answer) >= far:
        return "bigpoint"
    return "local"

def compute(size, moves, evals, human=1, deep=None):
    """-> dict met per-zet-analyse (beide kleuren) + samenvatting, of None bij te weinig data.
    evals[t] = stand vóór zet t (8 visits, uniform): {"lead": scoreLead zwart, "best": GTP, "pv": [...]}
    deep[t] = zelfde, nauwkeuriger (30 visits) voor opnieuw doorgerekende eigen fouten. Een verlies
    vergelijkt altijd binnen één visits-niveau (anders ontstaat een zaagtand van schijnfouten)."""
    deep = deep or {}
    board = [[0] * size for _ in range(size)]
    rows, prev = [], None
    for t, (x, y) in enumerate(moves):
        col = 1 if t % 2 == 0 else 2
        played = None if x < 0 else (x, y)
        src = deep if (col == human and t in deep and t + 1 in deep) else evals
        if t in src and t + 1 in src:
            sign = 1 if col == 1 else -1
            lost = sign * (src[t]["lead"] - src[t + 1]["lead"])
            answer = gtp_xy(src[t].get("best"), size)
            is_best = played == answer
            if is_best:
                lost = min(lost, 0.0)
            if not (played is None and answer is None):          # passen dat klopt: geen zet
                cls = move_class(max(0.0, lost), is_best)
                nxt = moves[t + 1] if t + 1 < len(moves) else None
                rows.append({
                    "t": t, "col": col, "lost": round(lost, 2), "cls": cls,
                    "cat": classify([r[:] for r in board], t, played, answer, max(lost, 0), prev, col)
                    if cls in ("inacc", "mistake", "blunder") else None,
                    "phase": phase_of(t, board, size), "played": played, "answer": answer,
                    "reply": tuple(nxt) if nxt and nxt[0] >= 0 else None,
                    "pv": [gtp_xy(m, size) for m in src[t].get("pv") or []]})
        if played:
            goban.apply_move(board, x, y, col)
            prev = played
    mine = [r for r in rows if r["col"] == human]
    if len(mine) < 5:
        return None
    counts = lambda rs: {k: sum(1 for r in rs if r["cls"] == k) for k, *_ in CLASSES}
    cats = lambda rs, k: {c: sum(1 for r in rs if r["cls"] == k and r["cat"] == c) for c in CATS
                          if any(r["cls"] == k and r["cat"] == c for r in rs)}
    loss = lambda rs: round(sum(max(0.0, r["lost"]) for r in rs) / len(rs), 2) if rs else None
    return {
        "v": VERSION, "moves": len(moves), "rows": rows,
        "loss_per_move": loss(mine),
        "accuracy": round(sum(move_acc(r["lost"]) for r in mine) / len(mine), 1),
        "phases": {ph: loss([r for r in mine if r["phase"] == ph]) for ph in ("open", "mid", "end")
                   if any(r["phase"] == ph for r in mine)},
        "me": counts(mine), "opp": counts([r for r in rows if r["col"] != human]),
        "types": {k: cats(mine, k) for k in ("blunder", "mistake", "inacc")},
        "leads": [round(evals[t]["lead"], 1) for t in range(len(moves) + 1) if t in evals],
    }


def recheck(rows, limit=20):
    """Welke beurten opnieuw doorrekenen met meer visits: alle eigen mistakes/blunders (max limit)."""
    bad = sorted((r for r in rows if r["cls"] in ("mistake", "blunder")), key=lambda r: -r["lost"])
    return [r["t"] for r in bad[:limit]]


# ---------- opslag ----------
def save(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    slim = {k: v for k, v in entry.items() if k != "rows"}
    slim["mine"] = [[r["t"], r["lost"], r["cls"], r["cat"], r["phase"]]     # compact per eigen zet
                    for r in entry.get("rows", []) if r["col"] == entry.get("human", 1)]
    with open(path, "a") as f:
        f.write(json.dumps(slim, separators=(",", ":")) + "\n")


def history(path, size=None, n=10, src=None):
    """Laatste n reviews op datum (oude OGS-potten komen op hun eigen plek); kapotte regels
    en oude formaten overslaan; opnieuw geanalyseerde potten één keer. src: 'ogs'|'off'|None."""
    rows = {}
    try:
        for i, line in enumerate(open(path)):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("v") == VERSION:
                rows[r.get("key") or i] = r
    except OSError:
        return []
    rows = list(rows.values())
    if size:
        rows = [r for r in rows if r.get("size") == size]
    if src:
        rows = [r for r in rows if r.get("src", "off") == src]
    rows.sort(key=lambda r: r.get("ts") or _date_ts(r.get("date")))
    return rows[-n:]


def _date_ts(d):
    try:
        return calendar.timegm(time.strptime(d, "%Y-%m-%d"))
    except (TypeError, ValueError):
        return 0
