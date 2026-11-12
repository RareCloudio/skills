#!/usr/bin/env bash
# The one thing the CI deploy key may do on the server: switch a Compose app to an image tag,
# wait for it to be healthy, and go back to the previous tag when it is not.
#
# Install it as root, so the deploy user can run it but not change it:
#   install -o root -g root -m 0755 deploy.sh /usr/local/bin/deploy-<APP>
# and give the CI key exactly this power in the deploy user's ~/.ssh/authorized_keys (one line):
#   restrict,command="/usr/local/bin/deploy-<APP>" ssh-ed25519 AAAA... ci-deploy
#
# Commands (from SSH_ORIGINAL_COMMAND, or from the arguments when you run it by hand):
#   deploy <tag>   pull the image with that tag, run migrations, start it, wait for health
#   rollback       go back to the tag that was live before the last successful deploy
#   status         print the live tag
#
# Needs bash, flock (util-linux) and GNU coreutils (chown and chmod --reference): Debian, Ubuntu
# and the RHEL family have them; on Alpine, install coreutils first.
#
# The folder, its files and their modes are described in references/first-deploy.md. In short:
# <APP_DIR>/compose.yaml names the app's image with the tag as a variable,
#   image: ghcr.io/example/shop:${APP_TAG:?set APP_TAG in .env}
# and has a healthcheck (in the Compose file or the image), because `up --wait` is the gate.
# <APP_DIR>/.env (owned by the deploy user, mode 0600) holds APP_TAG next to the app's other
# values, the database password among them. This script changes only the APP_TAG= line, by
# writing a copy with the same owner and mode and renaming it over .env, so the other lines are
# never lost and a person can still run `up -d` by hand (as the deploy user, with
# --project-directory <APP_DIR>, as references/first-deploy.md does). The tag that was live
# before the last switch is kept in <APP_DIR>/.previous-tag.
# Caddy's config, <APP_DIR>/caddy/Caddyfile, is not this script's: an edit to it is applied
# with a graceful reload, as the header of templates/compose.yaml shows.
#
# Placeholders, with the sample values the template is checked with:
#   <APP>       short name of the app, used in the script's name          sample: shop
#   <APP_DIR>   directory holding compose.yaml, writable by the deploy user sample: /srv/shop
#   <SERVICE>   Compose service of the app: the only one pulled, and the one that runs the
#               migrations                                                sample: app
#   <MIGRATE>   the migration command as words, a program the image itself provides (for
#               example /server migrate, or npm run migrate), or empty. It runs in the new
#               image before the switch, in place of the image's entrypoint and with no shell
#               around it, so it works on an image without a shell   sample: (empty)
set -euo pipefail
umask 027

APP_DIR="<APP_DIR>"
SERVICE="<SERVICE>"
MIGRATE=(<MIGRATE>)
WAIT_SECONDS=120

log() {
  echo "$*" >&2
  logger -t "deploy" -- "$*" 2>/dev/null || true
}

live_tag() {
  awk '/^APP_TAG=/ { sub(/^APP_TAG=/, ""); gsub(/["\047]/, ""); print; exit }' .env
}

# Rewrite only the APP_TAG= line of .env; every other line is copied as it is.
record() {
  local tmp
  tmp="$(mktemp .env.XXXXXX)"
  if chown --reference=.env "$tmp" && chmod --reference=.env "$tmp" &&
    awk -v tag="$1" '
      /^APP_TAG=/ { if (!done) print "APP_TAG=" tag; done = 1; next }
      { print }
      END { if (!done) print "APP_TAG=" tag }' .env >"$tmp" &&
    mv -f "$tmp" .env; then
    return 0
  fi
  rm -f "$tmp"
  log "$1 runs, but .env could not be updated and still names the tag before it; fix .env by hand"
  return 1
}

start() {
  APP_TAG="$1" docker compose up --detach --wait --wait-timeout "$WAIT_SECONDS"
}

cd "$APP_DIR"
if [[ ! -f .env ]]; then
  log "$APP_DIR/.env is missing; create it first (references/first-deploy.md)"
  exit 78
fi

# One deploy at a time, even when two pipelines race.
exec 9>.deploy.lock
flock --nonblock 9 || { log "another deploy is running"; exit 75; }

# Split the request into words; it is never evaluated by a shell.
read -r -a words <<<"${SSH_ORIGINAL_COMMAND-$*}"
verb="${words[0]-}"

case "$verb:${#words[@]}" in
  deploy:2)
    tag="${words[1]}"
    if [[ ! "$tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
      log "refused: not an image tag"
      exit 64
    fi
    previous="$(live_tag)"
    log "deploy $tag (live: ${previous:-none})"
    # A missing tag or a registry error stops here, before anything changes.
    APP_TAG="$tag" docker compose pull --quiet "$SERVICE"
    if ((${#MIGRATE[@]})); then
      # The command replaces the entrypoint, so it is not handed to a server as its arguments.
      APP_TAG="$tag" docker compose run --rm --entrypoint "${MIGRATE[0]}" "$SERVICE" "${MIGRATE[@]:1}"
    fi
    if start "$tag"; then
      if [[ -n "$previous" && "$previous" != "$tag" ]]; then
        printf '%s\n' "$previous" >.previous-tag
      fi
      record "$tag"
      log "live: $tag"
    else
      log "$tag did not become healthy"
      if [[ -n "$previous" ]]; then
        if start "$previous"; then
          log "rolled back to $previous"
        else
          log "rollback to $previous did not become healthy either"
        fi
      fi
      exit 1
    fi
    ;;
  rollback:1)
    target="$(cat .previous-tag 2>/dev/null || true)"
    if [[ -z "$target" ]]; then
      log "nothing to roll back to"
      exit 1
    fi
    current="$(live_tag)"
    log "rollback from ${current:-none} to $target"
    start "$target"
    record "$target"
    printf '%s\n' "$current" >.previous-tag
    log "live: $target"
    ;;
  status:1)
    live_tag
    ;;
  *)
    log "refused: expected 'deploy <tag>', 'rollback' or 'status'"
    exit 64
    ;;
esac
