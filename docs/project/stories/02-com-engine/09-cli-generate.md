# Story 2.9: CLI — `testradius generate`

**Status**: Complete
**Epic**: 2 — COM Generation Engine
**Effort**: 1d

---

## Summary

Full test suite generation CLI. `testradius generate <url>` fetches a page, finds all significant components (NavBar, LoginForm, Sidebar, etc.), generates COM files for each, a POM file composing them, and a pytest test file.

## Files Created

- `services/workbench/tests/testsquad_workbench/generation/test_generate.py` — 5 tests
- `docs/project/stories/02-com-engine/09-cli-generate.md` — This file

## Usage

```bash
# Generate full test suite in ./output/
uv run python -m testsquad_workbench.generation.cli generate file:///path/to/page.html -o ./output -n LoginSuite

# Output structure:
# ./output/LoginSuite/
#   LoginSuite.py        # POM
#   test_LoginSuite.py   # pytest tests
#   LoginForm.py         # COM
#   NavBar.py            # COM
#   Sidebar.py           # COM
```

## Key Decisions

- **Component auto-discovery** walks DOM tree depth-first, collecting significant elements (confidence > 0, non-GenericComponent)
- **Max 8 components** per page to keep output focused
- **Suite name** defaults from page `<title>`, overridable with `--name`
- **COM files** generated alongside POM and tests in a subdirectory

## Verification

```bash
uv run pytest tests/testsquad_workbench/generation/test_generate.py -v
```

Expected: 5 passed
