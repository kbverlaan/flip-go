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

_ghosts = {}


def ghost(surf, px, py, r, color):
    """Geditherde steen: 50%-schaakbord zodat een niet-gezette zet
    onmiskenbaar anders is dan een echte steen."""
    key = (r, color)
    if key not in _ghosts:
        mag = (255, 0, 255)
        g = pygame.Surface((r * 2 + 2, r * 2 + 2))
        g.fill(mag)
        g.set_colorkey(mag)
        stone(g, r + 1, r + 1, r, color)
        for y in range(g.get_height()):
            for x in range(g.get_width()):
                if (x + y) % 2:
                    g.set_at((x, y), mag)
        _ghosts[key] = g
    surf.blit(_ghosts[key], (px - r - 1, py - r - 1))


def text_r(surf, s, right_x, y, color=None, size=8):
    img = font(size).render(s, False, color or PAL["text"])
    surf.blit(img, (right_x - img.get_width(), y))


def fmt_time(sec):
    """Seconden -> '2d4h' / '3h05m' / '4:32'."""
    if sec is None:
        return ""
    sec = max(0, int(sec))
    if sec >= 86400:
        return f"{sec // 86400}d{(sec % 86400) // 3600}h"
    if sec >= 3600:
        return f"{sec // 3600}h{(sec % 3600) // 60:02d}m"
    return f"{sec // 60}:{sec % 60:02d}"


def stone(surf, px, py, r, color):
    """Pixel-steen met 1px outline en glimlicht."""
    if color == "B":
        pygame.draw.circle(surf, PAL["black"], (px, py), r)
        pygame.draw.circle(surf, (16, 16, 20), (px, py), r, 1)
        surf.set_at((px - r // 2, py - r // 2), PAL["black_hi"])
        surf.set_at((px - r // 2 + 1, py - r // 2), PAL["black_hi"])
    else:
        pygame.draw.circle(surf, PAL["white"], (px, py), r)
        pygame.draw.circle(surf, PAL["white_sh"], (px, py), r, 1)
        pygame.draw.circle(surf, (120, 120, 114), (px + 1, py + 1), r, 1)
