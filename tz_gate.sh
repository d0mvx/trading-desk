#!/usr/bin/env bash
# tz_gate.sh HH:MM ZONE DAYS CMD...  -> runs CMD only if the current time in ZONE is HH:MM
# and the ISO weekday (1=Mon..7=Sun) in ZONE is in DAYS (e.g. 12345 or 1234567).
# Debian cron has no CRON_TZ, so cron fires in a Berlin window and this gate handles DST.
want=$1 zone=$2 days=$3; shift 3
now=$(TZ=$zone date +%H:%M); dow=$(TZ=$zone date +%u)
[ "$now" = "$want" ] && [[ "$days" == *"$dow"* ]] && exec "$@"
exit 0
