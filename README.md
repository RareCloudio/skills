# RareCloud Agent Skills

Skills that turn your coding agent into a DevOps engineer. It sets up and secures Linux servers,
deploys your app to a server or a Kubernetes cluster, writes the configs, and fixes things when
they break. Works on any provider, including a server you already have.

```bash
npx skills add RareCloudio/skills                   # both skills
npx skills add RareCloudio/skills --skill devops    # only devops
```

Installs in Claude Code, Codex, Cursor, Gemini CLI and any agent that supports
[Agent Skills](https://agentskills.io). `npx` needs Node.js.

## Try it

Open your project and ask the way you would ask a colleague:

- "Put this app online."
- "Secure my new VPS."
- "Add a domain and HTTPS."
- "Write a Dockerfile and a Compose file for this project."
- "Deploy this to my Kubernetes cluster."
- "Set up deploys from GitHub Actions."
- "Set up nightly backups and test a restore."
- "My site is down."

## What it does

| | The agent can |
|---|---|
| **Deploy** | Read your project, pick the setup that fits (one server, several behind a load balancer, or Kubernetes), build it, deploy it and check it from outside |
| **Servers** | Harden a new Linux server: SSH keys, firewall, automatic updates, a non-root user, with a way back in at every step |
| **Web** | Put Caddy or nginx in front of your app, with a domain, HTTPS and renewals |
| **Containers** | Write the Dockerfile and the Compose file, with health checks, restarts and log rotation |
| **Kubernetes** | Write the manifests, set up the Gateway API or an ingress with certificates, roll out and roll back, and find out why a pod will not start |
| **CI/CD** | Deploy on every push, with a health check after and a rollback when it fails |
| **Backups** | Back up files and databases off the server, and prove a restore works |
| **Monitoring** | Set up alerts for a site that is down, a disk that fills up or a certificate about to expire, and read the logs |
| **Debugging** | Find out why the site is down or slow: DNS, certificate, proxy, app, database, disk, memory |
| **Cost** | Size the setup for your app and read today's prices before anything is created |

Every config it writes is checked with the real tool before you get it, and every deploy is tested
from outside. When a check could not run, it says which one. It tells you the price before it
creates anything that bills, and asks before it deletes something or does anything that could take
a live site offline.

## On RareCloud

With a [RareCloud](https://rarecloud.io) account and an API token the agent does the whole job by
itself: it creates the server or the cluster, the network, the firewall and the load balancer,
then deploys. The Claude Code plugin brings both skills, `devops` and `rarecloud`, and the
RareCloud MCP server, so there is nothing to click through:

```bash
claude plugin marketplace add RareCloudio/skills
claude plugin install rarecloud@rarecloud-skills
```

The MCP server reads the token from the `RARECLOUD_API_TOKEN` environment variable.

## Skills

| Skill | Use it for |
|---|---|
| [`devops`](skills/devops/SKILL.md) | Everything above, on any provider |
| [`rarecloud`](skills/rarecloud/SKILL.md) | RareCloud itself: MCP server, CLI, API and Terraform provider |

Steps for other tools are in [docs/install-other-tools.md](docs/install-other-tools.md).

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Security reports:
[SECURITY.md](SECURITY.md).

## License

Apache License 2.0. Made by [RareCloud](https://rarecloud.io).
