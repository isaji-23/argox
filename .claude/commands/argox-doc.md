---
description: Record the current ticket's changes into the living documentation (devlog, ADRs, insights, SDK overview)
argument-hint: "[TICKET-ID]"
allowed-tools: Bash(git*), Read, Edit, Write, Glob, Grep
---

You are updating the Argox SDK **living documentation**. Capture what changed in
this ticket/PR so knowledge is not lost between sessions. Optional argument:
`$1` = ticket ID (e.g. `CORE-06`). Documentation destinations all live under
`argox-project/docs/`.

## Rules (reaffirm CLAUDE.md)

- **English only.** No AI attribution anywhere.
- One devlog entry per ticket/PR.
- Be concrete and concise — match the tone of existing docs
  (`docs/architecture/plugin-interface-evolution.md`, `docs/sdk/overview.md`).
- Do not invent changes: everything you write must be grounded in the diff.

## Steps

1. **Resolve context.** Run `git branch --show-current`. Derive the ticket ID
   from `$1` if given, else from the branch name (`feat/TICKET-NN-...`). Get
   today's date with `date +%Y-%m-%d`.
2. **Read the change set.** Run `git diff dev...HEAD --stat`, then read the
   substantive per-file diffs (`git diff dev...HEAD -- <path>`). If the branch
   is not pushed / no commits vs dev, fall back to `git diff` and
   `git diff --staged` on the working tree. Find the PR number with
   `gh pr view --json number -q .number` if available.
3. **Devlog (always).** Create `argox-project/docs/devlog/<date>-<TICKET>-<slug>.md`
   from the template below, summarizing *what changed* and *why*. Add a row to
   `argox-project/docs/devlog/_index.md` (newest first).
4. **ADR (conditional).** If the diff embodies a locked architectural decision
   (new/changed interface or contract, failure-mode semantics, a deliberately
   deferred refactor), create `argox-project/docs/architecture/ADR-NNNN-<slug>.md`
   from `docs/architecture/_template.md` and add it to that `_index.md`. Pick
   the next free `NNNN`.
5. **Errors & fixes (conditional).** If this session hit and fixed a non-trivial
   error, append an entry to `argox-project/docs/insights/errors.md`
   (newest-first) using the format documented in that file.
6. **SDK overview (conditional).** If public API or observable behaviour
   changed, update the relevant section of `argox-project/docs/sdk/overview.md`
   so it stays in sync with the code.
7. **Report.** Print one line listing exactly which doc files you created or
   modified. If you skipped a category, say why in a few words.

## Devlog entry template

```markdown
# [TICKET-NN] <short title>

- **Date:** YYYY-MM-DD
- **PR:** #NN  ·  **Branch:** <branch>
- **Status:** merged | in-review

## What changed
<bullet list of behavior/API changes, file-level>

## Why
<motivation; link to ADR if a decision was locked>

## Notes / follow-ups
<open items, deferred refactors>
```
