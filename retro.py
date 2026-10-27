"""Retro rendering: 320x240 intern canvas, integer-scaled naar venster.

Pokemon-achtige taal: dialoogbox met dubbele rand, 8px pixelfont,
klein vast palet. Alles tekent op het interne canvas; main.py schaalt.
"""
import re
import pygame
from pathlib import Path

import paths

W, H = 320, 240          # intern canvas; Flip = 640x480 = exact 2x
ASSETS = Path(paths.ASSETS)

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
    "green":    (88, 152, 72),    # gewonnen, laden, review: best
    "olive":    (120, 148, 56),   # review: good (tint halverwege groen en geel)
    "orange":   (224, 132, 40),   # review: mistake (?)
    "yellow":   (196, 164, 40),   # review: inaccuracy (?!)
}

_fonts = {}

def font(size=8):
    if size not in _fonts:
        _fonts[size] = pygame.font.Font(str(ASSETS / "PressStart2P.ttf"), size)
    return _fonts[size]

_TEXTS = {}

def _render(s, color, size):
    """Gerenderde tekst uit een cache: de menu's tekenen elk frame dezelfde regels."""
    key = (s, color or PAL["text"], size)
    if key not in _TEXTS:
        if len(_TEXTS) > 512:       # klokken en tellers maken steeds nieuwe regels
            _TEXTS.clear()
        _TEXTS[key] = font(size).render(s, False, key[1])
    return _TEXTS[key]

def text(surf, s, x, y, color=None, size=8):
    surf.blit(_render(s, color, size), (x, y))

def text_c(surf, s, cx, y, color=None, size=8):
    img = _render(s, color, size)
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
    img = _render(s, color, size)
    surf.blit(img, (right_x - img.get_width(), y))


# 3x5-pixelfont voor de coördinaten langs het bord (Press Start 2P kan niet kleiner dan 8px)
TINY = {
    "0": "111 101 101 101 111", "1": "1 1 1 1 1", "2": "111 001 111 100 111",
    "3": "111 001 011 001 111", "4": "101 101 111 001 001", "5": "111 100 111 001 111",
    "6": "111 100 111 101 111", "7": "111 001 010 010 010", "8": "111 101 111 101 111",
    "9": "111 101 111 001 111", "A": "010 101 111 101 101", "B": "110 101 110 101 110",
    "C": "011 100 100 100 011", "D": "110 101 101 101 110", "E": "111 100 110 100 111",
    "F": "111 100 110 100 100", "G": "011 100 101 101 011", "H": "101 101 111 101 101",
    "J": "001 001 001 101 010", "K": "101 101 110 101 101", "L": "100 100 100 100 111",
    "M": "101 111 111 101 101", "N": "101 111 111 111 101", "O": "010 101 101 101 010",
    "P": "110 101 110 100 100", "Q": "010 101 101 111 011", "R": "110 101 110 101 101",
    "S": "011 100 010 001 110", "T": "111 010 010 010 010",
}

def tiny_w(s):
    return sum(len(TINY[ch].split()[0]) + 1 for ch in s) - 1

def tiny(surf, s, x, y, color=None):
    """Tekst in 3x5 pixels ('1' is 1 px breed), linksboven op (x, y); 1 px tussen de tekens."""
    for ch in s:
        for r, row in enumerate(TINY[ch].split()):
            for k, bit in enumerate(row):
                if bit == "1":
                    surf.set_at((x + k, y + r), color or PAL["line"])
        x += len(row) + 1


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


# ---------- knoppen-hints met getekende pijltjes (het font heeft er geen) ----------
_ARROWS = {"{l}": "l", "{r}": "r", "{u}": "u", "{d}": "d"}


def _arrow(surf, x, y, d, color):
    """Pijltje van 7x7 px op de tekstregel (y = bovenkant van de tekst)."""
    pts = {"u": [(x + 3, y), (x, y + 6), (x + 6, y + 6)],
           "d": [(x, y + 1), (x + 6, y + 1), (x + 3, y + 7)],
           "l": [(x, y + 3), (x + 6, y), (x + 6, y + 6)],
           "r": [(x, y), (x, y + 6), (x + 6, y + 3)]}[d]
    pygame.draw.polygon(surf, color, pts)


def hint(surf, s, x, y, color=None, align="l", bg=None):
    """Tekst met {l} {r} {u} {d} als pijltjes en {A} {B} {X} {Y} {START} als knopje;
    align l/c/r t.o.v. x. bg = achtergrond (de letter in het knopje is uitgespaard)."""
    color = color or PAL["text"]
    parts = [p for p in re.split(r"(\{[lrud]\}|\{(?:A|B|X|Y|START)\})", s) if p]

    keycol = PAL["box"] if bg is None else PAL["text"]     # toets helder, actie gedimd

    def pw(p):
        return 8 if p in _ARROWS else font(8).size(p[1:-1] if p.startswith("{") else p)[0]
    w = sum(pw(p) for p in parts)
    x = x - w // 2 if align == "c" else x - w if align == "r" else x
    for p in parts:
        if p in _ARROWS:
            _arrow(surf, x, y, _ARROWS[p], keycol)
        elif p.startswith("{"):
            text(surf, p[1:-1], x, y, keycol)
        else:
            text(surf, p, x, y, color)
        x += pw(p)




# ---------- design system ----------
# Elk scherm gebruikt deze maten en onderdelen in plaats van eigen getallen. Raster: het 8px-font,
# maten in veelvouden van 2. Schrijfregels: TITELS en ACTIES in hoofdletters; data, hints en
# status in kleine letters, zonder punt.
#
#   Kop     menu: titel y 14, ondertitel y 30, lijst vanaf y 46.
#           datascherm (HISTORY, REVIEW, STATS): titel y 6, inhoud vanaf y 22.
#   Lijst   smalle menuregel 208 breed (gecentreerd), brede dataregel 304. Regel 20 hoog,
#           of 36 met een ondertitel; 4 ertussen. Pijl op x+8, label op x+20, waarde rechts op x+w-8.
#           Dataregel: bordmaat ('9x9') in een vaste kolom op x+158 (YOUR GAMES, HISTORY).
#   Onder   y 228: knoppenhints links, status rechts (laden, versturen, fouten, no wifi).
#           Knoppen (YOUR GAMES) op y 200, 20 hoog. Een melding (notice) neemt de hele onderste
#           regel over, in rood; het bord eindigt op y 226, dus hij valt er nooit overheen.
TITLE_Y, SUB_Y, LIST_Y = 14, 30, 46
DATA_TITLE_Y, DATA_Y = 6, 22
FOOT_Y, LEFT, RIGHT = 228, 4, 316
BUTTON_Y = 200
MENU, WIDE = (56, 208), (8, 304)          # (x, breedte)
ROW_H, ROW2_H, GAP = 20, 36, 4
SIZE_COL = 158                            # bordmaat-kolom in een dataregel


def arrow(surf, x, y, color=None):
    """Cursor: klein driehoekje, even hoog als een tekstregel."""
    pygame.draw.polygon(surf, color or PAL["text"], [(x, y), (x, y + 8), (x + 5, y + 4)])


def title(surf, s, data=False):
    text_c(surf, s, W // 2, DATA_TITLE_Y if data else TITLE_Y, PAL["box"])


def subtitle(surf, s, color=None):
    hint(surf, s, W // 2, SUB_Y, color or PAL["text_dim"], "c")


def row_y(i, two=False, top=LIST_Y):
    """y van lijstregel i (two = regels met ondertitel)."""
    return top + i * ((ROW2_H if two else ROW_H) + GAP)


def row(surf, y, label, value=None, sub=None, selected=False, wide=False,
        label_col=None, value_col=None):
    """Lijstregel: vak, pijl als hij gekozen is, label links, waarde rechts, ondertitel eronder.
    -> (x, tekst-y) voor wat een scherm er zelf nog in tekent (kolommen, balkjes)."""
    x, w = WIDE if wide else MENU
    dialog_box(surf, (x, y, w, ROW2_H if sub else ROW_H))
    ty = y + (7 if sub else 6)
    if selected:
        arrow(surf, x + 8, ty)
    if label:
        text(surf, label, x + 20, ty, label_col)
    if value:
        text_r(surf, value, x + w - 8, ty, value_col or PAL["text_dim"])
    if sub:
        text(surf, sub, x + 20, ty + 14, PAL["text_dim"])
    return x, ty


def button(surf, x, w, label, selected=False):
    """Knop op de knoppenregel (YOUR GAMES): label in het midden, pijl als hij gekozen is."""
    dialog_box(surf, (x, BUTTON_Y, w, ROW_H))
    if selected:
        arrow(surf, x + 8, BUTTON_Y + 6)
    text_c(surf, label, x + w // 2, BUTTON_Y + 6)


def foot(surf, s):
    """Knoppenhints op de onderste regel, links."""
    hint(surf, s, LEFT, FOOT_Y, PAL["text_dim"])


def status(surf, s, color=None):
    """Status op de onderste regel, rechts."""
    text_r(surf, s, RIGHT, FOOT_Y, color or PAL["text_dim"])


def notice(surf, s):
    """Melding over de hele onderste regel (wist hints en status), rood: 'hier moet je heen'."""
    pygame.draw.rect(surf, PAL["screen"], (0, FOOT_Y - 2, W, H - FOOT_Y + 2))
    hint(surf, s, LEFT, FOOT_Y, PAL["accent"])
