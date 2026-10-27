"""Minimaal Go-bord: zetten toepassen met captures.
De server valideert legaliteit (ko, suicide); wij tonen alleen correct.
Kleuren: 0 leeg, 1 zwart, 2 wit. y=0 is boven (OGS-conventie).
"""


COLS = "ABCDEFGHJKLMNOPQRST"     # GTP-kolommen (zonder I)
RULES = "japanese"               # voor alle potten die we zelf aanmaken: OGS en offline


def to_gtp(x, y, size):
    """(x, y) -> 'D4'; x < 0 = pass. y=0 is boven, GTP telt van onder."""
    return "pass" if x < 0 else f"{COLS[x]}{size - y}"


def star_line(size):
    """Lijn (vanaf 0) van de hoek-sterpunten: 3-3 op kleine borden, anders 4-4."""
    return 2 if size < 13 else 3


def color_at(t, handicap=0):
    """Kleur van zet t. Handicap (OGS-vorm): de eerste N zetten zijn de zwarte stenen, dan begint wit."""
    if handicap:
        return 1 if t < handicap else (2 if (t - handicap) % 2 == 0 else 1)
    return 1 if t % 2 == 0 else 2


def other(col):
    return 3 - col


def letter(col):
    """1/2 -> 'B'/'W' (GTP, retro.stone)."""
    return "B" if col == 1 else "W"


def _nbrs(x, y, size):
    return [(nx, ny) for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
            if 0 <= nx < size and 0 <= ny < size]


def _group(board, x, y):
    size = len(board)
    col = board[y][x]
    seen, stack, libs = {(x, y)}, [(x, y)], False
    while stack:
        cx, cy = stack.pop()
        for nx, ny in _nbrs(cx, cy, size):
            v = board[ny][nx]
            if v == 0:
                libs = True
            elif v == col and (nx, ny) not in seen:
                seen.add((nx, ny))
                stack.append((nx, ny))
    return seen, libs


def apply_move(board, x, y, col):
    """Plaats steen, verwijder gevangen vijandelijke groepen. -> aantal captures."""
    if x < 0:            # pass
        return 0
    size = len(board)
    board[y][x] = col
    caps = 0
    for nx, ny in _nbrs(x, y, size):
        if board[ny][nx] == other(col):
            grp, libs = _group(board, nx, ny)
            if not libs:
                caps += len(grp)
                for gx, gy in grp:
                    board[gy][gx] = 0
    grp, libs = _group(board, x, y)
    if not libs:         # suicide; server staat dit niet toe, maar wees robuust
        for gx, gy in grp:
            board[gy][gx] = 0
    return caps


def from_moves(size, moves, handicap=0):
    """Bouw bord uit OGS-moves ([x,y,ms]). -> (board, caps_black, caps_white, last)"""
    board = [[0] * size for _ in range(size)]
    caps = {1: 0, 2: 0}
    last = None
    for i, mv in enumerate(moves):
        x, y = int(mv[0]), int(mv[1])
        col = color_at(i, handicap)
        caps[col] += apply_move(board, x, y, col)
        last = (x, y) if x >= 0 else None
    return board, caps[1], caps[2], last
