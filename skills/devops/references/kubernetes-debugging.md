# Debugging an app on Kubernetes

Read this when something on a cluster is broken: a pod that will not start or keeps restarting,
a Service that sends traffic nowhere, a 5xx at the gateway, a certificate that never arrives, a
volume that will not attach, a node in trouble. It gives the path from the symptom to the cause,
with what the output really looks like. Setting an app up properly is in
[kubernetes.md](kubernetes.md); start there for the context check, which applies here first.

## Look first, change one thing, look again

Everything in the next sections up to "Commands that disrupt" only reads. Run them, name the
cause, say it to the person, and only then change one thing and look again. Three commands
cover most first looks:

```
kubectl --context <CONTEXT> -n <NS> get pods -o wide
kubectl --context <CONTEXT> -n <NS> describe pod <POD>          # the Events at the bottom
kubectl --context <CONTEXT> -n <NS> get events --sort-by=.lastTimestamp
```

Events are kept for about an hour by default, so on an older problem they may be gone and the
pod's `status` (`kubectl get pod <POD> -o yaml`) is what is left. The STATUS column is a
snapshot: a pod that is OOMKilled over and over shows `OOMKilled`, `CrashLoopBackOff` and even
`Running` within a few seconds of each other. Read the container's `lastState` for the reason.

Before a restart or a delete, save what would be lost: `kubectl logs` of the failing container,
the `describe` output. A deleted pod takes its logs with it.

## Pending

The scheduler found no node for the pod. `describe pod` says why:

```
Warning  FailedScheduling  default-scheduler  0/2 nodes are available: 1 Insufficient cpu,
1 node(s) had untolerated taint(s). preemption: 0/2 nodes are available: 2 Preemption is not
helpful for scheduling.
```

- `Insufficient cpu` or `memory`: the requests do not fit on any node. Compare the pod's
  requests with `kubectl describe node <NODE>` under "Allocated resources". Either the request is
  far above what the app uses (measure with `kubectl top pods` and lower it) or the cluster is
  full and the node autoscaler is at its maximum or absent.
- `untolerated taint(s)`: those nodes are reserved (the control plane, a GPU pool). Usually the
  other nodes are the problem, not the taint.
- a message about unbound PersistentVolumeClaims, a volume node affinity conflict or a
  ReadWriteOncePod claim in use: look at `kubectl get pvc`; see "A volume that will not attach".

During a rollout a Pending new pod leaves the old one serving, and `rollout status` keeps saying
`1 old replicas are pending termination...`. That is the design working, not a second problem.

## ImagePullBackOff and ErrImagePull

The node could not fetch the image. The reason is in the `Failed` event:

```
Failed to pull image "ghcr.io/example/app:9.9.9": ... failed to resolve reference
"ghcr.io/example/app:9.9.9": ... not found
```

- `not found`: the tag was never pushed or has a typo. Check the registry, or `docker manifest
  inspect <IMAGE>` from a machine logged in to it.
- `429 Too Many Requests` from `registry-1.docker.io`: Docker Hub's limit for anonymous pulls.
  This happened during the checks for this file. Pull with an account (a pull secret), or copy
  the image to the registry the app's own images live in.
- `unauthorized`, `403` or `denied`: the pull secret is missing, in another namespace, not
  listed in `imagePullSecrets`, or its token expired.
- `no match for platform in manifest`: an image built for one CPU architecture (arm64 from a
  laptop) on nodes of another (not reproduced here). Build for the nodes' architecture.

The kubelet keeps retrying with growing pauses; once the image exists, the pod starts on its
own within a few minutes.

## CrashLoopBackOff, and containers that never start

The container starts and exits, and the kubelet waits longer between each restart. The app's
last words are in its log, and the exit code is in `describe`:

```
kubectl --context <CONTEXT> -n <NS> logs <POD>
kubectl --context <CONTEXT> -n <NS> logs <POD> --previous
kubectl --context <CONTEXT> -n <NS> describe pod <POD>     # State, Last State, Exit Code
```

While the container waits for its next restart, plain `logs` shows the run that just died;
`--previous` asks for the one before and can answer `unable to retrieve container logs` when that
one is already cleaned up. Try both. Reading the exit code: 1 or another small number is the app
giving up (often missing configuration: `config: DATABASE_URL is not set`); 137 is a kill
(SIGKILL), usually the memory limit, see the next section; 139 is a segfault; 143 is a SIGTERM
the app did not handle.

A failing liveness probe looks similar but the events say so: `Liveness probe failed: HTTP probe
failed with statuscode: 404`, then `Container app failed liveness probe, will be restarted`. The
exit code is then whatever the app returns on SIGTERM; a well-behaved app shows `Completed` with
code 0, which is easy to misread as a clean exit. Fix the probe path or give the app a startup
probe, rather than loosening the liveness probe until it means nothing.

`CreateContainerConfigError` means the container was never created. The event names the cause:
`secret "app-secrets" not found` (create it, or fix the name), or `container has runAsNonRoot and
image has non-numeric user (app), cannot verify user is non-root` (set `runAsUser` to the
numeric id). A namespace that enforces Pod Security refuses the pod before it exists: the
ReplicaSet shows `FailedCreate ... violates PodSecurity "restricted:latest"` followed by the list
of missing settings, and `kubectl get pods` shows nothing at all.

## OOMKilled

The container used more memory than its limit and the kernel killed it:

```
Last State:     Terminated
  Reason:       OOMKilled
  Exit Code:    137
```

Look at real use with `kubectl top pod <POD> --containers` while it runs. If use climbs to the
limit under ordinary load, the limit is too low for this app: raise it to the measured peak with
headroom, and raise the request with it so the scheduler places the pod honestly. If use climbs
without end, it is a leak, and a higher limit only spaces the crashes out. Runtimes with their
own heap (JVM, Node.js) need the heap sized below the limit. A pod evicted by the node rather
than killed by its own limit shows `Evicted` and `The node was low on resource: memory`; that is
the node's problem, see the last section (not reproduced here).

## Running but not Ready

`READY 0/1` with status Running: the readiness probe fails, so the pod gets no traffic.

```
Warning  Unhealthy  kubelet  Readiness probe failed: HTTP probe failed with statuscode: 404
```

Ask the endpoint yourself to see what the probe sees:

```
kubectl --context <CONTEXT> -n <NS> port-forward pod/<POD> 18080:<PORT>
curl -i http://127.0.0.1:18080/<READY_PATH>        # in another terminal
```

A 404 is a wrong path in the probe; a 503 from the app's own ready check names the dependency it
cannot reach (read the app's log); a refused connection is a wrong port, or an app listening on
127.0.0.1 inside the container instead of all addresses. With `maxUnavailable: 0` the rollout
stops here and the old pods keep serving; `kubectl rollout undo` is the quick way back while you
fix it, and needs the person's yes on production.

## A Service with no endpoints

The gateway answers 503 and the pods look fine. Compare what the Service selects with the pods'
labels, and look at its endpoints:

```
kubectl --context <CONTEXT> -n <NS> get svc <SVC> -o jsonpath='{.spec.selector}'
kubectl --context <CONTEXT> -n <NS> get pods --show-labels
kubectl --context <CONTEXT> -n <NS> get endpointslices -l kubernetes.io/service-name=<SVC>
```

No pod matching the selector shows as `ENDPOINTS <unset>`. The ENDPOINTS column also lists pods
that are not ready, so for the real picture ask for the condition:

```
kubectl --context <CONTEXT> -n <NS> get endpointslices -l kubernetes.io/service-name=<SVC> \
  -o jsonpath='{range .items[*].endpoints[*]}{.addresses[0]} ready={.conditions.ready}{"\n"}{end}'
```

`kubectl get endpoints` still works but warns that v1 Endpoints is deprecated since v1.33. When
endpoints exist and traffic still fails, check the Service's `targetPort` against the port the
container listens on.

## 5xx at the gateway or ingress

What each answer meant on Envoy Gateway, reproduced with curl from outside:

- `503` with an empty body: the backend Service has no ready endpoints. See the two sections
  above.
- `503` with `upstream connect error or disconnect/reset before headers. reset reason: remote
  connection failure`: endpoints exist but nothing answers on the port, a wrong `targetPort` or a
  crashed app. Proxies built on nginx usually answer `502 Bad Gateway` to the same fault (not
  reproduced here).
- `504` with `upstream request timeout`: the route's timeout is shorter than the request. Either
  the app is slow (find out why) or the route needs a longer `timeouts.request`.
- `500`: the route points at a Service that does not exist. The route's status says so:
  `ResolvedRefs=False BackendNotFound: ... service web/web-api not found`.
- `404` on plain HTTP, or a TLS handshake failure on HTTPS (this machine's curl printed
  `curl: (35) ... SSL_ERROR_SYSCALL`): no listener or route matches the hostname, or the
  certificate Secret the listener names is missing.

The route's and the Gateway's status conditions are the first place to look, then the
implementation's own controller log (`kubectl -n <CONTROLLER_NS> logs deploy/<CONTROLLER>`):

```
kubectl --context <CONTEXT> -n <NS> describe httproute <ROUTE>
kubectl --context <CONTEXT> -n <NS> describe gateway <GATEWAY>
```

## A certificate that is not issued

cert-manager works in a chain: a Certificate creates a CertificateRequest, which for ACME creates
an Order, which creates one Challenge per name. Find the link that is stuck:

```
kubectl --context <CONTEXT> -n <NS> get certificate,certificaterequest,order,challenge
kubectl --context <CONTEXT> -n <NS> describe certificaterequest <NAME>
```

A Certificate with `READY False` and `Issuing certificate as Secret does not exist` is only in
progress. The cause is further down: here, an annotation naming an issuer that does not exist
gave `Referenced "Issuer" not found: issuer.cert-manager.io "letsencrypt-prod" not found`. With a
real ACME issuer, `describe challenge` gives the certificate authority's answer; the usual causes
are a DNS name that does not point at the gateway yet, port 80 closed or redirected in a way that
swallows `/.well-known/acme-challenge/`, a CAA record that does not allow the authority, or the
authority's rate limits after many failed attempts (these were not reproduced, since they need a
public name). Fix the cause. A change to the Certificate's own spec, such as the corrected
issuer, starts a new attempt at once (seen here); otherwise cert-manager retries on its own,
with longer pauses after each failure.

## A volume that will not attach

```
kubectl --context <CONTEXT> -n <NS> get pvc,pv
kubectl --context <CONTEXT> -n <NS> describe pvc <PVC>
kubectl --context <CONTEXT> get volumeattachments
```

A claim that is `Pending` with `WaitForFirstConsumer` is normal until a pod uses it. A new pod
Pending with `PersistentVolumeClaim with ReadWriteOncePod access mode already in-use by another
pod`, or an event starting `Multi-Attach error for volume` (not reproduced here), means another
pod still holds a single-writer disk, most often the old pod of a rolling update. The fix is a
`Recreate` strategy (see [kubernetes.md](kubernetes.md)), not deleting the old pod by hand on
every deploy. After a node dies, its disk can stay attached to the dead node for several minutes
before the cluster lets go of it (not reproduced here).

## A node under pressure

```
kubectl --context <CONTEXT> get nodes
kubectl --context <CONTEXT> top nodes
kubectl --context <CONTEXT> describe node <NODE>       # Conditions, Allocated resources
```

Under "Conditions", `MemoryPressure`, `DiskPressure` and `PIDPressure` are `False` on a healthy
node, and `Ready` is `True`. When one turns `True`, the kubelet stops placing new pods there
and starts evicting, pods using more than they requested first (not reproduced here). Disk pressure
usually comes from container logs, unused images or `emptyDir` volumes without a `sizeLimit`.
On a managed cluster the lasting fix is capacity (a bigger node size, more nodes) or the
workload's own requests; a bad node is replaced, not repaired by hand.

## Commands that disrupt, and need the person's yes

Each of these changes what is running. Say what it will do and how to undo it, and wait for the
person's yes, except on a throwaway cluster that is yours:

- `kubectl delete pod`: the pod is replaced, and on one replica the app is down meanwhile; its
  logs are gone.
- `kubectl rollout restart` and `kubectl rollout undo`: every pod is replaced.
- `kubectl scale --replicas=0`: the app is off until scaled back.
- `kubectl cordon` and `kubectl drain`: the node stops taking pods, and drain evicts them.
- `kubectl delete pvc`, `kubectl delete namespace`: with the usual `Delete` reclaim policy, the
  disks and their data go too. Not reversible without a backup.
- `kubectl edit`, `patch`, `set`, `helm rollback`, `helm uninstall` on live objects: a change to
  production that git does not know about until you bring it back in.

## Traps

- **Restarting before reading.** A delete or a restart that "fixed" it took the evidence with it,
  and the cause comes back. Logs and `describe` first.
- **Trusting one look at STATUS.** It flips between states; the reason is in `lastState` and
  the events.
- **Loosening a probe to make the alarm stop.** A liveness probe that never fails hides the hang
  it was meant to catch.
- **A fix made live and never put in git.** The next deploy undoes it. Every change you make
  while debugging goes back into the manifests before you call it done.

## Done means

The symptom is gone when checked from outside the cluster, the cause is named in a sentence, the
fix is in the manifests in git and was applied from there, `rollout status` succeeded, and
`kubectl get events --field-selector type=Warning` shows nothing new for the app.

Checked against: kind v0.33.0 (kindest/node v1.37.0), kubectl v1.36.2, Envoy Gateway v1.9.3,
cert-manager v1.21.3, metrics-server 0.9.0, podinfo 6.17.0 and busybox 1.37 as the broken apps,
2026-11-11.
