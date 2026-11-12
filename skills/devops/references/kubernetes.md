# Running an app on a Kubernetes cluster

Read this when an app with a container image goes onto a managed Kubernetes cluster: which
cluster you are talking to, the manifests and why they look the way they do, traffic and
certificates, configuration and secrets, volumes, autoscaling, rollouts and Helm. When something
on a cluster is already broken, read [kubernetes-debugging.md](kubernetes-debugging.md). Whether
a cluster is the right home at all, and how to move an app onto one, is in
[scaling-up.md](scaling-up.md) and [choosing.md](choosing.md).

## Say which cluster you are on before anything else

The classic way to change production by accident is a kubectl command that ran against the
context left over from yesterday. Before the first command that changes anything, look and say it
out loud to the person:

```
kubectl config get-contexts
kubectl --context <CONTEXT> config view --minify -o jsonpath='{.clusters[0].cluster.server}'
kubectl --context <CONTEXT> get nodes
kubectl --context <CONTEXT> get namespaces
```

"I am on context `prod-eu`, API server at `https://k8s.example.com`, three nodes, deploying into
namespace `web`." Put it in the plan you show before the first apply, by the context's name,
since a kubeconfig the person hands over can hold more than one. Then name the context on every
command (`kubectl --context`, `helm --kube-context`) instead of `kubectl config use-context`,
which changes the default for every other terminal, script and tool on the machine. A kubeconfig
the provider hands over goes in its own file, used with `KUBECONFIG=/path/to/file` for this job;
merging it into `~/.kube/config` is how a test cluster and a production one end up one typo
apart. If namespaces full of other workloads show up, it is shared or production: changes there
need the person's yes, step by step. `kubectl auth can-i create deployments -n web` tells you
whether the credentials can do the job before you are halfway through it.

## Learn what the cluster already provides

Managed clusters differ in what they ship. These answers decide which templates you use:

```
kubectl get storageclass            # the one marked (default) is what a PVC gets
kubectl get gatewayclass            # a Gateway API implementation is installed
kubectl get ingressclass            # an ingress controller is installed
kubectl top nodes                   # a metrics API exists, so autoscaling can work
kubectl get crds | grep cert-manager
```

`error: the server doesn't have a resource type "gatewayclass"` means the Gateway API CRDs are
not installed; `No resources found` means the CRDs are there but no implementation is. `kubectl
top` answering `error: Metrics API not available` means the autoscaler will not work until
metrics-server (or the provider's equivalent) is installed.

## The manifests, and the order to apply them

Start from [templates/kubernetes/](../templates/kubernetes/) even for one quick "deploy this
and give me a URL": a manifest written from memory is where probes, limits and the non-root
security context go missing (in a trial the pod ran as root, and nothing checked the file). The
set: namespace, Deployment, Service, a Gateway with HTTPRoutes (or an Ingress), a cert-manager
Issuer, autoscaler, disruption budget, NetworkPolicy, and a `kustomization.yaml` applying them
as one; each lists its placeholders at the top. Keep the Deployment and Service, and drop what
does not fit, from the kustomization too. No Gateway or ingress controller: a `type:
LoadBalancer` Service (billed, so ask) in place of Gateway and Issuer. One pod with a volume:
`replicas: 1`, `Recreate`, no autoscaler or budget (Volumes, below). Check, then apply:

```
kubectl kustomize . > /tmp/<APP>.yaml                      # read what will be sent
python3 scripts/check_config.py --allow-docker /tmp/<APP>.yaml   # kubeconform (downloads schemas)
kubectl --context <CONTEXT> apply -f namespace.yaml
kubectl --context <CONTEXT> -n <APP> create secret generic <APP>-secrets --from-env-file=<FILE>
kubectl --context <CONTEXT> apply -k . --dry-run=server    # the cluster validates it
kubectl --context <CONTEXT> diff -k .                      # what changes against live state
kubectl --context <CONTEXT> apply -k .
kubectl --context <CONTEXT> -n <APP> rollout status deploy/<APP> --timeout=5m
```

The server-side dry run checks against the real cluster, its CRDs and its admission rules, which
a local check cannot. Plain manifests and Kustomize suit your own app: one set of files, readable
by anyone, with overlays if staging and production differ. A Helm chart for your own single app
is templating you maintain for no gain, until you ship it to other people.

## The Deployment: probes, resources, security

**Probes** decide when a pod gets traffic and when it is restarted, so each has to mean
something. Readiness answers "can this pod serve right now": it fails while a dependency the app
needs is unreachable, and a failing pod is only taken out of the Service, not restarted.
Liveness answers "is the process stuck": it checks nothing outside the process, because a
liveness probe that tests the database restarts every pod at once when the database blinks, and
turns a short outage into a long one. A startup probe holds the other two back while a slow app
boots. A path that returns 200 whatever happens (a static `/`) proves nothing; if the app has no
health endpoint, adding one is part of the job.

**Requests and limits** come from what the app uses, not from a guess. Run it under ordinary load
and read `kubectl top pods -n <APP>`. Set the CPU and memory requests near the ordinary use: the
scheduler places pods by requests, the autoscaler counts against them, and a node autoscaler adds
nodes only when requests do not fit. Requests set far too high leave pods Pending and nodes half
empty; far too low and the node is overcommitted and starts evicting. Set a memory limit above
the peak you saw, because past it the kernel kills the container (OOMKilled). Leaving out a CPU
limit is a deliberate choice: CPU over the request is only throttled, and a limit throttles the
app even on an idle node. Runtimes with their own heap (the JVM, Node.js) must size it inside
the memory limit.

**The security context** in the template passes the `restricted` Pod Security profile, which
the namespace enforces: not root, no privilege escalation, all capabilities dropped, the default
seccomp profile, a read-only root filesystem with an `emptyDir` on `/tmp`. Keep it also for an
image that runs as root by default, and try it before giving it up. Two things bite. An
image whose Dockerfile says `USER app` (a name) fails with `container has runAsNonRoot and image
has non-numeric user (app), cannot verify user is non-root`, so set `runAsUser` to the numeric id
(`docker run --rm --entrypoint id <IMAGE>` shows it). An app that writes somewhere other than
`/tmp` needs that path mounted too, or it fails with a read-only filesystem error. Drop a
setting only after you have seen it fail, and say which one in the hand-over.

Use a tag that changes with every release (the git commit is a good one) or a digest, never
`latest`: with `latest` two nodes can run different builds, and a rollback has nothing to go
back to. Set the tag in `kustomization.yaml` (`kustomize edit set image <IMAGE>:<TAG>` writes its
`images:` field) and apply, so the files say what runs; a pipeline does the same with each
commit's SHA ([ci-cd.md](ci-cd.md)).

**A private registry** needs a pull secret in the app's namespace (secrets do not cross
namespaces). Use a read-only token made for pulling, not a person's password:

```
kubectl --context <CONTEXT> -n <APP> create secret docker-registry <APP>-registry \
  --docker-server=registry.example.com --docker-username=<USER> --docker-password=<TOKEN>
```

Then uncomment `imagePullSecrets` in the Deployment. If every pod in the namespace pulls from
that registry, attaching the secret to the namespace's `default` service account does the same.

## Configuration and secrets

Settings that are not secret go in the `configMapGenerator` in `kustomization.yaml`. The
generated name carries a hash of the content, so changing a value rolls the pods. Secrets go in a
Secret created from a file kept outside the repository, as above.

A Secret is base64, which is an encoding, not encryption: anyone who can read Secrets in the
namespace reads every value with `kubectl get secret -o yaml`. Whether it is encrypted where the
cluster stores it depends on the provider; check their documentation instead of assuming. So keep
Secret manifests with values out of git, give few people read access to Secrets, and check a
Secret with `kubectl describe secret <APP>-secrets`, which shows key names and sizes, not values.
To keep secrets in git, encrypt them first (Sealed Secrets, SOPS) or sync them from a secret
manager (External Secrets Operator). A changed Secret does not reach running pods that read it
as environment variables: run `kubectl rollout restart deploy/<APP>`, which replaces pods one by
one behind the readiness probe.

## Getting traffic in: Gateway API or Ingress

The state as checked on 2026-11-11, worth checking again when you read this:

- The community **ingress-nginx** controller was retired in March 2026; its repository has been
  archived (read-only) since 2026-03-24. Existing installs keep running, but get no releases, bug
  fixes or security patches. The Kubernetes Steering Committee quoted research putting it in
  about half of cloud native environments, so expect to find it. It is a different project from
  the NGINX Ingress Controller made by F5/NGINX, which is maintained separately.
- The **Ingress API** is stable and is not being removed, but it is frozen: nothing new is added.
  The Kubernetes documentation recommends the **Gateway API** instead. Its latest release was
  v1.7.0 (2026-10-29), and the conformance list at gateway-api.sigs.k8s.io/implementations
  includes Envoy Gateway, Istio, Cilium, NGINX Gateway Fabric, Traefik, Kong and the major
  clouds' own gateways, among others.
- `ingress2gateway` (kubernetes-sigs) converts existing Ingress objects and some controller
  annotations; it says itself that widely used annotations may not translate. Read its output.

So: on a new setup, use the Gateway API with whatever implementation the provider ships, or
install one. Use `ingress.yaml` when the cluster already has a maintained ingress controller and
the person would rather not add anything. If you find ingress-nginx, tell the person it no longer
receives security fixes and propose the move as its own planned change.

Each Gateway usually gets its own load balancer from the cloud, which is billed. One app: a
Gateway in its namespace, as in the template. Several apps: one shared Gateway in its own
namespace with `allowedRoutes` opened to the app namespaces, and each app brings only its
HTTPRoutes. After applying, check both sides:

```
kubectl --context <CONTEXT> -n <APP> get gateway        # PROGRAMMED True, an ADDRESS
kubectl --context <CONTEXT> -n <APP> describe httproute <APP>   # Accepted, ResolvedRefs
```

The route must show `Accepted` and `ResolvedRefs` true. Point the DNS name at the Gateway's
address before you expect a certificate, because the HTTP-01 check comes in through it on port 80.

**Certificates** come from cert-manager. Its Gateway API support is off by default: install it
with Helm and `--set crds.enabled=true --set config.gatewayAPI.enabled=true`, after the Gateway
API CRDs exist; if the CRDs came later, restart it (`kubectl -n cert-manager rollout restart
deploy/cert-manager`), since it looks for them only at start. The annotation on the Gateway
makes cert-manager create a Certificate for each HTTPS listener with a hostname. Start with the
staging server in `issuer.yaml`: mistakes against production use up rate limits for days. Then:

```
kubectl --context <CONTEXT> -n <APP> get certificate    # READY True
```

## Keep other workloads away from the app

Any pod in a cluster can open a connection to any other pod, in any namespace, until a
NetworkPolicy says otherwise, so another team's app, or one that was broken into, reaches the
app's pods and anything they expose. [templates/kubernetes/networkpolicy.yaml](../templates/kubernetes/networkpolicy.yaml),
in the kustomization, lets in only the app's own namespace and the gateway's. A network plugin
has to enforce it (kind's kindnet did); check from another namespace, for example
`kubectl --context <CONTEXT> -n default run probe --rm -i --restart=Never --image=busybox --
wget -T 4 -qO- http://<APP>.<APP>.svc/healthz`, which times out once the policy is in, while the
site still answers through the gateway.

## Database migrations, as a Job before the rollout

Run them once, from the new release's image, before its pods take traffic:
[templates/kubernetes/migrate-job.yaml](../templates/kubernetes/migrate-job.yaml), kept out of
the kustomization, with a writable `/tmp` because its root filesystem is read-only. Take a backup
first ([backups.md](backups.md)). The Kubernetes pipeline template runs it when `MIGRATION_JOB`
names the file: it gives the Job the release's tag and name with `kustomize edit set image` and
`set namesuffix`, applies it, waits, prints its log, and stops before the apply when the Job did
not complete, printing the Job's and the pod's events. By hand, run that step's commands.

Wait on the Job's `Complete` and `Failed` conditions, with a deadline of your own as well. A Job
whose pod is never created (a ResourceQuota, an admission webhook) is marked `Failed` with reason
`DeadlineExceeded` at `activeDeadlineSeconds` while `.status.failed` stays empty, so a wait on the
counters never ends; and `kubectl wait --for=condition=Complete` sits out its whole timeout on a
failed Job. A failed Job keeps its name for a day: to run the same release's migration again,
delete it first (a person's step; the pipeline's Role cannot). The Role needs `jobs`, and `watch`
on pods to read the log of a pod that never ran ([ci-cd.md](ci-cd.md)).

## Volumes, and the rolling update that cannot finish

A PersistentVolumeClaim gets a disk from the default StorageClass. Most cloud disks are
ReadWriteOnce, which means one node at a time, not one pod. During a rolling update the new pod
can land on another node, cannot attach the disk the old pod holds, and waits with a
`Multi-Attach error` event while the old pod waits for it to become ready: the rollout never
finishes (not reproduced here, since a local test cluster has no attachable disks). With
`ReadWriteOncePod` it hangs even on the same node (reproduced: the new pod stays Pending with
`PersistentVolumeClaim with ReadWriteOncePod access mode already in-use by another pod`). For a
Deployment with such a volume use `strategy: type: Recreate` (reproduced: the stuck rollout
finished once switched) and accept a short gap at each deploy, or keep the state out of the pod:
uploads in object storage, data in a database. A volume like this also rules out more than one
replica and the autoscaler.

Most StorageClasses have `reclaimPolicy: Delete`: deleting the claim, or the namespace that
holds it, deletes the disk and its data. Check with `kubectl get pv`, set `Retain` on a volume
that matters, and have a backup before any delete; a namespace delete needs the person's yes.

## Autoscaling and disruption budgets

The autoscaler in `hpa.yaml` needs two things: a metrics API (`kubectl top pods` answers) and a
CPU request on every container, because the target is a percentage of the request. Without the
request it shows `cpu: <unknown>/70%` and the event `missing request for cpu`. The Deployment
leaves out `replicas` on purpose: a number there is applied again on every deploy, and the pod
count drops to it until the autoscaler notices (reproduced: 3, then 2 after the apply, then 3).
When you remove `replicas` from a manifest that was applied with one, the first client-side apply
drops the Deployment to 1 replica until the autoscaler restores it (also reproduced): make
that one apply at a quiet time, or have the person remove `replicas` first with `kubectl apply
edit-last-applied deploy/<APP>`, which opens an editor. Set `<MAX_REPLICAS>` from what the
database can take: each pod opens its own pool of connections. More pods need nodes to run on:
that is the provider's node autoscaler, which adds a node when pods are Pending for lack of
room, in minutes, not seconds.

The PodDisruptionBudget keeps a node drain (upgrades, the node autoscaler shrinking the pool)
from removing more than one replica at a time. It only works if the replacement can be scheduled
somewhere: on a full cluster the drain stops with `Cannot evict pod as it would violate the
pod's disruption budget` and the node upgrade waits (reproduced). One replica with a budget that
allows zero blocks every drain for good.

## Rollouts, and what done means

`kubectl rollout status deploy/<APP> --timeout=5m` waits for the new pods and exits non-zero if
they do not become ready. With `maxUnavailable: 0` and a readiness probe that means something, a
broken version never takes traffic: the new pod stays `0/1` and the old ones keep serving.
`kubectl rollout undo deploy/<APP>` puts the previous version back fast, and on an object made
with `kubectl apply` warns that it "will not update the kubectl.kubernetes.io/last-applied-configuration
annotation": follow it by reverting the change in git and
applying again, so the next apply does not bring the broken version back. On production, an undo
is a change too; say what you are doing.

Done means all of these, checked, not assumed: `rollout status` succeeded; `kubectl get pods`
shows every pod Ready on the new image; the Gateway is programmed and the Certificate is Ready;
and the app answers from outside on its real name with a valid certificate, checked as in
[proving-it-works.md](proving-it-works.md). A green rollout with a 503 at the edge is not done.

## Helm for software other people wrote

For third-party software (cert-manager, a gateway, monitoring), Helm is the normal way. Keep a
values file in git, pin the chart version, and look before you change anything:

```
helm --kube-context <CONTEXT> get values cert-manager -n cert-manager -o yaml > values.yaml
helm template cert-manager oci://quay.io/jetstack/charts/cert-manager --version <VERSION> \
  -n cert-manager -f values.yaml | kubectl --context <CONTEXT> diff -n cert-manager -f -
helm --kube-context <CONTEXT> upgrade --install cert-manager \
  oci://quay.io/jetstack/charts/cert-manager --version <VERSION> -n cert-manager \
  --create-namespace -f values.yaml --rollback-on-failure --timeout 10m
```

Helm 4 renamed `--atomic` to `--rollback-on-failure`; `--atomic` still works and prints a
deprecation warning. On Helm 3 use `--atomic`. Check with `helm version`. The `helm-diff`
plugin gives a nicer diff if it is already installed. Helm installs CRDs from a chart's `crds/`
folder but never upgrades them, so read the release notes of charts that ship CRDs for the
step they ask you to run by hand.

## When the database stays outside the cluster

For one person or a small team, put the database outside the cluster: a managed database, or a
database server of its own with backups (see [databases.md](databases.md)). Inside a cluster a database is a
pod with a ReadWriteOnce volume: every node upgrade moves it, which is downtime, and a deleted
namespace takes the data with it. It is reasonable in the cluster with an operator built for it
(for Postgres, CloudNativePG is one) and someone who owns its backups to object storage and has
done a restore. Either way, the pods' connections add up: replicas times pool size has to stay
under the database's connection limit.

## Traps

- **The wrong context.** A delete or an apply that went to production. Name the context on
  every command, read it back to the person before any change.
- **`kubectl edit` or `kubectl set image` left on a live object.** The cluster drifts from git,
  and the next apply silently undoes the fix. Either is fine for a quick fix by hand that cannot
  wait; then write the same change into the files and commit it, so git and the cluster agree.
- **One LoadBalancer per app.** Each Gateway or `type: LoadBalancer` Service is usually a billed
  load balancer; share one Gateway across apps.
- **A Secret changed, nothing happened.** Pods read environment variables at start; restart the
  rollout.
- **Memory limit set from a quiet hour.** The app is OOMKilled at the first busy hour; size it from
  a peak, then watch `kubectl top pods` after launch.

Checked against: kind v0.33.0 (kindest/node v1.37.0, kindnet enforcing the NetworkPolicy; the
migration Job's wait loop on a passing and a failing Job; the undo warning), kubectl v1.36.2, Helm v4.2.2, Envoy
Gateway v1.9.3 (Gateway API v1.6.1 CRDs), cert-manager v1.21.3, metrics-server 0.9.0,
kubeconform v0.8.0, kustomize v5.8.3, podinfo 6.17.0 as the sample app, 2026-11-12.
