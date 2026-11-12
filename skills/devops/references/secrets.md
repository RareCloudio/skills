# Keeping secrets

Read this when an app needs passwords, API keys or tokens on a server, in containers, on a
Kubernetes cluster or in a CI pipeline, or when one has leaked, or before a repository goes public.
It says where secrets live at each size of setup, how to use one without showing it, and the order
of work after a leak. The deploy credential a pipeline holds is set up in [ci-cd.md](ci-cd.md);
what else to review before the first public deploy is in
[before-it-goes-public.md](before-it-goes-public.md).

## Where secrets live, by size of setup

The goal at every size is the same: the value is readable by the process that needs it and by
the people who run the machine, and by nothing else. Not the repository, not the image, not the
process list, not the log.

### One server: an env file outside the repository and the web root

```
sudo install -d -o root -g app -m 0750 /etc/shop
sudo install -o root -g app -m 0640 /dev/null /etc/shop/app.env
sudoedit /etc/shop/app.env
stat -c '%a %U:%G %n' /etc/shop/app.env     # 640 root:app /etc/shop/app.env
```

Creating the file empty with its mode first means there is no moment when it exists
world-readable. Owned by root and readable by the app's group, the app can read it but not change
it. Outside the web root, a mistake in the web server config cannot serve it; outside the
repository, `git add .` cannot commit it. Add `.env` and `*.env` to `.gitignore` anyway, for the
developer's copy.

### A systemd service: an environment file, or credentials

```
[Service]
User=app
EnvironmentFile=/etc/shop/app.env
```

Put values in that file and not in `Environment=` lines in the unit: unit files are readable by
every user, and `systemctl show shop -p Environment` and `systemctl cat shop` print those values
to anyone on the machine (checked as an unprivileged user on Debian 13 with systemd 257), while
`EnvironmentFile=` shows only the path. Environment variables are inherited by every child
process and are easy to dump by mistake, so for a value that only has to be read once, systemd's
credentials are tighter:

```
LoadCredential=db_password:/etc/credstore/db_password
```

The service then reads the file `$CREDENTIALS_DIRECTORY/db_password`, which only that service
can see. This one was not verified here: in a container running systemd 257 the unit was accepted
but the credential directory did not appear, so try it on the real host with
`systemd-run -p LoadCredential=... --pipe --wait sh -c 'ls -l "$CREDENTIALS_DIRECTORY"'` before
relying on it, and fall back to the environment file when it does not show up.

### Compose: `env_file`, or secrets as files

`env_file: /etc/shop/app.env` is the plain way. Know where values show up: whatever reaches a
container through `environment:` or `env_file:` is printed by `docker inspect` to anyone who can
use Docker, and `docker compose config` prints the interpolated values too. Compose secrets keep
the value out of both:

```
services:
  web:
    environment:
      DB_PASSWORD_FILE: /run/secrets/db_password
    secrets: [db_password]
secrets:
  db_password:
    file: /etc/shop/db_password
```

Outside Swarm a file secret is a read-only bind mount of that file at `/run/secrets/<name>`. The
`uid`, `gid` and `mode` options are ignored with a warning (Compose 2.26 and 5.6 both say so), so
on Linux the host file's own owner and mode decide who in the container can read it. A container
that runs as user 1000 gets "Permission denied" on a root-owned 0600 file; `chown root:1000` and
mode 0440 fixes it. The app has to read the file, which many images support through a
`<NAME>_FILE` variable; check the image's documentation.

### Kubernetes: Secrets, and SOPS with age for git

A Secret's `data` is base64, which is an encoding anyone can reverse, not encryption. Who can
read one:

- anyone allowed to `get` or `list` Secrets in the namespace;
- anyone allowed to create Pods in the namespace, or to create or patch anything that makes Pods
  (a Deployment, a StatefulSet, a Job, a CronJob), because a Pod can mount any Secret there. In
  tests, an account refused `get secrets` printed the value through a Pod it created and its
  log, and the deploy account of [ci-cd.md](ci-cd.md), which may not create Pods, read it
  through a Deployment that served the mounted file on a NodePort Service;
- anyone with access to etcd or its backups. On a kubeadm-style cluster (kind included) Secrets
  are stored in etcd as plain text unless the API server is given an encryption configuration;
  a managed cluster may encrypt them, so check its documentation rather than assume.

So treat `get secrets` and the right to make Pods as the same right. A pipeline that deploys
holds the second, so it can read every Secret in its namespace: give each app its own namespace
holding only that app's Secrets, bind the pipeline's account there and nowhere else, and keep
the token short-lived and released only to the protected deploy environment
([ci-cd.md](ci-cd.md)). App accounts get neither right.

To keep Secret manifests in git, encrypt them with SOPS (a tool that encrypts the values of a
YAML, JSON or env file and leaves the keys readable) using age keys (a small, modern file
encryption tool). Both ship static binaries on their GitHub release pages; verify the checksums.

```
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt        # prints the public key, age1...
cat > .sops.yaml <<'EOF'
creation_rules:
  - path_regex: secrets/.*\.yaml$
    encrypted_regex: ^(data|stringData)$
    age: age1first...,age1second...
EOF
sops encrypt -i secrets/app.yaml
sops decrypt secrets/app.yaml | kubectl apply -f -
```

The file in git then shows `kind`, `metadata` and the key names, with each value as
`ENC[AES256_GCM,...]`, so a diff still says which setting changed. What to know:

- The private key file is the only way back in. List at least two recipients (the person's key and
  a backup key kept offline, or the CI key), and after changing the list run
  `sops updatekeys secrets/app.yaml` to re-encrypt for it.
- The default key location is `~/.config/sops/age/keys.txt` on Linux but
  `~/Library/Application Support/sops/age/keys.txt` on macOS, which ignores the Linux path; set
  `SOPS_AGE_KEY_FILE` to be sure.
- Decrypting in a pipeline is fine when the age key is a secret of the protected deploy
  environment only, passed in `SOPS_AGE_KEY`, and the plaintext is piped straight to where it is
  used (`sops decrypt secrets/app.yaml | kubectl apply -f -`; tested: nothing reached the disk).
  The leak is a decrypted file left in the workspace, in an artifact or in a log
  ([ci-cd.md](ci-cd.md)).
- Change values with `sops edit` or `sops set`, never by hand: any hand edit, even to the
  unencrypted `metadata.name`, fails the next decrypt with "MAC mismatch".
- `sops decrypt --output file` writes the file with the default umask (0644 in the test); run
  `umask 077` first, or better, pipe straight into `kubectl apply` as above.
- For an env file, `sops encrypt app.env > app.enc.env` keeps the dotenv format, and
  `sops exec-env app.enc.env './start'` runs a command with the values in its environment
  without writing them to disk (the command runs through `/bin/sh`).

When the cluster already runs a secrets operator (External Secrets, Sealed Secrets) or the
provider has a secret manager, use that instead; SOPS is the simple option when there is none.

### The CI platform's store

Deploy credentials live in the platform's secret store, scoped to the environment that uses them
(GitHub environment secrets, GitLab protected variables scoped to an environment). Set them from
standard input so the value is not in your shell history or the process list:
`gh secret set NAME --env production < file`. App secrets stay where the app runs; a pipeline
that only deploys a new image does not need the database password.

## Using a secret without showing it

Say whether a value is set, and at most its last four characters, so the person can tell which
key is in use:

```
test -n "${DB_PASSWORD:-}" && echo "DB_PASSWORD is set" || echo "DB_PASSWORD is missing"
echo "API_KEY ends in ${API_KEY: -4}"     # bash; the space before -4 matters
```

Do not `cat` an env file, run `env` or `printenv`, `docker inspect` a container, `kubectl get
secret -o yaml`, or `set -x` in a script that handles secrets: each prints values into your
output, the chat and the CI log, where they stay. Read them by name (`grep -c '^DB_PASSWORD='
app.env` says whether a line exists) and refer to them by name and file in what you write.

**Not on the command line.** Arguments are visible to every user on the machine: another
account's `ps -o args` showed `--password=...` in full, while `/proc/<pid>/environ` of the same
process was "Permission denied" to it. Prefer, in this order: a file the program reads, standard
input (`docker login --password-stdin`, `gh secret set`), an environment variable. A tool that
only takes a password as an argument (`mysql -p<password>`) has a config-file alternative
(`~/.my.cnf` with mode 0600, or `--defaults-extra-file`); use that.

**Not in the image.** Whoever can pull the image can read every layer:

- a `--build-arg` value used in a `RUN` is recorded in `docker history --no-trunc` and in the
  image's config (Docker warns with `SecretsUsedInArgOrEnv`);
- a file copied in and deleted in a later step is still whole in the earlier layer, recovered in
  the test with `docker save` and `tar`;
- `ENV` with a value is in the image config.

When the build itself needs a secret (a private package registry), mount it for one step:

```
RUN --mount=type=secret,id=npm_token,env=NPM_TOKEN npm ci
```
```
docker build --secret id=npm_token,src=/etc/shop/npm_token .
```

The value is present while that step runs and appears in no layer and in no history line. Runtime
secrets do not belong in the build at all: the container gets them when it starts.

## When one leaks

A secret that reached a commit, a public log, a chat, an image or a screenshot counts as leaked,
even if it was deleted a minute later: public pushes are scanned by bots within minutes, and
forks, clones, CI logs and caches keep copies you cannot reach. Work in this order:

1. **Rotate first.** Create the replacement at its source (the provider's console, the database,
   the API's key page), deploy it, then revoke the old one. Until the old value stops working,
   everything else is cosmetic; rewriting history first only buys time for whoever already has it.
   Revoking at the source is usually the person's job in their own account, so tell them which
   key, where, and why it cannot wait.
2. **Find out whether it was used.** Read the provider's access or audit log for the window
   between the leak and the revocation: logins from unknown addresses, new keys or users created,
   resources started, data exported. A key that created another key needs that one revoked too.
3. **Then clean up, if it is still worth it.** Remove the value from the code and the image and
   rebuild. Rewriting git history (`git filter-repo --invert-paths --path .env` on a fresh clone,
   checked here on a sample repository) only matters for a repository that is or will become
   public, and it needs the person's yes: it rewrites every commit hash after that point, needs a
   force-push, and everyone with a clone has to clone again. The hosting provider can still serve
   the old commits by their hash, from forks or from pull request references, until its support
   removes them.

## Before a repository goes public

Scan the history, not only the files you see. A working-tree scan misses the secret that was
committed and deleted later, which is the most common case:

```
gitleaks git . --redact          # every commit; exits 1 when it finds something
gitleaks dir . --redact          # the files as they are on disk now
```

In the test, `dir` found nothing in a repository whose second commit had added a token and whose
third had removed it; `git` found it, with the commit and the file. Run it from the official image
(`ghcr.io/gitleaks/gitleaks`) or a release binary. Treat every finding as leaked and go through
the steps above; a clean scan is evidence, not proof, since scanners know common key shapes and
miss a plain password. TruffleHog is a second opinion; its verification mode sends each candidate
to the provider to test it, so ask before using that on someone's secrets.

## Traps

- **`.env` committed before `.gitignore` existed.** Ignoring a tracked file does nothing; `git rm
  --cached .env`, then rotate, because it is already in history.
- **A public variable prefix** (`NEXT_PUBLIC_`, `VITE_`, `REACT_APP_`) compiles the value into
  the JavaScript every visitor downloads. Only values meant to be public go there.
- **Secrets in a Compose `environment:` block in git.** The file gets committed with the values;
  point at an env file outside the repository instead.
- **One credential for everything.** The same database password in staging and production, or one
  admin token for CI, the app and the person, means one leak opens all of them and rotating it
  breaks all of them at once. Give each its own.
- **A secret pasted into the chat.** It is now in a transcript. Use it, then suggest rotating it.

## Done means

- No secret value in the repository or its history (a `gitleaks git` run is clean), in any image
  layer, or in a unit file; each lives in one place with a mode that you checked with `stat`.
- The app was restarted from those files and works, so they are the real source.
- The hand-over lists every secret by name and location, who can read it, and how to rotate it.
- After a leak: the old value is revoked and shown to fail, the access log was read, and the
  person knows what was found.

Checked against: sops 3.13.3 and age 1.3.2 (release binaries, debian:13 and macOS), kind 0.33.0
with Kubernetes 1.37.0, Docker 29.8 with Compose 5.6.0 and Docker 26.1.5 with Compose 2.26.1 on
debian:13, systemd 257 on debian:13, OpenSSH 10.0p2, gitleaks 8.30.1 (official image),
git-filter-repo from PyPI, 2026-11-12.
