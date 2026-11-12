#!/bin/sh
# Exempts the address you work from in fail2ban's sshd jail while you set a server up, and takes
# the exemption back when you finish.
#
# Why: your own checks that root and passwords are refused count as failed logins (a refused root
# login with a valid key logged three), and fail2ban reads back the last ten minutes of the
# journal when it starts, so two checks ban you, and the ban freezes the session you kept open.
#
# Run it from your SSH session, as the admin user (it uses sudo):
#   ssh <server> 'sh -s add' < fail2ban-exempt.sh      # before fail2ban starts or the checks run
#   ssh <server> 'sh -s remove' < fail2ban-exempt.sh   # when the work is done
#
# add: takes your address from ME=<address>, else from SSH_CONNECTION or SSH_CLIENT, else from
#   `who -m` (which needs a terminal), and stops when it finds none: sudo -i, su and the
#   provider's console clear both variables, and an empty entry would let your next check ban
#   you. The address goes in a drop-in of its own, zz-setup-address.local, whose
#   %(known/ignoreip)s keeps the list sshd.local gives (so it has to be read after it, hence the
#   name). A transient systemd timer deletes the drop-in and reloads fail2ban after EXEMPT_FOR
#   (2h by default) even if your session ends first; `add` again re-arms it. A reboot drops the
#   timer but not the drop-in: run `add` again after one.
# remove: cancels the timer, deletes the drop-in, reloads fail2ban and prints the list in force,
#   which should show no working address. Do not leave this to the timer: that address is often
#   a carrier's or a cloud runner's, shared with strangers.
#
# An address exempt for good (an office's fixed one) goes on the ignoreip line of sshd.local.
# No placeholders.
set -eu

DROPIN=/etc/fail2ban/jail.d/zz-setup-address.local
UNIT=f2b-setup-address
RELOAD='if systemctl is-active --quiet fail2ban; then fail2ban-client reload >/dev/null; fi'

case "${1:-}" in
add)
  conn=${SSH_CONNECTION:-${SSH_CLIENT:-}}
  ME=${ME:-${conn%% *}}
  if [ -z "$ME" ]; then
    ME=$(who -m 2>/dev/null | sed -n 's/.*(\([0-9A-Fa-f.:]*\))$/\1/p')
  fi
  case $ME in
    '' | *[!0-9A-Fa-f.:]*)
      echo "fail2ban-exempt: no working address found; ask the person for it, then run" \
        "ME=<address> sh -s add" >&2
      exit 1
      ;;
  esac
  sudo install -d /etc/fail2ban/jail.d
  printf '[sshd]\nignoreip = %%(known/ignoreip)s %s\n' "$ME" | sudo tee "$DROPIN" >/dev/null
  sudo systemctl stop "$UNIT.timer" 2>/dev/null || true
  sudo systemctl reset-failed "$UNIT.service" 2>/dev/null || true
  sudo systemd-run --quiet --on-active="${EXEMPT_FOR:-2h}" --timer-property=AccuracySec=1s \
    --unit="$UNIT" sh -c "rm -f $DROPIN; $RELOAD"
  sudo sh -c "$RELOAD"
  echo "fail2ban-exempt: $ME is exempt until the timer below fires or you run remove"
  systemctl list-timers "$UNIT.timer" --no-pager
  ;;
remove)
  sudo systemctl stop "$UNIT.timer" 2>/dev/null || true
  sudo rm -f "$DROPIN"
  sudo sh -c "$RELOAD"
  if systemctl is-active --quiet fail2ban; then
    sudo fail2ban-client get sshd ignoreip
  fi
  ;;
*)
  echo "usage: sh fail2ban-exempt.sh add|remove" >&2
  exit 2
  ;;
esac
