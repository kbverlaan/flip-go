"""Mappen naast de code. conf/ = instellingen, potten en reviews; engines/ = KataGo, GNU Go
en de netten (via flip-scp, niet via OTA); assets/ = font, geluid en icoon."""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "conf")
ENG = os.path.join(HERE, "engines")
ASSETS = os.path.join(HERE, "assets")
ENGINE_LOG = os.path.join(ENG, "engine.log")      # waarom een engine stopt
