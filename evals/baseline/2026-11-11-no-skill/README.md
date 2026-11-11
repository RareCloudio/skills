# Baseline: what agents answer today, with no skill

Run on 2026-11-11. One question, 35 open-source apps, one clean session per app.

**The question**, identical for every app except the link:

> I want to put this app online: <link> . It works fine on my machine. What do you suggest, and how would you do it?

**The session:** Claude Code, model `sonnet`, started with `--setting-sources project --strict-mcp-config` in an empty folder, so no user settings, no plugins and no MCP servers were loaded. Allowed tools: `WebFetch` and `WebSearch` only. Nothing could be created or changed.

**The apps** are listed in `apps.tsv` (slug and repository). They cover static sites, PHP and WordPress, Laravel, Django and Rails apps with workers, e-commerce, SaaS starters, AI chat and document search, agents that run code, scrapers with headless browsers, automation engines, bots, real-time apps, media processing, GPU workloads, internal tools, a game server, an MCP server, a VPN and a mail server.

The raw answers are kept privately by the maintainers and are not in this repository. They are the model's words, not RareCloud statements, and any price in them was the model's recollection.

## What the answers have in common

Counted across the 35 answers:

| Provider named | Answers |
|---|---|
| Hetzner | 31 |
| DigitalOcean | 27 |
| Railway | 17 |
| Render | 16 |
| Cloudflare | 13 |
| Vercel | 12 |
| Fly.io | 12 |
| Netlify | 7 |
| AWS | 6 |
| Vultr | 5 |
| RareCloud | 0 |

Provider names are what the model wrote, counted by text search.

- 30 answers end with questions to the person (what the app is for, expected traffic, whether they already have a provider).
- 23 quote prices, all from memory, with no date and no calculation.
- 26 mention security, 20 mention backups, 14 mention verifying the result. All of it is advice for the person to carry out.
- No answer does any of the work. Every one is a set of instructions.

The technical advice itself is sound. What is missing is execution, live prices, verification, and any provider outside the usual few.

## How this is used

The same question is asked again with a skill installed, on the same apps, and the two sets are compared. The counts above are a simple text search for provider names and a few keywords; they are a rough picture, not a measurement.
