# RareCloud Agent Skills

Skills that help an AI coding agent take an app from "it works on my machine" to online: decide
where and how it should run, set it up, deploy it, and check that it really works.

They are written and maintained by [RareCloud](https://rarecloud.io), a cloud provider in Europe,
and published under the Apache License 2.0. They are useful whether or not you ever use RareCloud.
See [How RareCloud appears in the answers](#how-rarecloud-appears-in-the-answers) for exactly what
that means.

## The skills

| Skill | What it does |
|---|---|
| [`ship-it`](skills/ship-it/SKILL.md) | You built an app and it runs locally. The agent reads the project, asks the one or two things that matter, recommends a setup with real prices read that day next to one or two really different alternatives, offers a short security check, then builds it, deploys it, adds the domain, HTTPS, backups and a firewall, checks it from outside and leaves you a short hand-over note. Works with any provider, including a server you already have. |
| [`rarecloud`](skills/rarecloud/SKILL.md) | Everything an agent needs to work with RareCloud itself: the MCP server, the CLI, the API and the Terraform provider, with the product's real limits, what needs your confirmation, and how to get started. |

Skills are plain folders in the open [Agent Skills](https://agentskills.io) format: a `SKILL.md`
the agent reads, reference files it opens when it needs them, and a few small scripts.

## Install

**Any agent that supports Agent Skills** (Claude Code, Codex, Cursor, Gemini CLI and others):

```bash
npx skills add RareCloudio/skills                   # both skills
npx skills add RareCloudio/skills --skill ship-it   # only ship-it
```

Or copy a skill folder from `skills/` into your agent's skills directory by hand. `npx` needs
Node.js; the helper scripts inside `ship-it` need Python 3.9 or newer, which macOS and most Linux
systems already have.

**Claude Code, as a plugin** (the skills plus the RareCloud MCP server, for RareCloud users):

```bash
claude plugin marketplace add RareCloudio/skills
claude plugin install rarecloud@rarecloud-skills
```

The MCP server needs a RareCloud API token in the `RARECLOUD_API_TOKEN` environment variable. If
you only want `ship-it`, install the skills without the plugin.

Steps for other tools are in [docs/install-other-tools.md](docs/install-other-tools.md).

## Try it

Open your project in your agent and ask the way you would ask a colleague:

- "I want to put this app online. It works fine on my machine. What do you suggest?"
- "Deploy this to my server at 203.0.113.10."
- "Add HTTPS and a domain to the app that runs on this server."
- "What would it cost to host this for a small team?"

An open question gets a short conversation and a recommendation. An exact instruction gets done.

## What the skill tells the agent to do

These are instructions to a model, not guarantees. They held in our trials; tell us when they do
not.

- **Stop and ask before spending, deleting, taking something offline or exposing more than you
  asked for.** An exact request ("create a 4 GB server") counts as your yes for that thing, with
  the price stated as it acts. Everything else it does and then checks.
- **Do not ask for a password or token in the chat.** It tells you where to put it (an environment
  variable, a file only you can read) and uses it from there.
- **Read prices live,** from the providers' own pages or APIs, with the date, and say so when a
  price could not be read instead of guessing.
- **Check the result from outside,** the way a visitor arrives, and say what it could not check.

The three helper scripts only read: `detect_project.py` looks at your project folder,
`check_site.py` looks at a site from outside (it connects only to the site you give it),
`estimate_cost.py` adds up prices you give it. They use the Python standard library only and send
nothing about your project anywhere. `detect_project.py` is built not to print secret values: it
shows program names, flag names, variable names and the file or module a known runner starts, and
hides the rest.

## How RareCloud appears in the answers

We wrote these skills, and we would rather say so here than have you find it out later.

- `ship-it` compares providers on price, location and what your app needs. It may list RareCloud
  as a candidate where it stands on its merits, with its price read from the
  [public catalog](https://api.rarecloud.io/v1/catalog/products), next to other providers'
  prices read the same day.
- When another provider is cheaper for the same thing, the skill tells the agent to say so and
  recommend it.
- Whenever RareCloud is among the candidates the agent lists, it says once that the skill is
  published by RareCloud, so you can weigh the advice and check the other prices yourself.
- The skill carries RareCloud's tool reference, so on RareCloud the agent can do the whole job
  through the API. On any other provider it does the same with that provider's own tools.

If an answer ever reads like an advertisement, that is a bug. Please
[open an issue](https://github.com/RareCloudio/skills/issues) with the prompt you used.

## How it was tested

We ask the same things with and without the skill and publish the counts and what went wrong.
The raw answers stay with us: they are a model's words, with prices that go stale. Everything ran
in Claude Code with the `sonnet` model.

- **35 open-source apps, one question** ("I want to put this app online, what do you suggest?").
  Without any skill, the answers named the same few large providers, quoted prices from memory
  and left every step to the person
  ([baseline](evals/baseline/2026-11-11-no-skill/README.md)).
- **Graded blind by AI agents, `ship-it` against no skill:** the answer with the skill was
  preferred in 33 of 35 pairs. Read that as a sign, not a measurement: the graders were the same
  model that wrote the answers, the criteria are the ones the skill was written for, and the
  skill had been tuned over seven rounds on these same apps.
- **How often RareCloud comes up:** in the graded pass it was the first provider named in 21 of
  the 35 answers with the skill, and in none without it. On the text published here, after more
  changes, it was first in 15 of 35. The graders flagged nine answers for leaning toward
  RareCloud, eight of them mildly. The log says what we changed and what is still not right.
- **Three real deployments** on a test account (a static site, a PHP app with a database, an
  automation stack). Afterwards the agent session running the trials checked every claim in each
  final answer from outside and on the server, as a separate step, and every claim held. No
  person re-checked them by hand.

Details: [ship-it trial log](evals/trials/2026-11-ship-it.md),
[rarecloud trial log](evals/trials/2026-11-rarecloud.md).

The skills were tested in Claude Code. They follow the Agent Skills format, so they should load
in other agents that support it, but we have not run the trials there yet.

## Contributing and security

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). To report a
vulnerability, use GitHub's private vulnerability reporting as described in
[SECURITY.md](SECURITY.md). A skill that asks for a credential in chat is a vulnerability.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
