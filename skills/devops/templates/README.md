# Templates

Starting points the skill adapts to the project. The comment at the top of each file is the
detailed source: its placeholders with sample values, where it goes, and how to check it. The
reference named here says when to use it and what to change. "check_config" means
[scripts/check_config.py](../scripts/check_config.py) recognises the file and runs that tool; CI
runs it on every one of those, filled with its sample values (`tools/check_templates.py`). The
nginx, Caddy, Compose and systemd checks run in their pinned container, since those tools act on
what the file says, and sshd -t runs on the CI machine.

The other templates are checked by hand, not in CI. Each was filled with its sample values and
run through the command in its row, last on 2026-11-12: `fail2ban-client -t` (fail2ban 1.0.2),
`apt-config dump` and `unattended-upgrade --dry-run` (apt 2.6.2), `iptables-restore --test
--noflush` and `ip6tables-restore` (iptables 1.8.9) and `logrotate -d` (logrotate 3.21.0), each
on `debian:12`; `check-jsonschema --builtin-schema vendor.gitlab-ci` (0.29.4) on
`python:3.12-slim`; the backup env file loaded with `set -a; . file`. The `.dockerignore` and this
index have no check.
Run the command again when you change one of them.

| Template | What it is | Explained in | Checked with |
|---|---|---|---|
| `sshd-hardening.conf` | sshd drop-in: no root login, keys only | [server-hardening.md](../references/server-hardening.md) | `sshd -t` (check_config) |
| `fail2ban-sshd.local` | fail2ban jail for SSH, reading the journal | [server-hardening.md](../references/server-hardening.md) | `fail2ban-client -t` |
| `fail2ban-exempt.sh` | exempts the address you work from while you set up, with a timer that takes it back | [server-hardening.md](../references/server-hardening.md) | ShellCheck (check_config) |
| `52unattended-upgrades-local` | automatic updates from the distribution's default origins, and a reboot at a quiet hour | [server-hardening.md](../references/server-hardening.md) | `apt-config dump`, `unattended-upgrade --dry-run` |
| `ufw-docker-user.rules` | makes ports Docker publishes obey a list, through `DOCKER-USER` | [firewall.md](../references/firewall.md) | `iptables-restore --test` |
| `Caddyfile` | Caddy in front of one app, HTTPS it renews itself | [web-and-https.md](../references/web-and-https.md) | `caddy validate` (check_config) |
| `nginx-site.conf` | nginx in front of one app, certificates from certbot's webroot | [web-and-https.md](../references/web-and-https.md) | `nginx -t` (check_config) |
| `nginx-php.conf` | the lines that run a PHP app through PHP-FPM, inside the nginx site | [web-and-https.md](../references/web-and-https.md) | `nginx -t` (check_config) |
| `certbot-deploy-hook.sh` | reloads nginx after certbot saves a new certificate | [web-and-https.md](../references/web-and-https.md) | ShellCheck (check_config) |
| `dockerfiles/node.Dockerfile` | multi-stage image for a Node.js app with a build step | [docker.md](../references/docker.md) | hadolint (check_config) |
| `dockerfiles/python.Dockerfile` | multi-stage image for a Python app served by gunicorn | [docker.md](../references/docker.md) | hadolint (check_config) |
| `dockerfiles/go.Dockerfile` | static Go binary on a distroless base | [docker.md](../references/docker.md) | hadolint (check_config) |
| `dockerfiles/.dockerignore` | keeps secrets and local state out of the build context | [docker.md](../references/docker.md) | none of its own; read by `docker build` |
| `compose.yaml` | production Compose file: the app, Postgres and Caddy | [docker.md](../references/docker.md) | `docker compose config` (check_config) |
| `app.service` | the app as a systemd service, with release folders | [systemd.md](../references/systemd.md) | `systemd-analyze verify` (check_config) |
| `app-job.service`, `app-job.timer` | a scheduled job of the app as a systemd timer | [systemd.md](../references/systemd.md) | `systemd-analyze verify` (check_config) |
| `kubernetes/namespace.yaml` | a namespace with the `restricted` Pod Security level | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/deployment.yaml` | the app: replicas, probes, requests, security context | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/service.yaml` | the in-cluster address of the app's ready pods | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/gateway.yaml` | traffic in through the Gateway API, HTTP sent to HTTPS | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/ingress.yaml` | the Ingress alternative to `gateway.yaml` | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/issuer.yaml` | cert-manager Issuer for Let's Encrypt | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/hpa.yaml` | adds and removes replicas with CPU use | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/pdb.yaml` | keeps a node drain from taking more than one replica | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/networkpolicy.yaml` | lets only the app's namespace and the gateway reach its pods | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/migrate-job.yaml` | the release's database migrations, run once before its rollout | [kubernetes.md](../references/kubernetes.md) | kubeconform (check_config) |
| `kubernetes/kustomization.yaml` | applies the manifests as one, in the app's namespace | [kubernetes.md](../references/kubernetes.md) | `kubectl kustomize`, then kubeconform |
| `ci/github-deploy-compose-ssh.yaml` | GitHub Actions: build, push, switch one server's tag over SSH | [ci-cd.md](../references/ci-cd.md) | actionlint (check_config) |
| `ci/github-deploy-kubernetes.yaml` | GitHub Actions: build, push, apply the kustomization with the new tag, undo on failure | [ci-cd.md](../references/ci-cd.md) | actionlint (check_config) |
| `ci/gitlab-deploy-compose-ssh.yml` | the GitLab CI version of the SSH deploy | [ci-cd.md](../references/ci-cd.md) | `check-jsonschema --builtin-schema vendor.gitlab-ci` |
| `ci/deploy.sh` | server side of the SSH deploys, run as a forced command | [ci-cd.md](../references/ci-cd.md) | ShellCheck (check_config) |
| `restic-backup.sh` | dump the databases, back up to a restic repository, prune, check | [backups.md](../references/backups.md) | ShellCheck (check_config) |
| `restic-backup.service`, `restic-backup.timer` | runs the backup daily | [backups.md](../references/backups.md) | `systemd-analyze verify` (check_config) |
| `restic-backup.env.example` | settings and storage keys for the backup, mode 0600 | [backups.md](../references/backups.md) | loaded in a shell with `set -a; . file` |
| `healthcheck.sh` | checks a URL, disk, certificate days and OOM kills | [monitoring-and-logs.md](../references/monitoring-and-logs.md) | ShellCheck (check_config) |
| `healthcheck.service`, `healthcheck.timer` | runs the health check every five minutes | [monitoring-and-logs.md](../references/monitoring-and-logs.md) | `systemd-analyze verify` (check_config) |
| `logrotate-app` | rotation for an app that writes its own log files | [monitoring-and-logs.md](../references/monitoring-and-logs.md) | `logrotate -d` |
