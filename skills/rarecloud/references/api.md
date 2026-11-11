<!-- Generated from RareCloud's published API, CLI, MCP and Terraform definitions. Do not edit by hand: changes are overwritten at the next refresh. To fix something here, open an issue. -->

# RareCloud API operations

All 282 operations of the RareCloud API contract, grouped by tag.
Paths are relative to `https://api.rarecloud.io/v1`, `https://console.rarecloud.io/api/v1`.

## Health

- `GET /health`: Health check
- `GET /maintenance`: Is a maintenance window pausing cloud operations?

## Limits

- `GET /limits`: Your effective quota limits and live usage
- `POST /limits/estimate`: What a managed-Kubernetes deployment would consume
- `GET /limits/requests`: Your quota-increase requests, newest first
- `POST /limits/requests`: Ask for a quota increase

## Sandboxes

- `GET /sandboxes`: List sandboxes
- `POST /sandboxes`: Create a sandbox
- `GET /sandboxes/sizes`: List sandbox sizes
- `GET /sandboxes/templates`: List sandbox templates
- `GET /sandboxes/{id}`: Get a sandbox
- `DELETE /sandboxes/{id}`: Delete a sandbox
- `POST /sandboxes/{id}/commands`: Run a shell command in a sandbox
- `GET /sandboxes/{id}/files`: Read a file from a sandbox
- `PUT /sandboxes/{id}/files`: Write a file into a sandbox
- `GET /sandboxes/{id}/logs`: Read a sandbox's logs
- `POST /sandboxes/{id}/ports/{port}`: Expose a sandbox port
- `POST /sandboxes/{id}/run_code`: Run code in a sandbox

## Account

- `GET /account`: Get current account profile
- `PATCH /account`: Update account profile
- `GET /account/activity`: your account audit trail (sign-ins, 2FA, service actions, billing ops)
- `GET /account/affiliate`: Get your affiliate status and stats
- `POST /account/affiliate/activate`: Activate the affiliate program for your account
- `POST /account/affiliate/link`: Generate a signed custom affiliate redirect link
- `POST /account/affiliate/withdraw`: Request an affiliate withdrawal (payout)
- `GET /account/clients`: List users linked to this client account
- `POST /account/clients`: Invite a sub-user via email
- `POST /account/clients/resend`: Resend a pending sub-user invitation email
- `GET /account/contacts`: billing/tech contacts (email-copy recipients, no login)
- `POST /account/contacts`: add/update/delete a contact ({ action, id?, firstname, lastname, email, ... })
- `GET /account/emails`: emails RareCloud sent you (list; ?id= returns one with HTML body)
- `GET /account/limits`: Get resource limits + current usage
- `POST /account/password`: Change account password
- `GET /account/ssh-keys`: List account SSH keys
- `POST /account/ssh-keys`: Register an account SSH key
- `DELETE /account/ssh-keys/{id}`: Delete an account SSH key
- `GET /account/two-factor`: Get two-factor (TOTP) status
- `POST /account/two-factor`: Set up, enable, or disable two-factor (TOTP)
- `POST /account/verify-email/resend`: Resend the email-address verification email

## Billing

- `GET /billing/alert`: your billing alert (spend threshold, runway threshold in days, month-to-date spend, runway, triggered)
- `PUT /billing/alert`: set the spend threshold, the runway threshold in days, or both
- `DELETE /billing/alert`: remove the billing alert
- `GET /billing/bonus`: promo (bonus) balance for the signed-in user
- `GET /billing/bonus/ledger`: full bonus credit ledger (grants + consumption)
- `GET /billing/campaign`: the currently-active credit campaign (or null)
- `GET /billing/credit`: Get credit balance
- `GET /billing/credit/ledger`
- `POST /billing/credit/top-up`: Creates a deposit invoice in the account currency and returns the link to pay it.
- `GET /billing/invoices`: List invoices
- `GET /billing/invoices/{id}`: Get invoice detail
- `POST /billing/invoices/{id}/checkout-url`: logged-in hosted-gateway pay link
- `POST /billing/invoices/{id}/pay`: Pays one of your unpaid invoices from your balance.
- `GET /billing/invoices/{id}/pay-preview`: Read-only breakdown of what paying this invoice from the account balance would use: promo bonus first, then real credit, plus any shortfall.
- `GET /billing/invoices/{id}/pdf`: Download invoice PDF
- `GET /billing/payment-methods`: Available payment options (payment gateways; no stored-card vault)
- `POST /billing/payment-methods`: add a payment method to your own account
- `DELETE /billing/payment-methods/{id}`: remove one of your own payment methods
- `GET /billing/state`: the open cloud invoice, the dated power-off and deletion schedule, and the informational runway for the signed-in user
- `POST /billing/vouchers/redeem`: Redeems a voucher on your own account.

## Tickets

- `GET /tickets`: List tickets
- `POST /tickets`: Open a new ticket
- `GET /tickets/departments`: List support departments
- `GET /tickets/{id}`: Get ticket thread
- `POST /tickets/{id}/close`: Close a support ticket
- `POST /tickets/{id}/replies`: Reply to a ticket

## Tokens

- `GET /tokens`: List API tokens
- `POST /tokens`: Create a new API token
- `DELETE /tokens/{id}`: Revoke an API token

## Catalog

- `GET /catalog/images`: List available OS images and marketplace apps
- `GET /catalog/kubernetes-versions`: List offered managed-Kubernetes versions
- `GET /catalog/listings/{category}`: List deploy-wizard product cards for a category
- `GET /catalog/products`: List orderable products
- `GET /catalog/products/{sku}`: Get product detail + all plans
- `GET /catalog/products/{sku}/details`: Get live product detail (cycles + config options)
- `GET /catalog/products/{sku}/os-templates`: List pre-purchase OS templates for a legacy/dedicated SKU
- `GET /catalog/regions`: List available regions

## Orders

- `GET /orders`: List your orders
- `GET /orders/{id}`: Get one of your orders

## Domains

- `GET /domains`: List your domains
- `POST /domains`: Register a domain
- `GET /domains/availability`: Check domain availability
- `GET /domains/tld-pricing`: List TLD pricing
- `POST /domains/transfers`: Transfer a domain in
- `GET /domains/{id}`: Get a domain
- `PUT /domains/{id}/api-access`: Set API access for a domain (console only)
- `GET /domains/{id}/contacts`: Get registrant contact
- `PUT /domains/{id}/contacts`: Update registrant contact
- `GET /domains/{id}/dns`: Get DNS host records
- `PUT /domains/{id}/dns`: Set DNS host records
- `GET /domains/{id}/manage`: Get domain management snapshot
- `POST /domains/{id}/manage`: Dispatch a domain management action
- `GET /domains/{id}/nameservers`: Get nameservers
- `PUT /domains/{id}/nameservers`: Set nameservers
- `POST /domains/{id}/renew`: Renew a domain

## Services

- `GET /api-access`: List resources that are read-only for API tokens
- `GET /services`: List services
- `POST /services`: Deploy a service
- `POST /services/preflight`: Check whether an order would be accepted
- `GET /services/{id}`: Get service detail
- `DELETE /services/{id}`: Destroy a service
- `POST /services/{id}/actions/{action}`: Trigger service action
- `PUT /services/{id}/api-access`: Set API access for a resource (console only)
- `GET /services/{id}/autorenew`: Whether this service auto-renews from balance.
- `PUT /services/{id}/autorenew`: Opt a service out of (enabled:false) or back into (enabled:true) automatic renewal from balance.
- `GET /services/{id}/backups`
- `POST /services/{id}/backups`
- `POST /services/{id}/cancel`: File a cancellation request (billing stops; the service is then terminated)
- `GET /services/{id}/console`
- `GET /services/{id}/console/ws`: noVNC WebSocket proxy (not available yet, returns 426).
- `POST /services/{id}/cpanel-sso`: Mint a single-use SSO URL deep-linked into a specific cPanel app (hosting only)
- `POST /services/{id}/high-availability`: Enable the HA control plane on a managed Kubernetes cluster (add-only; can't be removed; your own cluster only)
- `POST /services/{id}/hostname`: Change the hostname of a VPS or rename a cloud VM
- `GET /services/{id}/iso`
- `PUT /services/{id}/iso`
- `DELETE /services/{id}/iso`
- `GET /services/{id}/kubeconfig`: Short-lived admin kubeconfig for a managed Kubernetes cluster (your own only)
- `GET /services/{id}/kubeconfigs`: List long-lived kubeconfig credentials for a cluster
- `POST /services/{id}/kubeconfigs`: Create a long-lived kubeconfig credential (per-credential ServiceAccount in your cluster; revocable)
- `DELETE /services/{id}/kubeconfigs/{credId}`: Revoke a long-lived kubeconfig credential (deletes its ServiceAccount, so the token dies instantly)
- `GET /services/{id}/kubeconfigs/{credId}/download`: Re-download a long-lived kubeconfig (active credentials only)
- `GET /services/{id}/metrics`: Resource-usage metrics for a service.
- `GET /services/{id}/os-templates`: Images this service can be reinstalled with.
- `POST /services/{id}/panel-sso`: Mint a single-use SSO URL into the full legacy management panel
- `POST /services/{id}/password`: Reset the VPS root password (min 8 chars; never logged)
- `GET /services/{id}/pools`: List the node pools of a managed Kubernetes cluster (your own only)
- `POST /services/{id}/pools`: Add a named node pool to a managed Kubernetes cluster (your own only)
- `PATCH /services/{id}/pools/{pool}`: Edit a node pool's min/max/machineType/volume (your own cluster only)
- `DELETE /services/{id}/pools/{pool}`: Remove a node pool (never the last one; your own cluster only)
- `POST /services/{id}/pools/{pool}/rename`: Rename a node pool (add-new + remove-old → rolling node replacement; your own cluster only)
- `GET /services/{id}/provisioning`: Setup state of a pending service (paid vs unpaid vs stuck)
- `GET /services/{id}/rdns`: Get a Cloud VM's reverse DNS record
- `PUT /services/{id}/rdns`: Set a Cloud VM's reverse DNS record
- `DELETE /services/{id}/rdns`: Remove a Cloud VM's reverse DNS record
- `POST /services/{id}/renew`: Ensure the service's renewal invoice and return it for payment: an existing Unpaid renewal invoice is returned as-is (the billing system generates one 15 days before the due date); otherwise one is created inside the registrar-configured early-renew window.
- `POST /services/{id}/renew-sso`: Mint a single-use SSO URL to the early-renewal page
- `POST /services/{id}/resize`: Resize a cloud VM to a different plan (async)
- `GET /services/{id}/scale`: Current worker pools + add-ons for a managed Kubernetes cluster (your own only)
- `POST /services/{id}/scale`: Set the first worker pool's min/max workers (your own cluster only)
- `GET /services/{id}/smtp`: Get a Cloud VM's outbound email status
- `POST /services/{id}/smtp/unblock-request`: Request outbound email (port 25) for a Cloud VM
- `GET /services/{id}/ssh-keys`
- `POST /services/{id}/ssh-keys`
- `GET /services/{id}/ssh-keys/library`: List the SSH keys registered in a legacy VPS's key library.
- `POST /services/{id}/ssh-keys/library`: Add a new SSH key to a legacy VPS's key library: {name, key}.
- `POST /services/{id}/ssh-keys/library/apply`: Install a selected set of library SSH keys on a legacy VPS: {keyIds}.
- `PUT /services/{id}/tags`: Replace a cloud VM's tags
- `GET /services/{id}/upgrade`: Candidate plans+cycles for upgrade/downgrade
- `POST /services/{id}/upgrade`: Prorated quote (confirm=false, default) or create the upgrade order+invoice (confirm=true)
- `GET /services/{id}/vpanel`: native management panel shell (HTML) for an owned VPS, embedded in the console.
- `GET /services/{id}/vpanel/act`: read-only panel proxy for the embedded management view of an owned VPS.
- `POST /services/{id}/vpanel/act`: always refused with 403 PERMISSION_DENIED.
- `GET /services/{id}/vpanel/novnc`: the HTML5 (noVNC) browser console viewer for an owned legacy VPS.
- `GET /services/{id}/vpanel/novnc-assets/{path}`: same-origin proxy for a whitelisted noVNC static asset (app/core/vendor/po under the module's novnc/ dir) for an owned legacy VPS.
- `GET /services/{id}/vpanel/sso`: one-shot SSO auto-login URL into the control panel of an owned VPS (the browser opens it in a new tab).
- `GET /services/{id}/vpanel/status`: probe whether the owned VPS's control panel is reachable, before the console mounts the panel iframe.
- `GET /services/{id}/vpanel/ui-assets/{path}`: same-origin proxy for a whitelisted panel font asset (css2/ + fonts/ under the module's ui/ dir) for an owned service.

## Proxies

- `GET /proxies`: List your proxy services
- `POST /proxies`: Order a residential or mobile proxy plan (ISP, GB, or mobile)
- `GET /proxies/catalog`: Residential proxy catalog (tiers, locations, options)
- `GET /proxies/isp-global/catalog`: ISP Proxies Global catalog
- `GET /proxies/isp-global/location-countries`: List ISP Proxies Global countries
- `GET /proxies/isp-global/locations`: Search ISP Proxies Global locations
- `GET /proxies/mobile/prices`: Mobile proxy order prices
- `GET /proxies/residential-global/catalog`: Residential Proxies Global catalog
- `GET /proxies/residential-global/geo/asns`: Residential Proxies Global networks (ASN)
- `GET /proxies/residential-global/geo/cities`: Residential Proxies Global cities
- `GET /proxies/residential-global/geo/countries`: Residential Proxies Global countries
- `GET /proxies/residential-global/geo/regions`: Residential Proxies Global regions
- `GET /proxies/residential/countries`: GB residential countries
- `GET /proxies/residential/rotation-intervals`: GB residential rotation intervals
- `GET /proxies/tags`: List your proxy tags with counts
- `GET /proxies/{id}`: Get a proxy service
- `GET /proxies/{id}/auth`: Proxy authentication settings
- `PATCH /proxies/{id}/auth`: Switch the proxy authentication method
- `PUT /proxies/{id}/auth/credentials`: Change the proxy credentials
- `POST /proxies/{id}/auth/credentials/regenerate`: Regenerate proxy credentials (mobile non-VPN only)
- `POST /proxies/{id}/auth/whitelisted-ips`: Whitelist a device IP
- `DELETE /proxies/{id}/auth/whitelisted-ips/{ip}`: Remove a whitelisted device IP
- `POST /proxies/{id}/auto-renew`: Toggle automatic renewal
- `GET /proxies/{id}/auto-rotation`: Fetch auto-rotation settings (mobile only)
- `PUT /proxies/{id}/auto-rotation`: Update auto-rotation settings (mobile only)
- `GET /proxies/{id}/auto-top-up`: Residential Proxies Global auto top-up settings
- `PUT /proxies/{id}/auto-top-up`: Set Residential Proxies Global auto top-up
- `GET /proxies/{id}/bandwidth`: Bandwidth usage (GB plans and Residential Proxies Global)
- `POST /proxies/{id}/cancel`: Cancel a proxy
- `POST /proxies/{id}/check`: Live proxy check (exit IP, ISP, geo, health)
- `GET /proxies/{id}/credentials`: Residential Proxies Global credentials
- `POST /proxies/{id}/credentials/rotate`: Rotate the Residential Proxies Global password (not available)
- `POST /proxies/{id}/format`: Switch the proxy format
- `GET /proxies/{id}/ips`: List the IPs of an ISP Proxies Global plan
- `POST /proxies/{id}/ips/location`: Move several IPs of an ISP Proxies Global plan
- `POST /proxies/{id}/ips/place`: Place unplaced IPs of an ISP Proxies Global plan
- `POST /proxies/{id}/ips/{proxyId}/location`: Move one IP of an ISP Proxies Global plan
- `GET /proxies/{id}/locations`: Search locations for an ISP Proxies Global plan
- `GET /proxies/{id}/proxy-list`: Proxy endpoints and credentials
- `GET /proxies/{id}/proxy-requests`: List proxy-requests on a GB bucket
- `POST /proxies/{id}/proxy-requests`: Create a proxy-request on a GB bucket
- `DELETE /proxies/{id}/proxy-requests/{reqId}`: Delete a GB proxy-request
- `POST /proxies/{id}/proxy-requests/{reqId}/check`: Live-check a single GB proxy-request's proxies
- `GET /proxies/{id}/proxy-requests/{reqId}/proxy-list`: Proxy endpoints for a GB proxy-request
- `POST /proxies/{id}/renew`: Renew a proxy service
- `GET /proxies/{id}/replacements`: Replacement allowance and history
- `POST /proxies/{id}/replacements`: Request the included IP replacement
- `GET /proxies/{id}/replacements/locations`: Locations offered for a replacement
- `POST /proxies/{id}/rotate`: Rotate a mobile proxy IP
- `PUT /proxies/{id}/tags`: Set a proxy's tags
- `POST /proxies/{id}/top-up`: Add GB to a Residential Proxies Global plan
- `GET /proxies/{id}/usage`: Traffic of an ISP Proxies Global plan
- `GET /proxies/{id}/vpn-config`: Download VPN config file (mobile-vpn only)

## Reserved IPs

- `GET /reserved-ips`: List your reserved (floating) IPs with their live attachment
- `POST /reserved-ips`: Reserve a new public IP.
- `DELETE /reserved-ips/{id}`: Release a reserved IP (FIP deleted, billing stops).
- `POST /reserved-ips/{id}/attach`: Attach a reserved IP to one of your cloud VMs
- `POST /reserved-ips/{id}/detach`: Detach a reserved IP from its VM (stays allocated + billed until released)

## Object Storage

- `GET /object-storage`: Get your object storage account
- `POST /object-storage`: Enable object storage
- `DELETE /object-storage`: Disable object storage
- `GET /object-storage/buckets`: List your buckets
- `POST /object-storage/buckets`: Create a bucket
- `GET /object-storage/buckets/{id}`: Get one bucket
- `PATCH /object-storage/buckets/{id}`: Update a bucket
- `DELETE /object-storage/buckets/{id}`: Delete a bucket
- `GET /object-storage/buckets/{id}/usage`: Bucket usage series
- `GET /object-storage/keys`: List your access keys
- `POST /object-storage/keys`: Create an access key
- `DELETE /object-storage/keys/{id}`: Revoke an access key
- `GET /object-storage/regions`: List object storage regions
- `GET /object-storage/usage`: Account usage series

## Registry

- `GET /registry`: Get your container registry account
- `POST /registry`: Enable the container registry, reopen a closed one, or re-enable a purged one
- `PATCH /registry`: Change the registry's billing tier
- `DELETE /registry`: Close the container registry
- `GET /registry/clusters`: List clusters linked to your container registry
- `POST /registry/clusters/{serviceId}`: Link a Kubernetes cluster to your container registry
- `DELETE /registry/clusters/{serviceId}`: Unlink a Kubernetes cluster from your container registry
- `POST /registry/clusters/{serviceId}/rotate`: Rotate a linked cluster's pull credential
- `GET /registry/credentials`: List registry credentials
- `POST /registry/credentials`: Create a registry credential
- `DELETE /registry/credentials/{id}`: Revoke a registry credential
- `POST /registry/docker-credentials/kubernetes`: Get a ready-to-apply pull-secret manifest for a cluster you manage yourself
- `GET /registry/handles/suggest`: Suggest a free, valid container-registry handle
- `GET /registry/repositories`: List your registry repositories
- `GET /registry/repositories/{repo}`: Get one repository and its tags
- `DELETE /registry/repositories/{repo}`: Delete an entire repository
- `DELETE /registry/repositories/{repo}/manifests/{digest}`: Delete a manifest by digest
- `DELETE /registry/repositories/{repo}/tags/{tag}`: Delete one tag
- `GET /registry/repositories/{repo}/tags/{tag}/vulnerabilities`: List CVE findings for one tag
- `GET /registry/tiers`: List container registry tiers and their prices
- `GET /registry/token`: Docker Registry v2 token endpoint
- `POST /registry/token`: Docker Registry v2 token endpoint (form-encoded)

## Firewalls

- `GET /firewalls`: List your cloud firewalls (security groups)
- `POST /firewalls`: Create a new firewall
- `GET /firewalls/{id}`: Get firewall detail including rules
- `DELETE /firewalls/{id}`: Delete a firewall (must be detached from all VMs first)
- `POST /firewalls/{id}/attach`: Attach a firewall to a cloud VM
- `POST /firewalls/{id}/detach`: Detach a firewall from a cloud VM
- `POST /firewalls/{id}/rules`: Add a rule to a firewall
- `DELETE /firewalls/{id}/rules/{ruleId}`: Remove a rule from a firewall

## Load balancers

- `GET /load-balancers`: List load balancers
- `POST /load-balancers`: Create an L4 load balancer
- `GET /load-balancers/{id}`: Get a load balancer
- `DELETE /load-balancers/{id}`: Delete a load balancer
- `GET /load-balancers/{id}/members`: List load balancer members
- `POST /load-balancers/{id}/members`: Add a member
- `DELETE /load-balancers/{id}/members/{mid}`: Remove a member

## Networks

- `GET /networks`: List VPCs
- `POST /networks`: Create a VPC
- `GET /networks/{id}`: Get a VPC
- `DELETE /networks/{id}`: Delete a VPC
- `POST /networks/{id}/vms`: Move a VM into this VPC

## Snapshots

- `POST /services/{id}/restore`: Restore a cloud VM from one of its snapshots
- `GET /services/{id}/snapshots`: List a cloud VM's snapshots
- `POST /services/{id}/snapshots`: Take a snapshot of a cloud VM
- `GET /snapshots`: List your snapshots
- `GET /snapshots/{id}`: Get a snapshot
- `DELETE /snapshots/{id}`: Delete a snapshot

## Volumes

- `GET /volumes`: List block volumes
- `POST /volumes`: Create a block volume
- `GET /volumes/{id}`: Get a block volume
- `DELETE /volumes/{id}`: Delete a block volume
- `POST /volumes/{id}/attach`: Attach a volume to a VM
- `POST /volumes/{id}/detach`: Detach a volume from a VM
