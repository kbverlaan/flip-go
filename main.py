"""flip-go: retro OGS-client voor de Miyoo Flip (en de Mac om te testen).

Run:            python main.py
Screenshots:    python main.py --shot   (headless, schrijft out/*.png)

Besturing (Mac-test = Flip-mapping):
  pijltjes = D-pad   Enter/X = A   Backspace/Z = B   S = Start   R = refresh
In een pot: S opent het menu (Pass / Resign / Info / Quit).
"""
import os
import sys
import threading
import time

if "--shot" in sys.argv:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
import retro
from retro import PAL, W, H

import goban
import gtp
import json
import ogs
import review

_BG = {}


def board_bg(n):
    """Statisch bord (hout, raster, hoshi) 1x gerenderd per bordmaat (gedeeld)."""
    if n not in _BG:
        c = min(23, 192 // max(1, n - 1))
        span = c * (n - 1)
        o = (212 - span) // 2
        bg = pygame.Surface((212, 212))
        bg.fill(PAL["wood"])
        pygame.draw.rect(bg, PAL["line"], (0, 0, 212, 212), 1)
        for i in range(n):
            pygame.draw.line(bg, PAL["line"], (o, o + i * c), (o + span, o + i * c))
            pygame.draw.line(bg, PAL["line"], (o + i * c, o), (o + i * c, o + span))
        e = 2 if n < 13 else 3
        hoshi = [(a, b) for a in (e, n - 1 - e) for b in (e, n - 1 - e)] + [(n // 2, n // 2)]
        if n == 19:
            hoshi += [(3, 9), (15, 9), (9, 3), (9, 15)]
        if n in (9, 13, 19):
            for hx, hy in hoshi:
                pygame.draw.rect(bg, PAL["line"], (o + hx * c - 1, o + hy * c - 1, 3, 3))
        _BG[n] = bg
    return _BG[n]


def board_geom(n):
    c = min(23, 192 // max(1, n - 1))
    span = c * (n - 1)
    return c, 4 + (212 - span) // 2, 14 + (212 - span) // 2, max(4, c * 2 // 5 + 1)

_VF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version.txt")
VERSION = open(_VF).read().strip()[:7] if os.path.exists(_VF) else "dev"

SCALE = 2  # 640x480 venster; op de Flip fullscreen 2x
A_KEYS = (pygame.K_RETURN, pygame.K_x)
B_KEYS = (pygame.K_BACKSPACE, pygame.K_z)

# Flip-gamepad -> toetsen (X360-schema; zet Controls in het PM-menu op X360)
# Miyoo Flip (Knulli): A=0 B=1 X=2 Y=3 schouders=4-7 select=8 start=9 dpad=13-16
PAD_BUTTONS = {0: pygame.K_RETURN, 1: pygame.K_BACKSPACE, 2: pygame.K_r,
               3: pygame.K_ESCAPE, 8: pygame.K_s, 9: pygame.K_s,
               13: pygame.K_UP, 14: pygame.K_DOWN,
               15: pygame.K_LEFT, 16: pygame.K_RIGHT}
HAT_KEYS = {(0, 1): pygame.K_UP, (0, -1): pygame.K_DOWN,
            (-1, 0): pygame.K_LEFT, (1, 0): pygame.K_RIGHT}


_axis_state = {}


def pad_translate(ev):
    """Gamepad-event -> synthetisch KEYDOWN-event (of None).
    Logt elke knop/as naar stdout voor kalibratie op nieuwe apparaten."""
    if ev.type == pygame.JOYBUTTONDOWN:
        print(f"pad: button {ev.button}")
        k = PAD_BUTTONS.get(ev.button)
        return pygame.event.Event(pygame.KEYDOWN, key=k) if k else None
    if ev.type == pygame.JOYHATMOTION and ev.value in HAT_KEYS:
        return pygame.event.Event(pygame.KEYDOWN, key=HAT_KEYS[ev.value])
    if ev.type == pygame.JOYAXISMOTION:
        prev = _axis_state.get(ev.axis, 0)
        cur = 1 if ev.value > 0.6 else (-1 if ev.value < -0.6 else 0)
        _axis_state[ev.axis] = cur
        if cur != prev and cur:
            print(f"pad: axis {ev.axis} {'+' if cur > 0 else '-'}")
            if ev.axis in (0, 2):
                return pygame.event.Event(
                    pygame.KEYDOWN, key=pygame.K_RIGHT if cur > 0 else pygame.K_LEFT)
            if ev.axis in (1, 3):
                return pygame.event.Event(
                    pygame.KEYDOWN, key=pygame.K_DOWN if cur > 0 else pygame.K_UP)
    return None

_stone_snd = None


def play_stone():
    global _stone_snd
    try:
        if _stone_snd is None:
            _stone_snd = pygame.mixer.Sound(str(retro.ASSETS / "stone.wav"))
        _stone_snd.play()
    except Exception:
        pass


_dev = {"t": 0.0, "v": (None, False, None)}


def device_status():
    """(batterij%, aan lader, wifi) — None = niet beschikbaar (bv. op de Mac)."""
    now = time.time()
    if now - _dev["t"] > 5:
        batt, charging, wifi = None, False, None
        try:
            batt = int(open("/sys/class/power_supply/battery/capacity").read().strip())
            charging = "harging" in open("/sys/class/power_supply/battery/status").read()
        except Exception:
            pass
        try:
            wifi = any(":" in l and "wlan" in l for l in open("/proc/net/wireless"))
        except Exception:
            pass
        _dev["t"], _dev["v"] = now, (batt, charging, wifi)
    return _dev["v"]


def draw_status(s):
    """Batterij + wifi als pixel-iconen rechtsboven (alleen op het apparaat)."""
    batt, charging, wifi = device_status()
    if batt is not None:
        col = PAL["accent"] if batt < 20 and not charging else PAL["text_dim"]
        pygame.draw.rect(s, col, (298, 5, 14, 8), 1)
        pygame.draw.rect(s, col, (312, 7, 2, 4))
        w = max(1, 10 * batt // 100)
        pygame.draw.rect(s, PAL["green"] if charging else col, (300, 7, w, 4))
    if wifi is True:
        for i, h in enumerate((2, 4, 6)):
            pygame.draw.rect(s, PAL["text_dim"], (282 + i * 4, 13 - h, 3, h))
    elif wifi is False:
        pygame.draw.rect(s, PAL["accent"], (282, 7, 3, 6))


def arrow(s, x, y, color=None):
    """Pokemon-cursor: klein driehoekje."""
    c = color or PAL["text"]
    pygame.draw.polygon(s, c, [(x, y), (x, y + 8), (x + 5, y + 4)])


class TitleScene:
    def __init__(self):
        self.t0 = time.monotonic()

    def handle(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_RETURN, pygame.K_s, pygame.K_x):
            return GamesScene()
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        bx, by, cell = 104, 62, 14
        pygame.draw.rect(s, PAL["wood"], (bx - 10, by - 10, cell * 8 + 20, cell * 8 + 20))
        for i in range(9):
            pygame.draw.line(s, PAL["line"], (bx, by + i * cell), (bx + cell * 8, by + i * cell))
            pygame.draw.line(s, PAL["line"], (bx + i * cell, by), (bx + i * cell, by + cell * 8))
        for gx, gy, c in ((2, 2, "B"), (6, 2, "W"), (4, 4, "B"), (2, 6, "W"), (6, 6, "B")):
            retro.stone(s, bx + gx * cell, by + gy * cell, 6, c)
        retro.text_c(s, "FLIP GO", W // 2, 16, PAL["box"], 16)
        retro.text_c(s, "an OGS client", W // 2, 38, PAL["text_dim"])
        if int((time.monotonic() - self.t0) * 2) % 2 == 0:     # 0,5 s aan, 0,5 s uit
            retro.text_c(s, "PRESS START", W // 2, 205, PAL["box"])
        retro.text(s, "Y quit", 4, 228, PAL["text_dim"])
        retro.text_r(s, f"v {VERSION}", 316, 228, PAL["text_dim"])
        draw_status(s)


class GamesScene:
    """Je potten + open challenges + NEW GAME."""

    def __init__(self):
        self.games = None
        self.seeking = []
        self.error = None
        self.sel = 0
        self.t0 = time.monotonic()
        self.cancelq = None      # challenge-id in bevestiging
        self.stopping = None     # challenge-id die geannuleerd wordt
        self.me_label = None
        self.fsel = 0            # footer: 0 = NEW GAME, 1 = HISTORY
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            self.games = ogs.my_games()
            self.seeking = ogs.my_challenges()
            m = ogs.me()
            self.me_label = f"{m.get('username')} - {ogs.rank_label(m.get('ranking'))}"
        except Exception:
            self.error = "No connection"
            self.games = []

    FOOTER = ("NEW GAME", "HISTORY")

    def _rows(self):
        """-> lijst ('offline'|'game'|'seek', data); footer staat er los onder"""
        if not hasattr(self, "_offline"):
            sv = load_offline()
            bot = sv and next((b for b in gtp.BOTS if b[0] == sv.get("bot")), None)
            self._offline = (sv, bot) if bot else None
        rows = [("offline", self._offline)] if self._offline else []
        rows += [("game", g) for g in (self.games or [])]
        rows += [("seek", c) for c in self.seeking]
        return rows

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN or self.stopping:
            return self
        if self.cancelq:
            if ev.key in A_KEYS:
                self.stopping = self.cancelq
                self.cancelq = None
                threading.Thread(target=self._cancel, args=(self.stopping,), daemon=True).start()
            elif ev.key in B_KEYS:
                self.cancelq = None
            return self
        rows = self._rows()
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(rows), self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT) and self.sel == len(rows):
            self.fsel = 1 - self.fsel
        elif ev.key in A_KEYS:
            if self.sel == len(rows):
                if self.fsel == 1:
                    return HistoryScene()
                return OfflineScene() if self.error else NewGameScene()
            kind, data = rows[self.sel]
            if kind == "offline":
                sv, bot = data
                return OfflineGameScene(bot, sv["size"], sv["moves"])
            if kind == "game":
                return GameScene(data["id"])
            if kind == "seek":
                self.cancelq = data["id"]
        elif ev.key in B_KEYS:
            return TitleScene()
        elif ev.key == pygame.K_r:
            return GamesScene()
        return self

    def _cancel(self, cid):
        try:
            ogs.cancel_challenge(cid)
        except Exception:
            pass
        self._load()
        self.stopping = None
        self.sel = 0

    def draw(self, s):
        s.fill(PAL["screen"])
        retro.text_c(s, "YOUR GAMES", W // 2, 14, PAL["box"])
        draw_status(s)
        if self.games is None:
            retro.text_c(s, "loading" + "." * (int((time.monotonic() - self.t0) * 3) % 4), W // 2, 110, PAL["text_dim"])
            return
        rows = self._rows()
        off = max(0, min(self.sel - 3, len(rows) - 4))
        for i, (kind, data) in enumerate(rows[off:off + 4]):
            y = 44 + i * 30
            retro.dialog_box(s, (16, y, 288, 26))
            if i + off == self.sel:
                arrow(s, 24, y + 9)
            if kind == "offline":
                retro.text(s, f"vs {data[1][0]}", 36, y + 9)
                retro.text_r(s, "offline", 296, y + 9, PAL["text_dim"])
            elif kind == "game":
                retro.text(s, f"vs {data['opp'][:19]}", 36, y + 9)
                if data["my_turn"] and data.get("left"):
                    retro.text_r(s, retro.fmt_time(data["left"]), 296, y + 9)
                elif data["my_turn"]:
                    retro.text(s, "*", 288, y + 9, PAL["accent"])
                else:
                    retro.text_r(s, data["speed"], 296, y + 9, PAL["text_dim"])
            elif kind == "seek":
                if self.stopping == data["id"]:
                    retro.text(s, "stopping...", 36, y + 9, PAL["text_dim"])
                elif self.cancelq == data["id"]:
                    retro.text(s, "stop seeking? A/B", 36, y + 9, PAL["accent"])
                else:
                    retro.text(s, "seeking", 36, y + 9, PAL["text_dim"])
                    retro.text(s, data["speed"], 240, y + 9, PAL["text_dim"])
        # footer: twee boxen naast elkaar, gameboy-stijl
        on_footer = self.sel == len(rows)
        left_label = "OFFLINE" if self.error else "NEW GAME"
        for f, (bx, label) in enumerate(((16, left_label), (164, "HISTORY"))):
            retro.dialog_box(s, (bx, 192, 140, 26))
            if on_footer and self.fsel == f:
                arrow(s, bx + 10, 192 + 9)
            retro.text_c(s, label, bx + 76, 192 + 9)
        if self.error:
            retro.text_c(s, self.error, W // 2, 220, PAL["text_dim"])
        elif self.me_label:
            retro.text_c(s, self.me_label, W // 2, 226, PAL["text_dim"])


BOARD_SIZES = (9, 13)
_SIZE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conf", "size.txt")
try:              # laatst gekozen bordmaat onthouden: KataGo laadt dan meteen op die maat
    new_size = int(open(_SIZE_FILE).read())
except (OSError, ValueError):
    new_size = 9


def set_size(n):
    global new_size
    new_size = n
    try:
        os.makedirs(os.path.dirname(_SIZE_FILE), exist_ok=True)
        open(_SIZE_FILE, "w").write(str(n))
    except OSError:
        pass


class NewGameScene:
    """Nieuwe pot: daily, live (open challenge) of een bot van de bloemenladder."""
    OPTIONS = (("daily", "3d + 1d per move"),
               ("live", "2m + 30s per move"),
               ("bots", "the flower ladder"),
               ("offline", "local bot, no wifi"))

    def __init__(self, back=None):
        self.back = back or GamesScene
        self.sel = 0
        self.busy = False
        self.done = False
        self.msg = None

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        if self.done:
            return GamesScene()
        if ev.key in B_KEYS:
            return self.back()
        if self.busy:
            return self
        global new_size
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(self.OPTIONS) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
            i = BOARD_SIZES.index(new_size) + (1 if ev.key == pygame.K_RIGHT else -1)
            set_size(BOARD_SIZES[i % len(BOARD_SIZES)])
        elif ev.key in A_KEYS:
            if self.OPTIONS[self.sel][0] == "bots":
                return BotScene()
            if self.OPTIONS[self.sel][0] == "offline":
                return OfflineScene()
            self.busy = True
            self.msg = "Posting..."
            threading.Thread(target=self._create, daemon=True).start()
        return self

    def _create(self):
        try:
            ogs.create_challenge(self.OPTIONS[self.sel][0], new_size)
            self.msg = "Posted. Any key: games"
            self.done = True
        except Exception:
            self.msg = "Failed"
        self.busy = False

    def draw(self, s):
        s.fill(PAL["screen"])
        retro.text_c(s, "NEW GAME", W // 2, 14, PAL["box"])
        retro.text_c(s, f"< {new_size}x{new_size} > ranked - japanese", W // 2, 34, PAL["text_dim"])
        for i, (name, desc) in enumerate(self.OPTIONS):
            y = 54 + i * 40
            retro.dialog_box(s, (60, y, 200, 36))
            if i == self.sel:
                arrow(s, 68, y + 8)
            retro.text(s, name.upper(), 80, y + 7)
            retro.text(s, desc, 80, y + 21, PAL["text_dim"])
        if self.msg:
            retro.text_c(s, self.msg, W // 2, 210, PAL["text_dim"])


class BotScene:
    """De bloemenladder: challenge een bot, die accepteert vanzelf."""

    def __init__(self, back=None):
        self.back = back or NewGameScene
        self.flowers = ogs.FLOWERS
        self.sel = 3      # Bouvardia, de vaste sparringspartner
        self.busy = False
        self.done = False
        self.msg = None
        self.ranks = {}
        self.goto = None
        threading.Thread(target=self._load_ranks, daemon=True).start()

    def _load_ranks(self):
        for name, pid in self.flowers:
            try:
                d = ogs.api(f"players/{pid}")
                rating = (d.get("ratings") or {}).get("overall", {}).get("rating")
                self.ranks[pid] = ogs.rating_to_rank(rating)
            except Exception:
                pass

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        if self.done:
            return GamesScene()
        if ev.key in B_KEYS:
            return self.back()
        if self.busy:
            return self
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(self.flowers) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in A_KEYS:
            self.busy = True
            self.msg = "Challenging..."
            threading.Thread(target=self._challenge, daemon=True).start()
        return self

    def _challenge(self):
        try:
            name, pid = self.flowers[self.sel]
            ogs.challenge_player(pid, "daily", new_size)
            self.msg = "Starting..."
            known = {g["id"] for g in ogs.my_games() if g["opp"] != name}
            for _ in range(20):     # bot accepteert doorgaans binnen seconden
                time.sleep(1)
                for g in ogs.my_games():
                    if g["opp"] == name and g["id"] not in known:
                        self.goto = GameScene(g["id"])
                        self.busy = False
                        return
            self.msg = "No response"
        except Exception:
            self.msg = "Failed"
        self.busy = False

    def draw(self, s):
        s.fill(PAL["screen"])
        retro.text_c(s, "FLOWER LADDER", W // 2, 14, PAL["box"])
        retro.text_c(s, f"{new_size}x{new_size}", W // 2, 28, PAL["text_dim"])
        for i, (name, _) in enumerate(self.flowers):
            y = 44 + i * 26
            retro.dialog_box(s, (64, y, 192, 22))
            if i == self.sel:
                arrow(s, 72, y + 7)
            retro.text(s, name, 84, y + 7)
            rk = self.ranks.get(self.flowers[i][1])
            if rk:
                retro.text_r(s, rk, 248, y + 7, PAL["text_dim"])
        if self.msg:
            retro.text_c(s, self.msg, W // 2, 218, PAL["text_dim"])


class HistoryScene:
    """Laatste afgeronde potten: uitslag + tegenstander. A = terugkijken."""

    def __init__(self):
        self.rows = None
        self.sel = 0
        self.t0 = time.monotonic()
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            self.rows = ogs.my_history()
        except Exception:
            self.rows = []

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        if ev.key in B_KEYS:
            return GamesScene()
        rows = self.rows or []
        if ev.key == pygame.K_DOWN and rows:
            self.sel = min(len(rows) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP and rows:
            self.sel = max(0, self.sel - 1)
        elif ev.key in A_KEYS and rows:
            return GameScene(rows[self.sel]["id"], back=HistoryScene)
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        retro.text_c(s, "HISTORY", W // 2, 14, PAL["box"])
        if self.rows is None:
            retro.text_c(s, "loading" + "." * (int((time.monotonic() - self.t0) * 3) % 4), W // 2, 110, PAL["text_dim"])
        elif not self.rows:
            retro.text_c(s, "No finished games.", W // 2, 110, PAL["text_dim"])
        else:
            off = max(0, min(self.sel - 5, len(self.rows) - 6))
            for i, r in enumerate(self.rows[off:off + 6]):
                y = 44 + i * 30
                retro.dialog_box(s, (16, y, 288, 26))
                if i + off == self.sel:
                    arrow(s, 24, y + 9)
                retro.text(s, "won " if r["won"] else "lost", 36, y + 9,
                           PAL["green"] if r["won"] else PAL["accent"])
                retro.text(s, f"vs {r['opp'][:15]}", 76, y + 9)
                retro.text_r(s, r["result"], 296, y + 9, PAL["text_dim"])


class GameScene:
    """Echte OGS-pot (of mock als gid None). A = zet (met bevestiging),
    S = menu: Pass / Resign / Info / Quit."""
    MENU = ("PASS", "RESIGN", "INFO", "QUIT")

    def __init__(self, gid, back=None):
        self.gid = gid
        self.back = back or GamesScene
        self.size = 9
        self.cx = self.cy = 4
        self._polled = time.monotonic()   # laatste poll-moment
        self.board = [[0] * 9 for _ in range(9)]
        self.caps = (0, 0)
        self.last = None
        self.names = ("black", "white")
        self.komi = 6.5
        self.times = ("", "")
        self.rules = "japanese"
        self.speed = ""
        self.my_color = 1
        self.my_turn = False
        self.turn_color = 1
        self.phase = "play"
        self.outcome = ""
        self.winner_id = None
        self.me_id = None
        self.black_id = None
        self.nmoves = 0
        self.confirm = None      # ("move",x,y) | ("pass",) | ("resign",)
        self._snap = None        # door _load gepubliceerd, door draw overgenomen
        self._loading = False
        self.menu = None         # None | cursor-index
        self.info = False
        self.busy = False
        self.msg = "Loading..."
        if gid:
            threading.Thread(target=self._load, daemon=True).start()
        else:
            for x, y, c in ((4, 4, 1), (2, 6, 1), (6, 2, 2), (2, 2, 1), (6, 6, 2), (5, 3, 2)):
                self.board[y][x] = c
            self.names = ("kiemsan_", "amybot")
            self.my_turn = True
            self.msg = "Mock board"

    # ---------- data ----------
    def _load(self):
        self._loading = True
        try:
            gd = ogs.api(f"games/{self.gid}").get("gamedata", {})
            pl = gd.get("players", {})
            size = gd.get("width", 9)
            moves = gd.get("moves", [])
            board, cb, cw, last = goban.from_moves(size, moves, gd.get("handicap", 0))
            me_id = ogs.me().get("id")
            black_id = pl.get("black", {}).get("id")
            clk = gd.get("clock", {})
            cur = clk.get("current_player")
            phase = gd.get("phase", "play")

            def side_time(k):
                t = clk.get(k)
                if isinstance(t, dict):
                    return t.get("thinking_time")
                return t if isinstance(t, (int, float)) else None
            bt, wt = side_time("black_time"), side_time("white_time")
            if clk.get("expiration"):
                rem = clk["expiration"] / 1000 - time.time()
                if cur == black_id:
                    bt = rem
                else:
                    wt = rem
            passed = bool(moves) and moves[-1][0] < 0 and phase == "play"
            if len(moves) > self.nmoves and self.nmoves:
                play_stone()          # nieuwe zet binnengekomen
            # alles in één publicatie; draw neemt hem op de main thread over
            self._snap = dict(
                size=size, board=board, caps=(cb, cw), last=last, nmoves=len(moves),
                **({"cx": size // 2, "cy": size // 2} if size != self.size else {}),
                names=(pl.get("black", {}).get("username", "?"),
                       pl.get("white", {}).get("username", "?")),
                komi=float(gd.get("komi", 6.5)), rules=gd.get("rules", "japanese"),
                speed=ogs.speed_label(gd.get("time_control", {}).get("speed", "")),
                phase=phase, outcome=gd.get("outcome", ""),
                winner_id=gd.get("winner"), black_id=black_id, me_id=me_id,
                my_color=1 if black_id == me_id else 2, my_turn=cur == me_id,
                turn_color=1 if cur == black_id else 2,
                times=(retro.fmt_time(bt), retro.fmt_time(wt)),
                msg=("The end." if phase == "finished" else
                     "Counting" if phase == "stone removal" else
                     "Opp passed" if passed and cur == me_id else
                     "Your move." if cur == me_id else "Waiting..."))
        except Exception:
            self._snap = {"msg": "Load failed"}
        finally:
            self._loading = False

    def _do(self, action):
        try:
            if action[0] == "move":
                ogs.submit_move(self.gid, action[1], action[2])
                self.nmoves += 1     # eigen zet: _load mag niet nogmaals plokken
            elif action[0] == "pass":
                ogs.pass_move(self.gid)
                self.nmoves += 1
            elif action[0] == "resign":
                ogs.resign(self.gid)
            elif action[0] == "accept":
                ogs.accept_removal(self.gid)
            self._load()
        except Exception:
            self.msg = f"{action[0]} failed"[:10]
            self.busy = False
            return
        self.busy = False
        snap = self._snap or {}
        if action[0] in ("move", "pass") and snap.get("phase") == "play" and not snap.get("my_turn"):
            threading.Thread(target=self._await_opponent, args=(snap.get("nmoves", 0),),
                             daemon=True).start()

    def _await_opponent(self, nmoves):
        """Na eigen zet: socket open houden tot de tegenstander zet (push)."""
        try:
            if ogs.wait_for_move(self.gid, nmoves):
                self._load()
        except Exception as e:
            print("await opponent:", e)

    # ---------- input ----------
    def handle(self, ev):
        if ev.type != pygame.KEYDOWN or self.busy:
            return self
        if self.info:
            self.info = False
            return self
        if self.confirm:
            return self._handle_confirm(ev)
        if self.menu is not None:
            return self._handle_menu(ev)
        if self.phase == "finished" and ev.key in A_KEYS + B_KEYS:
            return self.back() if self.gid else TitleScene()
        if self.phase == "stone removal":
            if ev.key in A_KEYS:
                self.busy = True
                self.msg = "Sending..."
                threading.Thread(target=self._do, args=(("accept",),), daemon=True).start()
            elif ev.key in B_KEYS:
                return GamesScene()
            return self
        dx = (ev.key == pygame.K_RIGHT) - (ev.key == pygame.K_LEFT)
        dy = (ev.key == pygame.K_DOWN) - (ev.key == pygame.K_UP)
        if dx or dy:
            self.cx = max(0, min(self.size - 1, self.cx + dx))
            self.cy = max(0, min(self.size - 1, self.cy + dy))
        elif ev.key in A_KEYS:
            if self.my_turn and self.phase == "play" and self.board[self.cy][self.cx] == 0:
                x, y = self.cx, self.cy
                self.board[y][x] = self.my_color if self.gid else 1
                play_stone()
                if self.gid:
                    self.busy = True
                    self.msg = "Sending..."
                    threading.Thread(target=self._do, args=(("move", x, y),),
                                     daemon=True).start()
                else:
                    self.msg = "You: " + self._coord(x, y)
        elif ev.key == pygame.K_s:
            if self.gid and self.phase == "play":
                self.menu = 0
        elif ev.key == pygame.K_r:
            if self.gid:
                self.msg = "..."
                threading.Thread(target=self._load, daemon=True).start()
        elif ev.key in B_KEYS:
            return self.back() if self.gid else TitleScene()
        return self

    def _handle_confirm(self, ev):
        """Alleen pass/resign vragen bevestiging; zetten plaatsen direct."""
        if ev.key in A_KEYS:
            action = self.confirm
            self.confirm = None
            self.busy = True
            self.msg = "Sending..."
            threading.Thread(target=self._do, args=(action,), daemon=True).start()
        elif ev.key in B_KEYS:
            self.confirm = None
            self.msg = "Your move."
        return self

    def _handle_menu(self, ev):
        if ev.key == pygame.K_DOWN:
            self.menu = (self.menu + 1) % len(self.MENU)
        elif ev.key == pygame.K_UP:
            self.menu = (self.menu - 1) % len(self.MENU)
        elif ev.key in A_KEYS:
            item = self.MENU[self.menu]
            self.menu = None
            if item == "PASS":
                self.confirm = ("pass",)
                self.msg = "Pass? A/B"
            elif item == "RESIGN":
                self.confirm = ("resign",)
                self.msg = "Resign?A/B"
            elif item == "INFO":
                self.info = True
            elif item == "QUIT":
                return self.back()
        elif ev.key in B_KEYS + (pygame.K_s,):
            self.menu = None
        return self

    def _coord(self, x, y):
        return "ABCDEFGHJKLMNOPQRST"[x] + str(self.size - y)

    # ---------- draw ----------
    def _plate(self, s, y, color, name, caps, to_move):
        retro.dialog_box(s, (224, y, 92, 34))
        if to_move and self.phase == "play":
            arrow(s, 227, y + 7, PAL["accent"])
        retro.stone(s, 238, y + 11, 4, "B" if color == 1 else "W")
        retro.text(s, name[:8], 244, y + 7)
        retro.text(s, f"c:{caps}", 238, y + 20, PAL["text_dim"])
        retro.text_r(s, self.times[color - 1], 312, y + 20,
                     PAL["text"] if to_move and self.phase == "play" else PAL["text_dim"])

    def _board_bg(self):
        return board_bg(self.size)

    def draw(self, s):
        if self._snap:               # atomaire overname van een verse load
            self.__dict__.update(self._snap)
            self._snap = None
        s.fill(PAL["screen"])
        s.blit(self._board_bg(), (4, 14))
        n = self.size
        c = min(23, 192 // max(1, n - 1))
        span = c * (n - 1)
        ox = 4 + (212 - span) // 2
        oy = 14 + (212 - span) // 2
        r = max(4, c * 2 // 5 + 1)
        for y in range(n):
            for x in range(n):
                if self.board[y][x]:
                    retro.stone(s, ox + x * c, oy + y * c, r,
                                "B" if self.board[y][x] == 1 else "W")
        if self.last:
            lx, ly = self.last
            col = PAL["white_sh"] if self.board[ly][lx] == 1 else PAL["black_hi"]
            pygame.draw.rect(s, col, (ox + lx * c - 2, oy + ly * c - 2, 5, 5))
        if self.menu is None and not self.info:
            px, py = ox + self.cx * c, oy + self.cy * c
            can_play = (self.my_turn and self.phase == "play" and not self.busy
                        and self.board[self.cy][self.cx] == 0)
            if can_play:
                retro.stone(s, px, py, r, "B" if self.my_color == 1 else "W")
            else:
                a = PAL["accent"]
                d, k = c // 2 - 1, (4 if c >= 20 else 3)
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        x0, y0 = px + sx * d, py + sy * d
                        pygame.draw.line(s, a, (x0, y0), (x0 - sx * k, y0))
                        pygame.draw.line(s, a, (x0, y0), (x0, y0 - sy * k))
        # plates: zwart boven, wit onder — Go-conventie, direct onder elkaar
        playing = self.phase == "play"
        self._plate(s, 14, 1, self.names[0], self.caps[0], playing and self.turn_color == 1)
        self._plate(s, 52, 2, self.names[1], self.caps[1], playing and self.turn_color == 2)
        retro.dialog_box(s, (224, 198, 92, 28))
        retro.text(s, self.msg[:10], 230, 203)
        if self.gid and playing and self.menu is None:
            retro.text(s, "start menu", 230, 214, PAL["text_dim"])
        # menu tussen plates en berichtvak (Pokemon-pauzemenu)
        if self.menu is not None:
            retro.dialog_box(s, (224, 96, 92, 92))
            for i, item in enumerate(self.MENU):
                y = 104 + i * 20
                if i == self.menu:
                    arrow(s, 230, y)
                retro.text(s, item, 240, y)
        if self.info:
            retro.dialog_box(s, (224, 96, 92, 92))
            retro.text(s, self.speed or "local", 232, 104)
            retro.text(s, self.rules[:10], 232, 118, PAL["text_dim"])
            retro.text(s, f"komi {self.komi:g}", 232, 136)
            retro.text(s, f"move {self.nmoves}", 232, 150)
            retro.text(s, "B close", 232, 168, PAL["text_dim"])
        if self.phase == "finished" and self.gid:
            won = self.winner_id == self.me_id
            retro.dialog_box(s, (224, 96, 92, 92))
            retro.text_c(s, "YOU WON" if won else "YOU LOST", 270, 112)
            retro.text_c(s, ogs.format_outcome(self.winner_id == self.black_id,
                                               self.outcome), 270, 132)
            can_rev = self.speed == "offline" and hasattr(getattr(self, "eng", None), "evals")
            retro.text_c(s, "A review" if can_rev else "A back" if self.speed == "offline" else "A games",
                         270, 156, PAL["text_dim"])
        elif self.phase == "stone removal" and not self.busy:
            retro.dialog_box(s, (224, 96, 92, 92))
            retro.text_c(s, "COUNTING", 270, 112)
            retro.text_c(s, "A accept", 270, 132)
            retro.text_c(s, "B games", 270, 156, PAL["text_dim"])
        poll = 3 if self.speed in ("live", "blitz") else 30    # seconden
        if time.monotonic() - self._polled >= poll:
            self._polled = time.monotonic()
            if (self.gid and not self._loading and
                    (self.phase == "stone removal" or (playing and not self.my_turn))):
                threading.Thread(target=self._load, daemon=True).start()


SAVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conf", "offline.json")


def load_offline():
    try:
        with open(SAVE) as f:
            return json.load(f)
    except Exception:
        return None


class OfflineScene:
    """Lokale bot kiezen (engine op het apparaat), of de lopende pot hervatten."""

    def __init__(self):
        self.saved = load_offline()
        gtp.preload(new_size)
        self.rows = ([("continue", None)] if self.saved else []) + \
                    [("bot", b) for b in gtp.available()]
        self.sel = 0

    def handle(self, ev):
        global new_size
        if ev.type != pygame.KEYDOWN:
            return self
        if ev.key == pygame.K_s:
            return StatsScene(self)
        if ev.key in B_KEYS:
            return TitleScene()
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(self.rows) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
            i = BOARD_SIZES.index(new_size) + (1 if ev.key == pygame.K_RIGHT else -1)
            set_size(BOARD_SIZES[i % len(BOARD_SIZES)])
        elif ev.key in A_KEYS and self.rows:
            kind, bot = self.rows[self.sel]
            if kind == "continue":
                sv = self.saved
                bot = next((b for b in gtp.BOTS if b[0] == sv["bot"]), None)
                if bot:
                    return OfflineGameScene(bot, sv["size"], sv["moves"])
            else:
                return OfflineGameScene(bot, new_size)
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        retro.text_c(s, "OFFLINE", W // 2, 14, PAL["box"])
        retro.text_c(s, f"< {new_size}x{new_size} > japanese - komi 6.5", W // 2, 34,
                     PAL["text_dim"])
        if not self.rows:
            retro.text_c(s, "no engine installed", W // 2, 100, PAL["text_dim"])
        off = max(0, min(self.sel - 3, len(self.rows) - 7))      # 7 zichtbaar, scrollt
        for i, (kind, bot) in enumerate(self.rows[off:off + 7], off):
            y = 48 + (i - off) * 22
            retro.dialog_box(s, (64, y, 192, 20))
            if i == self.sel:
                arrow(s, 72, y + 6)
            if kind == "continue":
                sv = self.saved
                retro.text(s, "CONTINUE", 84, y + 6)
                retro.text_r(s, f"{sv['size']}x{sv['size']}", 248, y + 6, PAL["text_dim"])
            else:
                retro.text(s, bot[0], 84, y + 6)
        retro.text(s, "B back  START stats", 4, 228, PAL["text_dim"])
        if any(b[1] == "katago" for _, b in self.rows if b) and not gtp.is_warm():
            retro.text_r(s, "loading bot...", 316, 228, PAL["text_dim"])


class OfflineGameScene(GameScene):
    """Pot tegen een lokale engine. Jij zwart, bot wit; stand in conf/offline.json."""
    KOMI = 6.5

    def __init__(self, bot, size, moves=None):
        super().__init__(None)
        self.back = self._leave        # engine netjes afsluiten bij teruggaan
        self.gid = "offline"           # truthy: menu, pass/resign en _do werken zoals online
        self.bot, self.size, self.moves = bot, size, list(moves or [])
        self.board = [[0] * size for _ in range(size)]
        self.cx = self.cy = size // 2
        self.names = ("you", bot[0][:8])
        self.me_id, self.black_id = 1, 1
        self.komi, self.rules, self.speed = self.KOMI, "japanese", "offline"
        self.result = None             # (winner_kleur, 'x points'|'Resignation')
        self.review = None
        self.eng = None
        self.busy = True
        self.msg = "Loading bot" if bot[1] == "katago" and not gtp.is_warm() else "Loading..."
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self):
        try:
            self.eng = gtp.get_engine(self.bot[1], self.bot[2], self.size, self.KOMI)
            for i, (x, y) in enumerate(self.moves):
                self.eng.play("B" if i % 2 == 0 else "W", x, y)
            if len(self.moves) % 2 == 1:
                self._bot_move()
            elif hasattr(self.eng, "eval_async"):
                self.eng.eval_async()          # stand voor de mens alvast beoordelen (review)
            self._load()
        except Exception as e:
            print("offline: engine start failed:", e)
            self._snap = {"msg": "Bot failed"}
        self.busy = False

    def _passes(self):
        return len(self.moves) >= 2 and self.moves[-1][0] < 0 and self.moves[-2][0] < 0

    def _finish(self, winner=None, how=None):
        if winner is None:             # twee keer gepast: engine telt
            sc = self.eng.score() or "B+0"
            winner = 1 if sc[0] == "B" else 2
            how = f"{sc[2:]} points"
        self.result = (winner, how)
        try:
            os.remove(SAVE)
        except OSError:
            pass
        self.review = None
        threading.Thread(target=self._make_review, daemon=True).start()

    def _make_review(self):
        """Na de pot: ontbrekende stellingen aanvullen, alle eigen mistakes/blunders nauwkeuriger
        doorrekenen (30 visits) en de review in conf/reviews.jsonl bewaren."""
        e = self.eng
        if not hasattr(e, "evals"):
            self.review = {"error": "review: KataGo bots only"}
            return
        try:
            moves, gtp_moves = list(self.moves), list(e.moves)
            ev = e.fill_missing()                 # momentopname van déze pot (8 visits, uniform)
            r = review.compute(self.size, moves, ev, human=1)
            if r:                                 # eigen fouten nauwkeuriger, in een APARTE dict
                evd = {}
                for t in review.recheck(r["rows"]):
                    e.deep(t, ev=evd, moves=gtp_moves)
                r = review.compute(self.size, moves, ev, human=1, deep=evd)
            if not r:
                self.review = {"error": "game too short"}
                return
            r.update(size=self.size, bot=self.bot[0], won=self.result[0] == 1, human=1,
                     date=time.strftime("%Y-%m-%d"))
            review.save(REVIEWS, r)
            self.review = r
        except Exception as ex:
            print("review:", ex)
            self.review = {"error": "review failed"}

    def _bot_move(self):
        self._snap = {"msg": "Thinking...", "my_turn": False, "turn_color": 2}
        mv = self.eng.genmove("W")
        if mv == "resign":
            self._finish(1, "Resignation")
            return
        self.moves.append([-1, -1] if mv == "pass" else list(mv))
        if mv != "pass":
            play_stone()
        if self._passes():
            self._finish()

    def _save(self):
        if self.result:
            return
        os.makedirs(os.path.dirname(SAVE), exist_ok=True)
        with open(SAVE, "w") as f:
            json.dump({"bot": self.bot[0], "size": self.size, "moves": self.moves}, f)

    def _load(self):
        board, cb, cw, last = goban.from_moves(self.size, [m + [0] for m in self.moves])
        mine = len(self.moves) % 2 == 0 and not self.result
        bot_passed = bool(self.moves) and self.moves[-1][0] < 0
        self._snap = dict(
            board=board, caps=(cb, cw), last=last, nmoves=len(self.moves),
            phase="finished" if self.result else "play",
            outcome=self.result[1] if self.result else "",
            winner_id=self.result[0] if self.result else None,
            my_color=1, my_turn=mine, turn_color=1 if mine else 2,
            times=("", ""),
            msg=("The end." if self.result else
                 "Bot passed" if mine and bot_passed else
                 "Your move." if mine else "Thinking..."))

    def _do(self, action):
        try:
            if action[0] == "move":
                if not self.eng.play("B", action[1], action[2]):
                    self._load()
                    self._snap["msg"] = "Illegal"
                    self.busy = False
                    return
                self.moves.append([action[1], action[2]])
                self._bot_move()
            elif action[0] == "pass":
                self.eng.play("B", -1, -1)
                self.moves.append([-1, -1])
                if self._passes():
                    self._finish()
                else:
                    self._bot_move()
            elif action[0] == "resign":
                self._finish(2, "Resignation")
            self._save()
            self._load()
        except OSError as e:          # engine gestorven: opnieuw starten, zetten herspelen
            print("offline: engine lost, restarting:", e)
            self._snap = {"msg": "Loading bot"}
            self._start()
            return
        except Exception as e:
            print("offline:", e)
            self._snap = {"msg": f"{action[0]} failed"[:10]}
        self.busy = False

    def handle(self, ev):
        if ev.type == pygame.KEYDOWN and self.phase == "finished" and ev.key in A_KEYS \
                and hasattr(self.eng, "evals"):
            return GameReviewScene(self)
        return super().handle(ev)

    def _leave(self):
        if self.eng and self.eng.kind == "gnugo":     # KataGo blijft warm
            threading.Thread(target=self.eng.close, daemon=True).start()
        return OfflineScene()

REVIEWS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conf", "reviews.jsonl")
CLS_COL = {"best": "green", "good": "text_dim", "inacc": "yellow", "mistake": "orange", "blunder": "accent"}


def _coord(pt, n):
    return review.LET[pt[0]] + str(n - pt[1]) if pt else "pass"


def _draw_board(s, n, board, marks=()):
    """Bord links (zoals GameScene). marks: (kind, pt, extra) — 'last', 'played', 'ring', 'num'."""
    s.blit(board_bg(n), (4, 14))
    c, ox, oy, rr = board_geom(n)
    for y in range(n):
        for x in range(n):
            if board[y][x]:
                retro.stone(s, ox + x * c, oy + y * c, rr, "B" if board[y][x] == 1 else "W")
    for kind, pt, extra in marks:
        if not pt:
            continue
        x, y = ox + pt[0] * c, oy + pt[1] * c
        if kind == "last":
            col = PAL["white_sh"] if board[pt[1]][pt[0]] == 1 else PAL["black_hi"]
            pygame.draw.rect(s, col, (x - 2, y - 2, 5, 5))
        elif kind == "played":            # extra = (kleur 'B'/'W', markeerkleur)
            retro.stone(s, x, y, rr, extra[0])
            pygame.draw.rect(s, PAL[extra[1]], (x - 2, y - 2, 5, 5))
        elif kind == "ring":
            pygame.draw.circle(s, PAL["green"], (x, y), rr + 1, 2)
        elif kind == "num":               # extra = (kleur, nummer)
            retro.stone(s, x, y, rr, extra[0])
            retro.text_c(s, str(extra[1]), x + 1, y - 3, PAL["box"] if extra[0] == "B" else PAL["text"])


class GameReviewScene:
    """REVIEW per pot: scoreverloop, zetklassen jij/bot, verlies/zet, fouttypes."""

    def __init__(self, game):
        self.game = game

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        r = self.game.review
        if ev.key in B_KEYS:
            return self.game._leave()
        if ev.key in A_KEYS and r and r.get("rows"):
            return WalkScene(self, r, self.game.size)
        if ev.key == pygame.K_s:
            return StatsScene(self, self.game.size)
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        g, r = self.game, self.game.review
        res = "won" if g.result and g.result[0] == 1 else "lost"
        retro.text_c(s, "REVIEW", W // 2, 6, PAL["box"])
        retro.text_c(s, f"vs {g.bot[0]}  {g.size}x{g.size}  {res}", W // 2, 20, PAL["text_dim"])
        if r is None or r.get("error"):
            retro.text_c(s, r["error"] if r else "analysing", W // 2, 110, PAL["text_dim"])
            retro.text(s, "B back", 4, 228, PAL["text_dim"])
            return
        # scoreverloop (jouw perspectief: boven = jij voor)
        retro.dialog_box(s, (8, 32, 304, 58))
        L = r["leads"]
        if len(L) > 1:
            x0, x1, ym, hh = 14, 306, 61, 24
            cap = max(10.0, min(60.0, max(abs(v) for v in L)))
            pygame.draw.line(s, PAL["box_dk"], (x0, ym), (x1, ym))
            pts = [(x0 + int(i * (x1 - x0) / (len(L) - 1)), ym - int(max(-cap, min(cap, v)) / cap * hh))
                   for i, v in enumerate(L)]
            pygame.draw.lines(s, PAL["text"], False, pts, 1)
            for row in r["rows"]:
                if row["col"] == 1 and row["cls"] in ("mistake", "blunder") and row["t"] < len(pts):
                    px, py = pts[row["t"]]
                    pygame.draw.rect(s, PAL[CLS_COL[row["cls"]]], (px - 1, py - 1, 3, 3))
            retro.text(s, "you ahead", 14, 35, PAL["text_dim"])
            retro.text(s, "bot ahead", 14, 79, PAL["text_dim"])
            retro.text_r(s, f"move {len(L) - 1}", 306, 79, PAL["text_dim"])
        # zetklassen jij | bot
        retro.dialog_box(s, (8, 94, 150, 96))
        retro.text(s, "ERRORS", 14, 100)
        retro.text_r(s, "you", 114, 100, PAL["text_dim"])
        retro.text_r(s, "bot", 152, 100, PAL["text_dim"])
        for i, (k, lab, sym, _) in enumerate(review.CLASSES[2:]):     # best/good = ruis bij 8 visits
            y = 120 + i * 20
            retro.text(s, (("Inacc" if k == "inacc" else lab) + " " + sym).strip(), 14, y, PAL[CLS_COL[k]])
            retro.text_r(s, str(r["me"].get(k, 0)), 114, y)
            retro.text_r(s, str(r["opp"].get(k, 0)), 152, y, PAL["text_dim"])
        # verlies/zet + fouttypes
        retro.dialog_box(s, (162, 94, 150, 96))
        retro.text(s, "LOSS/MOVE", 168, 100)
        retro.text_r(s, f"{r['loss_per_move']:.1f}", 306, 100)
        retro.text(s, "TYPES", 168, 120)
        types = {}
        for k in ("blunder", "mistake"):
            for c, v in r["types"].get(k, {}).items():
                types[c] = types.get(c, 0) + v
        for i, (c, v) in enumerate(sorted(types.items(), key=lambda kv: -kv[1])[:3]):
            retro.text(s, review.CATS.get(c, (c,))[0], 168, 136 + i * 14)
            retro.text_r(s, f"x{v}", 306, 136 + i * 14, PAL["text_dim"])
        if not types:
            retro.text(s, "no mistakes", 168, 136, PAL["text_dim"])
        retro.dialog_box(s, (8, 196, 304, 22))
        retro.text(s, "A WALK", 16, 203)
        retro.text_c(s, "START STATS", 166, 203)
        retro.text_r(s, "B BACK", 304, 203)


class WalkScene:
    """Zet voor zet door de pot. <> zet, ^v vorige/volgende fout van jou, A betere variant."""

    def __init__(self, parent, r, size, start=None):
        self.parent, self.r, self.n = parent, r, size
        self.rows = {row["t"]: row for row in r["rows"]}
        self.T = r["moves"]
        self.t = start if start is not None else 0
        self.better = False
        self.boards = self._boards()

    def _boards(self):
        """Stand vóór elke zet (voor 13x13 ~250 kleine lijsten: goedkoop)."""
        g = self.parent.game
        b = [[0] * self.n for _ in range(self.n)]
        out = []
        for t, (x, y) in enumerate(g.moves):
            out.append([row[:] for row in b])
            if x >= 0:
                goban.apply_move(b, x, y, 1 if t % 2 == 0 else 2)
        out.append(b)
        return out

    def _bad(self):
        return sorted(t for t, row in self.rows.items()
                      if row["col"] == 1 and row["cls"] in ("inacc", "mistake", "blunder"))

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        if ev.key in B_KEYS:
            return self.parent
        bad = self._bad()
        if ev.key in A_KEYS:
            self.better = not self.better
            return self
        if ev.key == pygame.K_RIGHT:
            self.t = min(self.T - 1, self.t + 1)
        elif ev.key == pygame.K_LEFT:
            self.t = max(0, self.t - 1)
        elif ev.key == pygame.K_DOWN:
            nxt = [t for t in bad if t > self.t]
            self.t = nxt[0] if nxt else (bad[0] if bad else self.t)
        elif ev.key == pygame.K_UP:
            prv = [t for t in bad if t < self.t]
            self.t = prv[-1] if prv else (bad[-1] if bad else self.t)
        self.better = False
        return self

    def draw(self, s):
        g, n, t = self.parent.game, self.n, self.t
        row = self.rows.get(t)
        x, y = g.moves[t]
        played = None if x < 0 else (x, y)
        col_me = "B" if t % 2 == 0 else "W"
        col_op = "W" if col_me == "B" else "B"
        marks = []
        cls = row["cls"] if row else None
        if self.better and row and row["answer"]:
            line = MomentScene_line(row)
            marks += [("num", p, (col_me if k % 2 == 0 else col_op, k + 1)) for k, p in enumerate(line)]
            marks += [("ring", row["answer"], None)]
        else:
            marks += [("played", played, (col_me, CLS_COL.get(cls, "text_dim")))]
            if row and row["answer"] and row["answer"] != played and cls not in ("best", "good"):
                marks += [("ring", row["answer"], None)]
        s.fill(PAL["screen"])
        _draw_board(s, n, self.boards[t], marks)
        # zijpaneel
        retro.dialog_box(s, (224, 14, 92, 34))
        retro.text(s, f"#{t + 1} {_coord(played, n)}", 228, 20)
        retro.text(s, ("you" if col_me == "B" else "bot") + f"  {t + 1}/{self.T}", 228, 34, PAL["text_dim"])
        retro.dialog_box(s, (224, 52, 92, 50))
        if row:
            lab = next(l for k, l, _, _ in review.CLASSES if k == cls)
            sym = next(sy for k, _, sy, _ in review.CLASSES if k == cls)
            retro.text(s, (lab[:7] + " " + sym).strip(), 228, 58, PAL[CLS_COL[cls]])
            retro.text(s, f"-{max(0, row['lost']):.1f} pts" if cls != "best" else "top move", 228, 72,
                       PAL["text_dim"])
            if row["answer"] and cls not in ("best", "good"):
                retro.text(s, f"best {_coord(row['answer'], n)}", 228, 86, PAL["green"])
        else:
            retro.text(s, "no eval", 228, 58, PAL["text_dim"])
        if row and row.get("cat"):
            cat = review.CATS.get(row["cat"], (row["cat"], "", ""))
            retro.dialog_box(s, (224, 106, 92, 52))
            retro.text(s, cat[0], 228, 112)
            retro.text(s, cat[1], 228, 126, PAL["text_dim"])
            retro.text(s, cat[2], 228, 140, PAL["text_dim"])
        retro.dialog_box(s, (224, 162, 92, 64))
        retro.text(s, "<> move", 228, 168, PAL["text_dim"])
        retro.text(s, "^v mistake", 228, 182, PAL["text_dim"])
        retro.text(s, "A " + ("played" if self.better else "better"), 228, 196, PAL["text_dim"])
        retro.text(s, "B back", 228, 210, PAL["text_dim"])


def MomentScene_line(row):
    """Betere zet + vervolg (max 3), stopt bij de eerste pass in de variant."""
    pv = []
    for p in (row.get("pv") or [])[:3]:
        if not p:
            break
        pv.append(tuple(p))
    if row["answer"] and (not pv or pv[0] != tuple(row["answer"])):
        pv = [tuple(row["answer"])] + pv[:2]
    return pv


class StatsScene:
    """Hoog-over per bordmaat (laatste 20 potten): trend verlies/zet, per fase, fouten per pot,
    meest gemaakte typen blunders en mistakes."""

    def __init__(self, parent, size=None):
        self.parent = parent
        self.size = size if size in BOARD_SIZES else new_size

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        if ev.key in B_KEYS or ev.key == pygame.K_s:
            return self.parent
        if ev.key in (pygame.K_LEFT, pygame.K_RIGHT):
            i = BOARD_SIZES.index(self.size) + (1 if ev.key == pygame.K_RIGHT else -1)
            self.size = BOARD_SIZES[i % len(BOARD_SIZES)]
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        h = review.history(REVIEWS, self.size, 20)
        retro.text_c(s, "STATS", W // 2, 6, PAL["box"])
        retro.text_c(s, f"< {self.size}x{self.size} >  last {len(h)} games", W // 2, 20, PAL["text_dim"])
        if not h:
            retro.text_c(s, "no reviews yet", W // 2, 110, PAL["text_dim"])
            retro.text(s, "B back", 4, 228, PAL["text_dim"])
            return
        mean = lambda v: sum(v) / len(v) if v else None
        # 1. trend verlies/zet
        retro.dialog_box(s, (8, 32, 304, 60))
        retro.text(s, "LOSS/MOVE", 14, 38)
        vals = [r["loss_per_move"] for r in h]
        avg = mean(vals)
        retro.text_r(s, f"last {vals[-1]:.1f}  avg {avg:.1f}", 306, 38, PAL["text_dim"])
        top, base, x0, x1 = 8.0, 86, 16, 304
        if len(vals) > 1:
            pts = [(x0 + int(i * (x1 - x0) / (len(vals) - 1)), base - int(min(top, v) / top * 34))
                   for i, v in enumerate(vals)]
            ay = base - int(min(top, avg) / top * 34)
            for xx in range(x0, x1, 6):
                pygame.draw.line(s, PAL["box_dk"], (xx, ay), (xx + 2, ay))
            pygame.draw.lines(s, PAL["text"], False, pts, 1)
            for (px, py), r in zip(pts, h):
                pygame.draw.rect(s, PAL["green"] if r.get("won") else PAL["text"], (px - 1, py - 1, 3, 3))
        # 2. per fase: laatste 5 vs de 5 daarvoor
        retro.dialog_box(s, (8, 96, 150, 64))
        retro.text(s, "BY PHASE", 14, 102)
        if len(h) >= 10:
            retro.text_r(s, "vs prev", 152, 102, PAL["text_dim"])
        for i, (ph, lab) in enumerate((("open", "open"), ("mid", "mid"), ("end", "end"))):
            series = [r["phases"][ph] for r in h if r.get("phases", {}).get(ph) is not None]
            now, before = mean(series[-5:]), mean(series[-10:-5])
            y = 116 + i * 14
            retro.text(s, lab, 14, y)
            if now is not None:
                retro.text_r(s, f"{now:.1f}", 96, y)
                if before is not None and len(h) >= 10:
                    d = now - before
                    retro.text_r(s, f"{d:+.1f}", 152, y, PAL["accent"] if d > 0.2 else PAL["text_dim"])
        # 3. fouten per pot
        retro.dialog_box(s, (162, 96, 150, 64))
        retro.text(s, "PER GAME", 168, 102)
        for i, k in enumerate(("blunder", "mistake", "inacc")):
            lab, sym = next((l, sy) for kk, l, sy, _ in review.CLASSES if kk == k)
            v = mean([r["me"].get(k, 0) for r in h])
            retro.text(s, (lab[:7 if k != "inacc" else 5] + " " + sym).strip(), 168, 116 + i * 14, PAL[CLS_COL[k]])
            retro.text_r(s, f"{v:.1f}", 306, 116 + i * 14)
        # 4. meest gemaakte typen
        retro.dialog_box(s, (8, 164, 304, 54))
        for j, (k, title) in enumerate((("blunder", "BLUNDERS"), ("mistake", "MISTAKES"))):
            tot = {}
            for r in h:
                for c, v in (r.get("types", {}).get(k) or {}).items():
                    tot[c] = tot.get(c, 0) + v
            x = 14 + j * 152
            retro.text(s, title, x, 170, PAL[CLS_COL[k]])
            for i, (c, v) in enumerate(sorted(tot.items(), key=lambda kv: -kv[1])[:2]):
                retro.text(s, review.CATS.get(c, (c,))[0], x, 186 + i * 14)
                retro.text_r(s, f"x{v}", x + 142, 186 + i * 14, PAL["text_dim"])
            if not tot:
                retro.text(s, "-", x, 186, PAL["text_dim"])
        retro.text(s, "<> board", 4, 228, PAL["text_dim"])
        pygame.draw.rect(s, PAL["green"], (118, 230, 3, 3))
        retro.text(s, "won", 126, 228, PAL["text_dim"])
        retro.text_r(s, "B back", 316, 228, PAL["text_dim"])



REMOTE = "/tmp/flipgo-remote"     # dev: bestaat deze map, dan stuurt Claude toetsen + vraagt shots
REMOTE_KEYS = {"A": pygame.K_RETURN, "B": pygame.K_BACKSPACE, "START": pygame.K_s,
               "UP": pygame.K_UP, "DOWN": pygame.K_DOWN, "LEFT": pygame.K_LEFT,
               "RIGHT": pygame.K_RIGHT}


def remote_poll(canvas):
    """Lees toetsen uit REMOTE/keys (één per regel); SHOT bewaart het scherm."""
    f = os.path.join(REMOTE, "keys")
    if not os.path.exists(f):
        return []
    try:
        os.rename(f, f + ".busy")          # atomisch overnemen
        lines = open(f + ".busy").read().split()
        os.remove(f + ".busy")
    except OSError:
        return []
    evs = []
    for k in lines:
        if k.upper() == "SHOT":
            pygame.image.save(canvas, os.path.join(REMOTE, "shot.png"))
        elif k.upper() in REMOTE_KEYS:
            evs.append(pygame.event.Event(pygame.KEYDOWN, key=REMOTE_KEYS[k.upper()]))
    return evs


def main():
    pygame.init()
    try:
        pygame.mixer.init()
    except Exception:
        pass
    pygame.joystick.init()
    for i in range(pygame.joystick.get_count()):
        pygame.joystick.Joystick(i).init()
    print("pad: joysticks at start:", pygame.joystick.get_count(),
          [pygame.joystick.Joystick(i).get_name()
           for i in range(pygame.joystick.get_count())])
    shot = "--shot" in sys.argv
    win = pygame.display.set_mode((W * SCALE, H * SCALE))
    pygame.display.set_caption("flip-go")
    canvas = pygame.Surface((W, H))
    if shot:
        os.makedirs("out", exist_ok=True)
        game = GameScene(None)
        game.menu = 1
        for name, scene in (("title", TitleScene()), ("game", game),
                            ("newgame", NewGameScene())):
            scene.draw(canvas)
            pygame.image.save(pygame.transform.scale(canvas, (W * 2, H * 2)),
                              f"out/{name}.png")
        print("shots: out/title.png out/game.png out/newgame.png")
        return
    scene = TitleScene()
    clock = pygame.time.Clock()
    last_frame, fresh, last_input = None, 0, 0.0
    while True:
        remote = remote_poll(canvas) if os.path.isdir(REMOTE) else []
        for ev in pygame.event.get() + remote:
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.JOYDEVICEADDED:
                j = pygame.joystick.Joystick(ev.device_index)
                j.init()
                print("pad: joystick added:", j.get_name())
            ev = pad_translate(ev) or ev
            if ev.type == pygame.KEYDOWN:
                last_input = time.monotonic()
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                if isinstance(scene, TitleScene):
                    return
                ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_BACKSPACE)
            scene = scene.handle(ev)
        nxt = getattr(scene, "goto", None)
        if nxt is not None:
            scene.goto = None
            scene = nxt
        scene.draw(canvas)
        # alleen schalen + flippen als het canvas veranderde (2x: dubbele buffer)
        frame = canvas.get_buffer().raw
        if frame != last_frame:
            last_frame, fresh = frame, 2
        if fresh:
            fresh -= 1
            pygame.transform.scale(canvas, win.get_size(), win)
            pygame.display.flip()
        # 60 fps vlak na input; rust 20 fps (spaart accu, achtergrond-updates
        # binnen 50 ms); bot denkt / laadt: 15 fps laat de CPU aan de engine
        if getattr(scene, "busy", False):
            clock.tick(15)
        else:
            clock.tick(60 if time.monotonic() - last_input < 1 else 20)


if __name__ == "__main__":
    main()
