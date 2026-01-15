# Pre-Commit Hooks Setup

**Date**: 2026-01-15
**Engineer**: The Engineer
**Status**: Complete

## Overview

Implemented comprehensive pre-commit hooks to enforce code quality standards before commits are allowed. This prevents broken code from entering the repository and catches issues early in the development cycle.

## Configuration File

Location: `/home/klabautermann/klabautermann3/.pre-commit-config.yaml`

## Hook Categories

### 1. File Formatting (pre-commit-hooks)
- **trailing-whitespace**: Removes trailing whitespace
- **end-of-file-fixer**: Ensures files end with newline
- **mixed-line-ending**: Enforces LF line endings

### 2. File Validation (pre-commit-hooks)
- **check-yaml**: Validates YAML syntax (safe mode)
- **check-toml**: Validates TOML syntax
- **check-json**: Validates JSON syntax

### 3. Security (pre-commit-hooks)
- **detect-private-key**: Prevents accidental commit of private keys
- **check-added-large-files**: Blocks files larger than 500KB
- **check-merge-conflict**: Detects unresolved merge conflicts

### 4. Ruff - Linting & Formatting
- **ruff**: Lints Python code with auto-fix enabled
- **ruff-format**: Formats Python code
- Configured to match `pyproject.toml` settings:
  - Line length: 100
  - Target: Python 3.11
  - Selected rules: E, W, F, I, B, C4, UP, ARG, SIM, TCH, PTH, ERA, RUF

### 5. Mypy - Type Checking
- Runs on `src/` directory only (excludes tests)
- Uses settings from `pyproject.toml`
- Includes additional dependencies:
  - pydantic>=2.0
  - types-pyyaml

### 6. Python-Specific Checks (pygrep-hooks)
- **python-check-blanket-noqa**: Requires specific noqa codes (e.g., `# noqa: E501`)
- **python-check-blanket-type-ignore**: Requires specific type ignore codes
- **python-no-eval**: Prevents use of `eval()`
- **python-use-type-annotations**: Enforces type annotations over comments

## Installation

Automatic (via Makefile):
```bash
make dev
```

Manual:
```bash
pip install -r requirements-dev.txt
pre-commit install
```

## Usage

### Automatic (on commit)
Hooks run automatically when you commit:
```bash
git commit -m "Your message"
```

If hooks fail, the commit is blocked. Fix the issues and try again.

### Manual (all files)
Run on all files without committing:
```bash
pre-commit run --all-files
```

### Manual (specific hook)
Run a specific hook:
```bash
pre-commit run ruff --all-files
pre-commit run mypy --all-files
```

### Update hooks
Update to latest versions:
```bash
pre-commit autoupdate
```

### Skip hooks (emergency only)
Skip hooks for a specific commit (NOT RECOMMENDED):
```bash
git commit -m "Message" --no-verify
```

## Alignment with Makefile

Pre-commit hooks align with existing Makefile targets:

| Makefile Target | Pre-commit Hook | Scope |
|----------------|-----------------|-------|
| `make lint` | `ruff` | src/ and tests/ |
| `make format` | `ruff-format` | src/ and tests/ |
| `make type-check` | `mypy` | src/ only |

**Key Difference**: Pre-commit runs on **staged files only**, while Makefile targets run on **all specified directories**.

## Performance Considerations

Hooks are designed to be fast:
- **Ruff**: Extremely fast (Rust-based)
- **Mypy**: Runs only on src/ (not tests/)
- **File checks**: Minimal overhead

Typical commit time: 2-5 seconds for small changes.

## Troubleshooting

### Hook fails on existing files
If pre-commit fails on existing files:
```bash
# Fix all files at once
make format
make lint

# Or let pre-commit fix what it can
pre-commit run --all-files
```

### Mypy failures
Mypy is strict (`disallow_untyped_defs = true`). Common fixes:
```python
# Add return type annotation
def foo() -> None:
    pass

# Add parameter type annotations
def bar(x: int) -> str:
    return str(x)
```

### Large file blocked
If you need to commit a large file:
1. Verify it's necessary (not build artifacts, etc.)
2. Add to `.gitattributes` if it's a Git LFS candidate
3. Last resort: Skip hook with `--no-verify` (document why)

### Private key detected
If you need to commit example keys:
1. Ensure they're dummy/test keys only
2. Add to exception list in `.pre-commit-config.yaml`
3. Document in commit message why it's safe

## Dependencies Added

Updated `requirements-dev.txt`:
```
types-pyyaml>=6.0  # Type stubs for PyYAML (used by mypy)
```

All other dependencies were already present:
- ruff>=0.4
- mypy>=1.9
- pre-commit>=3.0

## Integration with CI

Pre-commit hooks are a **first line of defense**. CI (GitHub Actions) should:
1. Run the same checks (via `make check`)
2. Run tests (not included in pre-commit)
3. Fail the build if any check fails

This ensures that even if developers skip hooks, CI catches issues.

## Future Enhancements

Potential additions:
- **pytest**: Run unit tests on commit (may slow down commits)
- **bandit**: Security linting for Python
- **codespell**: Spell checking in code/docs
- **conventional-pre-commit**: Enforce conventional commit messages

## References

- Pre-commit docs: https://pre-commit.com/
- Ruff docs: https://docs.astral.sh/ruff/
- Mypy docs: https://mypy.readthedocs.io/
