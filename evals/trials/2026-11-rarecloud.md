# Trial log: the `rarecloud` skill, November 2026

Skill version 0.1.0. All sessions: Claude Code, model `sonnet`, started with `--setting-sources project --strict-mcp-config`, so no user settings or plugins were loaded. Real resources were created only on the dedicated test account.

## 1. Does the skill load when it should

The 20 requests in `evals/triggers/rarecloud.yaml`, one clean session each, with the skill in the project's `.claude/skills/` folder and only the `Skill` and `Read` tools allowed.

| | Loaded | Not loaded |
|---|---|---|
| 10 requests that should load it | 10 | 0 |
| 10 near misses that should not | 0 | 10 |

The description needed no tuning.

## 2. The same request, with and without the skill

The ten "should load" requests, each run twice in the same kind of clean session: once with the skill installed and once without. No MCP server in either; allowed tools `Skill`, `Read`, `WebFetch`, `WebSearch`. The raw answers and the blind key are kept privately by the maintainers and are not in this repository; they are the model's words, not RareCloud statements, and any price in them was the model's recollection.

A separate agent graded the ten pairs blind (answers labelled A and B in random order) on correctness for this provider, a useful next step, honest limits, and tone and length.

| Request | Preferred | Why |
|---|---|---|
| 4 GB server with SSH access | with skill | Asks only what matters, promises the price before creating |
| Cost of a bucket for about 200 GB | with skill | Specific terms; the other is thin and hedges |
| Deploy a small FastAPI app | with skill | A concrete plan |
| Connect the MCP server to Claude Code | with skill | Exact package, variable and steps; the other says it knows nothing |
| A VM cannot send mail | with skill | Knows the port 25 policy and the unblock steps |
| Quota for a cluster with 6 workers | tie | Neither can check without tools |
| Run an untrusted script in a sandbox | with skill | Knows the product, offers to run with the network off |
| Terraform: one VM, a volume, only 443 open | with skill | A real configuration, and a warning that the default firewall keeps 22 and 80 open |
| Start a VM in the cloud region | tie | Both blocked without tools |
| PERMISSION_DENIED on server create | with skill | Exact diagnosis: a missing scope |

With skill 8, tie 2, without skill 0.

Without the skill, the agent said it did not know the provider's port 25 policy, did not find the Terraform provider, and suggested CLI commands that do not exist.

**What the grader criticised in the skill's answers:** two are dense (the bucket cost and the mail answer), and one ends with a question the person had already answered. None read like an advertisement.

## 3. Real trials on the test account

Skill plus the MCP server (pinned 0.6.0), token from the environment, allowed tools `Skill`, `Read` and the MCP tools. A snapshot of the account was taken first with the maintainers' cleanup script (kept outside this repository).

**Price question.** "What is the cheapest RareCloud cloud server with at least 4 GB of memory, and what does it cost per month?" The agent loaded the skill, read the catalog through the MCP server and answered with the plan and price. Both match a separate read of the public catalog. It also said it had not compared the classic VPS line.

**Create a server.** "Create the smallest cloud VM with Ubuntu 24.04, call it skills-trial-1, and put this SSH key on it. Tell me the IP when it's ready." The agent created the smallest plan in the cloud region with the key, reported the IP, the plan, the cost per hour and the monthly cap, said the console password was returned once and does not work over SSH, and reminded that a stopped VM still bills. A login over SSH as `root` with the key worked about two and a half minutes after the create call.

What was not ideal:
- The agent created the server without showing the cost first. The request was explicit and one-shot; the cost was reported afterwards.
- It reported the server before it could confirm it was reachable (it had no shell in this session), and said so.
- It was unsure whether the login user is `root` or `ubuntu`. It is `root`.

**Cleanup.** The first `reap` failed safely: `server destroy` needs `--yes`, the cleanup script did not send it, nothing was deleted and the run ended "not clean". The server was deleted by hand and confirmed gone. The script now reads each delete command's help and adds `--yes` only where it is supported. A dry run after the fix lists nothing to delete.

The platform creates a default network on the first VM and refuses to delete it. The cleanup script skips it by the API's own marker.

## 4. Plugin

Loading the repository as a Claude Code plugin in a clean session: the plugin `rarecloud` 0.1.0 loaded, its MCP server connected with the token taken from the environment (224 tools), and the skill appeared.

## 5. Changes this trial calls for in the skill

- State that the login user on a Cloud VM is `root`.
- Read the Object Storage price from the public catalog (`/catalog/products` lists it); the skill currently points to the public page.
- A line on length and on not asking what the person already said.
- Decide whether an explicit one-shot "create X" request should still show the price first. Decided since: an exact request to create a named thing is the person's yes; the agent reads the price first and states it as it acts, and stops to ask when the cost is more than small, recurring in a way the person may not expect, or not what they asked for.
