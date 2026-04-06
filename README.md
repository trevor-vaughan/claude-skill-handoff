# /handoff

Saves current Claude session state into a portable markdown briefing. A new session, on any machine or environment, can read the file and resume where you left off.

## When to use

- Migrating between environments (containers, local machine, CI)
- Ending a session with unfinished work
- Handing off to a colleague's Claude session
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

Copy the `.claude/skills/handoff/` directory into your project's `.claude/skills/` directory:

```bash
# From within your project
mkdir -p .claude/skills
cp -r /path/to/this-repo/.claude/skills/handoff .claude/skills/handoff
```

Or install globally (available in all projects):

```bash
mkdir -p ~/.claude/skills
cp -r /path/to/this-repo/.claude/skills/handoff ~/.claude/skills/handoff
```

The skill is a single file (`.claude/skills/handoff/SKILL.md`) with no dependencies.

## Development

Requires [Task](https://taskfile.dev) and Python 3.

```bash
task validate          # Lint + structural tests (fast, no API calls)
task eval              # Functional evals via claude -p (~10 min, requires claude CLI)
task eval:latest       # Show latest eval dashboard
task eval MODE=llm     # Errors-only output for CI
```

`task validate` checks skill structure (frontmatter, required sections), eval schema (types, patterns, scaffolding), and README accuracy. `task eval` creates temp repos, runs the skill via `claude -p`, and grades outputs with deterministic checks (file exists, pattern grep) plus LLM-as-judge for content quality. Results go to `handoff-workspace/<timestamp>/`.
