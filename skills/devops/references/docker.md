# Docker and Compose in production on one server

Read this when an app should run in containers on a single server: writing its Dockerfile and
its Compose file, installing Docker, updating, rolling back and cleaning up. Running an app
without containers is in [systemd.md](systemd.md); a cluster is in [kubernetes.md](kubernetes.md); the proxy's own
configuration is in [web-and-https.md](web-and-https.md), and why a published port can slip past the host firewall
is in [firewall.md](firewall.md). Database dumps and restores are in [backups.md](backups.md).

## Read the project before writing anything

The manifest and the lockfile say the language, the package manager and its version, the
framework, and the build and start commands (`package.json` scripts, `pyproject.toml`, `go.mod`,
a `Procfile`). The code says the port it listens on, the environment variable names it reads
(look for `process.env`, `os.environ`, `getenv`, and the `.env.example` if there is one), whether
it writes to local disk, and what else must keep running beside the web process. Read an existing
Dockerfile or Compose file before replacing it: it often encodes a fix someone needed.

Ask the person only for what the files cannot tell you: the domain, which variables are secrets,
where the image registry is, whether there is data to bring over. When the app has no health
endpoint, propose adding one (a route that answers 200 once the app can serve); every check
below leans on it, and a page that renders the home screen is a slow and noisy substitute.

## Write the Dockerfile

Start from the template for the stack in [templates/dockerfiles/](../templates/dockerfiles/)
(`node.Dockerfile`, `python.Dockerfile`, `go.Dockerfile`) with the `.dockerignore` beside it,
and adapt it to what you found. What each part is for:

- **Two stages.** Compilers, dev dependencies and caches stay in the build stage; the final
  image carries the runtime and the built app. The Go template ends at about 15 MB, the Node
  one at about 350 MB, because the slim Node base itself is most of that.
- **A base image on the runtime's line,** the one the project runs (`node:24-trixie-slim`, not
  `node` or `latest`): the publisher rebuilds that tag with security fixes, while an exact
  patch tag is frozen once the next patch ships, and `latest` jumps to a new major that looks
  like a code bug. `docker build --pull` brings the fixes. This is the tag rule of
  [first-deploy.md](first-deploy.md); pin the digest too, moved by a bot, when builds must be
  reproducible.
- **Manifests before sources.** `COPY package.json package-lock.json ./` then install, then
  `COPY . .`, so editing code reuses the cached dependency layer. `RUN --mount=type=cache` keeps
  the package manager's download cache between builds without putting it in the image.
- **A non-root user** for the running app, with the code owned by root so the app cannot
  rewrite itself. Official images often ship one (`node`, distroless `nonroot`).
- **`.dockerignore`** keeps `.git`, `.env`, `node_modules` and local builds out of the build
  context: smaller uploads, no secrets copied in, no host-built binaries for the wrong OS.
- **A `HEALTHCHECK`** that requests the health endpoint with what the image already has (Node's
  `fetch`, Python's `urllib`, the Go binary's own flag; slim images have no curl).
- **Exec-form `CMD`** (`["node", "dist/server.js"]`), so the app is the process that receives
  the stop signal.

Secrets go in at run time, from the env file, never into the image. A build argument is not a
hiding place: `docker history --no-trunc <image>` prints `NPM_TOKEN=<value>` for any `ARG` used
by a `RUN`. When the build itself needs a credential (a private package registry), pass it as a
build secret, which exists only during that one step and is absent from the image and its
history. Taking it from the builder's environment keeps a token file out of the build context:

```
# Dockerfile
RUN --mount=type=secret,id=npm_token,env=NPM_TOKEN npm ci
# shell, with NPM_TOKEN set in the environment (CI secret store)
docker build --secret id=npm_token,env=NPM_TOKEN -t registry.example.com/shop/web:1.4.2 .
```

Lint with hadolint from its official image; it catches unpinned packages, missing `WORKDIR`
and shell-form commands:

```
docker run --rm -i hadolint/hadolint:v2.14.0 < Dockerfile
```

## Traps that break builds and stops

Each of these was reproduced; the error text is what you will see.

- **Installing only production dependencies before the build step.** `npm ci --omit=dev`
  followed by `npm run build` fails with exit code 127, because `tsc` or the bundler is a dev
  dependency. Install everything in the build stage, build, then `npm prune --omit=dev`.
- **A Go binary built with cgo, run on a static base.** The `golang` image has a C compiler, so
  cgo is on and a program that uses `net` links against glibc. On distroless `static` or
  `scratch` it dies with `exec /server: no such file or directory`: the missing file is the
  dynamic loader, not the binary. Build with `CGO_ENABLED=0`, or use a base with glibc.
- **A Python virtualenv copied to a different path.** The venv's scripts start with
  `#!/opt/venv/bin/python`; copied to `/app/venv`, `gunicorn` fails with the same misleading
  `no such file or directory`. Create the venv at the path it will run from.
- **The app as PID 1 ignores SIGTERM.** The kernel gives PID 1 no default signal handling, so
  a Node app without a SIGTERM handler is killed after Docker's 10 second stop timeout (exit
  137), on every deploy. Handle SIGTERM in the app, or set `init: true` in Compose (exit 143,
  at once). A shell-form `CMD` puts `sh` in front of the app and has the same effect, and
  `npm start` as the command exits with status 1 on every stop.
- **Python output that never shows up.** Without `PYTHONUNBUFFERED=1`, `print()` output is
  buffered when there is no terminal, and lost when the process dies.

## Install Docker on the server

Use Docker's own package repository. The distribution packages lag or differ: on Debian 13,
`docker.io` is 26.1 while Docker's repository carries 29.x; on Ubuntu 24.04 the package named
`docker-compose` is the retired Python version 1.29 with different behaviour (the plugin is
`docker-compose-v2`); AlmaLinux and Rocky ship no Docker package at all. Docker's repository
gives the engine, the `docker compose` plugin and buildx at matching versions. On Debian and
Ubuntu (`$ID` reads `debian` or `ubuntu` from the system):

```
apt-get update && apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
. /etc/os-release
curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/$ID
Suites: $VERSION_CODENAME
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker version && docker compose version && systemctl is-enabled docker
```

On the RHEL family: `dnf install -y dnf-plugins-core`, then
`dnf config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo`, the same
five packages with `dnf install`, and `systemctl enable --now docker`. Docker also publishes a
convenience script; it is meant for test machines, so read it before running it, and prefer the
repository on a server.

Membership of the `docker` group is root on the host (any member can mount `/` into a
container), so add only people who already have sudo. Docker Hub limits anonymous pulls per
address and answers `429 Too Many Requests` once a shared address has used them up; a
`docker login` with any Hub account raises the limit.

## Compose for production

Start from [templates/compose.yaml](../templates/compose.yaml): the app, Postgres and Caddy in
front, with its values in a `.env` file beside it. The folder (`/srv/<app>`), the owner and mode
of each file, and what `.env` holds are set once in [first-deploy.md](first-deploy.md); keep to
them, because the deploy script and the backup job rely on the same names. What the template
settles, and why:

- **`name:` fixed.** Without it the project is named after the folder; run Compose from a
  renamed or copied folder and it creates a second project with new, empty volumes.
- **The app's tag from `.env`** (`APP_TAG=1.4.2`). Updating and rolling back become a one-line
  change, and the running version is visible in one file. `latest` tells you neither. The
  other images follow the tag rule in [first-deploy.md](first-deploy.md).
- **`restart: unless-stopped`.** It acts when the process exits. Docker Engine does not restart
  a container for being `unhealthy`; that status only feeds `depends_on`, `--wait` and your
  monitoring. A container stopped with `docker stop` or `docker kill` counts as stopped by hand
  and stays down, so test the policy by ending the process from inside instead.
- **Health checks and `depends_on: condition: service_healthy`,** so the app starts after
  Postgres accepts connections and Caddy after the app answers. `restart: true` on a dependency
  restarts the app when Compose restarts the database (`docker compose restart db`), not when the
  database crashes and Docker restarts it; the app still has to reconnect on its own.
- **Named volumes for data.** A database service with no volume of its own writes into an
  anonymous volume: the data survives `up --force-recreate`, but after `down` and `up` the
  tables are gone (the old volume is left behind, unnamed). From Postgres 18 the official image
  keeps its data in `/var/lib/postgresql/18/docker`, so the volume goes on `/var/lib/postgresql`;
  a volume left on the old `/var/lib/postgresql/data` path makes the container exit with an
  error about an unused mount. A major-version change of an existing database needs
  `pg_upgrade` or a dump and restore, not a new tag. Bind mounts suit config files you edit on
  the host; they keep the host's owner, so a non-root container user needs that UID to write.
- **Log rotation.** On Linux the engine's default `json-file` driver has no size limit, and a
  chatty container fills the disk. The template sets `max-size` and `max-file` per service. A
  default for all containers goes in `/etc/docker/daemon.json` (`"log-driver": "json-file"`,
  `"log-opts": {"max-size": "10m", "max-file": "5"}`); it reaches only containers created after
  the daemon restarts, and restarting the daemon restarts what runs on the box, so ask first.
  Docker Desktop uses other defaults; do not judge a server by a laptop.
- **Ports.** Only Caddy publishes, on 80 and 443. When the proxy runs on the host instead,
  publish the app as `"127.0.0.1:3000:3000"`; a bare `"3000:3000"` listens on every address,
  and Docker's own firewall rules let it through a host firewall such as ufw ([firewall.md](firewall.md)).
  Never publish the database; reach it with `exec db psql -U app` (run as below) or an SSH
  tunnel.
- **The proxy's config in a mounted folder.** Caddy reads `caddy/Caddyfile` beside the Compose
  file through a folder mount, and an edit goes live with a graceful reload inside the container
  (the command is in the template's header): in the test no request failed, while recreating
  Caddy failed 60 of 400. `up -d` would not have applied the edit anyway: it does not re-read a
  single-file mount whose file an editor replaced, nor a config inline under `configs:`. A value
  Caddy gets through `environment:` (the site address) is different: `up -d` recreates Caddy.
- **Limits.** `deploy.resources.limits` applies under plain `docker compose up` (checked with
  `docker inspect`: `HostConfig.Memory`, `NanoCpus`). Without a limit, a leak in one service
  starves the database on a small server.
- **`.env` is parsed by Compose, not by a shell.** A `$` in a value is read as a variable: a
  password `pa$word` arrives as `pa`, with only a warning. Write `$$`, single-quote the value,
  or generate secrets as hex (`openssl rand -hex 32`), which also keeps them safe inside a URL.

## Update, roll back, clean up

Update to a new version: change the `APP_TAG=` line in `.env` and nothing else
(`sudoedit` keeps the file's owner and mode), then, as the folder's owner and with the folder
named, as in [first-deploy.md](first-deploy.md) (the folder is closed to the admin account):

```
sudo -u deploy docker compose --project-directory /srv/shop pull app
sudo -u deploy docker compose --project-directory /srv/shop up -d --wait
```

With the CI deploy script installed, `sudo -u deploy deploy-shop deploy <tag>` does the same and
records the previous tag; [ci-cd.md](ci-cd.md) has it.

`up -d` recreates only services whose image or configuration changed; the database container
keeps running. `restart` does not apply edits to the Compose file; `up -d` does. When images are
built on the server instead of pulled, run `build --pull app` first, the same way.

Roll back: set `APP_TAG` to the previous version and run `up -d --wait` again, the same way.
That needs the previous image, so keep it in the registry and do not prune it from the server.
Code goes back; the database schema does not. Migrations that only add (columns, tables) keep the
previous version working on the new schema; a migration that drops or renames something needs
its own plan and a backup taken just before.

Disk fills with old images and build cache. Safe to run: `docker image prune` (untagged layers
only) and `docker builder prune`. `docker image prune -a` also deletes the tagged images no
container uses, which includes your rollback target.

These delete data. Each one waits for the person's yes for that specific command, after a backup
that has been checked ([backups.md](backups.md)), because a deleted volume does not come back:

- `docker compose down -v` deletes the project's named volumes: the database and Caddy's
  certificates. Plain `docker compose down` keeps them.
- `docker volume rm <name>` and `docker volume prune -a` delete named volumes.
- `docker system prune --volumes` and `docker volume prune` delete anonymous volumes (on
  engine 29, named ones only with `-a`). An image that declares `VOLUME` (Postgres, MySQL)
  keeps its data in an anonymous volume when Compose gives it none.

## Check before hand-over

Run the whole stack once under a throwaway project name, on your machine or in CI, before it
goes to the server. The project name matters: `down -v` under the live project's name deletes
production data, so the check uses its own (`shop-check`). On the server itself, ports 80 and 443
are taken, so publish Caddy elsewhere with an override file, and serve plain HTTP:

```
# compose.check.yaml
services:
  caddy:
    ports: !override
      - "127.0.0.1:38080:80"
```

```
docker run --rm -i hadolint/hadolint:v2.14.0 < Dockerfile
docker build -t registry.example.com/shop/web:1.4.2 .
# check.env: APP_TAG=1.4.2, SITE_ADDRESS=:80, POSTGRES_PASSWORD from openssl rand -hex 32
# caddy/Caddyfile beside compose.yaml, from templates/Caddyfile
docker compose -p shop-check --env-file check.env -f compose.yaml -f compose.check.yaml config -q
docker compose -p shop-check --env-file check.env -f compose.yaml -f compose.check.yaml \
  up -d --wait --wait-timeout 120
curl -fsS http://127.0.0.1:38080/healthz
docker compose -p shop-check --env-file check.env -f compose.yaml -f compose.check.yaml down -v
```

`--wait` returns non-zero when a service does not become healthy; `docker compose -p shop-check
logs app` shows why. Then deploy for real and check from outside with
[proving-it-works.md](proving-it-works.md).

## Done means

- The image builds from a clean checkout, passes hadolint, runs as a non-root user, and holds
  no secret (`docker history --no-trunc` and the files under the app folder show none).
- `ps` on the server (run as above) shows every service running and `healthy`, the app
  answers through the proxy on its name, and nothing but 80 and 443 (and SSH) answers from
  outside.
- Logs rotate, data lives in named volumes, `.env` is mode 600 and not in git.
- The hand-over names the running tag, the one command to update, the one to roll back, and
  which commands delete data.

Checked against: Docker Engine 29.9.3 (docker:29-dind) and 29.8.2 with Compose v5.6.0,
hadolint 2.14.0, Debian 13, Ubuntu 24.04, AlmaLinux 9, postgres:18.4-trixie and
postgres:18-trixie (18.6), caddy:2.11.9-alpine and caddy:2-alpine (2.11.9); the Caddy reload
and the mount tests with Compose 5.7.0 in docker:29-dind, 2026-11-12.
