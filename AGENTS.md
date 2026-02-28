# Project

yikes is a simple C compiler written in Python.

# Contributing

## Style Guide

- Write clean and concise code. Don't add too many comments.
- Don't split things into multiple lines for no reason. Things that easily fit within the line limit of 160 characters should usually be on one line as long as it doesn't impact readability.
- Avoid short docstrings. Use docstrings only when detailed documentation spanning multiple lines is required, which should be rare.
- Always use absolute imports.
- Functions should always be separated by a single blank line, never by two blank lines.

## Before Committing

Always run the following checks:

```bash
ruff check .
ty check
pytest
```

All checks must pass before committing code.

Note: Some agents run in a sandbox and may see permissions errors writing to `~/.cache/pre-commit`. If that happens, request escalation so pre-commit can write to that directory. Other agents may not need this.

## Commit Messages

- Always use single-line commit messages.
- Do not add any signatures (e.g., Co-Authored-By).
