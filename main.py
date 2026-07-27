"""flip-go: retro OGS-client voor de Miyoo Flip (en de Mac om te testen).

Run:            python main.py
Screenshots:    python main.py --shot   (headless, schrijft out/*.png)

Besturing (Mac-test = Flip-mapping):
  pijltjes = D-pad   Enter/X = A   Backspace/Z = B   S = Start   R = refresh
"""
import os
import sys
import threading

if "--shot" in sys.argv:
    os.environ["SDL_VIDEODRIVER"] = "dummy"

import pygame
import retro
from retro import PAL, W, H

SCALE = 2  # 640x480 venster; op de Flip fullscreen 2x


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
    """Je actieve OGS-potten. Enter = openen."""

    def __init__(self):
        self.games = None      # None = laden, [] = geen, lijst = klaar
        self.error = None
        self.sel = 0
        self.t = 0
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            import ogs
            self.games = ogs.my_games()
        except Exception as e:
            self.error = "Offline - mock game"
            self.games = []

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        gs = self.games or []
        if ev.key == pygame.K_DOWN and gs:
            self.sel = min(len(gs) - 1, self.sel + 1)
        elif ev.key == pygame.K_UP and gs:
            self.sel = max(0, self.sel - 1)
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
            if gs:
                return GameScene(gs[self.sel]["id"])
            if self.error:
                return GameScene(None)     # offline: mock
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            return TitleScene()
        elif ev.key == pygame.K_r:
            return GamesScene()
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        retro.text_c(s, "YOUR GAMES", W // 2, 14, PAL["box"])
        if self.games is None:
            retro.text_c(s, "loading" + "." * ((self.t // 20) % 4), W // 2, 110, PAL["text_dim"])
        elif not self.games:
            retro.text_c(s, self.error or "No active games.", W // 2, 100, PAL["text_dim"])
            retro.text_c(s, "A: mock board  B: back", W // 2, 120, PAL["text_dim"])
        else:
            for i, g in enumerate(self.games[:6]):
                y = 44 + i * 30
                retro.dialog_box(s, (16, y, 288, 26))
                mark = ">" if i == self.sel and (self.t // 20) % 2 == 0 else " "
                retro.text(s, f"{mark}{g['black'][:8]} v {g['white'][:8]}", 24, y + 9)
                if g["my_turn"]:
                    retro.text(s, "*", 288, y + 9, PAL["accent"])
        self.t += 1


class GameScene:
    """Echte OGS-pot (of mock als gid None). A op leeg punt -> bevestig -> zet."""
    CELL = 23

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
        self.my_color = 1
        self.my_turn = False
        self.phase = "play"
        self.confirm = None      # (x, y) wacht op A/B
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
            self.phase = gd.get("phase", "play")
            board, cb, cw, last = goban.from_moves(
                self.size, gd.get("moves", []), gd.get("handicap", 0))
            self.board, self.caps, self.last = board, (cb, cw), last
            m = ogs.me()
            self.my_color = 1 if pl.get("black", {}).get("id") == m.get("id") else 2
            self.my_turn = gd.get("clock", {}).get("current_player") == m.get("id")
            if self.phase != "play":
                self.msg = self.phase
            else:
                self.msg = "Your move." if self.my_turn else "Waiting..."
        except Exception:
            self.msg = "Load failed"

    def _submit(self, x, y):
        try:
            import ogs
            ogs.submit_move(self.gid, x, y, self.size)
            self._load()
        except Exception:
            self.msg = "Move failed"
        self.busy = False

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN or self.busy:
            return self
        if self.confirm:
            if ev.key in (pygame.K_RETURN, pygame.K_x):
                x, y = self.confirm
                self.confirm = None
                if self.gid:
                    self.busy = True
                    self.msg = "Sending..."
                    threading.Thread(target=self._submit, args=(x, y), daemon=True).start()
                else:
                    self.board[y][x] = 1
                    self.msg = "You: " + self._coord(x, y)
            elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
                self.confirm = None
                self.msg = "Your move."
            return self
        dx = (ev.key == pygame.K_RIGHT) - (ev.key == pygame.K_LEFT)
        dy = (ev.key == pygame.K_DOWN) - (ev.key == pygame.K_UP)
        if dx or dy:
            self.cx = max(0, min(self.size - 1, self.cx + dx))
            self.cy = max(0, min(self.size - 1, self.cy + dy))
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
            if self.my_turn and self.board[self.cy][self.cx] == 0:
                self.confirm = (self.cx, self.cy)
                self.msg = self._coord(self.cx, self.cy) + "? A/B"
        elif ev.key == pygame.K_r:
            if self.gid:
                self.msg = "Refreshing..."
                threading.Thread(target=self._load, daemon=True).start()
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            return GamesScene() if self.gid else TitleScene()
        return self

    def _coord(self, x, y):
        return "ABCDEFGHJKLMNOPQRST"[x] + str(self.size - y)

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
        blink = (self.t // 20) % 2 == 0
        px, py = ox + self.cx * c, oy + self.cy * c
        if self.confirm:
            cx, cy = self.confirm
            retro.stone(s, ox + cx * c, oy + cy * c, r, "B" if self.my_color == 1 else "W")
            if blink:
                pygame.draw.circle(s, PAL["accent"], (ox + cx * c, oy + cy * c), r + 2, 1)
        elif blink:
            a = PAL["accent"]
            for sx in (-1, 1):
                for sy in (-1, 1):
                    x0, y0 = px + sx * 10, py + sy * 10
                    pygame.draw.line(s, a, (x0, y0), (x0 - sx * 4, y0))
                    pygame.draw.line(s, a, (x0, y0), (x0, y0 - sy * 4))
        # rechterkolom
        retro.dialog_box(s, (224, 14, 92, 52))
        retro.stone(s, 235, 27, 4, "B")
        retro.text(s, self.names[0][:8], 243, 23)
        retro.stone(s, 235, 48, 4, "W")
        retro.text(s, self.names[1][:8], 243, 44)
        retro.text(s, f"caps {self.caps[0]}-{self.caps[1]}", 228, 76, PAL["text_dim"])
        retro.text(s, f"komi {self.komi:g}", 228, 90, PAL["text_dim"])
        retro.dialog_box(s, (224, 198, 92, 28))
        retro.text(s, self.msg[:10], 230, 208)
        # rustige auto-refresh zolang we wachten
        if self.gid and not self.my_turn and self.phase == "play" and self.t and self.t % 2700 == 0:
            threading.Thread(target=self._load, daemon=True).start()
        self.t += 1


def main():
    pygame.init()
    shot = "--shot" in sys.argv
    win = pygame.display.set_mode((W * SCALE, H * SCALE))
    pygame.display.set_caption("flip-go")
    canvas = pygame.Surface((W, H))
    if shot:
        os.makedirs("out", exist_ok=True)
        for name, scene in (("title", TitleScene()), ("game", GameScene(None))):
            scene.t = 0
            scene.draw(canvas)
            pygame.image.save(pygame.transform.scale(canvas, (W * 2, H * 2)),
                              f"out/{name}.png")
        print("shots: out/title.png out/game.png")
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
