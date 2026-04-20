# Contributing to Argox

First off, thanks for taking the time to contribute. Argox is better because of people like you.

## How to contribute

### Reporting bugs

Open an [issue](../../issues) with the **bug** label. Include:

- What you expected to happen
- What actually happened
- Steps to reproduce it
- Python version, OS, and any relevant environment details

### Suggesting features

Open an [issue](../../issues) with the **enhancement** label. Describe the problem you're trying to solve, not just the solution you have in mind, it helps us understand the context and find the best approach.

### Submitting code

1. Fork the repository
2. Create a feature branch from `main` (`git checkout -b feature/your-feature-name`)
3. Make your changes
4. Run the test suite and make sure everything passes
5. Commit with a clear message describing what you changed and why
6. Push to your fork and open a Pull Request

### Pull Request guidelines

- Keep PRs focused, one feature or fix per PR
- Update documentation if your change affects public APIs or behavior
- Add tests for new functionality
- Follow the existing code style
- Link the related issue in your PR description

## Development setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/argox.git
cd argox

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

## Commit messages

Write commit messages that explain **what** changed and **why**. Use the imperative mood ("Add feature" not "Added feature").

```
Add cost threshold policy rule

Adds a new policy rule type that blocks agent execution
when cumulative cost exceeds a configurable daily limit.
Closes #42.
```

## Code of Conduct

Be kind, be respectful, assume good intentions. We're all here to build something useful.

## Questions?

If you're unsure about anything, open an issue and ask. There are no stupid questions, only missing documentation that we should probably write.