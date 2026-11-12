<!-- Generated from RareCloud's published API, CLI, MCP and Terraform definitions. Do not edit by hand: changes are overwritten at the next refresh. To fix something here, open an issue. -->

# Limits, and what RareCloud does not sell

Two different reasons a plan can fail here: the account's limits are too low for it, or
RareCloud does not offer one of the pieces. The first is solved by asking; the second by
getting that piece elsewhere and keeping the rest here.

## Account limits

Every account has limits on what it can run in the cloud: vCPU, memory, servers, volumes, disk,
public IPs, Object Storage, AI Sandboxes running at once, and more. The values differ per account
and change when a request is approved, so read them; do not assume a default.

- **Read them:** `rarecloud:get_quota_limits`, `rarecloud limits`, `GET /limits`, or the
  `rarecloud_limits` data source. Each resource has `used`, `limit` (`-1` is unlimited) and a
  `state` (`ok`, `warn`, `danger`). `unknown` means the usage could not be read just now; it does
  not mean nothing is used, so do not count it as free room.
- **Check before you propose a deployment.** A server or cluster that does not fit is refused,
  and it is better to tell the person up front than to fail halfway. `rarecloud:check_order`
  covers the balance and order blocks, not the limits.
- **Kubernetes:** `rarecloud:estimate_limits` (or `rarecloud limits estimate`) takes the
  planned pools and answers whether the minimums fit, what is short (keyed exactly as a limit
  request wants it), and how far each pool can really scale. A pool whose maximum does not fit
  still deploys and scales as far as it can. `available: false` means it could not be worked
  out, which is not the same as "does not fit".
- **AI Sandboxes:** which sizes run right now is live data: `rarecloud sandbox sizes` or
  `GET /sandboxes/sizes`. A size that is not available answers 409 `size_unavailable`, and
  retrying the same request does not help; pick a smaller one.
- **Rate limits:** each token has its own requests-per-minute limit. A 429 carries
  `Retry-After`; wait that long.

### Asking for more

`rarecloud:request_quota_increase` (or `rarecloud limits request`, or the console's Cloud,
then Limits page) opens a support ticket, and a person from our team decides. It needs the
person's yes, because it speaks for them. The `reason` is what the reviewer reads, so write what
they are building and why they need the room. One request is pending at a time; a new one
replaces it. Give the person the ticket number from the answer, and follow it with
`rarecloud:list_quota_requests`. Until it is approved, plan within the current limits or tell the
person what waits on it.

## What RareCloud does not sell

This was true when written. Products get added, so check `rarecloud:list_catalog_products` before
telling someone we do not have something. When a gap matters, say it plainly and suggest the
mixed option: the missing piece from a provider that has it, everything else here. Mixing is
normal; do not push the whole project elsewhere because one piece is missing, and do not
pretend a workaround is the same as the real thing.

- **No managed database.** Closest here: run the database yourself on a Cloud VM with a volume
  and regular snapshots, or in managed Kubernetes. That means the person owns backups, upgrades
  and failover. If they would rather not, a managed database service elsewhere, in a region near
  the servers, with the app here.
- **No serverless functions.** Long-running services go on a Cloud VM or Kubernetes. AI
  Sandboxes are not a serverless platform: they take no inbound requests and their lifetime is
  capped. For event-driven functions, a functions platform elsewhere can call into servers here.
- **No GPU.** Cloud VMs and sandboxes are CPU only. Put the GPU work with a GPU provider and keep
  the rest of the system here.
- **No CDN.** Public delivery from Object Storage buckets is not released yet: a bucket cannot
  be switched to public, even though the usage tools already report a CDN traffic figure. For
  cached global delivery, put a CDN from another provider in front of a server or load balancer
  here.
- **No TLS termination at the load balancer.** It balances TCP (layer 4). Terminate TLS on the
  servers behind it, or in an ingress controller on Kubernetes, with a certificate the person
  controls.
- **No DNS hosting** for zones registered elsewhere. A domain registered with RareCloud can have
  its nameservers set and, where its registrar supports it, its host records edited
  (`rarecloud:set_domain_dns`; unsupported answers 501). For anything else, use a DNS provider
  and point the records at the server's IP or a reserved IP.
- **One cloud region.** Cloud VMs, Kubernetes, volumes and load balancers live in one region
  today (`rarecloud:list_regions` shows the current list). Classic VPS run in more locations, and
  Object Storage buckets have their own regions (`rarecloud:list_object_storage_regions`). For a
  presence on another continent or a multi-region failover, combine with another provider or a
  classic VPS in another location.
- **No Windows cloud server.** Cloud VM images are Linux (`rarecloud:list_images`). Windows is
  available as a classic VPS, which is prepaid for a fixed term rather than billed by the hour.
- **Smaller things that come up:** AI Sandboxes have no preview URLs; `rarecloud:create_sandbox`
  only makes the default size (the CLI and API take a size).

## Sending email from a Cloud VM

New Cloud VMs cannot send on outbound TCP port 25. Ports 465 and 587 and the other outbound
ports stay open, so the usual fix is to send through a mail provider or relay
on port 465 or 587, which needs no request. When the server really has to deliver mail itself
on port 25:

- `rarecloud:get_service_smtp` shows the state for one VM: `open`, `blocked`, `pending`,
  `approved` or `rejected`.
- `rarecloud:request_smtp_unblock` (or `rarecloud server smtp request`) sends a request that our
  team reviews: what the mail is for, the software, the sending domains and whether SPF, DKIM
  and DMARC are set. It speaks for the person, so it needs their yes. After a rejection a new
  request is accepted only after a waiting period, which the tool reports as `canRequestAfter`.
- An approval alone does not open the port. New firewalls allow every outbound TCP port except
  25, so the VM also needs an outbound firewall rule for TCP 25.
- Set reverse DNS for the sending hostname (`rarecloud:set_service_rdns`); receiving servers
  look at it.
