# A first deploy, end to end

Read this when an app goes online for the first time, on one server or on a cluster, and to see
the conventions every other file and template in this skill follows: the app folder, which files
live in it and with which owner and mode, where the running image tag is recorded, the names the
Compose file, the deploy script and the backup job share, and the rule for image tags. Each step
below points to the file that does it in depth; this file holds the order and the joins between
them, because that is where a setup that passes every check can still break.

## The conventions

The examples use the app name `shop`; replace it with the app's own short name (lowercase
letters, digits and dashes), which then names the folder, the Compose project, the deploy script
and the backup job.

| What | Where or which name | Owner and mode |
|---|---|---|
| App folder | `/srv/shop` | `deploy:deploy`, 0750 |
| Compose file | `/srv/shop/compose.yaml`, from [templates/compose.yaml](../templates/compose.yaml), with `name: shop` | `deploy`, 0640 |
| Caddy's config | `/srv/shop/caddy/Caddyfile`, from [templates/Caddyfile](../templates/Caddyfile); an edit is applied with a reload, not a restart ([web-and-https.md](web-and-https.md)) | `deploy`, folder 0750, file 0640 |
| Values for the Compose file | `/srv/shop/.env`: `APP_TAG`, `SITE_ADDRESS`, `POSTGRES_PASSWORD`, and any other value the Compose file names | `deploy`, 0600, never in git |
| The running image tag | the `APP_TAG=` line of `.env`; the one before it in `/srv/shop/.previous-tag` | written by the deploy script |
| Services and containers | `app`, `db`, `caddy`; containers `shop-app-1`, `shop-db-1`, `shop-caddy-1` | |
| Database inside Compose | Postgres user and database `app`, password `POSTGRES_PASSWORD` | |
| Deploy user | `deploy`, in the `docker` group, its CI key limited to `/usr/local/bin/deploy-shop` | script `root`, 0755 |
| People | a personal admin account with sudo ([server-hardening.md](server-hardening.md)); nobody logs in as root or as `deploy` | |
| Compose by hand | as the folder's owner, with the folder named: `sudo -u deploy docker compose --project-directory /srv/shop <command>` | |
| Backup job | `/etc/restic-backup/shop.env` and `shop.password`; units `restic-backup-shop.service` and `.timer` | `root`, 0600 |
| Without containers | code in `/srv/shop/releases/<id>` with a `current` link, settings in `/etc/shop/env`, data in `/var/lib/shop`, unit `shop.service`, system user `shop` ([systemd.md](systemd.md)) | env file `root:shop`, 0640 |
| On a cluster | namespace `shop`, Deployment and Service `shop`, Secret `shop-secrets`, CI service account `deployer` | |

Why Compose runs as `deploy` and not from a `cd`: the folder is closed to everyone but `deploy`,
because `.env` holds the database password, so the admin's `cd /srv/shop` is refused, and a
`sudo -u deploy docker compose` started anywhere else finds no Compose file. Naming the folder
works from any directory and uses the same user, files and registry login as the pipeline.

Why one `.env` holds both the tag and the secrets: Compose reads exactly one file for its
`${...}` values unless told otherwise, and a person who runs `up -d` by hand (as in the table)
must get the same stack the pipeline started. So the deploy script
([templates/ci/deploy.sh](../templates/ci/deploy.sh)) rewrites only the `APP_TAG=` line, into a copy with the same owner and mode that it renames over
`.env`, and keeps the previous tag in `.previous-tag` for `rollback`. When you change the tag by
hand, edit that one line (`sudoedit /srv/shop/.env` keeps the owner and mode) and write nothing
else over the file. A copy of `.env` lives in the encrypted backup, so a lost server does not
take the database password with it.

## Image tags

One rule for every image, so that a pull brings fixes and never a surprise:

- **Your own app: an immutable tag,** the commit SHA the pipeline built (or a release number
  you never reuse). It names exactly one build, so the running code is known and a rollback is
  a tag that still exists. Not `latest`, which names whatever was pushed last.
- **Images other people publish: the line the publisher keeps rebuilding with fixes,** for
  example `postgres:18-trixie` (the major version, because a new major cannot open the old
  one's data folder and needs a migration, [databases.md](databases.md)), `caddy:2-alpine`,
  `nginx:stable`, and in a Dockerfile the runtime's line (`node:24-trixie-slim`,
  `python:3.14-slim-trixie`). An exact patch tag such as `postgres:18.4` is never rebuilt once
  18.5 is out, so it collects known, fixed vulnerabilities ([updates.md](updates.md) has the
  measurement).
- **They change only when you pull them, on purpose.** The deploy script pulls only the `app`
  service, so shipping the app never moves the database or the proxy. Refresh the others at a
  quiet moment, after a backup: `pull db caddy`, then `up -d --wait`, each run as in the table.
  Rebuild your own image with `docker build --pull` on a schedule for the same reason.
- **For builds that must be reproducible,** pin the digest as well
  (`postgres:18-trixie@sha256:<digest>`) and let a bot such as Renovate open the change when the
  line is rebuilt. A digest nobody moves is a frozen tag again.

## One server, in order

Do the steps in this order; each relies on what the one before proved.

1. **Choose the setup and the server** with the person ([choosing.md](choosing.md)).
2. **Look, then harden:** what is on the machine and whether it serves people
   ([preflight-and-safety.md](preflight-and-safety.md)), then the admin user, SSH keys only and
   automatic updates ([server-hardening.md](server-hardening.md)).
3. **Firewall:** SSH, 80 and 443 only, with the SSH rule first; and know that ports Docker
   publishes go around ufw and firewalld ([firewall.md](firewall.md)). The template publishes
   only Caddy, so nothing else answers.
4. **Docker from Docker's own repository** ([docker.md](docker.md)).
5. **The deploy user and the app folder.** The deploy user exists from the start, so the first
   deploy by hand and every later pipeline run work on the same files with the same rights:

   ```
   sudo useradd --create-home --shell /bin/bash deploy
   sudo usermod -aG docker deploy
   sudo install -d -o deploy -g deploy -m 0750 /srv/shop
   sudo install -o deploy -g deploy -m 0640 compose.yaml /srv/shop/compose.yaml
   sudo install -d -o deploy -g deploy -m 0750 /srv/shop/caddy
   sudo install -o deploy -g deploy -m 0640 Caddyfile /srv/shop/caddy/Caddyfile
   sudo -u deploy sh -c 'umask 077 && cat > /srv/shop/.env' <<EOF
   APP_TAG=<the commit SHA of the build to run>
   SITE_ADDRESS=app.example.com
   POSTGRES_PASSWORD=$(openssl rand -hex 32)
   EOF
   sudo stat -c '%a %U %n' /srv/shop /srv/shop/compose.yaml /srv/shop/caddy/Caddyfile /srv/shop/.env
   sudo -u deploy docker compose --project-directory /srv/shop config --quiet && echo config ok
   ```

   The password is made on the server and goes straight into the file, so it never appears in
   a command line, the chat or the shell history. Hex keeps it safe inside `DATABASE_URL`.
   `config --quiet` fails with "required variable ... is missing a value" when a line is
   missing. If the image is private, log `deploy` in to the registry with a read-only token
   (`docker login --password-stdin`, as in [ci-cd.md](ci-cd.md)).
6. **DNS before HTTPS.** The name must point at the server on A (and AAAA, or no AAAA at all)
   before Caddy asks for a certificate, or the request fails and counts against the rate limit
   ([dns-and-email.md](dns-and-email.md), [web-and-https.md](web-and-https.md)).
7. **The first deploy, by hand, watched:**

   ```
   sudo -u deploy docker compose --project-directory /srv/shop pull
   sudo -u deploy docker compose --project-directory /srv/shop up -d --wait --wait-timeout 180
   sudo -u deploy docker compose --project-directory /srv/shop ps
   sudo -u deploy docker compose --project-directory /srv/shop logs caddy | grep -i certificate
   ```

   `--wait` returns non-zero when a service does not become healthy; `logs app`, the same way,
   says why. Then look from outside, as a visitor would ([proving-it-works.md](proving-it-works.md)).
8. **Backups, with a restore tried once** ([backups.md](backups.md)). The values that join the
   backup job to the Compose file, in `/etc/restic-backup/shop.env`:

   ```
   BACKUP_TAG=shop
   DB_KIND=postgres
   DB_CONTAINER=shop-db-1
   DB_USER=app
   DB_NAME=app
   DUMP_DIR=/var/backups/shop
   BACKUP_PATHS="/srv/shop"
   ```

   `DB_USER` is the `POSTGRES_USER` of the Compose file: the official image creates no
   `postgres` role when another user is named, and the dump fails without it.
9. **Know when it breaks:** an outside uptime check of the site and the backup check-in
   ([monitoring-and-logs.md](monitoring-and-logs.md)).
10. **Deploy on every push,** once the hand deploy works ([ci-cd.md](ci-cd.md)): the deploy
    script installed as `/usr/local/bin/deploy-shop`, the CI key restricted to it, the host key
    pinned. Run `sudo -u deploy deploy-shop deploy <tag>` by hand once before the pipeline does.
11. **Prove it and hand it over** ([proving-it-works.md](proving-it-works.md)): what runs, the
    live tag (`sudo -u deploy deploy-shop status`), how to ship, how to roll back, where the
    secrets live, how to restore.

## A cluster, in order

1. **Say which cluster, context and namespace** to the person before anything, by the context's
   name, and learn what the cluster already provides: an ingress controller or Gateway,
   cert-manager, a storage class ([kubernetes.md](kubernetes.md)).
2. **The namespace and the Secret, by a person's credential:**
   `kubectl --context <CONTEXT> apply -f namespace.yaml`, then
   `kubectl --context <CONTEXT> -n shop create secret generic shop-secrets --from-env-file=<FILE>`
   from a file outside the repository. The pipeline never creates or reads it.
3. **The manifests** from [templates/kubernetes/](../templates/kubernetes/) with `<APP>` set to
   `shop`, also for one quick app (keep the Deployment's probes, limits and security context;
   drop the files that do not fit, as [kubernetes.md](kubernetes.md) says). The rendered output
   checked with `kubeconform` and `kubectl apply --dry-run=server`, then `diff -k`, `apply -k` and
   `rollout status`. Readiness probe first: it is what every later gate leans on.
   The NetworkPolicy in the kustomization keeps other namespaces out; migrations run as a Job
   before each rollout.
4. **DNS and the certificate:** the name points at the load balancer of the Gateway or Ingress,
   and cert-manager reports the Certificate `Ready`.
5. **The database:** a managed database or a server outside the cluster is the usual choice for
   a small team; its backups follow [backups.md](backups.md).
6. **Deploy on every push** with the service account and Role in [ci-cd.md](ci-cd.md), in the
   app's own namespace, since deploy rights there reach every Secret in it.
7. **Prove it from outside and hand it over** ([proving-it-works.md](proving-it-works.md)).

## Traps at the joins

- **A tool that owns a file nobody else may write.** The pipeline's deploy script once replaced
  `.env` with a single `APP_TAG` line: the first deploy worked (the stack was already up), then
  every `docker compose` command in the folder failed with "required variable
  POSTGRES_PASSWORD is missing a value", the automatic rollback included, and the only copy of
  the password was in `docker inspect` of the running container. Any tool that writes into the
  app folder changes its own line and keeps the rest.
- **Two names for one thing.** A Compose project called `shop` has containers called
  `shop-db-1`, not `db` or `app-db-1`; a backup that names the wrong container dumps nothing and
  a check that names the wrong one passes on nothing. Take names from the table above or from
  `ps`, run as in the table, not from memory.
- **A floating tag for your own app, or a frozen one for someone else's.** The first makes a
  rollback point at code that no longer exists; the second keeps the database on an image that
  will never get another fix.
- **A Compose file run from another folder or under another project name** (`-p`) creates a
  second project with new, empty volumes. The template fixes `name:`; name the folder with
  `--project-directory /srv/shop` every time, as in the table.

## Done means

- `/srv/shop`, `compose.yaml` and `.env` exist with the owners and modes in the table, and
  `sudo -u deploy docker compose --project-directory /srv/shop config --quiet` passes.
- The stack is healthy (`ps`, the same way), answers on its name over HTTPS from outside, and
  `sudo -u deploy deploy-shop status` prints the tag that `images app` shows.
- A deploy, a rollback and a plain `up -d` by hand each leave `.env` with all its lines, and the
  app still reaches its database.
- The backup job dumps `shop-db-1` and a restore was tried; the hand-over names all of it.

Checked against: Docker Engine 29.8.2 with Compose 5.7.0 (docker:29-cli), the filled
templates/compose.yaml with postgres:18-trixie (18.6) and caddy:2-alpine (2.11.9),
templates/ci/deploy.sh under bash 5.3 with util-linux flock 2.42, registry:3: a hand deploy, a
forced-command deploy, a broken tag rolled back, a manual rollback and a plain `up -d`; Caddy's
config in `caddy/` with a reload under load (Compose 5.7.0, docker:29-dind), 2026-11-12.
