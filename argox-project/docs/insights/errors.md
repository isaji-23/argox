# Errors & Fixes Log

Debugging knowledge captured as it happens. Append newest-first. The goal is
that a problem solved once is never re-debugged from scratch — record the
symptom (verbatim error string when possible), the root cause, the fix, and the
guard that prevents regression. Populated by `/argox-doc` when a session hits
and resolves a non-trivial error.

<!-- Add new entries directly below this line, newest first. -->

## Format

```markdown
## YYYY-MM-DD — <symptom one-liner>  [TICKET-NN]
- **Symptom:** <error string / observed behavior>
- **Root cause:** <why>
- **Fix:** <what resolved it; file:line>
- **Guard:** <test added / check to prevent regression>
```
