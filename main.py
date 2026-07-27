"""flip-go: retro OGS-client voor de Miyoo Flip (en de Mac om te testen).

Run:            python main.py
Screenshots:    python main.py --shot   (headless, schrijft out/*.png)

Besturing (Mac-test = Flip-mapping):
  pijltjes = D-pad   Enter/X = A   Backspace/Z = B   S = Start
"""
import os
import sys

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
            return GameScene()
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        # decoratief bordje
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


class GameScene:
    """Mock-pot voor de look; OGS-koppeling komt hierna."""
    CELL = 20

    def __init__(self):
        self.size = 9
        self.cx, self.cy = 4, 4
        self.t = 0
        self.board = [[0] * 9 for _ in range(9)]
        for x, y, c in ((4, 4, 1), (2, 6, 1), (6, 2, 2), (2, 2, 1), (6, 6, 2), (5, 3, 2)):
            self.board[y][x] = c
        self.msg = "Your move."

    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return self
        dx = (ev.key == pygame.K_RIGHT) - (ev.key == pygame.K_LEFT)
        dy = (ev.key == pygame.K_DOWN) - (ev.key == pygame.K_UP)
        if dx or dy:
            self.cx = max(0, min(self.size - 1, self.cx + dx))
            self.cy = max(0, min(self.size - 1, self.cy + dy))
        elif ev.key in (pygame.K_RETURN, pygame.K_x):
            if self.board[self.cy][self.cx] == 0:
                self.board[self.cy][self.cx] = 1
                self.msg = f"You played {'ABCDEFGHJ'[self.cx]}{9 - self.cy}."
        elif ev.key in (pygame.K_BACKSPACE, pygame.K_z):
            return TitleScene()
        return self

    def draw(self, s):
        s.fill(PAL["screen"])
        # bord
        pygame.draw.rect(s, PAL["wood"], (8, 8, 184, 184))
        pygame.draw.rect(s, PAL["line"], (8, 8, 184, 184), 1)
        ox = oy = 8 + 12
        c = self.CELL
        for i in range(9):
            pygame.draw.line(s, PAL["line"], (ox, oy + i * c), (ox + 8 * c, oy + i * c))
            pygame.draw.line(s, PAL["line"], (ox + i * c, oy), (ox + i * c, oy + 8 * c))
        for hx, hy in ((2, 2), (6, 2), (4, 4), (2, 6), (6, 6)):
            pygame.draw.circle(s, PAL["line"], (ox + hx * c, oy + hy * c), 2)
        for y in range(9):
            for x in range(9):
                if self.board[y][x]:
                    retro.stone(s, ox + x * c, oy + y * c, 8,
                                "B" if self.board[y][x] == 1 else "W")
        # cursor: vier rode hoekjes, knipperend
        if (self.t // 20) % 2 == 0:
            px, py = ox + self.cx * c, oy + self.cy * c
            a = PAL["accent"]
            for sx in (-1, 1):
                for sy in (-1, 1):
                    x0, y0 = px + sx * 9, py + sy * 9
                    pygame.draw.line(s, a, (x0, y0), (x0 - sx * 4, y0))
                    pygame.draw.line(s, a, (x0, y0), (x0, y0 - sy * 4))
        # zijpaneel
        retro.dialog_box(s, (200, 8, 112, 74))
        retro.stone(s, 212, 22, 5, "B")
        retro.text(s, "kiemsan_", 222, 18)
        retro.text(s, "10:00", 222, 30, PAL["text_dim"])
        retro.stone(s, 212, 50, 5, "W")
        retro.text(s, "amybot", 222, 46)
        retro.text(s, "10:00", 222, 58, PAL["text_dim"])
        retro.dialog_box(s, (200, 90, 112, 40))
        retro.text(s, "caps  0-0", 208, 98)
        retro.text(s, "komi  6.5", 208, 112)
        # dialoog
        retro.dialog_box(s, (4, 196, 312, 40))
        retro.text(s, self.msg, 14, 206)
        self.t += 1


def main():
    pygame.init()
    shot = "--shot" in sys.argv
    win = pygame.display.set_mode((W * SCALE, H * SCALE))
    pygame.display.set_caption("flip-go")
    canvas = pygame.Surface((W, H))
    if shot:
        os.makedirs("out", exist_ok=True)
        for name, scene in (("title", TitleScene()), ("game", GameScene())):
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
