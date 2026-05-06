# /handoff

Captures the current AI coding session into a portable markdown briefing. A new session — on any host (Claude Code, Copilot CLI, etc.), machine, or environment — can read the file and resume where you left off.


----

> 🤖 LLM WARNING 🤖
>
> This project was written with LLM (AI) assistance.
>
> 🤖 LLM WARNING 🤖

----

## When to use

- Migrating between environments (containers, local machine, CI)
- Ending a session with unfinished work
- Handing off to a colleague's session
- Checkpointing task progress, decisions, and next steps

## Usage

```
/handoff
```

The skill writes a structured briefing to `.claude/handoff/state.md` (gitignored) containing:

- Mission: what you're building and why
- Plan & Progress: full task list with statuses
- Key Decisions: settled choices with rationale, so the next session doesn't re-debate them
- Blockers & Failed Approaches: what was tried and didn't work
- Key Files: orientation for the codebase
- Git State: branch, uncommitted changes, recent commits
- Environment: OS, runtimes, installed tools
- Next Steps: concrete actions to take immediately

### Verification

The skill runs a 3-step verification:

1. Self-review: re-scans the conversation for missed decisions, blockers, and context
2. Dry-run: spawns a fresh subagent to read the handoff cold and report gaps
3. Patch: fixes any issues found before finalizing

### Resuming

To resume in a new session:

```
Read .claude/handoff/state.md and continue where the previous session left off.
```

No special skill needed on the receiving end. The file is self-contained.

## Installation

This project is a [lola](https://lobstertrap.org/lola/) module — an [agentskills.io](https://agentskills.io/specification)-compliant skill (at `module/skills/handoff/`) plus a slash-command wrapper (at `module/commands/handoff.md`). Lola is the supported way to install it; it handles the skill *and* the `/handoff` command together, and works across multiple AI assistants.

### Install lola

See the lola [homepage](https://lobstertrap.org/lola/) for current install instructions. As of this writing:

```bash
uv tool install git+https://github.com/LobsterTrap/lola
```

### Install this module

```bash
# From a clone of this repo:
lola mod add -n handoff ./
lola install handoff                              # interactive picker for assistant + scope
lola install handoff -a claude-code --scope user  # non-interactive example
```

Supported assistants: `claude-code`, `cursor`, `gemini-cli`, `openclaw`, `opencode`. See `lola install --help` for all flags (scope, force-overwrite, project path, etc.).

The repo's `Taskfile.yml` wraps `lola install` / `lola uninstall` with sensible defaults for this skill — `-a claude-code --scope user` — so a plain `task install` puts handoff in `~/.claude/` (globally available, no per-project clutter). Pass `-- <flags>` to override:

```bash
task install                                      # default: -a claude-code --scope user
task install -- -a cursor --scope user            # override: install for cursor instead
task install -- -a claude-code --scope user -f    # force-overwrite (re-install after edits)
task install -- -a claude-code --scope project    # opt into project scope if you really want it
```

### Update after source changes

Lola **copies** files at install time — it does not symlink. After editing the skill or command in this repo, re-run install with `-f` to overwrite the previous copy.

### Uninstall

```bash
lola uninstall handoff -a claude-code --scope user   # remove installed files
lola mod rm handoff                                  # remove from lola's registry
```

Or just `task uninstall` — it runs both steps so it's a complete inverse of `task install`. Override defaults the same way as install (`task uninstall -- -a cursor --scope user`, etc.).

## How it works

The `/handoff` slash command is the only way the skill is meant to be invoked — it's an explicit, user-initiated checkpoint. The slash command body activates the `handoff` skill, which contains the actual workflow. This split keeps the trigger user-controlled (slash commands cannot be auto-invoked by the model) while keeping the workflow logic in a single agentskills.io-compliant SKILL.md.

## Development

Requires [Task](https://taskfile.dev) and Python 3.

```bash
task validate          # Lint + structural tests (fast, no API calls)
task eval              # Functional evals via claude -p (~10 min, requires claude CLI)
task eval:latest       # Show latest eval dashboard
task eval MODE=llm     # Errors-only output for CI
```

`task validate` checks skill structure (frontmatter, required sections), eval schema (types, patterns, scaffolding), and README accuracy. `task eval` creates temp repos, runs the skill via `claude -p`, and grades outputs with deterministic checks (file exists, pattern grep) plus LLM-as-judge for content quality. Results go to `handoff-workspace/<timestamp>/`.
