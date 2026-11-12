#!/bin/sh
# Reloads nginx after certbot has saved a new certificate, so nginx starts serving it.
# nginx reads certificate files only when it starts or reloads; without this it keeps serving
# the old certificate from memory until that one expires, even though renewal "worked".
#
# No placeholders. For another server, change the two commands (for example haproxy, or nginx
# in Compose: sudo -u deploy docker compose --project-directory /srv/<app> exec -T proxy nginx
# -s reload, as the folder's owner like every Compose command in references/first-deploy.md).
#
# Install (-D creates the folder, which certbot makes only on its first run):
#   install -D -m 0755 certbot-deploy-hook.sh /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
# certbot runs every executable in that folder after each certificate it saves, with
# RENEWED_LINEAGE set to that certificate's folder under /etc/letsencrypt/live.
# Test: certbot renew --dry-run --run-deploy-hooks. A plain --dry-run skips deploy hooks, and
# the certbot 2.1 that Debian 12 ships has no such flag: there, run the hook by hand once.
set -eu

if nginx -t -q; then
    systemctl reload nginx
else
    echo "reload-nginx: nginx -t failed, so nginx still serves the old certificate" \
        "for ${RENEWED_LINEAGE:-unknown}; fix the config and reload" >&2
    exit 1
fi
