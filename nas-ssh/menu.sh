#!/bin/bash
# Interactive node picker for ttyd, with last-login times, audit log and
# session recordings.
#
# nodes.conf format (one per line):  name|host|user|port|keyfile
# Only name and host are required. Use "gateway" as host for the NAS itself.

umask 077

CONF="${NODES_FILE:-/config/nodes.conf}"
GATEWAY_IP=$(ip route show default | awk '/default/ {print $3; exit}')
DEF_USER="${SSH_USER:-homeuser}"
DEF_PORT="${SSH_PORT:-22}"
DEF_KEY=/keys/id_ed25519
LOG_DAYS="${LOG_DAYS:-30}"

STATE="${STATE_DIR:-/state}"
[ -w "$STATE" ] || STATE=/tmp
KNOWN_MAIN="$STATE/known_hosts"
KNOWN_GW=/tmp/known_hosts_gw          # fresh scan written by entrypoint.sh
AUDIT="$STATE/audit.log"              # ts|node|event|detail
SESS="$STATE/sessions"                # one transcript per connection
mkdir -p "$SESS"

# ANSI colours (map to the 16 colours of the active theme)
R=$'\e[0m'; B=$'\e[1m'; DIM=$'\e[2m'
RED=$'\e[91m'; GRN=$'\e[92m'; YEL=$'\e[93m'; BLU=$'\e[94m'; MAG=$'\e[95m'; CYN=$'\e[96m'

# ---- housekeeping -----------------------------------------------------------
find "$SESS" -type f -mtime +"$LOG_DAYS" -delete 2>/dev/null
if [ -f "$AUDIT" ] && [ "$(wc -l < "$AUDIT")" -gt 2000 ]; then
  tail -n 1000 "$AUDIT" > "$AUDIT.tmp" && mv "$AUDIT.tmp" "$AUDIT"
fi

log() { printf '%s|%s|%s|%s\n' "$(date '+%F %T')" "$1" "$2" "$3" >> "$AUDIT"; }

box() {
  printf "  ${B}${MAG}╭──────────────────────────────────────────────╮${R}\n"
  printf "  ${B}${MAG}│${R}  ${B}${CYN}%-44s${R}${B}${MAG}│${R}\n" "$1"
  printf "  ${B}${MAG}╰──────────────────────────────────────────────╯${R}\n"
}

load_nodes() {
  names=(); hosts=(); users=(); ports=(); keys=()
  names+=("NAS"); hosts+=("$GATEWAY_IP"); users+=("$DEF_USER"); ports+=("$DEF_PORT"); keys+=("$DEF_KEY")
  [ -r "$CONF" ] || return 0
  while IFS='|' read -r n h u p k; do
    n="${n//[$'\r']/}"; [[ -z "$n" || "$n" == \#* ]] && continue
    [ "$h" = "gateway" ] && h="$GATEWAY_IP"
    [ -z "$h" ] && continue
    names+=("$n"); hosts+=("$h"); users+=("${u:-$DEF_USER}"); ports+=("${p:-22}"); keys+=("${k:-$DEF_KEY}")
  done < "$CONF"
}

load_last() {
  unset LAST; declare -gA LAST
  [ -r "$AUDIT" ] || return 0
  while IFS='|' read -r ts n ev _; do
    [ "$ev" = start ] && LAST["$n"]="${ts:0:16}"
  done < "$AUDIT"
}

connect() {
  local i=$1
  local n="${names[$i]}" f t0 rc
  local -a cmd=(ssh -tt -p "${ports[$i]}" -i "${keys[$i]}"
      -o "UserKnownHostsFile=$KNOWN_MAIN $KNOWN_GW"
      -o StrictHostKeyChecking=accept-new
      -o ConnectTimeout=10 -o ServerAliveInterval=30
      "${users[$i]}@${hosts[$i]}")
  f="$SESS/$(date +%Y%m%d-%H%M%S)_${n// /_}.log"
  echo; echo "${DIM}Connecting to ${n}...${R}"
  log "$n" start "$(basename "$f")"
  t0=$SECONDS
  if command -v script >/dev/null 2>&1; then
    script -qfe -c "$(printf '%q ' "${cmd[@]}")" "$f"
  else
    "${cmd[@]}"
  fi
  rc=$?
  log "$n" end "exit=$rc duration=$((SECONDS-t0))s"
  echo
  read -rsn1 -p "Session ended (exit code $rc). Press any key for menu..."
}

show_file() {   # strip terminal escapes so the transcript is readable
  sed -E 's/\x1b\[[0-9;?]*[ -\/]*[@-~]//g; s/\x1b\][^\x07]*\x07//g' "$1" | tr -d '\r\000' | { command -v less >/dev/null 2>&1 && less || more; }
}

view_logs() {
  local c f d t nm s k
  local -a files
  while true; do
    clear; box "ACTIVITY LOG"; echo
    printf "  ${B}${YEL}1${R}${DIM})${R} ${GRN}recent activity${R}\n"
    printf "  ${B}${YEL}2${R}${DIM})${R} ${GRN}session recordings${R} ${DIM}(commands + output)${R}\n"
    printf "  ${B}${YEL}b${R}${DIM})${R} ${MAG}back${R}\n\n"
    read -rp "  ${B}${CYN}❯${R} " c
    case "$c" in
      1) clear; box "RECENT ACTIVITY"; echo
         if [ -s "$AUDIT" ]; then
           tail -n 25 "$AUDIT" | awk -F'|' -v y="$YEL" -v g="$GRN" -v d="$DIM" -v r="$R" \
             '{det=($3=="start")?"":$4; printf "  %s%-19s%s %s%-12s%s %-6s %s%s%s\n", d,$1,r, g,$2,r, $3, d,det,r}'
         else echo "  (no activity yet)"; fi
         echo; read -rsn1 -p "  Press any key..." ;;
      2) clear; box "SESSION RECORDINGS"; echo
         mapfile -t files < <(ls -1t "$SESS" 2>/dev/null | head -15)
         if [ "${#files[@]}" -eq 0 ]; then echo "  (none yet)"; echo; read -rsn1 -p "  Press any key..."; continue; fi
         for k in "${!files[@]}"; do
           f="${files[$k]}"; d="${f:0:8}"; t="${f:9:6}"; nm="${f:16}"; nm="${nm%.log}"
           printf "  ${B}${YEL}%2d${R}${DIM})${R} ${DIM}%s-%s-%s %s:%s${R}  ${B}${GRN}%s${R}\n" \
             "$((k+1))" "${d:0:4}" "${d:4:2}" "${d:6:2}" "${t:0:2}" "${t:2:2}" "$nm"
         done
         echo; read -rp "  number to view (Enter = back): " s
         [[ "$s" =~ ^[0-9]+$ ]] && [ "$s" -ge 1 ] && [ "$s" -le "${#files[@]}" ] && show_file "$SESS/${files[$((s-1))]}" ;;
      b|B|'') return ;;
    esac
  done
}

while true; do
  load_nodes; load_last
  clear
  box "SELECT NODE      theme: ${THEME:-default}"; echo
  for i in "${!names[@]}"; do
    printf "  ${B}${YEL}%2d${R}${DIM})${R} ${B}${GRN}%-14s${R} ${DIM}last: %s${R}\n" \
      "$((i+1))" "${names[$i]}" "${LAST[${names[$i]}]:-never}"
  done
  echo
  printf "  ${B}${YEL} l${R}${DIM})${R} ${MAG}activity log & recordings${R}\n"
  printf "  ${B}${YEL} c${R}${DIM})${R} ${MAG}custom${R} ${DIM}(user@host[:port])${R}\n"
  printf "  ${B}${YEL} s${R}${DIM})${R} ${MAG}shell in this container${R}\n"
  printf "  ${B}${RED} q${R}${DIM})${R} ${RED}quit${R}\n\n"
  read -rp "  ${B}${CYN}❯${R} " ch
  case "$ch" in
    q|Q) exit 0 ;;
    l|L) view_logs ;;
    s|S) log "container-shell" start ""; bash -l; log "container-shell" end "" ;;
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