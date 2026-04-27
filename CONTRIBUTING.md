# Contributing to Argox

Thank you for your interest in contributing to **Argox**! This document outlines the process and conventions that keep our codebase stable and collaboration smooth, whether you're a core team member or an external contributor.

---

## Table of Contents

- [Contributing to Argox](#contributing-to-argox)
	- [Table of Contents](#table-of-contents)
	- [Code of Conduct](#code-of-conduct)
	- [Getting Started](#getting-started)
	- [Development Environment](#development-environment)
	- [Branching Strategy](#branching-strategy)
		- [Branch Naming Conventions](#branch-naming-conventions)
		- [Pushing a Branch for the First Time](#pushing-a-branch-for-the-first-time)
		- [Deleting a Branch After Merging](#deleting-a-branch-after-merging)
	- [Commit Guidelines](#commit-guidelines)
	- [Pull Request Process](#pull-request-process)
	- [Project Board \& Issue Tracking](#project-board--issue-tracking)
	- [Versioning](#versioning)
	- [License](#license)

---

## Code of Conduct

By participating in this project, you agree to uphold a respectful and collaborative environment. We expect all contributors to communicate professionally and constructively, regardless of experience level.

---

## Getting Started

1. **Fork** the repository and clone your fork locally.
2. Make sure you have **Python 3.9+** installed.
3. Set up your development environment (see below).
4. Browse the [open issues](../../issues) to find something to work on, or open a new issue to propose a change before starting.

---

## Development Environment

Install the package in editable mode with all development dependencies:

```bash
pip install -e ".[dev]"
```

Run the test suite to verify your setup:

```bash
pytest
```

All tests must pass before submitting a Pull Request. If you add new functionality, please include corresponding tests.

---

## Branching Strategy

Argox follows a **simplified GitHub Flow**:

- `main` is the single source of truth and is **protected**. Direct pushes are not allowed.
- All work happens on short-lived feature branches that are merged back into `main` via Pull Requests.

### Branch Naming Conventions

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feat/` | New features or enhancements | `feat/add-auth-module` |
| `fix/` | Bug fixes | `fix/null-pointer-on-init` |
| `docs/` | Documentation changes only | `docs/update-api-reference` |

**Create your branch from `main`:**

```bash
git checkout main
git pull origin main
git checkout -b feat/your-feature-name
```

### Pushing a Branch for the First Time

The first time you push a new branch, Git doesn't yet know which remote branch it should track. Run:

```bash
git push --set-upstream origin feat/your-feature-name
# or equivalently
git push -u origin feat/your-feature-name
```

The `-u` flag links your local branch to `origin/feat/your-feature-name`. From that point on, a plain `git push` is enough.

If you want this to happen automatically for every new branch without having to think about it, enable the following global option:

```bash
git config --global push.autoSetupRemote true
```

### Deleting a Branch After Merging

Once your PR has been merged, delete the branch both remotely and locally to keep the repository tidy.

**Delete the remote branch:**

```bash
git push origin --delete feat/your-feature-name
```

**Delete the local branch** (switch to `main` first):

```bash
git checkout main
git branch -d feat/your-feature-name
```

The `-d` flag is safe: it only deletes the branch if it has already been merged. Use `-D` (uppercase) only if you need to force-delete an unmerged branch.

Finally, bring your local `main` up to date:

```bash
git pull origin main
```

---

## Commit Guidelines

Write clear, concise commit messages that describe *what* changed and *why*. Use the imperative mood in the subject line:

```
feat: add retry logic to HTTP client
fix: handle empty response from search endpoint
docs: clarify installation steps in README
```

Keep commits focused, one logical change per commit makes the history easier to review and revert if needed.

---

## Pull Request Process

1. **Push your branch** to your fork and open a Pull Request against `main`.
2. **Link the related issue** using a closing keyword in the PR description (e.g., `Closes #42`). This automatically moves the issue on the project board.
3. **Fill out the PR template** with a clear description of the changes, the motivation behind them, and any relevant context.
4. **Ensure all checks pass**, the test suite must be green before requesting a review.
5. **Request a review** from at least one core team member. A minimum of **one approval** is required to merge.
6. Once approved, the PR author (or a maintainer) merges the branch. Delete the branch after merging to keep the repository tidy.

> [!Note] 
> A maintainer will check your PR if your fork doesn't have access. Please be patient, we aim to review PRs within a few business days.

---

## Project Board & Issue Tracking

We use **GitHub Projects** with a Kanban board to track all work. The columns are:

| Column | Meaning |
|--------|---------|
| **Backlog** | Ideas and future work not yet scheduled |
| **Todo** | Issues ready to be picked up |
| **In Progress** | Actively being worked on |
| **In Review** | A PR has been opened and is awaiting review |
| **Done** | Merged and closed |

**Guidelines:**

- Before starting work, check the board to avoid duplicating effort.
- Move your issue to **In Progress** when you begin, and to **In Review** once your PR is open.
- Every PR should be linked to an issue. If no issue exists for your change, create one first.

---

## Versioning

Argox follows [Semantic Versioning (SemVer)](https://semver.org/) strictly:

```
MAJOR.MINOR.PATCH
```

- **MAJOR** - incompatible API changes
- **MINOR** - new backwards-compatible functionality
- **PATCH** - backwards-compatible bug fixes

Version bumps are managed by the core team as part of the release process. If your contribution warrants a version change, mention it in your PR description.

---

## License

By contributing to Argox, you agree that your contributions will be licensed under the **Apache License 2.0**, the same license that covers this project. See the [LICENSE](./LICENSE) file for the full text.

---

*Questions? Open an issue or reach out to the core team. We're happy to help.*