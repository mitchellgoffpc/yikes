# Instructions for Coding Agents

## Code Style

- Write clean and concise code. Don't add too many comments.
- Don't split things into multiple lines for no reason. Things that easily fit within the line limit of 160 characters should usually be on one line as long as it doesn't impact readability.

## Before Committing

Always run the following checks:

```bash
ruff check .
ty check
pytest
```

All checks must pass before committing code.

## Commit Messages

- Always use single-line commit messages.
- Do not add any signatures (e.g., Co-Authored-By).
