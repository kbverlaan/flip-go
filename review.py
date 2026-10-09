"""Review na een offline pot: verlies per zet, blunders, de 3 duurste momenten en hun categorie.

evals: {beurt t: {"lead": scoreLead (zwart-perspectief) van de stelling na t zetten,
                   "best": beste zet (GTP, bv. "D4") in die stelling}}
Verlies van zet t = score vóór - score na, vanuit de speler aan zet. Categorieën volgen de
MiniGo-taxonomie (app.py _classify_mistake) plus 'Passed'. Puur Python: testbaar op de Mac.
"""
import json
import os

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
VERSION = 2       # opslagformaat reviews.jsonl (categorieën v2)


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

def compute(size, moves, evals, human=1, pick_from=None):
    """-> dict met samenvatting, of None als er te weinig evaluaties zijn.
    pick_from: set beurten waaruit de 3 momenten gekozen worden (de diep doorgerekende top-5)."""
    board = [[0] * size for _ in range(size)]
    rows, prev = [], None
    for t, (x, y) in enumerate(moves):
        col = 1 if t % 2 == 0 else 2
        mine = col == human
        if mine and t in evals and t + 1 in evals:
            sign = 1 if col == 1 else -1
            lost = sign * (evals[t]["lead"] - evals[t + 1]["lead"])
            played = None if x < 0 else (x, y)
            answer = gtp_xy(evals[t].get("best"), size)
            if played is None and answer is None:      # passen was ook het beste: geen zet
                if x >= 0:
                    goban.apply_move(board, x, y, col)
                continue
            if played is not None and answer == played:
                lost = min(lost, 0.0)          # de beste zet zelf kost niets
            nxt = moves[t + 1] if t + 1 < len(moves) else None
            rows.append({"t": t, "lost": round(lost, 2), "played": played, "answer": answer,
                         "reply": tuple(nxt) if nxt and nxt[0] >= 0 else None,
                         "pv": [gtp_xy(m, size) for m in evals[t].get("pv") or []],
                         "cat": classify([r[:] for r in board], t, played, answer, max(lost, 0), prev, col),
                         "board": [r[:] for r in board], "prev": prev})
        if x >= 0:
            goban.apply_move(board, x, y, col)
            prev = (x, y)
    if len(rows) < 5:
        return None
    n = len(moves)
    phase = lambda t: "open" if t < 0.15 * n else "end" if t >= 0.75 * n else "mid"
    loss = [max(0.0, r["lost"]) for r in rows]
    by_phase = {}
    for r in rows:
        by_phase.setdefault(phase(r["t"]), []).append(max(0.0, r["lost"]))
    mistakes = [r for r in rows if r["lost"] >= 2.0]
    cats = {}
    for r in mistakes:
        cats[r["cat"]] = cats.get(r["cat"], 0) + 1
    ranked = sorted(rows, key=lambda r: -r["lost"])
    cands = [r["t"] for r in ranked[:5]]
    cands += [r["t"] for r in ranked[5:] if r["lost"] >= BLUNDER][:8]   # blunders = kopgetal
    pool = [r for r in ranked if pick_from is None or r["t"] in pick_from]
    top = pool[:3]
    return {
        "v": VERSION, "candidates": cands,
        "moves": n, "my_moves": len(rows),
        "loss_per_move": round(sum(loss) / len(loss), 2),
        "blunders": sum(1 for v in loss if v >= BLUNDER),
        "phases": {k: round(sum(v) / len(v), 2) for k, v in by_phase.items()},
        "cats": cats,
        "moments": [{"t": r["t"], "lost": r["lost"], "cat": r["cat"], "played": r["played"],
                     "answer": r["answer"], "board": r["board"], "prev": r["prev"],
                     "reply": r["reply"], "pv": r["pv"]} for r in top if r["lost"] > 0.5],
    }


# ---------- opslag ----------
def save(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    slim = dict(entry)
    slim["moments"] = [{k: v for k, v in m.items() if k != "board"} for m in entry.get("moments", [])]
    slim.pop("candidates", None)
    with open(path, "a") as f:
        f.write(json.dumps(slim, separators=(",", ":")) + "\n")


def history(path, size=None, n=10):
    """Laatste n reviews; kapotte regels (bv. half geschreven) en oude formaten overslaan."""
    rows = []
    try:
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("v") == VERSION:
                rows.append(r)
    except OSError:
        return []
    if size:
        rows = [r for r in rows if r.get("size") == size]
    return rows[-n:]
