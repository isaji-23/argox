# Argox Development Standards & Rules

You are a core collaborator on the Argox project. Your goal is to maintain technical consistency and follow the Git workflow strictly.

## 0. Language Policy
- **STRICT REQUIREMENT:** All technical output MUST be in **English**. This includes:
  - Variable, class, and function names.
  - Inline comments and Docstrings (Google format).
  - Git commit messages.
  - Pull Request titles and descriptions.
  - Documentation (.md files).

## 1. Branching Strategy
- **Base Branch:** The main development branch is `dev`. All feature branches must branch off `dev`, and Pull Requests must target `dev`.
- **Protection:** Never push directly to `main` or `dev`.
- **Naming Conventions:**
  | Prefix | Purpose | Example |
  |---------|-----------|---------|
  | `feat/` | New features | `feat/CORE-06-pipeline-manager` |
  | `fix/`  | Bug fixes | `fix/POL-01-cache-invalidation` |
  | `docs/` | Documentation only | `docs/DX-05-processor-guide` |

## 2. Commit Guidelines
- **Language:** English only.
- **Mood:** Use the imperative mood (e.g., "add", not "added" or "adds").
- **Format:** `<type>: [ID-TICKET] short description`
- **No Signature:** DO NOT add "Co-authored-by: Claude" or any other AI attribution to commit messages.
- **Clean Messages:** Commit messages must contain ONLY the header and, optionally, a clean body description. No metadata.
- **Examples:**
  - `feat: [CORE-06] wire ArgoxProcessor into manager`
  - `fix: [POL-02] validate yaml schema before parsing`

## 3. Pull Request (PR) Process
- **Creation:** Use `gh pr create --base dev`.
- **Linking:** The PR body must include `Closes #XX` to link and auto-close the issue.
- **Content (In English):** Describe what changed, why, and how to test it.
- **Cleanup:** After merging, delete the local branch with `git branch -d <name>` and the remote branch with `git push origin --delete <name>`.

## 4. Technical Standards (Python 3.9+)
- **Environment:** Use `pip install -e ".[dev]"`.
- **Quality:** Run `pytest` before proposing any commit or PR. Broken tests are not allowed.
- **Tests:** New features must include corresponding tests in the `tests/` directory.
- **OTel:** Observe "OTel" capitalization and OpenTelemetry Semantic Conventions.

## 5. Project Management (GitHub Projects)
- **Context:** User: `isaji-23`, Repo: `argox`, Project: `1`.
- **Workflow:** - Move issue to **In Progress** when starting.
  - Move to **In Review** when the PR is opened.
  - **Done** is only reached after merging into `dev`.

## 6. Documentation Methodology (Living Docs)
As work happens, knowledge must be recorded so it survives between sessions. All living docs are **English** and live under `argox-project/docs/` (authoritative). Root `*.html` files and temporary analysis `*.md` files (e.g., `plan.md`, `temp.md`) are legacy references, not maintained going forward. Key root docs (`README.md`, `CONTRIBUTING.md`, `CLAUDE.md`) are still maintained.

- **Trigger:** after completing a ticket (with or before the PR), run the `/argox-doc` slash command. It reads the diff and updates the docs below.
- **Destinations and what each captures:**
  | Doc | Path | Captures |
  |---|---|---|
  | Devlog | `argox-project/docs/devlog/` | One entry per ticket/PR: what changed and why. |
  | ADRs | `argox-project/docs/architecture/` | Locked architectural decisions (use `_template.md`). |
  | Errors & fixes | `argox-project/docs/insights/errors.md` | Non-trivial bugs hit and how they were resolved. |
  | SDK overview | `argox-project/docs/sdk/overview.md` | Conceptual SDK explanation, kept in sync with code. |
- **Nudge:** a Stop hook (`.claude/hooks/check-undocumented.sh`) reminds once per session when source under `argox-project/argox-*/src` changed but no devlog entry was added. It only reminds — `/argox-doc` does the writing.
- **Rules:** English only, no AI attribution, grounded strictly in the diff.

## Claude Workflow Instruction:
When assigned a ticket ID (e.g., CORE-06):
1. Read the issue description using `gh issue view`.
2. Create a branch `feat/ID-TICKET-description` from `dev`.
3. Implement changes in **English** and verify with `pytest`.
4. Commit using the imperative format in **English**.
5. Create a PR targeting `dev` including "Closes #ID" in the description.
6. Run `/argox-doc ID-TICKET` to record the change in the living docs.