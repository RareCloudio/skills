<!-- Generated from RareCloud's published API, CLI, MCP and Terraform definitions. Do not edit by hand: changes are overwritten at the next refresh. To fix something here, open an issue. -->

# Prices and how billing works

This file holds no prices on purpose. They change, they depend on the account's currency, and a
figure remembered from training or an old page is how people get surprised by a bill. Read the
price at the moment you need it and say where it came from.

## Where each price lives

Catalog reads are public: they work without a token, so you can answer cost questions before the
person has an account.

- **Plans and sizes of any product:** `rarecloud:list_catalog_listings` for a category, then
  `rarecloud:get_catalog_plan` or `rarecloud:get_product_details` for one SKU. CLI:
  `rarecloud catalog plans <sku>` and `rarecloud catalog details <sku>`. API:
  `GET /catalog/listings/{category}` (categories such as `cloud-vm`, `cloud-k8s`,
  `cloud-volume`, `cloud-loadbalancer`, `cloud-reserved-ip`, `server`, `hosting`, `proxy`,
  `domain`) and `GET /catalog/products/{sku}/details`. Terraform: the `rarecloud_catalog_plan`
  and `rarecloud_product` data sources. The listings take a `currency` query parameter.
- **AI Sandboxes:** `rarecloud sandbox sizes` or `GET /sandboxes/sizes` give the price per hour
  of every size; `rarecloud:list_sandbox_templates` gives each template's price at its default
  size only. With a token, both answer in the account's currency.
- **Object Storage:** the catalog lists it as the product `object-storage` (kind
  `cloud_object_storage`). `rarecloud:get_catalog_plan` with that sku,
  `rarecloud catalog details object-storage`, or `GET /catalog/products/object-storage` return
  its price card under `metadata`; the API and CLI reads need no token. Once the service is enabled, `rarecloud:get_object_storage` shows
  the card in force for the account. The public page https://rarecloud.io/object-storage/ is a
  fallback only.
- **Container Registry:** `rarecloud:list_registry_tiers`.
- **Domains:** `rarecloud:get_tld_pricing` (register, transfer and renew per TLD).
- **Proxies:** `rarecloud:get_proxy_catalog`, and `rarecloud proxy mobile prices` for mobile lines.
- **What the account is spending now:** `rarecloud:get_billing_state` (month to date, burn per
  hour, how long the balance lasts), `rarecloud:list_invoices`, `rarecloud:get_credit_balance`.
- **Tax:** prices are net. `rarecloud:get_account` carries `taxRatePercent`, the VAT rate on this
  account's invoices (0 for reverse charge). Say whether a figure includes it.

Catalog amounts are in cents of the currency shown next to them: a monthly `amount` of 1234 is
12.34, and hourly amounts are fractions of a cent. Fields named `...Cents` or `..._cents` are
cents too. Divide by 100 before you quote anything, or the price comes out a hundred times too
high.

When you present a cost, give the figure with its currency, the period (hour or month), whether
tax is added, and the tool you read it from. For a plan the person is about to order, a monthly
estimate is clearer than an hourly rate alone.

## How the bill works

These are the rules of the model. The dates and amounts for a given account come from
`rarecloud:get_billing_state`.

- **Cloud resources** (Cloud VMs, Kubernetes worker pools, volumes, snapshots, load balancers,
  reserved IPs, Object Storage, the registry) are metered by the hour and invoiced monthly. A
  Cloud VM never costs more in a month than its plan's monthly price.
- **A resource is billed for as long as it exists**, running or stopped, even while the account
  is suspended. Only deleting it stops the meter. When the person wants to stop paying, say what
  has to be deleted, and that deleting is permanent.
- **AI Sandboxes** are billed per second while they run, and stop billing when deleted, when
  their lifetime ends, or, in run mode, when their program exits. A sandbox that never started
  is not billed.
- **A new account** needs a balance that covers a new cloud resource before it can create it.
  Once the account is established and nothing is overdue, creates need no balance and usage is
  invoiced afterwards. `rarecloud:check_order` tells you which case applies without creating
  anything.
- **Credit on the account pays a cloud invoice automatically.** An open invoice therefore means
  the credit did not cover it. Left unpaid, the account's cloud resources are powered off and
  later deleted, on dates `rarecloud:get_billing_state` reports (`suspendAt`, `deleteAt`).
- **Classic products** (classic VPS, hosting, proxies, domains) are prepaid for a fixed term and
  renewed by invoice. Most renew from the balance automatically unless the person turned that
  off (`rarecloud:get_service_autorenew` shows it for one service); proxies have their own
  auto-renew setting. A classic renewal never powers off a cloud resource.
- **Spend alerts:** `rarecloud:set_billing_alert` flags the month's spend passing a threshold,
  and can email the person daily while the balance would last fewer than a set number of days.
  Worth suggesting when someone starts running things by the hour.
