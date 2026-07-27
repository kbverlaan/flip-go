#!/bin/bash
# PortMaster-launcher voor flip-go op de Miyoo Flip (stock OS).
# Hoort op de SD-kaart als /mnt/SDCARD/Roms/PM/FlipGo.sh;
# de app zelf in /mnt/SDCARD/Roms/PM/ports/flipgo/.

XDG_DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
if [ -d "/mnt/SDCARD/App/PortMaster/.portmaster/PortMaster" ]; then
  controlfolder="/mnt/SDCARD/App/PortMaster/.portmaster/PortMaster"
elif [ -d "/opt/system/Tools/PortMaster/" ]; then
  controlfolder="/opt/system/Tools/PortMaster"
else
  controlfolder="/roms/ports/PortMaster"
fi
source "$controlfolder/control.txt"
[ -f "${controlfolder}/mod_${CFW_NAME}.txt" ] && source "${controlfolder}/mod_${CFW_NAME}.txt"
get_controls

GAMEDIR="${directory:-/mnt/SDCARD/Roms/PM}/ports/flipgo"
cd "$GAMEDIR"
> "$GAMEDIR/log.txt" && exec > >(tee "$GAMEDIR/log.txt") 2>&1
date    # verkeerde klok = SSL-fouten; check dit bij problemen

# Python 3.11-runtime (squashfs) mounten; staat al in libs/, anders download
runtime="pyxel_2.2.8_python_3.11"
$ESUDO "$controlfolder/harbourmaster" --quiet --no-check runtime_check "${runtime}.squashfs"
PYTHONDIR="/tmp/python-flipgo"
$ESUDO mkdir -p "$PYTHONDIR"
$ESUDO umount "$PYTHONDIR" 2>/dev/null
$ESUDO mount -o loop "$controlfolder/libs/${runtime}.squashfs" "$PYTHONDIR"

export HOME="$GAMEDIR/conf"                 # token.json leeft in conf/.config/flip-go/
export XDG_DATA_HOME="$HOME/.local/share"
export SDL_GAMECONTROLLERCONFIG="$sdl_controllerconfig"
export PYTHONHOME="$PYTHONDIR"
export PYTHONPATH="$GAMEDIR/pylibs"
export PYTHONPYCACHEPREFIX="$GAMEDIR/cache"  # squashfs is read-only
export SSL_CERT_FILE="$GAMEDIR/pylibs/certifi/cacert.pem"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
export WEBSOCKET_CLIENT_CA_BUNDLE="$SSL_CERT_FILE"
export PATH="$PYTHONDIR/bin:$PATH"

"$PYTHONDIR/bin/python3" main.py

$ESUDO umount "$PYTHONDIR"
pm_finish
