---
name: handoff
disable-model-invocation: true
description: >-
  Save current session state for resuming in a new Claude session. Invoked
  explicitly via /handoff slash command. Use when migrating between environments
  (containers, machines), ending a session with unfinished work, or whenever you
  need a portable snapshot of the current task, progress, decisions, and next
  steps.
---

# /handoff — Portable Session State Capture

## Overview

This skill captures the current session state into a self-contained markdown briefing that a fresh Claude session can use to resume work without losing context. The briefing must be portable: it cannot depend on conversation history, memory entries, or anything outside the file itself and the repository it lives in.

Flow:

1. Gather state from conversation context, git, filesystem, and environment.
2. Write draft briefing to `.claude/handoff/state.md` inside the project root.
3. Verify completeness: self-review the conversation for gaps, then spawn a subagent to dry-run the handoff and report what's missing or unclear. Patch any gaps found.
4. Ensure `.claude/handoff/` is in `.gitignore` so the briefing is never committed.
5. Tell the user where the file is and how to resume.

## Gathering State

Collect information from four sources. Synthesize; do not dump raw output.

### From conversation context

- Mission: What is the user trying to accomplish? One or two sentences.
- Plan & progress: If a task list or implementation plan exists, reproduce it IN FULL with status for every item (done, in-progress, blocked, not-started). Do not summarize or truncate the list.
- Key decisions: Frame as "We decided X because Y." Include architectural choices, library selections, naming conventions, and anything a new session would otherwise re-debate.
- Blockers & failed approaches: What was tried and didn't work, and why. This prevents the next session from repeating mistakes.
- Next steps: Concrete and specific. Not "continue implementation" but "implement the validation logic in `src/validator.go` per the spec in `docs/validation.md`."

### From git

Run these commands and synthesize the results:

- `git rev-parse --show-toplevel` (project root)
- `git branch --show-current` (current branch)
- `git status --short` (uncommitted changes)
- `git log --oneline -10` (recent commits)
- `git diff --stat` (unstaged diff summary)

### From filesystem

Identify key files and their roles. This is orientation, not inventory: list the files that matter for understanding the project and resuming work. Include files created or heavily modified during the session.

### From environment

- OS and version (e.g., from `/etc/os-release`)
- Language runtimes and versions (node, python, go, rust, etc.), only those relevant to the project
- Tools installed during this session (anything you `dnf install`'d, `pip install`'d, etc.)
- Project dependency files (`package.json`, `go.mod`, `Cargo.toml`, `requirements.txt`, etc.)

## Document Template

Write the briefing to `.claude/handoff/state.md` using this exact structure:

````markdown
# Handoff: [Project Name]

> **Generated**: [ISO 8601 timestamp]
>
> **To resume**: Open a new Claude session in this repository and say:
> "Read `.claude/handoff/state.md` and continue where the previous session left off."

## Mission

[One or two sentences describing the goal.]

## Plan & Progress

[Narrative summary of where things stand.]

| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Example task | done | Completed in commit abc1234 |
| 2 | Another task | in-progress | Blocked on X |
| 3 | Future task | not-started | — |

## Key Decisions

- **[Decision]**: [Rationale]. Example: "We chose SQLite over PostgreSQL because this is a single-user CLI tool with no concurrent access requirements."

## Blockers & Failed Approaches

- **[What was tried]**: [Why it failed and what to do instead.]

## Key Files

| Path | Role |
|------|------|
| `src/main.go` | Entry point |
| `docs/spec.md` | Requirements spec |

## Git State

- **Branch**: `feature/foo`
- **Recent commits**:
  ```
  abc1234 feat: add validation logic
  def5678 chore: scaffold project
  ```
- **Uncommitted changes**: [summary or "clean"]

## Environment

- **OS**: CentOS Stream 10
- **Runtimes**: Go 1.22, Node 20
- **Installed this session**: `jq`, `yq`
- **Dependency files**: `go.mod`, `go.sum`

## Next Steps

1. [Concrete next action with file paths and specifics.]
2. [Another action.]
````

## Verify Completeness

The first draft of a handoff document almost always has gaps, especially on complex projects with long conversations. You must verify before finalizing. This is a three-step process: self-review, dry-run, and patch.

### Step 1: Self-review (you do this)

Re-read your conversation context from the beginning. For each category below, confirm the document captures everything relevant, or explicitly note there was nothing to capture:

- Every architectural or library decision (and its rationale)
- Every approach that was tried and abandoned (and why it failed)
- Every blocker, open question, or unresolved issue
- Every file that was created or significantly modified during the session
- The full task list (if one exists) with accurate statuses
- Concrete, actionable next steps, not "continue working on X" but specific file paths and actions

If you find gaps, add them to the document now before proceeding to Step 2.

### Step 2: Dry-run handoff (subagent does this)

Spawn a subagent to simulate the receiving session. The subagent has never seen your conversation. It reads the handoff document and the repository cold, exactly as the real receiving session would.

Dispatch the subagent with this prompt:

> You are a fresh Claude session picking up work from a previous session. Read the handoff document at `<path-to-state.md>` and explore the repository at `<project-root>`.
>
> Your job is to evaluate whether this handoff document gives you everything you need to continue the work effectively. Report:
>
> 1. **Gaps**: What information is missing that you'd need before you could start working? Be specific — "I don't know X" is more useful than "more detail needed."
> 2. **Confusion**: What parts of the document are unclear or contradictory?
> 3. **Stale info**: Does anything in the document contradict what you see in the repo? (e.g., files mentioned that don't exist, git state that doesn't match)
> 4. **Verdict**: Could you start the next step right now, or would you need to ask the user questions first?
>
> Do NOT actually do the work. Just evaluate the handoff quality.

### Step 3: Patch gaps

Read the subagent's report. For each gap or confusion it identified:

- If the information exists in your conversation context, add it to the document.
- If the subagent found stale info (e.g., a file path that changed), correct it.
- If the gap is something you genuinely don't know (e.g., a decision the user hasn't made), add it to the **Blockers** section so the receiving session knows to ask.

Rewrite `.claude/handoff/state.md` with the patches applied.

## Git Hygiene

After writing the briefing, ensure it will not be accidentally committed:

1. Check if `.gitignore` exists at the project root. If not, create it.
2. Check if `.claude/handoff/` is already covered by an existing pattern (e.g., `.claude/` would cover it).
3. If not covered, append `.claude/handoff/` to `.gitignore` on its own line.
4. Do not commit the `.gitignore` change automatically. Leave it staged or unstaged for the user to review.

## After Writing

Tell the user:

1. The absolute path to the briefing file.
2. The exact resume instruction:

> To resume in a new session, open Claude in this repo and say:
> **"Read `<absolute-path>/.claude/handoff/state.md` and continue where the previous session left off."**
>
> (Replace `<absolute-path>` with the actual project root shown in item 1 above.)

## What NOT to Include

- No conversation transcript. Synthesize context into structured sections. Do not paste chat history.
- No file contents. Reference paths; do not inline source code. The new session can read files itself.
- No CLAUDE.md content. The new session loads CLAUDE.md automatically. Duplicating it wastes tokens and risks staleness.
- No memory entries. These persist independently via `claude memory`. Do not duplicate them in the briefing.
