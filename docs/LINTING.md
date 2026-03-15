# Linting & Static Analysis

## Automated Tools

| Tool | Config File | Command |
|------|------------|---------|
| mypy | (default) | `mypy --ignore-missing-imports *.py terminal/*.py` |
| ruff | (to configure) | `ruff check .` |
| isort | (to configure) | `isort --check-only .` |

## Key Rules

- No unused imports
- No wildcard imports (`from x import *`)
- No mutable default arguments (use `field(default_factory=...)` for dataclasses)
- No bare `except:` — always catch specific exceptions
- No `type: ignore` without explanation comment
- Import order: stdlib → third-party → local

## Manual Review Checklist

- [ ] No dead code (unused functions, unreachable branches)
- [ ] No hardcoded secrets, keys, or credentials
- [ ] No TODO/FIXME without a `CURRENT_TASKS.md` entry
- [ ] All public APIs have docstrings
- [ ] Error paths are handled (no silent swallows)
- [ ] No duplicate logic that should be extracted
- [ ] Config access uses `.get("key", default)` — never bare key access on dicts
- [ ] All new functions have type hints
- [ ] Dataclasses used for structured data, not naked dicts
