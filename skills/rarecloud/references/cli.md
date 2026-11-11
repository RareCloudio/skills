<!-- Generated from RareCloud's published API, CLI, MCP and Terraform definitions. Do not edit by hand: changes are overwritten at the next refresh. To fix something here, open an issue. -->

# RareCloud CLI commands

All 320 commands of the `rarecloud` CLI, from its own `--help`.
Run `rarecloud <command> --help` for the flags of one command.

## rarecloud 2fa

- `rarecloud 2fa`: Manage two-factor authentication (TOTP) (aliases: `two-factor`, `mfa`)
- `rarecloud 2fa disable`: Disable 2FA
- `rarecloud 2fa enable`: Enable 2FA with a code from your authenticator (returns one-time backup codes)
- `rarecloud 2fa setup`: Begin 2FA setup (returns the secret + otpauth URL to add to your authenticator)
- `rarecloud 2fa status`: Show 2FA status

## rarecloud account

- `rarecloud account`: Account management
- `rarecloud account activity`: Show the account activity (audit) log, newest first
- `rarecloud account affiliate`: Show your affiliate account (activate and withdraw in the console)
- `rarecloud account affiliate link`: Create a custom referral link that lands on the given page
- `rarecloud account api-access`: List resources that are read-only for API tokens (switch it in the console)
- `rarecloud account contacts`: List and manage the extra contacts on your account (aliases: `contact`)
- `rarecloud account contacts add`: Add a contact (--first-name, --last-name and --email are required)
- `rarecloud account contacts delete`: Delete a contact (needs --yes) (aliases: `rm`, `remove`)
- `rarecloud account contacts list`: List contacts
- `rarecloud account contacts update`: Update a contact (only the flags you pass are sent)
- `rarecloud account emails`: List emails sent to you (50 per page)
- `rarecloud account emails get`: Show one sent email (subject, date and HTML body)
- `rarecloud account show`: Show the current account profile
- `rarecloud account update`: Update profile fields (only the flags you pass are sent)
- `rarecloud account users`: List users with access to this account (read only; invite in the console) (aliases: `sub-users`, `clients`)

## rarecloud auth

- `rarecloud auth`: Manage CLI authentication (API token)
- `rarecloud auth login`: Save an API token from /dashboard/account/api
- `rarecloud auth logout`: Clear the locally-saved API token
- `rarecloud auth whoami`: Print the email of the current API token's owner

## rarecloud billing

- `rarecloud billing`: Billing settings
- `rarecloud billing alert`: Billing alert: a month-to-date spend threshold, a runway threshold in days, or both
- `rarecloud billing alert delete`: Remove the billing alert (aliases: `rm`)
- `rarecloud billing alert get`: Show the billing alert
- `rarecloud billing alert set`: Set the billing alert thresholds (a threshold you leave out keeps its stored value)

## rarecloud bucket

- `rarecloud bucket`: Object Storage buckets (S3-compatible) (aliases: `buckets`)
- `rarecloud bucket create`: Create a bucket (enables Object Storage if it is off)
- `rarecloud bucket get`: Show one bucket
- `rarecloud bucket list`: List your buckets
- `rarecloud bucket rm`: Delete a bucket (irreversible) (aliases: `delete`)
- `rarecloud bucket update`: Change a bucket's versioning or public (CDN) delivery
- `rarecloud bucket usage`: Daily usage for one bucket (stored, CDN)

## rarecloud catalog

- `rarecloud catalog`: Browse the orderable product catalog (aliases: `products`)
- `rarecloud catalog details`: Show live product details (region availability, pricing, config options)
- `rarecloud catalog images`: List available OS images
- `rarecloud catalog kubernetes-versions`: List the managed Kubernetes versions on offer (the first is the default) (aliases: `k8s-versions`)
- `rarecloud catalog os-templates`: List the OS templates a legacy VPS or dedicated product can be ordered with
- `rarecloud catalog plans`: Show plans (sizes + prices) for a product
- `rarecloud catalog products`: List all orderable products
- `rarecloud catalog regions`: List available regions (datacenter slugs)

## rarecloud completion

- `rarecloud completion`: Generate the autocompletion script for the specified shell
- `rarecloud completion bash`: Generate the autocompletion script for bash
- `rarecloud completion fish`: Generate the autocompletion script for fish
- `rarecloud completion powershell`: Generate the autocompletion script for powershell
- `rarecloud completion zsh`: Generate the autocompletion script for zsh

## rarecloud credit

- `rarecloud credit`: Account credit balance and ledger
- `rarecloud credit balance`: Show current credit balance
- `rarecloud credit bonus`: Show the bonus (promo) balance
- `rarecloud credit bonus ledger`: List bonus grants and consumption, newest first
- `rarecloud credit ledger`: List credit ledger entries, newest first
- `rarecloud credit state`: Show cloud billing state: any open cloud invoice, the dated suspension schedule, and the runway
- `rarecloud credit top-up`: Create a credit top-up invoice and print its payment link (charges nothing by itself)

## rarecloud domain

- `rarecloud domain`: Register and manage domains (aliases: `domains`)
- `rarecloud domain available`: Check whether a domain is available to register
- `rarecloud domain contacts`: View or update a domain's registrant contact (WHOIS) (aliases: `contact`, `whois`)
- `rarecloud domain contacts get`: Show a domain's registrant contact
- `rarecloud domain contacts update`: Update a domain's registrant contact (only the flags you pass change)
- `rarecloud domain dns`: View or update a domain's DNS host records (registrar-dependent)
- `rarecloud domain dns get`: Show a domain's DNS host records
- `rarecloud domain dns update`: Replace a domain's DNS records from a JSON file ([{hostname,type,address,priority?}])
- `rarecloud domain get`: Show details for one domain
- `rarecloud domain list`: List your domains
- `rarecloud domain manage`: Registrar lock, ID protection and the transfer (EPP) code
- `rarecloud domain manage epp`: Request the transfer (EPP) code; the registrar emails it to the registrant contact
- `rarecloud domain manage get`: Show the registrar lock, ID protection, auto-renew and nameservers
- `rarecloud domain manage id-protection`: Turn WHOIS ID protection on or off (aliases: `idprotect`)
- `rarecloud domain manage lock`: Turn the registrar (transfer) lock on or off; off needs --yes
- `rarecloud domain nameservers`: View or update a domain's nameservers (aliases: `ns`)
- `rarecloud domain nameservers get`: Show a domain's nameservers
- `rarecloud domain nameservers update`: Replace a domain's nameservers (2-5 required)
- `rarecloud domain register`: Register a new domain (places an order + invoice; fulfils on payment)
- `rarecloud domain renew`: Renew a domain (optionally toggle auto-renew)
- `rarecloud domain tld-pricing`: Show register / transfer / renew prices per TLD (aliases: `pricing`, `tlds`)
- `rarecloud domain transfer`: Transfer a domain in (places an order; needs the EPP/auth code)

## rarecloud firewall

- `rarecloud firewall`: Cloud firewalls (security groups) (aliases: `fw`, `firewalls`)
- `rarecloud firewall attach`: Attach a firewall to a cloud VM
- `rarecloud firewall create`: Create a new firewall
- `rarecloud firewall delete`: Delete a firewall
- `rarecloud firewall detach`: Detach a firewall from a cloud VM
- `rarecloud firewall get`: Show a firewall and its rules
- `rarecloud firewall list`: List your firewalls
- `rarecloud firewall rule`: Manage firewall rules
- `rarecloud firewall rule add`: Add a rule to a firewall
- `rarecloud firewall rule rm`: Remove a rule from a firewall

## rarecloud invoice

- `rarecloud invoice`: List and view invoices (aliases: `invoices`)
- `rarecloud invoice checkout-url`: Print a logged-in link to pay an invoice by card or another gateway (opens nothing)
- `rarecloud invoice get`: Show one invoice with its line items
- `rarecloud invoice list`: List invoices for the current account
- `rarecloud invoice pay`: Pay an invoice from your account balance (bonus first, then credit)
- `rarecloud invoice pay-preview`: Show what paying an invoice from balance would use (bonus first, then credit); changes nothing

## rarecloud limits

- `rarecloud limits`: Show your quota limits and usage, estimate a deployment, ask for more (aliases: `limit`, `quota`)
- `rarecloud limits estimate`: Estimate what a managed Kubernetes deployment would consume of your quota
- `rarecloud limits request`: Ask for a quota increase (opens a support ticket; needs --yes)
- `rarecloud limits requests`: List your quota increase requests, newest first

## rarecloud load-balancer

- `rarecloud load-balancer`: L4 load balancers (aliases: `lb`, `load-balancers`)
- `rarecloud load-balancer add-member`: Add a cloud VM as a member
- `rarecloud load-balancer create`: Create an L4 load balancer
- `rarecloud load-balancer delete`: Delete a load balancer (aliases: `rm`)
- `rarecloud load-balancer get`: Show one load balancer (incl. members)
- `rarecloud load-balancer list`: List your load balancers
- `rarecloud load-balancer remove-member`: Remove a member from the load balancer

## rarecloud network

- `rarecloud network`: Private networks (VPCs) (aliases: `networks`, `vpc`)
- `rarecloud network attach-vm`: Attach a cloud VM to this network
- `rarecloud network create`: Create a private network
- `rarecloud network delete`: Delete a network (must have no attached VMs)
- `rarecloud network get`: Show one network
- `rarecloud network list`: List your private networks

## rarecloud object-storage

- `rarecloud object-storage`: S3-compatible Object Storage: account, usage, regions, access keys (aliases: `objectstorage`, `obj`)
- `rarecloud object-storage disable`: Permanently delete your Object Storage account (irreversible)
- `rarecloud object-storage enable`: Enable Object Storage (starts the monthly base fee)
- `rarecloud object-storage key`: Manage S3 access keys (aliases: `keys`)
- `rarecloud object-storage key create`: Create an S3 access key (secret shown once)
- `rarecloud object-storage key list`: List access keys (never shows a secret)
- `rarecloud object-storage key rm`: Revoke an access key (irreversible) (aliases: `revoke`, `delete`)
- `rarecloud object-storage regions`: List the regions a bucket can be created in
- `rarecloud object-storage status`: Show Object Storage status, usage, this month's charge and the price card (aliases: `get`)
- `rarecloud object-storage usage`: Daily usage for the whole account (stored, egress, CDN)

## rarecloud order

- `rarecloud order`: View your orders (aliases: `orders`)
- `rarecloud order get`: Show one order (incl. the service line items it created)
- `rarecloud order list`: List your orders (newest first)

## rarecloud payment-method

- `rarecloud payment-method`: Manage payment methods / checkout gateways (aliases: `payment-methods`, `pm`)
- `rarecloud payment-method add`: Not available: gateways are chosen at checkout, nothing is stored (the API answers not implemented)
- `rarecloud payment-method list`: List available payment methods
- `rarecloud payment-method remove`: Not available: gateways are chosen at checkout, nothing is stored (the API answers not implemented) (aliases: `delete`, `rm`)

## rarecloud proxy

- `rarecloud proxy`: Order, renew and manage your proxies (aliases: `proxies`)
- `rarecloud proxy auth`: Proxy authentication settings
- `rarecloud proxy auth get`: Show the auth method, username and IP whitelist
- `rarecloud proxy auth method`: Switch the auth method (ISP plans only; GB plans are always combined)
- `rarecloud proxy auto-renew`: Automatic renewal from account credit (ISP and mobile)
- `rarecloud proxy auto-renew get`: Show whether the proxy renews automatically
- `rarecloud proxy auto-renew set`: Turn automatic renewal on or off
- `rarecloud proxy auto-rotation`: Automatic IP rotation of a mobile line
- `rarecloud proxy auto-rotation get`: Show the auto-rotation setting
- `rarecloud proxy auto-rotation set`: Set auto-rotation (interval 5 to 1440 minutes)
- `rarecloud proxy bandwidth`: Show bandwidth usage of a GB residential plan
- `rarecloud proxy cancel`: Cancel a proxy at the end of its paid term (needs --yes)
- `rarecloud proxy catalog`: Residential proxy catalog: ISP tiers, locations, options and GB plans
- `rarecloud proxy check`: Live check: exit IP, ISP, location, up/down and latency per proxy
- `rarecloud proxy credentials`: Change or regenerate the proxy username and password (aliases: `creds`)
- `rarecloud proxy credentials regenerate`: Generate new random credentials (mobile 4G and multisim lines only)
- `rarecloud proxy credentials set`: Set the proxy username and password (password read from stdin)
- `rarecloud proxy export`: Print the proxy list (includes credentials)
- `rarecloud proxy format`: Switch an ISP proxy between HTTP/HTTPS and SOCKS5 (needs --yes)
- `rarecloud proxy get`: Show one proxy service
- `rarecloud proxy list`: List your proxy services
- `rarecloud proxy mobile`: Mobile proxy reference data
- `rarecloud proxy mobile prices`: Mobile proxy order prices per kind and location, in your billing currency
- `rarecloud proxy order`: Order a proxy plan (shows the price first; needs --yes to place it)
- `rarecloud proxy renew`: Renew a proxy for another term (charged to your account; needs --yes)
- `rarecloud proxy replacement`: Included IP replacements (ISP plans only) (aliases: `replacements`)
- `rarecloud proxy replacement list`: Show the monthly replacement allowance and past requests
- `rarecloud proxy replacement locations`: List the locations a replacement IP can be moved to
- `rarecloud proxy replacement request`: Request the included IP replacement
- `rarecloud proxy requests`: Proxy-requests on a GB residential plan (country + rotation + count) (aliases: `request`, `proxy-requests`)
- `rarecloud proxy requests check`: Live check of one proxy-request's proxies
- `rarecloud proxy requests create`: Allocate proxies from a GB plan in a country with a rotation interval
- `rarecloud proxy requests delete`: Delete a proxy-request (its proxies stop working) (aliases: `rm`)
- `rarecloud proxy requests export`: Print a proxy-request's proxy list (includes credentials) (aliases: `proxy-list`)
- `rarecloud proxy requests list`: List the proxy-requests of a GB plan
- `rarecloud proxy residential`: Reference lists for GB residential proxy-requests
- `rarecloud proxy residential countries`: List the countries a GB proxy-request can use
- `rarecloud proxy residential rotation-intervals`: List the rotation intervals a GB proxy-request can use
- `rarecloud proxy rotate`: Rotate the exit IP of a mobile line now
- `rarecloud proxy tags`: Label your proxies with tags
- `rarecloud proxy tags clear`: Remove all tags from a proxy
- `rarecloud proxy tags list`: List the tags in use on your proxies, with counts
- `rarecloud proxy tags set`: Replace a proxy's tags
- `rarecloud proxy vpn-config`: Download the VPN connect file of a mobile VPN line (contains its keys)
- `rarecloud proxy whitelist`: Manage the IP whitelist of a proxy service (aliases: `wl`)
- `rarecloud proxy whitelist add`: Whitelist an IPv4 or IPv6 address
- `rarecloud proxy whitelist list`: List the whitelisted IPs (and the IP the API sees you calling from)
- `rarecloud proxy whitelist remove`: Remove a whitelisted IP (aliases: `rm`)

## rarecloud registry

- `rarecloud registry`: Private container registry (Docker/OCI images) (aliases: `reg`)
- `rarecloud registry close`: Close your container registry (reopenable with the same handle until the grace window ends)
- `rarecloud registry clusters`: Link RareCloud-managed Kubernetes clusters to your registry
- `rarecloud registry clusters link`: Link one of your own Kubernetes clusters to the registry
- `rarecloud registry clusters list`: List clusters linked to your container registry
- `rarecloud registry clusters rotate`: Rotate a linked cluster's pull credential
- `rarecloud registry clusters unlink`: Unlink a Kubernetes cluster from the registry
- `rarecloud registry credentials`: Manage registry robot credentials (docker login) (aliases: `creds`)
- `rarecloud registry credentials create`: Create a registry robot credential (secret shown once)
- `rarecloud registry credentials list`: List registry robot credentials (never includes a secret)
- `rarecloud registry credentials revoke`: Revoke a registry credential immediately
- `rarecloud registry enable`: Enable your private container registry (or reopen a closed one)
- `rarecloud registry get`: Show your container registry account, usage, quota, and push state
- `rarecloud registry k8s-manifest`: Get a ready-to-apply pull-secret manifest for a cluster you manage yourself (BYO) (aliases: `kubernetes-manifest`)
- `rarecloud registry manifests`: Manage image manifests (by digest) within a repository
- `rarecloud registry manifests delete`: Delete a manifest by digest (every tag serving it goes with it)
- `rarecloud registry repos`: List and manage registry repositories (aliases: `repositories`, `repo`)
- `rarecloud registry repos delete`: Delete an entire repository (irreversible)
- `rarecloud registry repos get`: Show one repository and its tags
- `rarecloud registry repos list`: List the repositories under your handle
- `rarecloud registry set-tier`: Change your container registry's billing tier
- `rarecloud registry tags`: Manage tags within a repository
- `rarecloud registry tags delete`: Delete one tag (the tag only: an image left untagged is removed by retention, or delete it by digest)
- `rarecloud registry tags vulnerabilities`: List vulnerability findings for one tag (scanning is not active yet, so it reports the scan as unavailable)
- `rarecloud registry tiers`: List container registry billing tiers

## rarecloud reserved-ip

- `rarecloud reserved-ip`: Reserved public IPs (aliases: `reserved-ips`, `rip`)
- `rarecloud reserved-ip attach`: Attach a reserved IP to a cloud VM
- `rarecloud reserved-ip create`: Reserve a new public IP (billed while reserved)
- `rarecloud reserved-ip detach`: Detach a reserved IP from its VM (stays reserved + billed)
- `rarecloud reserved-ip list`: List your reserved IPs
- `rarecloud reserved-ip release`: Release a reserved IP (stops billing, IP returns to the pool)

## rarecloud sandbox

- `rarecloud sandbox`: AI code sandboxes (ephemeral execution environments) (aliases: `sandboxes`, `sbx`)
- `rarecloud sandbox create`: Create a sandbox (defaults to the python template)
- `rarecloud sandbox exec`: Run a shell command inside a sandbox
- `rarecloud sandbox expose`: Not available yet: preview URLs for a sandbox port
- `rarecloud sandbox files`: Download or upload a file in a sandbox (aliases: `file`)
- `rarecloud sandbox files get`: Download a file from a sandbox (to stdout, or to --output with mode 0600)
- `rarecloud sandbox files put`: Upload a file to a sandbox (from --from, or stdin); at most 25 MiB
- `rarecloud sandbox get`: Show one sandbox
- `rarecloud sandbox list`: List your sandboxes
- `rarecloud sandbox logs`: Print the last lines of a sandbox's output (live, or kept for 24 h after a run-mode exit)
- `rarecloud sandbox rm`: Terminate and delete a sandbox (aliases: `delete`)
- `rarecloud sandbox run`: Run code inside a sandbox (--code, --file, or stdin)
- `rarecloud sandbox sizes`: List sandbox sizes with vCPU, RAM and hourly price
- `rarecloud sandbox templates`: List sandbox templates with their default size and hourly price

## rarecloud server

- `rarecloud server`: Manage servers (legacy VPS + cloud compute) (aliases: `servers`, `vps`)
- `rarecloud server autorenew`: Show or set auto-renew from balance for a legacy service
- `rarecloud server autorenew get`: Show whether auto-renew from balance is on
- `rarecloud server autorenew set`: Turn auto-renew from balance on or off
- `rarecloud server backup`: Manage server backups (for snapshots see `server snapshot`)
- `rarecloud server backup create`: Create a new backup
- `rarecloud server backup list`: List backups for a server
- `rarecloud server cancel`: Request cancellation of a legacy VPS or hosting service (needs --yes)
- `rarecloud server check`: Check whether a server order would be accepted, without creating anything
- `rarecloud server console`: Get the web console (noVNC) URL for a server
- `rarecloud server create`: Provision a new server
- `rarecloud server destroy`: Permanently destroy a server (irreversible) (aliases: `delete`, `rm`)
- `rarecloud server get`: Show details for a single server
- `rarecloud server ha`: High-availability control plane of a managed Kubernetes cluster
- `rarecloud server ha enable`: Enable the HA control plane (one-way; adds a surcharge; needs --yes)
- `rarecloud server hostname`: Change a server's hostname
- `rarecloud server iso`: Mount or unmount an ISO image on a legacy VPS
- `rarecloud server iso get`: Show whether an ISO is mounted
- `rarecloud server iso mount`: Mount an ISO from a public URL as a virtual CD-ROM
- `rarecloud server iso unmount`: Unmount the ISO
- `rarecloud server kubeconfig`: Fetch a short-lived admin kubeconfig for a managed Kubernetes cluster
- `rarecloud server kubeconfigs`: Manage long-lived kubeconfig credentials for a managed Kubernetes cluster
- `rarecloud server kubeconfigs create`: Create a long-lived kubeconfig credential (revocable any time)
- `rarecloud server kubeconfigs download`: Re-download the kubeconfig for an active credential
- `rarecloud server kubeconfigs list`: List long-lived kubeconfig credentials for a cluster
- `rarecloud server kubeconfigs revoke`: Revoke a credential (immediate, its kubeconfig stops working)
- `rarecloud server list`: List your servers
- `rarecloud server metrics`: Show CPU / RAM / disk / network metrics for a server
- `rarecloud server os-templates`: List the images a server can be reinstalled with
- `rarecloud server pool`: Manage the node pools of a managed Kubernetes cluster (aliases: `pools`)
- `rarecloud server pool add`: Add a node pool (billed; needs --yes)
- `rarecloud server pool delete`: Remove a node pool (never the last one; needs --yes) (aliases: `rm`, `remove`)
- `rarecloud server pool list`: List the node pools of a cluster
- `rarecloud server pool rename`: Rename a node pool (replaces its nodes; needs --yes)
- `rarecloud server pool update`: Change a node pool's size range, machine type or volume (needs --yes)
- `rarecloud server rdns`: Manage a cloud VM's reverse DNS record
- `rarecloud server rdns delete`: Remove the PTR record for a cloud VM's primary IPv4
- `rarecloud server rdns get`: Read the PTR record for a cloud VM's primary IPv4
- `rarecloud server rdns set`: Set the PTR record for a cloud VM's primary IPv4
- `rarecloud server reboot`: Soft-reboot a server
- `rarecloud server reinstall`: Reinstall (destructively rebuild) a cloud VM from a chosen image
- `rarecloud server renew`: Renew a legacy VPS: get (or create) its renewal invoice (needs --yes)
- `rarecloud server reset-password`: Reset the root password on a running cloud VM (live, non-destructive)
- `rarecloud server resize`: Resize a cloud VM to a different plan (async)
- `rarecloud server scale`: Show or set worker min/max for a managed Kubernetes cluster
- `rarecloud server set-password`: Set the root password of a legacy VPS (changes access; needs --yes)
- `rarecloud server smtp`: Outbound email (port 25) status and unblock requests for a cloud VM
- `rarecloud server smtp request`: Ask for outbound port 25 to be opened on a cloud VM
- `rarecloud server smtp status`: Show whether outbound email is open, blocked, pending, approved or rejected
- `rarecloud server snapshot`: Manage cloud VM snapshots (copies of the root disk) (aliases: `snapshots`)
- `rarecloud server snapshot create`: Take a snapshot of a cloud VM's root disk
- `rarecloud server snapshot delete`: Permanently delete a snapshot (irreversible) (aliases: `rm`)
- `rarecloud server snapshot get`: Show one snapshot
- `rarecloud server snapshot list`: List the snapshots taken from a cloud VM
- `rarecloud server snapshot restore`: Restore a cloud VM from one of its snapshots (replaces the root disk)
- `rarecloud server ssh-key`: Manage the SSH keys installed on a legacy VPS (aliases: `ssh-keys`)
- `rarecloud server ssh-key add`: Install an SSH public key on a legacy VPS
- `rarecloud server ssh-key library`: Manage the SSH key library of a legacy VPS
- `rarecloud server ssh-key library add`: Register a public key in the VPS key library (apply it with `library apply`)
- `rarecloud server ssh-key library apply`: Install library keys on the VPS (adds them; keys already installed stay)
- `rarecloud server ssh-key library list`: List the keys in the VPS key library
- `rarecloud server ssh-key list`: List the SSH keys on a server
- `rarecloud server start`: Power on a server
- `rarecloud server status`: Show the setup (provisioning) state of a server (aliases: `provisioning`)
- `rarecloud server stop`: Power off a server
- `rarecloud server tag`: Manage a cloud VM's tags
- `rarecloud server tag clear`: Remove every tag from a cloud VM
- `rarecloud server tag set`: Replace a cloud VM's tags with the given ones
- `rarecloud server upgrade`: Upgrade or downgrade a legacy VPS to another product (--quote to price it, --yes to order)
- `rarecloud server upgrade-options`: List the products a legacy VPS can be upgraded or downgraded to

## rarecloud snapshot

- `rarecloud snapshot`: Cloud VM snapshots across your account (aliases: `snapshots`)
- `rarecloud snapshot delete`: Permanently delete a snapshot (irreversible) (aliases: `rm`)
- `rarecloud snapshot get`: Show one snapshot
- `rarecloud snapshot list`: List all your snapshots

## rarecloud ssh-key

- `rarecloud ssh-key`: Manage SSH keys attached to your account (aliases: `ssh-keys`, `keys`)
- `rarecloud ssh-key add`: Register a new SSH public key
- `rarecloud ssh-key list`: List your registered SSH keys
- `rarecloud ssh-key remove`: Unregister an SSH key (does NOT touch authorized_keys on existing servers)

## rarecloud ticket

- `rarecloud ticket`: Open and manage support tickets (aliases: `tickets`)
- `rarecloud ticket close`: Close a ticket
- `rarecloud ticket create`: Open a new support ticket
- `rarecloud ticket departments`: List support departments (ids for `ticket create --department`)
- `rarecloud ticket get`: Show one ticket (incl. messages)
- `rarecloud ticket list`: List your support tickets
- `rarecloud ticket reply`: Reply to a ticket

## rarecloud token

- `rarecloud token`: Manage API tokens for scripting / CI / agents (aliases: `tokens`, `api-token`, `api-tokens`)
- `rarecloud token create`: Create a new API token (token shown ONCE, not retrievable later)
- `rarecloud token list`: List your API tokens
- `rarecloud token revoke`: Revoke an API token (immediate, no propagation delay)

## rarecloud upgrade

- `rarecloud upgrade`: Upgrade the CLI to the latest released version

## rarecloud volume

- `rarecloud volume`: Block storage volumes (aliases: `volumes`, `vol`)
- `rarecloud volume attach`: Attach a volume to a cloud VM
- `rarecloud volume create`: Create a block volume (billed per GB while it exists)
- `rarecloud volume delete`: Delete a volume (stops billing; must be detached)
- `rarecloud volume detach`: Detach a volume from its VM
- `rarecloud volume get`: Show one volume
- `rarecloud volume list`: List your volumes

## rarecloud voucher

- `rarecloud voucher`: Redeem vouchers (aliases: `vouchers`)
- `rarecloud voucher redeem`: Redeem a voucher code into bonus balance
