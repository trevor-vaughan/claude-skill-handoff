# handoff

Portable session-state capture for AI coding sessions. Lets you end a session and resume in a different Claude session, container, machine, or even a different agent host without losing context.

## What this module provides

- **`handoff` skill** — captures the active session into `.claude/handoff/state.md`: a self-contained briefing covering mission, plan, progress, key decisions, blockers, failed approaches, key files, git state, environment, and next steps.

The skill is invoked explicitly (`/handoff` in Claude Code, or by activating the skill by name in any spec-compliant host). It does not auto-trigger on its own — handoff is always a deliberate user action at a checkpoint.

## When to use

- Migrating work between environments (containers, local machine, CI)
- Ending a session with unfinished work
- Handing off to a colleague's session
- Checkpointing progress and decisions before a risky step

## Output contract

The skill writes a single file: `.claude/handoff/state.md` in the project root. The skill ensures `.claude/handoff/` is gitignored before writing, so briefings are never committed.

## Resuming

A receiving session needs no special skill. It reads `.claude/handoff/state.md` directly:

```
Read .claude/handoff/state.md and continue where the previous session left off.
```

The briefing is self-contained — it does not depend on memory, conversation history, or external systems beyond the project repository it lives in.

## Notes for AI assistants

- The handoff briefing must be portable. Do not write paths, identifiers, or references that only make sense in the originating session.
- Verify completeness before declaring success: re-scan the conversation for missed decisions, then dry-run the briefing through a fresh subagent and patch gaps.
