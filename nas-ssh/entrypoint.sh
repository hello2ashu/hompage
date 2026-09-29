#!/bin/bash
set -e

# ---- Network: detect the Docker gateway (= the NAS host) -------------------
GATEWAY_IP=$(ip route show default | awk '/default/ {print $3; exit}')
if [ -z "$GATEWAY_IP" ]; then
  echo "[entrypoint] ERROR: could not detect gateway IP" >&2
  exit 1
fi
echo "[entrypoint] Using NAS host IP: $GATEWAY_IP"

SSH_PORT="${SSH_PORT:-22}"
export SSH_USER="${SSH_USER:-homeuser}"
KNOWN_HOSTS=/tmp/known_hosts

# Scan the host key fresh each start against whatever the gateway IP
# turns out to be right now — no stale known_hosts file to maintain.
ssh-keyscan -T 5 -p "$SSH_PORT" "$GATEWAY_IP" > "$KNOWN_HOSTS" 2>/tmp/keyscan.err || true

if [ ! -s "$KNOWN_HOSTS" ]; then
  echo "[entrypoint] ERROR: no host key from $GATEWAY_IP:$SSH_PORT" >&2
  cat /tmp/keyscan.err >&2
  echo "[entrypoint] Check that sshd is running and the firewall allows this Docker subnet" >&2
  exit 1
fi

# ---- Look & feel ------------------------------------------------------------
# THEME: dracula | nord | tokyo-night | catppuccin | gruvbox | solarized | default
THEME="${THEME:-dracula}"
FONT_SIZE="${FONT_SIZE:-15}"
FONT_FAMILY="${FONT_FAMILY:-JetBrains Mono, Fira Code, Cascadia Code, Menlo, Consolas, monospace}"

case "$THEME" in
  dracula)
    T='{"background":"#282a36","foreground":"#f8f8f2","cursor":"#f8f8f2","cursorAccent":"#282a36","selectionBackground":"#44475a","black":"#21222c","red":"#ff5555","green":"#50fa7b","yellow":"#f1fa8c","blue":"#bd93f9","magenta":"#ff79c6","cyan":"#8be9fd","white":"#f8f8f2","brightBlack":"#6272a4","brightRed":"#ff6e6e","brightGreen":"#69ff94","brightYellow":"#ffffa5","brightBlue":"#d6acff","brightMagenta":"#ff92df","brightCyan":"#a4ffff","brightWhite":"#ffffff"}' ;;
  nord)
    T='{"background":"#2e3440","foreground":"#d8dee9","cursor":"#d8dee9","cursorAccent":"#2e3440","selectionBackground":"#434c5e","black":"#3b4252","red":"#bf616a","green":"#a3be8c","yellow":"#ebcb8b","blue":"#81a1c1","magenta":"#b48ead","cyan":"#88c0d0","white":"#e5e9f0","brightBlack":"#4c566a","brightRed":"#bf616a","brightGreen":"#a3be8c","brightYellow":"#ebcb8b","brightBlue":"#81a1c1","brightMagenta":"#b48ead","brightCyan":"#8fbcbb","brightWhite":"#eceff4"}' ;;
  tokyo-night)
    T='{"background":"#1a1b26","foreground":"#c0caf5","cursor":"#c0caf5","cursorAccent":"#1a1b26","selectionBackground":"#33467c","black":"#15161e","red":"#f7768e","green":"#9ece6a","yellow":"#e0af68","blue":"#7aa2f7","magenta":"#bb9af7","cyan":"#7dcfff","white":"#a9b1d6","brightBlack":"#414868","brightRed":"#f7768e","brightGreen":"#9ece6a","brightYellow":"#e0af68","brightBlue":"#7aa2f7","brightMagenta":"#bb9af7","brightCyan":"#7dcfff","brightWhite":"#c0caf5"}' ;;
  catppuccin)
    T='{"background":"#1e1e2e","foreground":"#cdd6f4","cursor":"#f5e0dc","cursorAccent":"#1e1e2e","selectionBackground":"#585b70","black":"#45475a","red":"#f38ba8","green":"#a6e3a1","yellow":"#f9e2af","blue":"#89b4fa","magenta":"#f5c2e7","cyan":"#94e2d5","white":"#bac2de","brightBlack":"#585b70","brightRed":"#f38ba8","brightGreen":"#a6e3a1","brightYellow":"#f9e2af","brightBlue":"#89b4fa","brightMagenta":"#f5c2e7","brightCyan":"#94e2d5","brightWhite":"#a6adc8"}' ;;
  gruvbox)
    T='{"background":"#282828","foreground":"#ebdbb2","cursor":"#ebdbb2","cursorAccent":"#282828","selectionBackground":"#504945","black":"#282828","red":"#cc241d","green":"#98971a","yellow":"#d79921","blue":"#458588","magenta":"#b16286","cyan":"#689d6a","white":"#a89984","brightBlack":"#928374","brightRed":"#fb4934","brightGreen":"#b8bb26","brightYellow":"#fabd2f","brightBlue":"#83a598","brightMagenta":"#d3869b","brightCyan":"#8ec07c","brightWhite":"#ebdbb2"}' ;;
  solarized)
    T='{"background":"#002b36","foreground":"#839496","cursor":"#93a1a1","cursorAccent":"#002b36","selectionBackground":"#073642","black":"#073642","red":"#dc322f","green":"#859900","yellow":"#b58900","blue":"#268bd2","magenta":"#d33682","cyan":"#2aa198","white":"#eee8d5","brightBlack":"#586e75","brightRed":"#cb4b16","brightGreen":"#586e75","brightYellow":"#657b83","brightBlue":"#839496","brightMagenta":"#6c71c4","brightCyan":"#93a1a1","brightWhite":"#fdf6e3"}' ;;
  *)
    T='' ;;
esac

# Allow a fully custom xterm.js theme JSON (e.g. copied from terminalcolors.com)
[ -n "$THEME_JSON" ] && T="$THEME_JSON"
export COLORTERM=truecolor

THEME_ARGS=()
[ -n "$T" ] && THEME_ARGS=(-t "theme=$T")

exec ttyd \
  -p 7681 \
  -c "${TTYD_USER}:${TTYD_PASS}" \
  --writable \
  -t titleFixed=NAS \
  -t "fontSize=${FONT_SIZE}" \
  -t "fontFamily=${FONT_FAMILY}" \
  -t cursorBlink=true \
  -t cursorStyle=bar \
  "${THEME_ARGS[@]}" \
  --ping-interval 30 \
  /menu.sh
