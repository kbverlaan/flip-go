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
import ogs

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


def arrow(s, x, y, color=None):
    """Pokemon-cursor: klein driehoekje."""
    c = color or PAL["text"]
    pygame.draw.polygon(s, c, [(x, y), (x, y + 8), (x + 5, y + 4)])


class TitleScene:
    def __init__(self):
        self.t = 0

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
        if (self.t // 30) % 2 == 0:
            retro.text_c(s, "PRESS START", W // 2, 205, PAL["box"])
        self.t += 1


class GamesScene:
    """Je potten + open challenges + NEW GAME."""

    def __init__(self):
        self.games = None
        self.seeking = []
        self.error = None
        self.sel = 0
        self.t = 0
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
            self.error = "Offline - mock game"
            self.games = []

    FOOTER = ("NEW GAME", "HISTORY")

    def _rows(self):
        """-> lijst ('game'|'seek', data); footer staat er los onder"""
        rows = [("game", g) for g in (self.games or [])]
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
                return GameScene(None) if self.error else NewGameScene()
            kind, data = rows[self.sel]
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
        if self.games is None:
            retro.text_c(s, "loading" + "." * ((self.t // 20) % 4), W // 2, 110, PAL["text_dim"])
            self.t += 1
            return
        rows = self._rows()
        for i, (kind, data) in enumerate(rows[:5]):
            y = 44 + i * 30
            retro.dialog_box(s, (16, y, 288, 26))
            if i == self.sel:
                arrow(s, 24, y + 9)
            if kind == "game":
                retro.text(s, f"vs {data['opp'][:19]}", 36, y + 9)
                retro.text(s, data["speed"], 240, y + 9, PAL["text_dim"])
                if data["my_turn"]:
                    retro.text(s, "*", 288, y + 9, PAL["accent"])
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
        left_label = "MOCK BOARD" if self.error else "NEW GAME"
        for f, (bx, label) in enumerate(((16, left_label), (164, "HISTORY"))):
            retro.dialog_box(s, (bx, 192, 140, 26))
            if on_footer and self.fsel == f:
                arrow(s, bx + 10, 192 + 9)
            retro.text_c(s, label, bx + 76, 192 + 9)
        if self.error:
            retro.text_c(s, self.error, W // 2, 220, PAL["text_dim"])
        elif self.me_label:
            retro.text_c(s, self.me_label, W // 2, 226, PAL["text_dim"])
        self.t += 1


class NewGameScene:
    """Nieuwe pot: daily, live (open challenge) of een bot van de bloemenladder."""
    OPTIONS = (("daily", "3d + 1d per move"),
               ("live", "2m + 30s per move"),
               ("bots", "the flower ladder"))

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
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(self.OPTIONS) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in A_KEYS:
            if self.OPTIONS[self.sel][0] == "bots":
                return BotScene()
            self.busy = True
            self.msg = "Posting..."
            threading.Thread(target=self._create, daemon=True).start()
        return self

    def _create(self):
        try:
            ogs.create_challenge(self.OPTIONS[self.sel][0])
            self.msg = "Posted. Any key: games"
            self.done = True
        except Exception:
            self.msg = "Failed"
        self.busy = False

    def draw(self, s):
        s.fill(PAL["screen"])
        retro.text_c(s, "NEW GAME", W // 2, 14, PAL["box"])
        retro.text_c(s, "9x9 - ranked - japanese", W // 2, 34, PAL["text_dim"])
        for i, (name, desc) in enumerate(self.OPTIONS):
            y = 60 + i * 44
            retro.dialog_box(s, (60, y, 200, 38))
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
            ogs.challenge_player(pid, "daily")
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
        for i, (name, _) in enumerate(self.flowers):
            y = 40 + i * 24
            retro.dialog_box(s, (76, y, 168, 20))
            if i == self.sel:
                arrow(s, 84, y + 6)
            retro.text(s, name, 96, y + 6)
            rk = self.ranks.get(self.flowers[i][1])
            if rk:
                retro.text(s, rk, 212, y + 6, PAL["text_dim"])
        if self.msg:
            retro.text_c(s, self.msg, W // 2, 218, PAL["text_dim"])


class HistoryScene:
    """Laatste afgeronde potten: uitslag + tegenstander. A = terugkijken."""

    def __init__(self):
        self.rows = None
        self.sel = 0
        self.t = 0
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
            retro.text_c(s, "loading" + "." * ((self.t // 20) % 4), W // 2, 110, PAL["text_dim"])
        elif not self.rows:
            retro.text_c(s, "No finished games.", W // 2, 110, PAL["text_dim"])
        else:
            for i, r in enumerate(self.rows[:6]):
                y = 44 + i * 30
                retro.dialog_box(s, (16, y, 288, 26))
                if i == self.sel:
                    arrow(s, 24, y + 9)
                retro.text(s, "won " if r["won"] else "lost", 36, y + 9,
                           PAL["green"] if r["won"] else PAL["accent"])
                retro.text(s, f"vs {r['opp'][:15]}", 76, y + 9)
                retro.text(s, r["result"], 240, y + 9, PAL["text_dim"])
        self.t += 1


class GameScene:
    """Echte OGS-pot (of mock als gid None). A = zet (met bevestiging),
    S = menu: Pass / Resign / Info / Quit."""
    MENU = ("PASS", "RESIGN", "INFO", "QUIT")

    def __init__(self, gid, back=None):
        self.gid = gid
        self.back = back or GamesScene
        self.size = 9
        self.cx = self.cy = 4
        self.t = 0
        self.board = [[0] * 9 for _ in range(9)]
        self.caps = (0, 0)
        self.last = None
        self.names = ("black", "white")
        self.komi = 6.5
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
        self._bg = None
        self._bg_size = None
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
            cur = gd.get("clock", {}).get("current_player")
            phase = gd.get("phase", "play")
            if len(moves) > self.nmoves and self.nmoves:
                play_stone()          # nieuwe zet binnengekomen
            # alles in één publicatie; draw neemt hem op de main thread over
            self._snap = dict(
                size=size, board=board, caps=(cb, cw), last=last, nmoves=len(moves),
                names=(pl.get("black", {}).get("username", "?"),
                       pl.get("white", {}).get("username", "?")),
                komi=float(gd.get("komi", 6.5)), rules=gd.get("rules", "japanese"),
                speed=ogs.speed_label(gd.get("time_control", {}).get("speed", "")),
                phase=phase, outcome=gd.get("outcome", ""),
                winner_id=gd.get("winner"), black_id=black_id, me_id=me_id,
                my_color=1 if black_id == me_id else 2, my_turn=cur == me_id,
                turn_color=1 if cur == black_id else 2,
                msg=("The end." if phase == "finished" else
                     "Counting" if phase == "stone removal" else
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
        retro.text(s, name[:9], 244, y + 7)
        retro.text(s, f"caps {caps}", 238, y + 20, PAL["text_dim"])

    def _board_bg(self):
        """Statisch bord (hout, raster, hoshi) 1x gerenderd per bordmaat."""
        if self._bg is None or self._bg_size != self.size:
            n = self.size
            c = min(23, 184 // max(1, n - 1))
            span = c * (n - 1)
            o = (212 - span) // 2
            bg = pygame.Surface((212, 212))
            bg.fill(PAL["wood"])
            pygame.draw.rect(bg, PAL["line"], (0, 0, 212, 212), 1)
            for i in range(n):
                pygame.draw.line(bg, PAL["line"], (o, o + i * c), (o + span, o + i * c))
                pygame.draw.line(bg, PAL["line"], (o + i * c, o), (o + i * c, o + span))
            if n == 9:
                for hx, hy in ((2, 2), (6, 2), (4, 4), (2, 6), (6, 6)):
                    pygame.draw.rect(bg, PAL["line"], (o + hx * c - 1, o + hy * c - 1, 3, 3))
            self._bg, self._bg_size = bg, n
        return self._bg

    def draw(self, s):
        if self._snap:               # atomaire overname van een verse load
            self.__dict__.update(self._snap)
            self._snap = None
        s.fill(PAL["screen"])
        s.blit(self._board_bg(), (4, 14))
        n = self.size
        c = min(23, 184 // max(1, n - 1))
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
                # ghost-steen: je ziet wat A gaat doen
                ghost = pygame.Surface((r * 2 + 4, r * 2 + 4))
                ghost.fill((255, 0, 255))
                ghost.set_colorkey((255, 0, 255))
                retro.stone(ghost, r + 2, r + 2, r, "B" if self.my_color == 1 else "W")
                ghost.set_alpha(140)
                s.blit(ghost, (px - r - 2, py - r - 2))
            else:
                a = PAL["accent"]
                for sx in (-1, 1):
                    for sy in (-1, 1):
                        x0, y0 = px + sx * 10, py + sy * 10
                        pygame.draw.line(s, a, (x0, y0), (x0 - sx * 4, y0))
                        pygame.draw.line(s, a, (x0, y0), (x0, y0 - sy * 4))
        # plates: zwart boven, wit onder — Go-conventie, direct onder elkaar
        playing = self.phase == "play"
        self._plate(s, 14, 1, self.names[0], self.caps[0], playing and self.turn_color == 1)
        self._plate(s, 52, 2, self.names[1], self.caps[1], playing and self.turn_color == 2)
        retro.dialog_box(s, (224, 198, 92, 28))
        retro.text(s, self.msg[:10], 230, 208)
        # menu tussen plates en berichtvak (Pokemon-pauzemenu)
        if self.menu is not None:
            retro.dialog_box(s, (224, 96, 92, 92))
            for i, item in enumerate(self.MENU):
                y = 104 + i * 20
                if i == self.menu:
                    arrow(s, 230, y)
                retro.text(s, item, 240, y)
        if self.info:
            retro.dialog_box(s, (40, 80, 240, 76))
            retro.text(s, f"{self.speed or 'local'} - {self.rules}", 52, 92)
            retro.text(s, f"komi {self.komi:g}", 52, 108)
            retro.text(s, f"move {self.nmoves}", 52, 124)
            retro.text(s, "B: close", 52, 140, PAL["text_dim"])
        if self.phase == "finished" and self.gid:
            won = self.winner_id == self.me_id
            retro.dialog_box(s, (40, 84, 240, 68))
            retro.text_c(s, "YOU WON" if won else "YOU LOST", 160, 98,
                         PAL["green"] if won else PAL["accent"])
            retro.text_c(s, ogs.format_outcome(self.winner_id == self.black_id,
                                               self.outcome), 160, 116)
            retro.text_c(s, "A: back to games", 160, 134, PAL["text_dim"])
        elif self.phase == "stone removal" and not self.busy:
            retro.dialog_box(s, (40, 84, 240, 68))
            retro.text_c(s, "COUNTING", 160, 98)
            retro.text_c(s, "A: accept result", 160, 116)
            retro.text_c(s, "B: back to games", 160, 134, PAL["text_dim"])
        poll = 180 if self.speed in ("live", "blitz") else 1800
        if (self.gid and self.t and self.t % poll == 0 and not self._loading and
                (self.phase == "stone removal" or (playing and not self.my_turn))):
            threading.Thread(target=self._load, daemon=True).start()
        self.t += 1


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
            scene.t = 0
            scene.draw(canvas)
            pygame.image.save(pygame.transform.scale(canvas, (W * 2, H * 2)),
                              f"out/{name}.png")
        print("shots: out/title.png out/game.png out/newgame.png")
        return
    scene = TitleScene()
    clock = pygame.time.Clock()
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                return
            if ev.type == pygame.JOYDEVICEADDED:
                j = pygame.joystick.Joystick(ev.device_index)
                j.init()
                print("pad: joystick added:", j.get_name())
            ev = pad_translate(ev) or ev
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
        pygame.transform.scale(canvas, win.get_size(), win)
        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    main()
