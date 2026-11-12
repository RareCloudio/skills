#!/usr/bin/env bash
# healthcheck.sh: a small check of one site and the server it runs on, for a systemd timer.
#
# It checks that a URL answers, that no watched filesystem is nearly full (space or inodes),
# that the site's certificate has enough days left, and whether the kernel killed a process
# for memory since the last run. It prints one line per problem and exits 1, prints one OK
# line and exits 0, or exits 2 when it is set up wrong.
#
# There are no placeholders in this file. It reads its settings from the environment, which
# healthcheck.service sets:
#   CHECK_URL         the address a visitor uses; a 2xx or 3xx answer counts as up
#   DISK_PATHS        mount points to watch, separated by spaces (default: /)
#   DISK_MAX_PERCENT  a problem at or above this use of space or inodes (default: 85)
#   CERT_MIN_DAYS     a problem when the certificate has fewer days left (default: 14)
#   ALERT_URL         optional: problems and recoveries are POSTed there as plain text,
#                     only when the set of problems changes, so a long outage sends one alert
#
# Needs bash, curl 7.75 or later, openssl, GNU df and GNU date.
set -uo pipefail

url="${CHECK_URL:-}"
disk_paths="${DISK_PATHS:-/}"
disk_max="${DISK_MAX_PERCENT:-85}"
cert_min="${CERT_MIN_DAYS:-14}"
state_dir="${STATE_DIRECTORY:-/var/lib/healthcheck}"

if [ -z "$url" ]; then
    echo "CHECK_URL is not set; nothing to check" >&2
    exit 2
fi

problems=()
notes=()

# 1. The site answers. --retry rides out a single dropped connection or a 502 during a deploy.
result=$(curl --silent --output /dev/null --max-time 15 --retry 2 --retry-delay 5 \
    --write-out '%{http_code} %{errormsg}' "$url")
code="${result%% *}"
case "$code" in
    2??|3??) notes+=("url $code") ;;
    000) problems+=("url: $url did not answer: ${result#* }") ;;
    *) problems+=("url: $url answered HTTP $code") ;;
esac

# 2. Space and inodes. A filesystem out of inodes refuses new files while df -h shows room.
for path in $disk_paths; do
    read -r space inodes < <(df --output=pcent,ipcent "$path" 2>/dev/null | tail -n 1 | tr -d '%')
    if [ -z "${space:-}" ]; then
        problems+=("disk $path: could not read its use")
        continue
    fi
    notes+=("disk $path ${space}%")
    if [ "$space" -ge "$disk_max" ]; then
        problems+=("disk $path: ${space}% used")
    fi
    if [[ "${inodes:-}" =~ ^[0-9]+$ ]] && [ "$inodes" -ge "$disk_max" ]; then
        problems+=("inodes $path: ${inodes}% used")
    fi
done

# 3. Days left on the certificate the server really sends (by name, with SNI).
if [[ "$url" == https://* ]]; then
    hostport="${url#https://}"
    hostport="${hostport%%/*}"
    host="${hostport%%:*}"
    port=443
    if [[ "$hostport" == *:* ]]; then
        port="${hostport##*:}"
    fi
    not_after=$(timeout 20 openssl s_client -connect "$host:$port" -servername "$host" \
        </dev/null 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null)
    not_after="${not_after#notAfter=}"
    if [ -z "$not_after" ]; then
        problems+=("cert: could not read the certificate of $host:$port")
    else
        days_left=$(( ($(date -d "$not_after" +%s) - $(date +%s)) / 86400 ))
        notes+=("cert ${days_left}d")
        if [ "$days_left" -lt "$cert_min" ]; then
            problems+=("cert: $host expires in $days_left days ($not_after)")
        fi
    fi
fi

# 4. Processes killed for memory since the last run. /proc/vmstat counts every OOM kill since
# boot, those inside a container or a service's memory limit included, and anyone can read it.
kills=$(awk '$1 == "oom_kill" {print $2}' /proc/vmstat 2>/dev/null)
if [[ "$kills" =~ ^[0-9]+$ ]]; then
    last_kills=$(cat "$state_dir/oom_kill" 2>/dev/null || echo "$kills")
    if [[ "$last_kills" =~ ^[0-9]+$ ]] && [ "$kills" -gt "$last_kills" ]; then
        problems+=("memory: $((kills - last_kills)) process(es) killed since the last run (journalctl -k)")
    fi
    mkdir -p "$state_dir" 2>/dev/null && printf '%s' "$kills" > "$state_dir/oom_kill" 2>/dev/null
fi

# Alert only when the set of problems changes (the part before the first colon).
if [ -n "${ALERT_URL:-}" ]; then
    keys=""
    if [ "${#problems[@]}" -gt 0 ]; then
        keys=$(printf '%s\n' "${problems[@]}" | cut -d: -f1 | sort -u | tr '\n' ' ')
    fi
    previous=$(cat "$state_dir/last" 2>/dev/null || true)
    if [ "$keys" != "$previous" ]; then
        if [ -n "$keys" ]; then
            message=$(printf '%s: problems found\n' "$(hostname)"; printf '%s\n' "${problems[@]}")
        else
            message="$(hostname): recovered, all checks pass for $url"
        fi
        if printf '%s\n' "$message" | curl --silent --show-error --fail --max-time 15 \
            --data-binary @- "$ALERT_URL" >/dev/null; then
            mkdir -p "$state_dir" && printf '%s' "$keys" > "$state_dir/last"
        else
            echo "could not send the alert to ALERT_URL" >&2
        fi
    fi
fi

if [ "${#problems[@]}" -gt 0 ]; then
    printf 'PROBLEM %s\n' "${problems[@]}" >&2
    exit 1
fi
echo "OK ${notes[*]}"
