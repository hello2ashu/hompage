#!/bin/bash
# Interactive node picker for ttyd. Runs inside the web terminal.
# nodes.conf format (one per line):  name|host|user|port|keyfile
# Only name and host are required. Use "gateway" as host for the NAS itself.

CONF="${NODES_FILE:-/config/nodes.conf}"
GATEWAY_IP=$(ip route show default | awk '/default/ {print $3; exit}')
DEF_USER="${SSH_USER:-homeuser}"
DEF_PORT="${SSH_PORT:-22}"
DEF_KEY=/keys/id_ed25519

STATE=/state
[ -w "$STATE" ] || STATE=/tmp
KNOWN_MAIN="$STATE/known_hosts"
KNOWN_GW=/tmp/known_hosts_gw   # fresh scan written by entrypoint.sh

load_nodes() {
  names=(); hosts=(); users=(); ports=(); keys=()
  # built-in entry: the NAS host itself
  names+=("NAS"); hosts+=("$GATEWAY_IP"); users+=("$DEF_USER"); ports+=("$DEF_PORT"); keys+=("$DEF_KEY")
  [ -r "$CONF" ] || return 0
  while IFS='|' read -r n h u p k; do
    n="${n//[$'\r']/}"; [[ -z "$n" || "$n" == \#* ]] && continue
    [ "$h" = "gateway" ] && h="$GATEWAY_IP"
    [ -z "$h" ] && continue
    names+=("$n"); hosts+=("$h"); users+=("${u:-$DEF_USER}"); ports+=("${p:-22}"); keys+=("${k:-$DEF_KEY}")
  done < "$CONF"
}

connect() {
  local i=$1
  echo
  echo "${DIM}Connecting to ${names[$i]}...${R}"
  ssh -tt -p "${ports[$i]}" -i "${keys[$i]}" \
      -o UserKnownHostsFile="$KNOWN_MAIN $KNOWN_GW" \
      -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=10 \
      -o ServerAliveInterval=30 \
      "${users[$i]}@${hosts[$i]}"
  local rc=$?
  echo
  read -rsn1 -p "Session ended (exit code $rc). Press any key for menu..."
}

# ANSI colours - these map to the 16 palette colours of the active theme
R=$'\e[0m'; B=$'\e[1m'; DIM=$'\e[2m'
RED=$'\e[91m'; GRN=$'\e[92m'; YEL=$'\e[93m'; BLU=$'\e[94m'; MAG=$'\e[95m'; CYN=$'\e[96m'

while true; do
  load_nodes
  clear
  printf "%s\n" "${B}${MAG}  ╭──────────────────────────────────────────────╮${R}"
  printf "  ${B}${MAG}│${R}  ${B}${CYN}SELECT NODE${R}  ${DIM}theme: %-24s${R}${B}${MAG}│${R}\n" "${THEME:-default}"
  printf "%s\n" "${B}${MAG}  ╰──────────────────────────────────────────────╯${R}"
  echo
  for i in "${!names[@]}"; do
    printf "  ${B}${YEL}%2d${R}${DIM})${R} ${B}${GRN}%s${R}\n" "$((i+1))" "${names[$i]}"
  done
  echo
  printf "  ${B}${YEL} c${R}${DIM})${R} ${MAG}custom${R} ${DIM}(user@host[:port])${R}\n"
  printf "  ${B}${YEL} s${R}${DIM})${R} ${MAG}shell in this container${R}\n"
  printf "  ${B}${RED} q${R}${DIM})${R} ${RED}quit${R}\n"
  echo
  read -rp "  ${B}${CYN}❯${R} " ch
  case "$ch" in
    q|Q) exit 0 ;;
    s|S) bash -l ;;
    c|C)
      read -rp "  user@host[:port]: " t
      [ -z "$t" ] && continue
      u="${t%%@*}"; hp="${t#*@}"; h="${hp%%:*}"; p=22
      [[ "$hp" == *:* ]] && p="${hp##*:}"
      names+=("custom"); hosts+=("$h"); users+=("$u"); ports+=("$p"); keys+=("$DEF_KEY")
      connect "$(( ${#names[@]} - 1 ))" ;;
    ''|*[!0-9]*) ;;
    *) idx=$((ch-1)); [ "$idx" -ge 0 ] && [ "$idx" -lt "${#names[@]}" ] && connect "$idx" ;;
  esac
done