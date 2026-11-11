# Install in Gemini CLI, Antigravity and Grok

The skills in this repository follow the open Agent Skills format, so other coding agents can load them too. This page gives the install steps for three of them, taken from each tool's own documentation.

The MCP server needs a RareCloud API token, which you create in the console at https://console.rarecloud.io/account/api. Never paste it into a chat or commit it to a file. The skills work without it; only the MCP tools need it.

## Gemini CLI

Gemini CLI installs extensions from a GitHub repository. This repository ships a `gemini-extension.json` at its root, so one command installs both skills and the MCP server:

```bash
gemini extensions install https://github.com/RareCloudio/skills
```

Run it in your terminal, not inside a Gemini CLI session. During the install the CLI asks for the RareCloud API token and keeps it in your system keychain. You can change it later with `gemini extensions config rarecloud`, and pull a newer version with `gemini extensions update rarecloud`. Restart Gemini CLI after any of these.

If you only want one skill, without the MCP server:

```bash
gemini skills install https://github.com/RareCloudio/skills.git --path skills/ship-it
```

You can also copy a skill folder (for example `skills/ship-it`) into `~/.gemini/skills/` or `~/.agents/skills/` for every project, or into `.gemini/skills/` or `.agents/skills/` for one project.

Google's README says Gemini CLI is now meant for Gemini Code Assist Standard and Enterprise; free and Google AI Pro or Ultra users are pointed to the Antigravity CLI below.

We tested the skills in Claude Code only. These steps follow the Gemini CLI documentation and have not been run.

Documentation: https://geminicli.com/docs/extensions/reference/ and https://geminicli.com/docs/cli/skills/ (source: https://github.com/google-gemini/gemini-cli/tree/main/docs), read 2026-11-11.

## Google Antigravity

Antigravity installs plugins from a GitHub repository. This repository ships `.antigravity-plugin/plugin.json` and `mcp_config.json`, so the plugin brings both skills and the MCP server:

```bash
agy plugin install https://github.com/RareCloudio/skills
agy plugin enable rarecloud
```

The plugin installs disabled because its MCP server needs the token. `agy plugin enable rarecloud` asks for the token; in the Antigravity App you turn the plugin on under Customizations, Installed, which opens the same prompt. Check the result with `agy plugin list`.

If you only want the skills, copy a skill folder into `~/.gemini/config/skills/` for every workspace or into `.agents/skills/` in one project.

To add the MCP server by hand instead, put this in `~/.gemini/config/mcp_config.json` (or `.agents/mcp_config.json` in one workspace) and replace the placeholder with your token on your own machine:

```json
{
  "mcpServers": {
    "rarecloud": {
      "command": "npx",
      "args": ["-y", "@rarecloudio/mcp-server"],
      "env": { "RARECLOUD_API_TOKEN": "<your token>" }
    }
  }
}
```

We tested the skills in Claude Code only. These steps follow the Antigravity documentation and have not been run.

Documentation: https://antigravity.google/docs/plugins, https://antigravity.google/docs/build-plugins, https://antigravity.google/docs/skills and https://antigravity.google/docs/mcp, read 2026-11-11.

## Grok

Grok's documentation describes plugins and a `grok plugin install` command, but it does not publish a plugin manifest format of its own or the install syntax for a GitHub repository, so this repository ships nothing Grok-specific. The documentation does say Grok reads Claude Code plugins, marketplaces, skills and MCP servers with no extra setup, so if you installed this plugin in Claude Code, Grok should see it as well.

Without Claude Code, copy the skill folders by hand. For every project, put them in `~/.grok/skills/` or `~/.agents/skills/`; for one project, in `.grok/skills/`:

```bash
git clone https://github.com/RareCloudio/skills.git rarecloud-skills
mkdir -p ~/.grok/skills
cp -R rarecloud-skills/skills/rarecloud rarecloud-skills/skills/ship-it ~/.grok/skills/
```

To connect the MCP server, add this to `~/.grok/config.toml`. Grok expands `${RARECLOUD_API_TOKEN}` from your environment when it loads the file, so the token stays out of the config:

```toml
[mcp_servers.rarecloud]
command = "npx"
args = ["-y", "@rarecloudio/mcp-server"]
env = { RARECLOUD_API_TOKEN = "${RARECLOUD_API_TOKEN}" }
```

Run `grok inspect` to see which skills and MCP servers Grok found, and `grok mcp doctor rarecloud` if the server does not connect. The first `npx` start downloads the package, which may need a higher `startup_timeout_sec`.

We tested the skills in Claude Code only. These steps follow the Grok documentation and have not been run.

Documentation: https://docs.x.ai/build/features/skills-plugins-marketplaces, https://docs.x.ai/build/features/mcp-servers and https://docs.x.ai/build/cli/reference, read 2026-11-11.
