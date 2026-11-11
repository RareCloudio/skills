# Before it goes public

Whatever is wrong with the app ships with it. A secret in the repository, a package with a
known hole or a debug page becomes public the moment the app has an address, and automated
scanners find new addresses within hours. A short review before the first deploy is the
cheapest time to catch these, so offer one, in a line with that reason, as a suggestion rather
than a gate:

> Before this goes online I'd like to spend a few minutes checking it for the usual problems:
> secrets in the code, packages with known holes, debug settings. Shall I?

If the person says no, go ahead, and list "security review: not done" in the hand-over. If
they asked only for one change to something already running, do not turn it into an audit;
mention a problem you happen to see.

## What a review looks at

Examples to start from; the app in front of you will suggest others.

- **Secrets:** committed `.env` files, keys in the git history (deleting the file does not
  remove it from history), secrets compiled into a client bundle through a public variable
  prefix, secrets baked into an image layer or passed as build arguments.
- **Dependencies:** the ecosystem's own audit tool where there is one (`npm audit`,
  `pip-audit`, `composer audit`, `bundle audit`, `cargo audit`, `govulncheck`), and an image
  scanner for containers.
- **Settings:** debug mode on in production, default admin passwords, wide-open CORS together
  with credentials, session cookies without the secure flags.
- **Who may read and change data:** database access rules on a hosted database (row-level
  security left off is common in generated apps), endpoints that act on an id without checking
  who owns it, uploads that can end up executed.
- **What the app itself opens:** an admin or metrics page, a database port bound to every
  interface, a container port published past the host firewall.
- **Code the app runs that nobody wrote by hand:** model output or user scripts belong in a
  sandbox, never in the app's own process with its credentials.

When you are not sure whether a version of a package or a piece of server software has known
problems, look it up (the ecosystem's advisory database, the project's security page, a CVE
search) rather than trusting memory, which is out of date by definition.

## What to do with what you find

Fix what is safe and small and say you did: a debug flag, a missing ignore entry, a patch
upgrade with the tests still passing. Report the rest by severity, in plain words: what someone
could do with it, how likely that is, and what the fix costs. The person decides on those.

Do not hold a deploy on trivia; a missing header is a note for later. Do stop for the few
things that would hurt on day one: a live secret in the code or the bundle, data anyone can
read or change, an admin screen with a default password.

A secret that was ever committed or shipped counts as leaked. Removing it is not enough; it
needs replacing at its source, which is usually the person's job in that provider's console,
so tell them which one and why. While reviewing, refer to secrets by name and file, and keep
their values out of the chat.

## The baseline for whatever gets built

Goals, each with its reason. How you reach them depends on the setup: on a server you do it
yourself, on a platform most of it is the platform's job and you check it.

- **Only the intended ports reachable from the internet.** Every open port is something to
  attack. Check from outside, because a container runtime can publish ports past the host
  firewall, and a provider's default firewall may admit more than you think
  ([rarecloud-overview.md](rarecloud-overview.md) has RareCloud's case under its traps).
- **No password logins.** Password guessing never stops on a public address; keys only, for
  SSH and for anything else that offers it. When changing SSH or firewall rules on a running
  server, keep a second session open and test the configuration before reloading, so a mistake
  does not lock everyone out.
- **Updates applied,** and security updates applied on their own. Most break-ins use holes
  that already had a fix.
- **Secrets out of the repository and out of images.** Repositories get cloned and images get
  pushed. Keep secrets in a file only the service can read, or the platform's secret store,
  and give the app and the agent tokens with only the rights they need.
- **Backups that have been restored once,** kept off the server and encrypted. A backup nobody
  has restored is a hope, and replication copies a mistake as fast as it copies data.
- **Admin screens not public.** Hosting panels, database consoles and automation editors are a
  common way in. Put them behind a VPN or an SSH tunnel, or at the least an address allowlist
  and a login.
- **HTTPS on everything public,** with certificates that renew on their own.

## The firm part

Making something reachable from the internet is not undone by closing it later: whatever was
read in between is gone. What the person asked to put online, usually the web ports, is covered
by the request: open it and say so as you do. Anything beyond that, such as another port, a
public bucket, an admin screen or a credential handed out, waits for the person's yes, after
you say what becomes reachable and to whom.
Changing SSH or the firewall on a server that is serving people can take it offline, so ask
whether it is in use and keep a way back. The rest of the baseline is ordinary good practice:
do it, and mention it in the hand-over.
