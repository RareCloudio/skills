<!-- Generated from RareCloud's published API, CLI, MCP and Terraform definitions. Do not edit by hand: changes are overwritten at the next refresh. To fix something here, open an issue. -->

# Getting started on RareCloud

The goal: the person has an account, an API token scoped to the job and stored where the tools
read it, and enough funds when the account needs them. Three steps need the person: create the
account, create an API token, add funds. Everything after that you can do with the tools.

## What you can check yourself

- If `rarecloud:` MCP tools are in the session, a token exists. `rarecloud:get_account` shows
  which account it belongs to.
- With the CLI, `rarecloud auth whoami` prints the email of the token's owner.
- To see whether an environment variable is set without printing it:
  `test -n "$RARECLOUD_TOKEN" && echo set`.
- Public catalog reads need no token at all, so you can show plans, regions, images and prices
  before the person has an account, for example `GET https://api.rarecloud.io/v1/catalog/listings/cloud-vm`.

## 1. Create the account (the person, in a browser)

The person signs up at https://console.rarecloud.io/register. You cannot do this for them: it
is their identity, their email address and their payment relationship. If they later see that
their email is not verified, `rarecloud:resend_email_verification` sends the email again (it
needs `account:write`).

## 2. Create an API token (the person, in the console)

In the console: **Account, then API tokens, then New token**; the direct page is
https://console.rarecloud.io/account/api. They give it a name, pick its
scopes, and can set an expiry date and a rate limit. The token starts with `rc_pat_` and is
shown once.

Only a signed-in console session can create a token, so a token can never mint a stronger one.
That is why this step stays with the person.

Help them pick scopes for the job at hand. A narrow token is the safer default for an agent;
they can make another later.

- Reading and reporting: `account:read`, `services:read`, `billing:read` (add `domains:read`
  or `tickets:read` when those matter).
- Creating and changing cloud resources: add `services:write`.
- Changing the profile, the account's SSH keys or its contacts, or resending the verification
  email: add `account:write`.
- Domains: `domains:read` and `domains:write`. Support tickets: `tickets:read` and
  `tickets:write`.
- `billing:write` lets a client set spend alerts, redeem vouchers, create top-up links and pay
  invoices from the balance. Suggest it only when the person wants that.

Scopes match exactly: `services:write` does not include `services:read`, so an agent that reads
and acts needs both. An expiry date is a good habit for a token an agent holds.

### Where the token goes (the person puts it there)

Tell the person where to put it; do not take it through the chat.

- **MCP server** (`@rarecloudio/mcp-server`, needs Node.js 21 or newer). It reads
  `RARECLOUD_API_TOKEN`. In Claude Code the person runs, in their own terminal:
  `claude mcp add rarecloud -e RARECLOUD_API_TOKEN=<their token> -- npx -y @rarecloudio/mcp-server`
  (add `-s user` for every project). Claude Desktop, Cursor and Windsurf take the same server
  in their JSON config, with the token under `env`. The client usually has to reload before
  the tools appear; until then the CLI or the API can do the work.
- **CLI and Terraform** read `RARECLOUD_TOKEN`, a different name from the MCP server's. The
  person can export it in their shell profile, or run `rarecloud auth login` and paste it
  there, which saves it to a file only they can read. Terraform takes it from the same
  variable; keep it out of `.tf` files.
- Installing the CLI: `brew install rarecloudio/tap/rarecloud`, or a release from
  https://github.com/RareCloudio/rarecloud-cli/releases. The Terraform provider is
  `rarecloudio/rarecloud` on the Terraform Registry.

If the person pastes a token into the chat anyway, do not repeat it, and suggest they revoke it
(Account, then API tokens) and make a new one, since the conversation now holds it.

## 3. Add funds (the person pays)

Whether money is needed now depends on the account. A new account needs a balance before it can
create cloud resources; an established one with nothing overdue is invoiced for what it used.
Do not guess: `rarecloud:check_order` (or `rarecloud server check`, or
`POST /services/preflight`) says whether an order would be accepted, creates nothing, and on a
refusal returns the add-funds or pay-invoice link. Give the person that link.

With `billing:write`, `rarecloud credit top-up --amount <amount>` creates a top-up invoice and
prints its payment link; it charges nothing until the person pays. An unpaid invoice has its own
link from `rarecloud invoice checkout-url <invoice-id>`. You never handle card or bank details.
Once they have paid, `rarecloud:get_credit_balance` shows the new balance.

## Then

Confirm with `rarecloud:get_account` and `rarecloud:get_quota_limits`, and carry on with what the
person asked for.
