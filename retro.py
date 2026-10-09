"""Retro rendering: 320x240 intern canvas, integer-scaled naar venster.

Pokemon-achtige taal: dialoogbox met dubbele rand, 8px pixelfont,
klein vast palet. Alles tekent op het interne canvas; main.py schaalt.
"""
import pygame
from pathlib import Path

W, H = 320, 240          # intern canvas; Flip = 640x480 = exact 2x
ASSETS = Path(__file__).parent / "assets"

PAL = {
    "screen":   (24, 32, 28),     # buiten het bord
    "wood":     (222, 178, 106),  # bordhout
    "line":     (110, 74, 30),
    "black":    (44, 44, 52),
    "black_hi": (92, 92, 104),
    "white":    (242, 242, 234),
    "white_sh": (188, 188, 178),
    "box":      (248, 248, 240),
    "box_dk":   (96, 104, 112),
    "text":     (48, 56, 64),
    "text_dim": (136, 144, 152),
    "accent":   (204, 64, 48),    # cursor / actief
    "green":    (88, 152, 72),
    "orange":   (224, 132, 40),   # review: mistake (?)
    "yellow":   (196, 164, 40),   # review: inaccuracy (?!)
}

_fonts = {}

def font(size=8):
    if size not in _fonts:
        _fonts[size] = pygame.font.Font(str(ASSETS / "PressStart2P.ttf"), size)
    return _fonts[size]

def text(surf, s, x, y, color=None, size=8):
    surf.blit(font(size).render(s, False, color or PAL["text"]), (x, y))

def text_c(surf, s, cx, y, color=None, size=8):
    img = font(size).render(s, False, color or PAL["text"])
    surf.blit(img, (cx - img.get_width() // 2, y))

def dialog_box(surf, rect):
    """Pokemon-stijl box: wit vlak, dikke donkere rand met lichte binnenlijn,
    hoekpixels weggelaten voor de afgeronde look."""
    x, y, w, h = rect
    pygame.draw.rect(surf, PAL["box"], (x, y, w, h))
    d = PAL["box_dk"]
    pygame.draw.rect(surf, d, (x, y, w, h), 1)
    pygame.draw.rect(surf, PAL["white_sh"], (x + 1, y + 1, w - 2, h - 2), 1)
    # hoeken "afronden"
    for cx, cy in ((x, y), (x + w - 1, y), (x, y + h - 1), (x + w - 1, y + h - 1)):
        surf.set_at((cx, cy), PAL["screen"])

def text_r(surf, s, right_x, y, color=None, size=8):
    img = font(size).render(s, False, color or PAL["text"])
    surf.blit(img, (right_x - img.get_width(), y))


def fmt_time(sec):
    """Seconden -> '2d' / '23h' / '4:32' — grover naarmate er meer tijd is."""
    if sec is None:
        return ""
    sec = max(0, int(sec))
    if sec >= 86400:
        return f"{sec // 86400}d"
    if sec >= 3600:
        return f"{sec // 3600}h"
    return f"{sec // 60}:{sec % 60:02d}"


_STONES = {}


def _stone_sprite(r, color):
    """Ronde pixel-steen, diameter 2r+1: exact gecentreerd op het snijpunt."""
    key = (r, color)
    if key not in _STONES:
        n = 2 * r + 1
        sp = pygame.Surface((n, n))
        sp.fill((255, 0, 255))
        sp.set_colorkey((255, 0, 255))
        inside = lambda x, y: abs(x) <= r and abs(y) <= r and x * x + y * y <= r * r + r
        for y in range(-r, r + 1):
            for x in range(-r, r + 1):
                if not inside(x, y):
                    continue
                rim = not all(inside(x + a, y + b) for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                if color == "B":
                    c = (16, 16, 20) if rim else PAL["black"]
                elif not inside(x + 1, y + 1):
                    c = (120, 120, 114)          # schaduw rechtsonder
                else:
                    c = PAL["white_sh"] if rim else PAL["white"]
                sp.set_at((x + r, y + r), c)
        if color == "B":
            sp.set_at((r - r // 2, r - r // 2), PAL["black_hi"])
            sp.set_at((r - r // 2 + 1, r - r // 2), PAL["black_hi"])
        _STONES[key] = sp
    return _STONES[key]


def stone(surf, px, py, r, color):
    """Pixel-steen met 1px outline en glimlicht."""
    surf.blit(_stone_sprite(r, color), (px - r, py - r))
