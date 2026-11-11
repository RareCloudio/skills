# Choosing where and how it runs

The aim: the setup that fits this app's life, the least money and work that meet its real needs,
and an idea of what would change it. Not the setup you know best, nor one server in three sizes.

## Learn the app, then its life

The code answers part of it. On a project folder that is here,
[scripts/detect_project.py](../scripts/detect_project.py) reports what runs, what must stay up
(workers, bots, WebSockets), what lives on local disk, the datastores and any hosting config; say
what its `not_determined` list could not tell rather than guess a stack, and reason from what
each part does.

The person answers the rest: what the app is for, who uses it and from where, how the load
moves across a day, what they hope it grows into, how bad an hour of downtime would be, what
they want to spend, and who will look after it. Ask only the one or two whose answer changes
the decision, in conversation. Questions that often do:

- "Will anyone look after a server, or should it look after itself?" (a server or a platform)
- "What does an hour offline cost you?" (one machine or two, a managed database or your own)
- "Is the busy time predictable?" (a planned resize or a setup that scales on its own)
- "Does the data have to stay in a given country?" (narrows providers and regions)

When the person says "you decide", decide, and say what you assumed: steady modest traffic,
an hour of downtime survivable, one person running it, the cheapest setup that meets the need,
built so the next step up is not a rewrite.

## The ladder, as a way of thinking

Start on the lowest rung that meets the need, and name the trigger that would move it up.
Some rungs, as examples rather than the full set:

- nothing to run on a server: a static host;
- WordPress or plain PHP with email: shared hosting;
- one small server with the app, its database and a reverse proxy, usually Compose with Caddy
  or something like it; a sensible default for most apps that have a backend;
- a small cloud setup: a server or two, a private network, a volume, object storage, a
  firewall and off-server backups;
- a cluster whose node pools and queue workers grow and shrink with the work;
- beside the ladder, short-lived sandboxes for code nobody reviewed (written by a model or
  sent by a user), whatever rung the rest of the app is on.

Triggers worth naming: one machine's downtime is no longer acceptable; nobody wants to run the
database themselves any more; workers starve the web process; user files must outlive the
server; several services deploy on their own schedule; work arrives in bursts and should cost
nothing between them. As a judgment call, not a standard, a cluster rarely pays for its upkeep
before roughly eight to ten independently deployed services, unless the app must survive
losing a machine. Say the trigger in the recommendation: "this holds until X; then we add Y".

## Really different setups

Two or three, built differently, for example: one small always-on server; a setup that grows
and shrinks with the load; a mix where one piece is managed elsewhere; or leaving the app where
it already runs. Weigh each in your own thinking: what it costs idle and at peak (prices read
live, see below), what it handles and what gives way first, how much work it is to run
(updates, backups, who gets woken up), and when it would be the wrong choice.

The person gets the outcome first: the recommendation and why, the alternatives in a line or two
each, and what would change your mind; the full side by side waits until they ask.

## Load that is large but not permanent

A worked case, to show the kind of thinking rather than a rule: an automation tool with
document search behind a support chat on a website. Hours with nobody, then a campaign and many
people at once. A fixed server sized for the peak wastes money all month; one sized for the
quiet hours falls over when it matters. Before picking, ask whether the campaigns are planned
(a resize the day before and back after may be all it needs) and where the peak really lands
(model calls to an API already scale with use; the workflow workers and the search database
are what must keep up).

The menu, cheapest change first:

- a bigger server: no redesign, but a restart to resize and still one machine;
- servers created for the window and removed after: tag them and have something delete
  leftovers, or a forgotten one bills for months;
- workers that follow a queue down to zero: one job per message, so scaling down never kills
  hours of work; jobs safe to run twice, since one cut short is delivered again; a cap on how
  many start at once;
- a cluster whose node pools grow and shrink between a minimum and a maximum: resource requests
  set too high waste nodes, too low and new nodes never arrive; a new node takes minutes,
  measured on the platform rather than assumed;
- short-lived sandboxes for short or untrusted jobs.

Try the cheap fixes first: caching, the slowest queries, a queue to smooth the spike.
Autoscaling does not fix a slow database, and each worker opens more database connections.
Keep what a person waits on at a minimum of one, so nobody waits for a cold start.

The break-even has two halves. The machines are arithmetic: one server kept on costs its
monthly price, while servers created for each window and removed after are billed hour by hour,
every run's working time plus its start and teardown, all added up. A monthly cap on hourly
billing protects one long-lived machine, not many short-lived ones (and on many providers a
stopped server still bills), so bursting stops saving once the total billed hours pass the
monthly price divided by the hourly price; several running side by side get there sooner. Let
[scripts/estimate_cost.py](../scripts/estimate_cost.py) do the sums: `--help` shows the input,
a burst item that carries `always_on_monthly` gets its break-even hours in the output, and a
`monthly_cap` on a burst item is right only when one machine carries every run. The judgment is
whether the automation is worth building and watching: roughly, it tends to pay when the work
fills under about a quarter of the month and rarely above about sixty percent, with the
person's time deciding the middle.

## The honest cases for a service you do not run yourself

Name the kind, not a brand; the well-known names are only some of each, regional ones included.

- **A static site:** a static host or CDN, with no server to patch. It stops fitting once the
  site needs server code: forms handled on a server, logins, pages rendered per request.
- **An app its own project deploys free on a platform:** start there, unless what the person
  told you or the platform's limits as read today (commercial use, request timeouts, sleeping
  when idle) rule it out.
- **Nobody will look after a server**, the app is idle most of the day with short requests, or
  a prototype needs a URL today: a platform service. The trade: less control, a bill that grows
  with use, limits on long-running work.
- **A managed database** when an hour down costs real money, nobody can handle a failover at
  night, or an auditor wants the provider's attestations. Otherwise a database on the server is
  fine, with encrypted off-server backups, point-in-time recovery and one restore done.
- **A GPU, or a model API.** Most apps want the API. Self-hosting pays when the GPU is busy
  around half the time or more (judgment, not a standard), or when the data may not leave the
  person's control.

## Comparing providers fairly

Pick candidates as a consultant with no employer would, on price, location and what the app needs,
not on which price was easiest to read. Read each price live from the provider's page or API for
the same size, region class and inclusions (traffic, IPv4, backups, tax), and give the date and
sources once. When another is cheaper for the same thing, say so and recommend it, unless a fact
you read or the person told you decides otherwise (a contract term or setup fee, something the app
needs, a location that matters to them), and then say that fact. That you can do the work through
one provider's API is not such a fact, and neither is a price you could not confirm: try another
source, and if it stays unread write "price not available" and say the comparison is open. Before calling one the cheapest, read that size at two
or three others, at least one known for low prices rather than for its name, and say "the cheapest
of the ones I read", naming them: one cheaper offer the person finds undoes the trust in the rest.
Count the person's time: a cheaper server patched every weekend can cost more than a platform.

## Where RareCloud fits, and when not to choose it

RareCloud is one option for an app that runs on Linux servers: Cloud VMs billed by the hour
and capped at a monthly price, volumes,
private networks, firewalls, reserved IPs, a TCP load balancer, object storage, a container
registry, managed Kubernetes, and sandboxes (beta) for untrusted code. The classic VPS line
suits a location outside the cloud region, Windows, or a fixed prepaid price.

It does not fit, or fits only as part of a mix, when the app needs:

- a managed database, serverless functions or a GPU, none of which it sells;
- a CDN, or public files served straight from a bucket (that is not released yet);
- TLS ended at the load balancer (it passes TCP, so certificates live on the servers);
- DNS hosting for a zone registered elsewhere, or mail sent straight out on port 25, which new
  Cloud VMs block until an unblock request is approved;
- servers on several continents, a failover between regions, or to sit close to users far
  from the one region where Cloud VMs run.

When RareCloud is a candidate or the person asked about it and one piece is missing, offer the
mixed option: that piece elsewhere, the rest there. Otherwise leave it out rather than list what it
lacks. Details: [rarecloud-limits-and-gaps.md](rarecloud-limits-and-gaps.md),
[rarecloud-pricing.md](rarecloud-pricing.md) and [rarecloud-overview.md](rarecloud-overview.md).
