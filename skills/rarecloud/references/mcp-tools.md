<!-- Generated from RareCloud's published API, CLI, MCP and Terraform definitions. Do not edit by hand: changes are overwritten at the next refresh. To fix something here, open an issue. -->

# RareCloud MCP tools

All 224 tools of the RareCloud MCP server, by product area.
A tool marked "needs `confirm: true`" refuses and makes no API call until the call carries `confirm: true`; pass it only after the user has approved the action.
A tool marked "takes `idempotency_key`" runs at most once per key: reuse the key when you retry the same request.

## Catalog

- `rarecloud:list_catalog_products`: List orderable products from the RareCloud catalog.
- `rarecloud:list_catalog_listings`: List the deploy-wizard product cards for one category: the same tiles the console shows on the "create" screen, each with sku, display name, tier, pricing, specs, and available regions.
- `rarecloud:get_catalog_plan`: Get full details for a single catalog product including all plans (sizes), their specs (vCPU, RAM, disk, bandwidth), pricing for every supported billing cycle, and supported billing tracks.
- `rarecloud:get_product_details`: Get the live, order-ready detail for one product SKU: every billing cycle with its price, the plans (sizes) on offer, and the config options (e.g. the OS-template field) a purchase must fill in.
- `rarecloud:list_regions`: List available RareCloud datacenter regions.
- `rarecloud:list_images`: List available OS images (Ubuntu / Debian / Rocky) that can be installed on new servers.
- `rarecloud:list_prepurchase_os_templates`: List the OS templates selectable at purchase time for a legacy VPS / dedicated-server SKU: each with slug, display name, and version.

## Cloud VMs

- `rarecloud:list_services`: List all services in the authenticated account: VPS servers, cloud VMs, proxies, hosting, domains.
- `rarecloud:get_service`: Get full details for a single service by ID: status, network config, billing state, current-month usage.
- `rarecloud:check_order`: Check whether deploy_service would be accepted for this account right now, without creating or reserving anything.
- `rarecloud:deploy_service`: Deploy (order + provision) a new service. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:get_provisioning_state`: Setup state of a pending service: whether its order is paid, whether the VM exists yet, and whether provisioning looks stuck (paid but unprovisioned past the grace period).
- `rarecloud:start_service`: Power on a service (cloud VM or legacy VPS). (takes `idempotency_key`)
- `rarecloud:stop_service`: Power off a service (cloud VM or legacy VPS). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:reboot_service`: Reboot a service (cloud VM or legacy VPS). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:reinstall_service`: Reinstall (rebuild from scratch) a service; works on BOTH a cloud VM (UUID service_id) and a legacy VPS (numeric service_id). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:list_os_templates`: Operating systems a service can be reinstalled with: templates for a classic VPS, or the curated reinstall images for a cloud VM.
- `rarecloud:resize_service`: Resize a cloud VM service to a new flavor (target plan PUBLIC SKU, e.g. c-4vcpu-8gb, from list_catalog_products). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:reset_service_password`: Reset the root password on a RUNNING cloud VM (UUID service_id) live; the VM keeps running and keeps its data (this is NOT a reboot or rebuild). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:set_service_hostname`: Rename a service.
- `rarecloud:set_service_tags`: Replace the tags of a cloud VM with the given list: the whole set is replaced, so pass every tag the VM should keep, and [] removes them all.
- `rarecloud:get_service_metrics`: Get resource metrics (CPU / RAM / disk / bandwidth time series) for a single service.
- `rarecloud:destroy_service`: Permanently destroy a service and release its resources. (needs `confirm: true`)

## Snapshots

- `rarecloud:list_snapshots`: List every VM snapshot the account owns, across all cloud VMs (including snapshots whose VM was deleted).
- `rarecloud:list_service_snapshots`: List the snapshots of one cloud VM (up to 5 per VM).
- `rarecloud:get_snapshot`: Get one VM snapshot: use it to poll a new snapshot until state is ready.
- `rarecloud:create_snapshot`: Take a snapshot of a cloud VM's root disk. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:restore_snapshot`: Restore a cloud VM from one of its own snapshots: the undo for a change that went wrong. (needs `confirm: true`)
- `rarecloud:delete_snapshot`: Delete a VM snapshot. (needs `confirm: true`)

## Volumes

- `rarecloud:list_volumes`: List block storage volumes in the account: id, name, size, status, which VM it is attached to, region.
- `rarecloud:get_volume`: Get one block storage volume: id, name, size, status, region, and which VM it is attached to.
- `rarecloud:create_volume`: Create a new block storage volume, billed per GB monthly (not a catalog SKU). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:attach_volume`: Attach a block storage volume to a cloud VM.
- `rarecloud:detach_volume`: Detach a block storage volume from a cloud VM. (needs `confirm: true`)
- `rarecloud:delete_volume`: Delete a block storage volume. (needs `confirm: true`)

## Private networks

- `rarecloud:list_networks`: List private networks (VPCs): id, name, CIDR, status, attached VM count, whether it is the default.
- `rarecloud:get_network`: Get one private network (VPC): id, name, CIDR, status, whether it is the default, and its attached VMs.
- `rarecloud:create_network`: Create a new private network (VPC); VPCs carry no separate charge. (takes `idempotency_key`)
- `rarecloud:attach_network_vm`: Move a cloud VM into a private network (VPC), detaching it from its current VPC (the VM's public eth0 interface is untouched). (needs `confirm: true`)
- `rarecloud:delete_network`: Delete a private network (VPC). (needs `confirm: true`)

## Reserved IPs

- `rarecloud:list_reserved_ips`: List reserved (static) public IPs: id, address, status, which VM it is attached to.
- `rarecloud:reserve_ip`: Reserve a new static public IP (billed monthly until released). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:attach_reserved_ip`: Attach a reserved (static) public IP to one of your cloud VMs.
- `rarecloud:detach_reserved_ip`: Detach a reserved public IP from its VM. (needs `confirm: true`)
- `rarecloud:release_reserved_ip`: Release (permanently delete) a reserved public IP; billing for it stops. (needs `confirm: true`)

## Firewalls

- `rarecloud:list_firewalls`: List cloud firewalls (security groups): id, name, isDefault (attached to every new VM), isPrivateNetwork, inboundCount, outboundCount, attachedServerIds.
- `rarecloud:get_firewall`: Get one firewall (security group) including isDefault, isPrivateNetwork, its full inbound/outbound rule set and which VMs it is attached to.
- `rarecloud:create_firewall`: Create a new cloud firewall (security group). (takes `idempotency_key`)
- `rarecloud:add_firewall_rule`: Add an inbound/outbound rule to a cloud firewall. (takes `idempotency_key`)
- `rarecloud:delete_firewall_rule`: Remove a rule from a cloud firewall. (needs `confirm: true`)
- `rarecloud:attach_firewall`: Attach a cloud firewall to every interface of a cloud VM, the public one included.
- `rarecloud:detach_firewall`: Detach a cloud firewall from every interface of a cloud VM. (needs `confirm: true`)
- `rarecloud:delete_firewall`: Delete a cloud firewall. (needs `confirm: true`)

## Load balancers

- `rarecloud:list_load_balancers`: List L4 load balancers: id, name, status, public IP, listener port, member count.
- `rarecloud:get_load_balancer`: Get one load balancer with its members (backend VMs and ports).
- `rarecloud:create_load_balancer`: Create a new L4 (TCP) load balancer: a VIP on your subnet, a listener + pool on port, the given VMs as members, and a public floating IP. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:list_load_balancer_members`: List the backend members of a load balancer: each member's address and its port in the pool.
- `rarecloud:add_load_balancer_member`: Add a VM as a member of a load balancer pool. (takes `idempotency_key`)
- `rarecloud:remove_load_balancer_member`: Remove a member from a load balancer pool. (needs `confirm: true`)
- `rarecloud:delete_load_balancer`: Delete a load balancer. (needs `confirm: true`)

## Reverse DNS and email

- `rarecloud:get_service_rdns`: Get the reverse DNS (PTR) record of a cloud VM's primary public IPv4 address: the IP and the hostname it resolves back to.
- `rarecloud:set_service_rdns`: Set the reverse DNS (PTR) record of a cloud VM's primary public IPv4 address, e.g. mail.example.com for a mail server. (needs `confirm: true`)
- `rarecloud:delete_service_rdns`: Remove the reverse DNS (PTR) record of a cloud VM's primary public IPv4 address. (needs `confirm: true`)
- `rarecloud:get_service_smtp`: Get the outbound email state of a cloud VM.
- `rarecloud:request_smtp_unblock`: Ask RareCloud to open outbound email on TCP port 25 for a cloud VM. (needs `confirm: true`)

## Kubernetes

- `rarecloud:list_kubernetes_versions`: List the managed Kubernetes versions currently offered, newest-supported first.
- `rarecloud:get_cluster_scale`: Get the current scale of a managed Kubernetes cluster: its worker node pools plus any add-ons (autoscaler bounds, HA control plane, etc.).
- `rarecloud:set_cluster_scale`: Set the autoscaling bounds (minimum/maximum worker count) of the FIRST node pool of a managed Kubernetes cluster. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:list_cluster_pools`: List the worker node pools of a managed Kubernetes cluster: each pool's name, machine type/flavor, node count, and autoscaling min/max.
- `rarecloud:add_cluster_pool`: Add a named worker node pool to a managed Kubernetes cluster. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:update_cluster_pool`: Edit an existing worker node pool of a managed Kubernetes cluster: any of its autoscaling bounds (minimum/maximum), machineType, or per-node volumeSizeGb (10-1000 GiB). (needs `confirm: true`)
- `rarecloud:rename_cluster_pool`: Rename a worker node pool of a managed Kubernetes cluster. (needs `confirm: true`)
- `rarecloud:delete_cluster_pool`: Remove a worker node pool from a managed Kubernetes cluster. (needs `confirm: true`)
- `rarecloud:enable_cluster_ha`: Enable the HIGH-AVAILABILITY control plane on a managed Kubernetes cluster (multi-zone API server / etcd). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:get_cluster_kubeconfig`: Fetch a SHORT-LIVED admin kubeconfig for a managed Kubernetes cluster: a freshly-minted cluster-admin credential that expires within hours and leaves NO standing credential behind.
- `rarecloud:list_cluster_kubeconfigs`: List the LONG-LIVED kubeconfig credentials issued for a managed Kubernetes cluster: metadata only (id, name, role admin|view, createdAt, expiresAt, revokedAt, lastDownloadedAt, status active|expired|revoking|revoked).
- `rarecloud:create_cluster_kubeconfig`: Create a LONG-LIVED, revocable kubeconfig credential (a per-credential ServiceAccount) for a managed Kubernetes cluster, for standing automation (CI, GitOps). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:download_cluster_kubeconfig`: Re-download a LONG-LIVED kubeconfig credential for a managed Kubernetes cluster by its credential id: a revocable, per-credential ServiceAccount kubeconfig for standing automation that must keep working (unlike the short-lived admin config from get_cluster_kubeconfig).
- `rarecloud:revoke_cluster_kubeconfig`: Revoke a LONG-LIVED kubeconfig credential of a managed Kubernetes cluster by its credential id; deletes the underlying ServiceAccount so the token stops working immediately. (needs `confirm: true`)

## Object storage

- `rarecloud:get_object_storage`: Get the account's Object Storage (S3-compatible) service: status, namespace handle (the prefix every bucket name carries), plan, the price card (base monthly fee, included GB, per-GB storage and egress, CDN fees), this month's accrued charge, and the bucket and key limits.
- `rarecloud:enable_object_storage`: Enable Object Storage (S3-compatible) on the account. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:disable_object_storage`: Disable Object Storage and remove the storage account. (needs `confirm: true`)
- `rarecloud:get_object_storage_usage`: Get the Object Storage account's daily usage series (active and deleted stored bytes, egress bytes, CDN bytes and requests) for the last N days.
- `rarecloud:list_object_storage_regions`: List the regions a bucket can be created in: id, label, S3 endpoint, country, and whether it is in the EU.
- `rarecloud:list_buckets`: List Object Storage buckets: id, full bucket name, region, status, versioning, whether it is public over the CDN, its S3 endpoint and URLs, and the last measured size and object count.
- `rarecloud:get_bucket`: Get one Object Storage bucket: full bucket name, region, status, versioning, public (CDN) state and public URL, S3 endpoint and bucket URL, and the last measured size and object count.
- `rarecloud:create_bucket`: Create an Object Storage bucket. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:update_bucket`: Change a bucket's versioning or public delivery. (needs `confirm: true`)
- `rarecloud:get_bucket_usage`: Get one bucket's daily usage series (active and deleted stored bytes, egress bytes, and CDN bytes and requests if it has ever been public) for the last N days.
- `rarecloud:delete_bucket`: Delete an Object Storage bucket. (needs `confirm: true`)
- `rarecloud:list_object_storage_keys`: List Object Storage S3 access keys: id, name, access key id, a four-character secret preview, scope (buckets + read or readwrite), status and revocation time.
- `rarecloud:create_object_storage_key`: Create an S3 access key for Object Storage. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:delete_object_storage_key`: Revoke an Object Storage S3 access key. (needs `confirm: true`)

## Container registry

- `rarecloud:get_registry`: Get the authenticated account's container registry: handle, hostname, tier, status (active, suspended: pushes blocked and pulls still work, closed), usage, quota, push and clusters.
- `rarecloud:suggest_registry_handle`: Suggest up to 3 free, valid container-registry handles derived from `base` (typically whatever the customer has typed so far).
- `rarecloud:enable_registry`: Enable the account's private container registry, or reopen/re-enable a previously closed one. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:list_registry_tiers`: List the container registry's billing tiers: for each tier, its included storage quota (decimal GB), burst ceiling (quota multiplied by the tier's burst multiplier; the free tier never bursts), monthly price in EUR/USD cents, overage price per GB-month above quota, and whether the tier is currently generally available (`available`; false while the registry is paused).
- `rarecloud:set_registry_tier`: Change the billing tier of the account's container registry. (needs `confirm: true`)
- `rarecloud:close_registry`: Close the account's container registry. (needs `confirm: true`)
- `rarecloud:list_registry_repositories`: List the repositories under the account's own registry handle: name, path, sizeBytes, lastPush, newestTag.
- `rarecloud:get_registry_repository`: Get one repository's full tag list.
- `rarecloud:list_registry_tag_vulnerabilities`: List paginated CVE findings (from the registry's vulnerability scan) for one tag of one repository: id, severity, title, affected packages.
- `rarecloud:delete_registry_tag`: Delete one tag from a repository in the account's container registry. (needs `confirm: true`)
- `rarecloud:delete_registry_manifest`: Delete one image by its manifest digest from a repository in the account's container registry, removing the manifest and EVERY tag pointing at it, at once and for good. (needs `confirm: true`)
- `rarecloud:delete_registry_repository`: Delete an entire repository from the account's container registry. (needs `confirm: true`)
- `rarecloud:list_registry_credentials`: List the account's container registry robot credentials (for `docker login` / pull / push), oldest first: id, name, scope, username (`<handle>+<name>`), expiresAt, createdAt, lastUsedAt, revokedAt.
- `rarecloud:create_registry_credential`: Create a robot credential for `docker login` / pull / push against the account's container registry. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:revoke_registry_credential`: Revoke a container registry robot credential immediately. (needs `confirm: true`)
- `rarecloud:list_registry_clusters`: List the Kubernetes clusters linked to the account's container registry: serviceId, clusterName, status (linking/active/rotating/unlinking/error), installedAt, syncerImage, syncerReady (probed about hourly; an "active" link can still report false), syncerCheckedAt, lastError, credentialName (the pull credential's name, e.g. k8s-<serviceId>, never the secret).
- `rarecloud:link_registry_cluster`: Link one of the account's OWN Kubernetes clusters to its container registry. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:rotate_registry_cluster_link`: Rotate a linked cluster's registry pull credential. (needs `confirm: true`)
- `rarecloud:unlink_registry_cluster`: Unlink a Kubernetes cluster from the account's container registry. (needs `confirm: true`)
- `rarecloud:create_registry_kubernetes_manifest`: Get a ready-to-apply pull-secret manifest for a Kubernetes cluster the account manages ITSELF (BYO: a kind/EKS/GKE/bare-metal cluster RareCloud does not run). (needs `confirm: true`)

## AI sandboxes

- `rarecloud:list_sandbox_templates`: List the templates a sandbox can be created from (python, node, base) with their size (vcpu, ramGb, diskGb), the image each runs, and the price per hour in EUR and USD (billed per second).
- `rarecloud:list_sandboxes`: List the AI Sandboxes this account owns: id, name, status, template, image, labels, envKeys (the NAMES of its environment variables; values are never returned), networkBlocked, run (null = interactive), createdAt, timeoutMs and expiresAt (when it stops and is deleted automatically).
- `rarecloud:get_sandbox`: Get one AI Sandbox: status (and statusReason while an image is pulling or failed to pull), template, image, name, labels, envKeys (names only, never values), networkBlocked, run, createdAt, timeoutMs and expiresAt.
- `rarecloud:create_sandbox`: Create an isolated AI Sandbox (a short-lived container for running code). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:run_sandbox_command`: Run a shell command inside an AI Sandbox (sh -c) and return { stdout, stderr, exitCode }.
- `rarecloud:run_sandbox_code`: Run a code snippet inside an AI Sandbox (python3 -c or node -e) and return { stdout, stderr, exitCode, results? }.
- `rarecloud:read_sandbox_file`: Read one file from a sandbox by absolute path, up to 25 MiB.
- `rarecloud:write_sandbox_file`: Create or overwrite one file inside an AI Sandbox (parent directories are created).
- `rarecloud:get_sandbox_logs`: Read the last lines of a sandbox program's output (stdout and stderr) as plain text, returned verbatim.
- `rarecloud:delete_sandbox`: Terminate and remove an AI Sandbox. (needs `confirm: true`)

## Limits and quotas

- `rarecloud:get_quota_limits`: Get the account's effective cloud quotas with live usage: one row per resource (cores, ram, instances, volumes, gigabytes, floatingip, ...) with used, limit (-1 = unlimited), state (ok | warn | danger | unknown) and ratio, plus registry and sandboxes figures (null when not in use).
- `rarecloud:estimate_limits`: Pre-flight a managed Kubernetes deployment against the account's quotas and live usage, without creating or reserving anything.
- `rarecloud:list_quota_requests`: List the account's quota-increase requests, newest first: requested ceilings, reason, and status (pending | approved | auto_approved | denied).
- `rarecloud:request_quota_increase`: Ask for a higher cloud quota. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:get_account_limits`: Get account counters: active services, API tokens (cap 20) and sub-users (cap 10).

## Classic VPS and hosting

- `rarecloud:list_upgrade_options`: Plans (and billing cycles with prices) a service could be upgraded/downgraded to, from its product group.
- `rarecloud:upgrade_service`: Create an upgrade order moving a service to a new product/plan. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:renew_service`: Ensure a renewal invoice exists for a service (renew the current term). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:get_service_autorenew`: Get whether a service auto-renews from account balance ({enabled}).
- `rarecloud:set_service_autorenew`: Toggle auto-renew (renew automatically from account balance) for a service.
- `rarecloud:cancel_service`: File a cancellation request for a service. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:set_service_password`: Set the root/administrator password of a legacy VPS service. (needs `confirm: true`)
- `rarecloud:list_ssh_keys`: List the SSH keys on a specific server (legacy VPS).
- `rarecloud:add_service_ssh_key`: Install an SSH public key on a service (per-server), distinct from add_service_ssh_key_to_library, which registers a key in the server's reinstall-time key library. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:list_service_ssh_key_library`: List the SSH keys registered in a legacy VPS's key library: each with id, name, publicKey, and a server-computed fingerprint.
- `rarecloud:add_service_ssh_key_to_library`: Register a new SSH key in a legacy VPS's key library: the set of keys selectable when reinstalling this server (see list_service_ssh_key_library). (takes `idempotency_key`)
- `rarecloud:apply_service_ssh_key_library`: Install a selected set of library SSH keys on a legacy VPS. (needs `confirm: true`)
- `rarecloud:get_service_iso`: Get the mounted-ISO status for a legacy VPS: whether a rescue/install ISO is currently attached and, if so, which one.
- `rarecloud:mount_service_iso`: Mount a rescue/install ISO on a VPS as a virtual CD-ROM.
- `rarecloud:unmount_service_iso`: Unmount the currently mounted ISO from a VPS.
- `rarecloud:list_backups`: List existing backups for a single legacy VPS server.
- `rarecloud:create_service_backup`: Create an on-demand backup of a legacy VPS service. (takes `idempotency_key`)

## Domains

- `rarecloud:list_domains`: List registered domains: id, name, status, expiry, auto-renew, and apiAccess ("full", or "read_only" when the user made the domain read-only for agents and API tokens: no tool can change it, see list_api_access; missing means "full").
- `rarecloud:get_domain`: Get one domain: nameservers, transfer lock, WHOIS privacy, auto-renew, expiry, and apiAccess ("full", or "read_only" when the user made it read-only for agents and API tokens: no tool can change its nameservers, DNS, contacts or settings; missing means "full").
- `rarecloud:get_domain_management`: Get the combined management snapshot for an owned domain in one call: status, expiry, auto-renew, WHOIS ID protection, nameservers, and transfer lock (per-registrar fields are null when the registrar exposes no API for them).
- `rarecloud:check_domain_availability`: Check whether a domain name is available to register: a pre-purchase WHOIS availability lookup for a single domain.
- `rarecloud:get_tld_pricing`: List register / transfer / renew prices per TLD, in the account currency.
- `rarecloud:register_domain`: Register a new domain name. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:transfer_domain`: Transfer a domain in from another registrar. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:renew_domain`: Renew an owned domain. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:manage_domain`: Dispatch a single domain management action. (needs `confirm: true`)
- `rarecloud:get_domain_nameservers`: Get the nameservers currently set on an owned domain: where its DNS is delegated.
- `rarecloud:set_domain_nameservers`: Replace an owned domain's nameservers (2-5). (needs `confirm: true`)
- `rarecloud:get_domain_dns`: Get the DNS host records on an owned domain: its A / CNAME / MX / TXT / etc entries (registrar-dependent; returns a not-implemented error when the registrar exposes no DNS API).
- `rarecloud:set_domain_dns`: Replace an owned domain's DNS host records (registrar-dependent: returns a not-implemented error when the registrar exposes no DNS API). (needs `confirm: true`)
- `rarecloud:get_domain_contacts`: Get the registrant WHOIS contact on an owned domain (registrar-dependent).
- `rarecloud:set_domain_contacts`: Update an owned domain's registrant WHOIS contact (registrar-dependent). (needs `confirm: true`)

## Proxies

- `rarecloud:get_proxy_catalog`: Get the residential proxy catalog for the order wizard: ISP IP-count tiers with EUR + USD pricing per Day/Week/Month, orderable locations, protocol + authentication options, plus a `gb` section of monthly GB Residential bandwidth-bucket tiers (EUR + USD).
- `rarecloud:order_proxy`: Order a new residential proxy plan. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:list_proxies`: List your proxy services: id, kind (residential-isp, residential-gb, mobile-4g, mobile-vpn or mobile-multisim), status, quantity, location, expiry, auto-renew and tags.
- `rarecloud:get_proxy`: Get one proxy service: kind (residential-isp, residential-gb, mobile-4g, mobile-vpn or mobile-multisim), status, quantity, location, and expiry/renewal.
- `rarecloud:get_proxy_list`: List the live proxy endpoints and credentials (ip, port, username, password) for an active proxy service: this is the direct endpoint list for ISP fixed-IP plans.
- `rarecloud:check_proxy`: Run a live check on every proxy of a service: the API routes a small request through each one and reports ip, port, up (true/false), the real exit IP, ISP, city, country, countryCode, latencyMs and routed.
- `rarecloud:get_proxy_auth`: Get the authentication settings for a proxy service: the auth method, the proxy credentials (null when the service is IP-authenticated only), the IP whitelist, and the caller's detected IP.
- `rarecloud:set_proxy_auth_method`: Switch a proxy service's authentication method (ip / password / combined). (needs `confirm: true`)
- `rarecloud:set_proxy_credentials`: Set a proxy service's username/password credentials. (needs `confirm: true`)
- `rarecloud:add_proxy_whitelisted_ip`: Add an IP address to a proxy service's whitelist (used by the 'ip' auth method). (takes `idempotency_key`)
- `rarecloud:remove_proxy_whitelisted_ip`: Remove an IP address from a proxy service's whitelist. (needs `confirm: true`)
- `rarecloud:get_proxy_auto_rotation`: Get the auto-rotation settings of a mobile proxy line: enabled and intervalMinutes (how often the exit IP changes on its own).
- `rarecloud:set_proxy_auto_rotation`: Turn a mobile proxy line's automatic IP rotation on or off and set how often it rotates. (needs `confirm: true`)
- `rarecloud:rotate_proxy`: Rotate the exit IP of a mobile proxy line now. (needs `confirm: true`)
- `rarecloud:get_proxy_replacements`: Get the IP-replacement allowance and history for a proxy service: the included monthly allowance (1/month), how much is used, and past replacement requests.
- `rarecloud:list_proxy_replacement_locations`: List the locations (id + label) a new IP can be placed in when replacing an IP of an ISP proxy service.
- `rarecloud:request_proxy_replacement`: Request an IP replacement for a proxy service, consuming the included monthly allowance (1/month). (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:get_proxy_bandwidth`: Get the bandwidth usage of a GB Residential bandwidth bucket: unit (e.g. MB), total, used and available.
- `rarecloud:list_gb_residential_countries`: List the countries (id + name) selectable when creating a GB Residential proxy-request.
- `rarecloud:list_gb_rotation_intervals`: List the rotation intervals (id + label: all, high, 1min, 10min, 30min) selectable when creating a GB Residential proxy-request.
- `rarecloud:list_proxy_requests`: List the proxy-requests on a GB Residential bandwidth bucket: the country + rotation-interval + count groups that allocate endpoints from the bucket.
- `rarecloud:create_proxy_request`: Create a proxy-request (country + rotation-interval + count group) on a GB Residential bucket, allocating endpoints from it. (takes `idempotency_key`)
- `rarecloud:get_proxy_request_list`: List the live proxy endpoints and credentials (ip, port, username, password) for one proxy-request on a GB Residential bucket.
- `rarecloud:delete_proxy_request`: Delete a proxy-request from a GB Residential bucket. (needs `confirm: true`)
- `rarecloud:set_proxy_auto_renew`: Turn a proxy service's auto-renew on or off.
- `rarecloud:renew_proxy`: Renew a proxy service for another billing term. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:cancel_proxy`: Cancel a proxy service (ISP, GB Residential, or mobile, any kind). (needs `confirm: true`)

## Billing

- `rarecloud:get_billing_state`: Get the cloud billing state of the account: state (ok or suspended), any open cloud invoice with its dated suspension schedule, and the runway.
- `rarecloud:get_credit_balance`: Get the current account credit balance (prepaid credit).
- `rarecloud:get_credit_ledger`: List credit ledger entries (top-ups, hourly metering debits, refunds) for the authenticated account.
- `rarecloud:get_bonus_balance`: Get the account's promo (bonus) balance in cents (EUR).
- `rarecloud:get_bonus_ledger`: List all bonus-credit ledger entries (newest first): campaign and voucher grants (positive) and promo consumption (negative).
- `rarecloud:redeem_voucher`: Redeem a voucher / promo code into the bonus (promo) balance. (takes `idempotency_key`)
- `rarecloud:get_billing_campaign`: Get the currently-active credit (deposit-match) campaign in public shape: the "double your credits" promo, or {campaign:null} when none is running.
- `rarecloud:list_invoices`: List invoices for the authenticated account: number, status (paid / unpaid / cancelled), issued date, total.
- `rarecloud:get_invoice`: Get full details for a single invoice: every line item, taxes, payment method used, payment timestamp.
- `rarecloud:get_invoice_pay_preview`: Preview what paying an invoice from the account balance would consume: promo bonus first, then real credit, then any remaining shortfall.
- `rarecloud:list_payment_methods`: List the account's available payment options (gateways).
- `rarecloud:list_orders`: List the authenticated account's orders: the purchase records behind its services.
- `rarecloud:get_order`: Get one order by id: its line items (product, plan, cycle, price), status, paymentStatus, and the invoice it belongs to.
- `rarecloud:get_billing_alert`: Get the spending-alert state: the configured threshold, month-to-date spend, and whether the alert has triggered.
- `rarecloud:set_billing_alert`: Set (or update) the month-to-date spend alert.
- `rarecloud:delete_billing_alert`: Remove the month-to-date spend alert. (needs `confirm: true`)

## Support tickets

- `rarecloud:list_ticket_departments`: List the support departments and their numeric ids: the department ids accepted when opening a ticket (POST /tickets).
- `rarecloud:list_tickets`: List support tickets for the authenticated account: id, subject, status (open / awaiting-staff / awaiting-client / closed), department, last-updated.
- `rarecloud:get_ticket`: Get a single support ticket with its full message thread.
- `rarecloud:create_ticket`: Open a support ticket. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:reply_ticket`: Post a reply to an existing support ticket. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:close_ticket`: Close a support ticket.

## Account

- `rarecloud:get_account`: Get the authenticated user's profile: email, name, country, billing currency, account creation date.
- `rarecloud:update_account`: Update the account's billing / contact profile. (needs `confirm: true`)
- `rarecloud:get_account_activity`: Get the account audit trail (newest first): sign-ins, 2FA changes, service actions, and billing operations.
- `rarecloud:get_two_factor_status`: Get the authenticated user's two-factor (TOTP) status: whether 2FA is enabled on the account.
- `rarecloud:resend_email_verification`: Resend the account's email-address verification email.
- `rarecloud:list_account_emails`: List the emails RareCloud sent to this account (invoices, notices, password resets), newest first.
- `rarecloud:list_account_contacts`: List the account's billing / technical contacts: additional email-copy recipients with no login of their own.
- `rarecloud:manage_account_contact`: Add, update, or delete a billing/technical contact on the account. (needs `confirm: true`; takes `idempotency_key`)
- `rarecloud:list_account_clients`: List the users linked to this client account: accepted members AND pending invitations.
- `rarecloud:list_account_ssh_keys`: List the account-wide SSH public keys registered on the profile: the keys offered at deploy time when creating a new server.
- `rarecloud:add_account_ssh_key`: Add an account-wide SSH public key (offered when deploying new cloud VMs). (takes `idempotency_key`)
- `rarecloud:delete_account_ssh_key`: Delete an account-wide SSH key. (needs `confirm: true`)
- `rarecloud:list_api_access`: Resources the user made read-only for agents and API tokens.
- `rarecloud:get_affiliate`: Get the authenticated account's affiliate status and stats: referral link, visitors / signups / conversion rate, commissions summary (pending maturation / available balance / total withdrawn), payout minimum, and the per-referral list.
- `rarecloud:create_affiliate_link`: Mint a signed affiliate referral link that redirects to a destination of your choice after placing the affiliate cookie.
