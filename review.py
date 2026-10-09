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
CATS = {   # label (<= 11 tekens) en twee regels uitleg (<= 11 tekens) voor het 8px-font
    "capture": ("Capture", "A group was", "in atari"),
    "lifedeath": ("Life&death", "Vital point", "missed"),
    "bigpoint": ("Big point", "Bigger move", "elsewhere"),
    "endgame": ("Endgame", "Boundary", "move missed"),
    "weak": ("Weak group", "Own group", "was short"),
    "contact": ("Contact", "Pushed into", "a stone"),
    "direction": ("Direction", "Better", "direction"),
    "passed": ("Passed", "Passed", "too early"),
}


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


def classify(board, n, played, answer, lost, prev, col):
    """board = stand vóór de zet; played/answer = (x,y) of None; col = 1/2 (speler aan zet)."""
    if played is None:
        return "passed"
    if answer is None:
        return "direction"
    size, opp = len(board), 3 - col
    px, py = played
    bx, by = answer

    def adj(x, y, c):
        return [_libs(board, nx, ny) for nx, ny in goban._nbrs(x, y, size) if board[ny][nx] == c]

    if any(l <= 1 for l in adj(bx, by, opp)) or any(l <= 1 for l in adj(bx, by, col)):
        return "capture"
    if lost >= 12:
        return "lifedeath"
    d_played = max(abs(bx - px), abs(by - py))
    d_prev = max(abs(bx - prev[0]), abs(by - prev[1])) if prev else 99
    if d_played >= 3 and d_prev >= 3:
        return "bigpoint"
    if n >= size * size * 0.5 and min(bx, by, size - 1 - bx, size - 1 - by) <= 1 and lost < 8:
        return "endgame"
    if any(l <= 2 for l in adj(bx, by, col)):
        return "weak"
    nb = goban._nbrs
    if any(board[y][x] == opp for x, y in nb(px, py, size)) and \
            not any(board[y][x] == opp for x, y in nb(bx, by, size)):
        return "contact"
    return "direction"


def compute(size, moves, evals, human=1):
    """-> dict met samenvatting, of None als er te weinig evaluaties zijn."""
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
            if played is not None and answer == played:
                lost = min(lost, 0.0)          # de beste zet zelf kost niets
            rows.append({"t": t, "lost": round(lost, 2), "played": played, "answer": answer,
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
    top = sorted(rows, key=lambda r: -r["lost"])[:3]
    return {
        "moves": n, "my_moves": len(rows),
        "loss_per_move": round(sum(loss) / len(loss), 2),
        "blunders": sum(1 for v in loss if v >= BLUNDER),
        "phases": {k: round(sum(v) / len(v), 2) for k, v in by_phase.items()},
        "cats": cats,
        "moments": [{"t": r["t"], "lost": r["lost"], "cat": r["cat"], "played": r["played"],
                     "answer": r["answer"], "board": r["board"], "prev": r["prev"]} for r in top
                    if r["lost"] > 0.5],
    }


# ---------- opslag ----------
def save(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    slim = dict(entry)
    slim["moments"] = [{k: v for k, v in m.items() if k != "board"} for m in entry.get("moments", [])]
    with open(path, "a") as f:
        f.write(json.dumps(slim, separators=(",", ":")) + "\n")


def history(path, size=None, n=10):
    try:
        rows = [json.loads(l) for l in open(path) if l.strip()]
    except OSError:
        return []
    if size:
        rows = [r for r in rows if r.get("size") == size]
    return rows[-n:]
