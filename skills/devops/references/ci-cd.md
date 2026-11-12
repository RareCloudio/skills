# Deploying on every push

Read this when a person wants a push to their main branch to put the new version live, on one
server over SSH or on a Kubernetes cluster, for a small team or one person. It covers the shape of
the pipeline, the narrow credential it deploys with, the health gate and the rollback, and the
hygiene that keeps a CI system from becoming the easiest way into production. Where the secrets
live and what to do when one leaks is in [secrets.md](secrets.md); the Compose file and the
Dockerfile are in [docker.md](docker.md); Deployments, probes and ingress are in [kubernetes.md](kubernetes.md); checking the
result from outside is in [proving-it-works.md](proving-it-works.md).

## The shape that works

Each piece is there because of a failure it prevents.

1. **Build once, tag the image with the commit.** A tag like `:latest` or `:prod` names whatever
   was pushed last, so nobody can say what is running, two servers can run different code under
   one name, and Kubernetes sees no change when the tag is reused. The commit SHA is unique and
   ties the running code to the source.
2. **Push it to a registry, deploy that exact tag.** The server never builds. What was tested is
   what runs, and putting an old version back is a pull of an old tag, not a rebuild.
3. **Gate on health, then check from outside.** The server or cluster waits for the new version
   to report healthy; the pipeline then requests the public address, because a container that is
   healthy inside can still be unreachable behind a proxy, firewall or DNS change.
4. **Roll back to the previous tag when either check fails,** automatically, and fail the run so
   a person sees it.
5. **Say which version is live,** at the end of every run, whatever happened.

The templates in [templates/ci/](../templates/ci/) implement this:
[github-deploy-compose-ssh.yaml](../templates/ci/github-deploy-compose-ssh.yaml) for one server,
[github-deploy-kubernetes.yaml](../templates/ci/github-deploy-kubernetes.yaml) for a cluster,
[gitlab-deploy-compose-ssh.yml](../templates/ci/gitlab-deploy-compose-ssh.yml) for GitLab, and
[deploy.sh](../templates/ci/deploy.sh), the server side of the SSH ones. Each lists its
placeholders at the top. Both GitHub templates also accept a manual run with a tag, which deploys
an earlier build without building: that is how a person goes back more than one version.

## Deploy by hand first, automate second

Do the first deploy by hand, together with the person: create the deploy user, install the
script, log the server in to the registry, run `sudo -u deploy deploy-shop deploy <tag>` yourself
and watch it come up. A pipeline that fails on its first run fails for ten reasons at once
(registry login, host key, firewall, a missing env file, a healthcheck that never passes) and each
retry costs a commit.
Once the manual run works, the pipeline only repeats a known-good sequence, and you add it then.

## To one server over SSH

The pipeline holds an SSH key. If that key opens a shell, anyone who can change a workflow file or
steal a CI secret owns the server. So the key gets one power: running the deploy script.

**The deploy user and the script.** The user `deploy`, the app folder `/srv/shop` and its `.env`
are made as in [first-deploy.md](first-deploy.md), which owns those names. Install the script,
filled in, owned by root:

```
sudo install -o root -g root -m 0755 deploy.sh /usr/local/bin/deploy-shop
```

`useradd` leaves the password locked, so there is no password to guess, and key logins still work
(checked on Debian 13 with the stock `UsePAM yes`). Keep the shell a real shell: a forced command
is run through the user's login shell, and with `/usr/sbin/nologin` every deploy fails with "This
account is currently not available". Membership of the `docker` group is root on that machine
(`docker run -v /:/host` reads any file), which is why the key, not the user, is what gets
restricted. The script is owned by root so the deploy user can run it but not rewrite it.

**The key, restricted.** Generate it where it will be handed to the CI store, not on the server:

```
ssh-keygen -t ed25519 -N '' -C ci-deploy -f deploy_key
```

Put the public half on the server as one line in `~deploy/.ssh/authorized_keys` (directory 0700,
file 0600, owned by deploy):

```
restrict,command="/usr/local/bin/deploy-shop" ssh-ed25519 AAAA... ci-deploy
```

`command=` replaces whatever the client asked to run; the request arrives in
`SSH_ORIGINAL_COMMAND`, which the script splits into words and checks, never evaluates. `restrict`
turns off port, agent and X11 forwarding, the terminal and `~/.ssh/rc`. When the CI runners have
fixed addresses (a self-hosted runner), add `from="203.0.113.10"` as well. Then prove it, from
another machine, before the key goes anywhere:

```
ssh -i deploy_key -l deploy app.example.com status            # prints the live tag
ssh -i deploy_key -l deploy app.example.com id                # refused, exit 64
ssh -i deploy_key -l deploy app.example.com 'deploy v1; id'   # refused, exit 64
ssh -i deploy_key -l deploy -W 127.0.0.1:8080 app.example.com # "administratively prohibited"
scp -i deploy_key -o User=deploy somefile app.example.com:/tmp/   # connection closed
```

Hand the private half to the platform's store from standard input, so it never appears in an
argument, then delete the local copy:

```
gh secret set DEPLOY_SSH_KEY --env production < deploy_key && rm deploy_key
```

**Pin the host key; never turn checking off.** `StrictHostKeyChecking no` in a pipeline means it
will hand the deploy to whatever answers on that address after a DNS mistake or a hijack. Read the
fingerprint on the server itself (its console, or a session you already trust), fetch the key from
outside, and compare the two fingerprints before saving it:

```
ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub                     # on the server
ssh-keyscan -p 22 -t ed25519 app.example.com > known_hosts && ssh-keygen -lf known_hosts
gh variable set DEPLOY_KNOWN_HOSTS --env production < known_hosts
```

A host key is public, so it can live in a variable, or in the repository. For a port other than 22
`ssh-keyscan -p` writes the entry as `[host]:port`. When the server is rebuilt its host key changes
and the deploy fails with "Host key verification failed": that is the check working, so update
the stored line after checking the new fingerprint the same way.

**The server pulls.** Log the deploy user in to the registry once, with a token that can only
read images (`docker login` as deploy stores it in `~deploy/.docker/config.json`). The Compose
file is [templates/compose.yaml](../templates/compose.yaml): it names the app's image as
`<image>:${APP_TAG:?...}` and has a healthcheck, because `up --wait` is the gate.

`deploy.sh` keeps the live tag on the `APP_TAG=` line of the `.env` beside `compose.yaml`, the
same file that holds the database password and the site address. It rewrites only that line,
into a copy with the file's owner and mode that it renames over `.env`, so a person running
`up -d` by hand gets the stack the pipeline started, and the previous tag goes
to `.previous-tag`. It pulls only the app's service first, so a missing tag changes nothing and
a deploy never moves the database or the proxy to a newer image; then it runs
`up --detach --wait`, and on an unhealthy result starts the previous tag again and exits 1. It
takes a lock, so two pipelines cannot deploy at once (the second exits 75), and logs each step
with `logger` (on a systemd host, `journalctl -t deploy`). Rehearsed: three tags in a local
registry, the third built without its health file; the script reported "container is unhealthy",
came back on the second tag and exited 1, and `rollback` afterwards went to the first.

## To a Kubernetes cluster

The pipeline applies the app's manifests, so it gets a service account that can write the kinds
in the app's kustomization in that one namespace and nothing else, not the admin kubeconfig the
person uses. A person creates the namespace and the app's Secret once, with their own credential.

```
apiVersion: v1
kind: ServiceAccount
metadata: {name: deployer, namespace: shop}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: deployer, namespace: shop}
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "create", "patch"]
  - apiGroups: ["apps"]
    resources: ["replicasets"]     # rollout status, undo and history read these
    verbs: ["get", "list", "watch"]
  # The other kinds the kustomization holds. No Secrets rule, yet see below: it can still read them.
  - apiGroups: ["", "autoscaling", "policy", "networking.k8s.io", "cert-manager.io",
                "gateway.networking.k8s.io"]
    resources: ["configmaps", "services", "horizontalpodautoscalers", "poddisruptionbudgets",
                "networkpolicies", "issuers", "gateways", "httproutes"]
    verbs: ["get", "create", "patch"]
  - apiGroups: ["batch"]            # the migration Job (kubernetes.md), one per release
    resources: ["jobs"]
    verbs: ["get", "create"]
  - apiGroups: [""]                 # the Job's log and events; watch: for a pod not running
    resources: ["pods", "pods/log", "events"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: deployer, namespace: shop}
subjects: [{kind: ServiceAccount, name: deployer, namespace: shop}]
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: deployer}
---
# The Namespace is cluster-wide, so a Role cannot cover it; this allows that one by name.
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: deployer-shop}
rules:
  - {apiGroups: [""], resources: ["namespaces"], resourceNames: ["shop"], verbs: ["get", "patch"]}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: deployer-shop}
subjects: [{kind: ServiceAccount, name: deployer, namespace: shop}]
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: deployer-shop}
```

Without the ReplicaSet rule, `rollout undo` fails with "cannot list resource replicasets" on the
day you need it; without the namespace rule, `apply -k` stops at the Namespace; without `watch` on
pods, the log of a migration whose pod never started is Forbidden. A kind added to the
kustomization goes into the Role too (an Ingress: `ingresses` in `networking.k8s.io`). Verify:

```
kubectl --kubeconfig ci-kubeconfig auth can-i --list -n shop
kubectl --kubeconfig ci-kubeconfig get secrets -n shop     # Forbidden
kubectl --kubeconfig ci-kubeconfig get deploy -n default   # Forbidden
```

That `Forbidden` is not the whole story. An account that may create or patch a Deployment can
start a Pod that mounts any Secret in the namespace and send the value out; on kind this Role
read the app's database password through a Deployment and a NodePort Service it was allowed to
create. So size a leak of this kubeconfig as a leak of every Secret in `shop`: keep that
namespace to this one app, bind the account only there, and keep the token short-lived and
released only to the protected environment.

**The token.** `kubectl -n shop create token deployer --duration=720h` gives a token that expires
on its own (the API server may cap it; renew it before it runs out). A Secret of type
`kubernetes.io/service-account-token` annotated with the account's name gives one with no expiry,
revoked by deleting that Secret. For a small setup the expiring token with a calendar reminder is
the better default; no stored token (the cluster trusting the CI platform's OIDC identity) is
stronger, and more setup.
Build the kubeconfig with `kubectl config set-cluster ... --embed-certs`, `set-credentials
--token`, `set-context --namespace`, and store the whole file as the `KUBECONFIG` secret.

**The rollout.** Git is the source of truth, so the pipeline changes the cluster only by applying
the files. It checks out the commit it deploys, runs that release's migration Job and waits for
it when `MIGRATION_JOB` names one, writes that commit's tag into the kustomization
(`kustomize edit set image ghcr.io/example/shop:<sha>` sets its `images:` field) and runs
`kubectl apply -k`; with Helm, `helm upgrade --set image.tag=<sha>`. What runs is then always one
commit's files with that commit's image, and putting an old version back is a run with that
commit's SHA. A fix made by hand with `kubectl set image` is undone by the next deploy unless it
is written back to git (see [kubernetes.md](kubernetes.md)).

`kubectl rollout status --timeout=5m` is the gate; it exits 1 on the timeout or when the
Deployment's `progressDeadlineSeconds` passes. `kubectl rollout undo --to-revision` then returns to
the revision the run noted before applying, and only when the run made a new one. The gate means
something only when the pod has a readiness probe: without one a pod is "ready" as soon as it
starts. With one, a broken version never receives traffic; in the rehearsal the old pods kept
serving (2/2 available) the whole time the new pod failed. On kind with the Role above, the template
undid a missing tag and a failed outside check, and left a re-deploy of the live tag alone.

## Pipeline hygiene, with the reasons

- **Least-privilege `permissions`.** Set `permissions: {}` at the top and grant per job
  (`contents: read`, `packages: write` for the build). The default token can otherwise write to
  the repository from any step.
- **Third-party actions pinned to a commit,** with the version as a comment
  (`uses: docker/login-action@8aa5831fb8d48d8f76594c7ddde61ae58019f550 # v4.8.0`). A tag can be
  moved to new code by whoever controls that repository; a commit cannot. Look the SHA up in the
  action's own repository (`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`), never from a
  blog post. GitHub's guide now also describes a workflow dependency lockfile; check for it.
- **Secrets from the platform's store, never echoed.** Pass them to a step through `env:` and
  write them to a file with mode 0600. Masking in the log is a safety net, not a control: GitHub
  documents that a transformed value (base64, part of a JSON blob) may not be masked.
- **No `${{ }}` inside `run:` for anything a user can type** (branch names, titles, inputs). It is
  pasted into the script before the shell sees it; pass it through `env:` instead.
- **Pull requests from forks get no secrets.** On GitHub a `pull_request` run from a fork gets no
  secrets and a read-only token; never check out pull request code in a `pull_request_target`
  workflow, which runs with the base repository's rights. On GitLab, protected variables reach
  only protected branches and tags, and fork pipelines do not see the parent's variables.
- **One deploy at a time.** A `concurrency` group with `cancel-in-progress: false` (GitHub) or a
  `resource_group` (GitLab): the newest pending commit wins, and a running deploy is never cut off.
- **An environment with approval for production.** The deploy secrets are environment secrets,
  released to a job only after the environment's protection rules pass; add required reviewers
  where the person wants to approve each deploy. On GitLab, `when: manual` is the simple version.
- **`persist-credentials: false` on checkout,** so the token is not left in `.git/config`.
- **Lint the workflow:** `actionlint` for syntax and shell, `zizmor` for the posture above.

## Database migrations

Run them as their own step, before the new version takes traffic, from the new image: `deploy.sh`
runs the command you put in `<MIGRATE>` with `docker compose run --rm`, in place of the image's
entrypoint and without a shell (so name a program the image has, such as `/server migrate`), and
stops the deploy if it fails; on Kubernetes, the pipeline template runs the migration Job named
in `MIGRATION_JOB` and waits for it before the apply ([kubernetes.md](kubernetes.md)). Take a backup
right before ([backups.md](backups.md)), since a migration is the one step a rollback does not undo.
Rolling back the image is safe only when the old code still works with the new schema, so write
migrations that add (a new column, a new table) and remove things in a later release, after no
running version uses them. A migration that drops or rewrites data needs the person's yes, with the
backup named, because the way back is a restore, with the data written since then lost.

## GitLab CI

The same shape, in [gitlab-deploy-compose-ssh.yml](../templates/ci/gitlab-deploy-compose-ssh.yml):
build with Docker-in-Docker, push to the project's registry as `$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA`
(logging in with `--password-stdin`), and deploy with the same `deploy.sh` on the server. What
differs:

- Store the key and the known-hosts line as **File** variables, Protected, scoped to the
  `production` environment: a File variable holds the path to a temporary file, which suits a
  multi-line key that GitLab's masking (one line, no spaces) cannot hide.
- `resource_group: production` does what `concurrency` does on GitHub.
- `environment: production` records each deploy, and `when: manual` makes a person press Run.
- Quote any script line that contains a colon followed by a space: unquoted,
  `- echo "Live version: x"` is read as a YAML mapping and the file is rejected.
- Check the file with `check-jsonschema --builtin-schema vendor.gitlab-ci .gitlab-ci.yml`, or in
  the project's pipeline editor, which also resolves includes.

## Traps

- **Deploying `:latest`.** Nothing changes on a cluster (same spec, no rollout), a server may keep
  its cached copy, and rollback has nothing to point at. Tag with the commit.
- **Re-deploying the same tag on Kubernetes** is a no-op: the same spec makes no new revision. If
  the outside check then fails, a plain `rollout undo` goes back one revision further than you
  meant; the template compares the revision before and after, and undoes only its own.
- **The CI key with a shell.** Any workflow change, compromised action or leaked log line becomes
  root on the server through the docker group. Forced command, proved as above.
- **A decrypted secret left in the workspace.** A `sops decrypt` to a file, or an env file copied
  onto the runner, can leave in an artifact, a cache or a `set -x` log. Decrypting in the pipeline
  is fine when the age key is a secret of the protected deploy environment and the output is piped
  to where it is used, `sops decrypt ... | kubectl apply -f -` (the Role then needs `secrets`; see
  [secrets.md](secrets.md)). Otherwise keep app secrets on the server or in the cluster.
- **No readiness probe or healthcheck.** The gate passes as soon as the process starts, so a
  version that crashes on its first request is declared live.
- **An image name with capitals.** Docker refuses it ("repository name must be lowercase"), and
  `${{ github.repository }}` keeps the owner's capitals; write the image name out in lowercase.
- **Old images filling the disk.** Every deploy leaves an image on the server. Remove old ones on a
  schedule, keeping the last few tags so a rollback does not need the registry.

## Done means

- The first deploy was done by hand and worked; the pipeline then deployed a commit on its own.
- The deploy key was shown to run `status` and to be refused for `id`, a chained command, a
  forward and `scp`; the host key in CI matches the fingerprint read on the server.
- A deliberately broken version was deployed once, and the pipeline rolled back and failed red.
- The run summary names the live version, and the hand-over says how to deploy an earlier tag.
- `actionlint` (and `zizmor`, where available) pass on the workflow.

Checked against: actionlint 1.7.12 and zizmor 1.32.0 (official images, no findings in the
pedantic persona), OpenSSH 10.0p2 server and client on debian:13 containers with Docker 26.1.5
and Compose 2.26.1, registry:3, kind 0.33.0 with Kubernetes 1.37.0, kubectl 1.37.2 and
kustomize 5.8.3, check-jsonschema 0.39.0 and shellcheck 0.11.0, 2026-11-12.
