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

if "--shot" in sys.argv:
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame
import retro
from retro import PAL, W, H

SCALE = 2  # 640x480 venster; op de Flip fullscreen 2x

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
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            import ogs
            self.games = ogs.my_games()
            self.seeking = ogs.my_challenges()
        except Exception:
            self.error = "Offline - mock game"
            self.games = []

    def _rows(self):
        """-> lijst ('game'|'seek'|'new', data)"""
        rows = [("game", g) for g in (self.games or [])]
        rows += [("seek", c) for c in self.seeking]
        rows.append(("new", None))
        return rows

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN or self.stopping:
            return self
        if self.cancelq:
            if ev.key in (pygame.K_RETURN, pygame.K_x):
                self.stopping = self.cancelq
                self.cancelq = None
                threading.Thread(target=self._cancel, args=(self.stopping,), daemon=True).start()
            elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
                self.cancelq = None
            return self
        rows = self._rows()
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(rows) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
            kind, data = rows[self.sel]
            if kind == "game":
                return GameScene(data["id"])
            if kind == "seek":
                self.cancelq = data["id"]
            elif kind == "new":
                if self.error:
                    return GameScene(None)
                return NewGameScene()
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            return TitleScene()
        elif ev.key == pygame.K_r:
            return GamesScene()
        return self

    def _cancel(self, cid):
        try:
            import ogs
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
        for i, (kind, data) in enumerate(rows[:6]):
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
            else:
                label = "MOCK BOARD" if self.error else "NEW GAME"
                retro.text(s, label, 36, y + 9)
        if self.error:
            retro.text_c(s, self.error, W // 2, 220, PAL["text_dim"])
        self.t += 1


class NewGameScene:
    """Nieuwe pot: daily, live (open challenge) of een bot van de bloemenladder."""
    OPTIONS = (("daily", "3d + 1d per move"),
               ("live", "2m + 30s per move"),
               ("bots", "the flower ladder"))

    def __init__(self):
        self.sel = 0
        self.t = 0
        self.busy = False
        self.done = False
        self.msg = None

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN or self.busy:
            return self
        if self.done:
            return GamesScene()
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(self.OPTIONS) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
            if self.OPTIONS[self.sel][0] == "bots":
                return BotScene()
            self.busy = True
            self.msg = "Posting..."
            threading.Thread(target=self._create, daemon=True).start()
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            return GamesScene()
        return self

    def _create(self):
        try:
            import ogs
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
        self.t += 1


class BotScene:
    """De bloemenladder: challenge een bot, die accepteert vanzelf."""

    def __init__(self):
        import ogs
        self.flowers = ogs.FLOWERS
        self.sel = 3      # Bouvardia, de vaste sparringspartner
        self.t = 0
        self.busy = False
        self.done = False
        self.msg = None

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN or self.busy:
            return self
        if self.done:
            return GamesScene()
        if ev.key == pygame.K_DOWN:
            self.sel = min(len(self.flowers) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP:
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
            self.busy = True
            self.msg = "Challenging..."
            threading.Thread(target=self._challenge, daemon=True).start()
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            return NewGameScene()
        return self

    def _challenge(self):
        try:
            import ogs
            ogs.challenge_player(self.flowers[self.sel][1], "live")
            self.msg = "Sent. Any key: games"
            self.done = True
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
        if self.msg:
            retro.text_c(s, self.msg, W // 2, 218, PAL["text_dim"])
        self.t += 1


class GameScene:
    """Echte OGS-pot (of mock als gid None). A = zet (met bevestiging),
    S = menu: Pass / Resign / Info / Quit."""
    MENU = ("PASS", "RESIGN", "INFO", "QUIT")

    def __init__(self, gid):
        self.gid = gid
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
        self.phase = "play"
        self.outcome = ""
        self.nmoves = 0
        self.confirm = None      # ("move",x,y) | ("pass",) | ("resign",)
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
        try:
            import ogs
            import goban
            g = ogs.api(f"games/{self.gid}")
            gd = g.get("gamedata", {})
            self.size = gd.get("width", 9)
            pl = gd.get("players", {})
            self.names = (pl.get("black", {}).get("username", "?"),
                          pl.get("white", {}).get("username", "?"))
            self.komi = float(gd.get("komi", 6.5))
            self.rules = gd.get("rules", "japanese")
            sp = gd.get("time_control", {}).get("speed", "")
            self.speed = "daily" if sp == "correspondence" else sp
            self.phase = gd.get("phase", "play")
            self.outcome = gd.get("outcome", "")
            moves = gd.get("moves", [])
            board, cb, cw, last = goban.from_moves(self.size, moves, gd.get("handicap", 0))
            if len(moves) > self.nmoves and self.nmoves:
                play_stone()          # nieuwe zet binnengekomen
            self.nmoves = len(moves)
            self.board, self.caps, self.last = board, (cb, cw), last
            m = ogs.me()
            self.my_color = 1 if pl.get("black", {}).get("id") == m.get("id") else 2
            self.my_turn = gd.get("clock", {}).get("current_player") == m.get("id")
            if self.phase == "finished":
                self.msg = self.outcome[:10] or "finished"
            elif self.phase != "play":
                self.msg = self.phase[:10]
            else:
                self.msg = "Your move." if self.my_turn else "Waiting..."
        except Exception:
            self.msg = "Load failed"

    def _do(self, action):
        try:
            import ogs
            if action[0] == "move":
                ogs.submit_move(self.gid, action[1], action[2], self.size)
                play_stone()
            elif action[0] == "pass":
                ogs.pass_move(self.gid)
            elif action[0] == "resign":
                ogs.resign(self.gid)
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
        dx = (ev.key == pygame.K_RIGHT) - (ev.key == pygame.K_LEFT)
        dy = (ev.key == pygame.K_DOWN) - (ev.key == pygame.K_UP)
        if dx or dy:
            self.cx = max(0, min(self.size - 1, self.cx + dx))
            self.cy = max(0, min(self.size - 1, self.cy + dy))
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
            if self.my_turn and self.phase == "play" and self.board[self.cy][self.cx] == 0:
                self.confirm = ("move", self.cx, self.cy)
                self.msg = self._coord(self.cx, self.cy) + "? A/B"
        elif ev.key == pygame.K_s:
            if self.gid and self.phase == "play":
                self.menu = 0
        elif ev.key == pygame.K_r:
            if self.gid:
                self.msg = "..."
                threading.Thread(target=self._load, daemon=True).start()
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            return GamesScene() if self.gid else TitleScene()
        return self

    def _handle_confirm(self, ev):
        if ev.key in (pygame.K_RETURN, pygame.K_x):
            action = self.confirm
            self.confirm = None
            if self.gid:
                self.busy = True
                self.msg = "Sending..."
                threading.Thread(target=self._do, args=(action,), daemon=True).start()
            elif action[0] == "move":
                self.board[action[2]][action[1]] = 1
                play_stone()
                self.msg = "You: " + self._coord(action[1], action[2])
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            self.confirm = None
            self.msg = "Your move."
        return self

    def _handle_menu(self, ev):
        if ev.key == pygame.K_DOWN:
            self.menu = (self.menu + 1) % len(self.MENU)
        elif ev.key == pygame.K_UP:
            self.menu = (self.menu - 1) % len(self.MENU)
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
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
                return GamesScene()
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z, pygame.K_s):
            self.menu = None
        return self

    def _coord(self, x, y):
        return "ABCDEFGHJKLMNOPQRST"[x] + str(self.size - y)

    # ---------- draw ----------
    def _plate(self, s, y, color, name, caps, to_move):
        retro.dialog_box(s, (224, y, 92, 34))
        if to_move and self.phase == "play":
            arrow(s, 228, y + 7, PAL["accent"])
        retro.stone(s, 240, y + 11, 4, "B" if color == 1 else "W")
        retro.text(s, name[:8], 248, y + 7)
        retro.text(s, f"caps {caps}", 240, y + 20, PAL["text_dim"])

    def draw(self, s):
        s.fill(PAL["screen"])
        pygame.draw.rect(s, PAL["wood"], (4, 14, 212, 212))
        pygame.draw.rect(s, PAL["line"], (4, 14, 212, 212), 1)
        n = self.size
        c = min(23, 184 // max(1, n - 1))
        span = c * (n - 1)
        ox = 4 + (212 - span) // 2
        oy = 14 + (212 - span) // 2
        for i in range(n):
            pygame.draw.line(s, PAL["line"], (ox, oy + i * c), (ox + span, oy + i * c))
            pygame.draw.line(s, PAL["line"], (ox + i * c, oy), (ox + i * c, oy + span))
        if n == 9:
            for hx, hy in ((2, 2), (6, 2), (4, 4), (2, 6), (6, 6)):
                pygame.draw.circle(s, PAL["line"], (ox + hx * c, oy + hy * c), 2)
        r = max(4, c * 2 // 5 + 1)
        for y in range(n):
            for x in range(n):
                if self.board[y][x]:
                    retro.stone(s, ox + x * c, oy + y * c, r,
                                "B" if self.board[y][x] == 1 else "W")
        if self.last:
            lx, ly = self.last
            col = PAL["white_sh"] if self.board[ly][lx] == 1 else PAL["black_hi"]
            pygame.draw.rect(s, col, (ox + lx * c - 2, oy + ly * c - 2, 4, 4))
        if self.confirm and self.confirm[0] == "move":
            _, cx, cy = self.confirm
            retro.stone(s, ox + cx * c, oy + cy * c, r, "B" if self.my_color == 1 else "W")
            pygame.draw.circle(s, PAL["accent"], (ox + cx * c, oy + cy * c), r + 2, 1)
        elif self.menu is None and not self.info:
            a = PAL["accent"]
            px, py = ox + self.cx * c, oy + self.cy * c
            for sx in (-1, 1):
                for sy in (-1, 1):
                    x0, y0 = px + sx * 10, py + sy * 10
                    pygame.draw.line(s, a, (x0, y0), (x0 - sx * 4, y0))
                    pygame.draw.line(s, a, (x0, y0), (x0, y0 - sy * 4))
        # Pokemon-plates: tegenstander boven, jij onder
        opp = 2 if self.my_color == 1 else 1
        me_i, opp_i = self.my_color - 1, opp - 1
        names = self.names
        caps = self.caps
        opp_turn = not self.my_turn
        self._plate(s, 14, opp, names[opp_i], caps[opp_i], opp_turn)
        self._plate(s, 156, self.my_color, names[me_i], caps[me_i], self.my_turn)
        retro.dialog_box(s, (224, 198, 92, 28))
        retro.text(s, self.msg[:10], 230, 208)
        # menu-overlay (Pokemon-pauzemenu)
        if self.menu is not None:
            retro.dialog_box(s, (224, 56, 92, 92))
            for i, item in enumerate(self.MENU):
                y = 64 + i * 20
                if i == self.menu:
                    arrow(s, 230, y)
                retro.text(s, item, 240, y)
        if self.info:
            retro.dialog_box(s, (40, 80, 240, 76))
            retro.text(s, f"{self.speed or 'local'} - {self.rules}", 52, 92)
            retro.text(s, f"komi {self.komi:g}", 52, 108)
            retro.text(s, f"move {self.nmoves}", 52, 124)
            retro.text(s, "B: close", 52, 140, PAL["text_dim"])
        poll = 180 if self.speed in ("live", "blitz") else 1800
        if self.gid and not self.my_turn and self.phase == "play" and self.t and self.t % poll == 0:
            threading.Thread(target=self._load, daemon=True).start()
        self.t += 1


def main():
    pygame.init()
    try:
        pygame.mixer.init()
    except Exception:
        pass
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
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                return
            scene = scene.handle(ev)
        canvas.fill((0, 0, 0))
        scene.draw(canvas)
        win.blit(pygame.transform.scale(canvas, win.get_size()), (0, 0))
        pygame.display.flip()
        clock.tick(60)


if __name__ == "__main__":
    main()
