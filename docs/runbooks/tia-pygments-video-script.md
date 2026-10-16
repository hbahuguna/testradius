# Video script — "Test Impact Analysis on a 5,000-test suite (Pygments)"

**Format:** screen recording + voiceover. **Target length:** 6:30–7:30.
**Resolution:** 1920×1080, terminal font ≥ 16pt, browser zoom 110%.
**Repo:** `hbahuguna/pygments` · **PR:** https://github.com/hbahuguna/pygments/pull/1

Legend: `[SCREEN]` what's visible · `[DO]` action · `[VO]` voiceover · `[TEXT]`
lower-third/caption.

---

## Scene 0 — Cold open / hook (0:00–0:40)

`[SCREEN]` Split: left = GitHub PR diff (`pygments/formatters/irc.py`, 6-line
change); right = a terminal running the **full** Pygments suite.
`[DO]` Start the full suite; timer visible.
`[VO]` "This is Pygments — a Python library with over five thousand tests. A
one-line change to a formatter still means running all of them: here, about
twenty-five seconds on a laptop. In a real monorepo that's minutes to hours per
push. What if CI could run only the tests this change can actually break?"
`[TEXT]` "5,345 tests · one changed file · ~26s — can we do better?"

---

## Scene 1 — What we're changing (0:40–1:30)

`[SCREEN]` GitHub PR page for `pull/1`, Files changed.
`[DO]` Scroll the two-file diff: `irc.py` (+4/−2) and
`tests/test_irc_formatter.py` (+11).
`[VO]` "The change is deliberately small and real: `IRCFormatter` mis-handles a
custom color scheme that names a color the built-in map doesn't know — it used
to raise `KeyError`. The fix falls back to emitting the text without a color
code. One production line, one new test."
`[TEXT]` "PR #1 · 2 files · +15/−2"
`[SCREEN]` Briefly show the failing reproduction: `KeyError: 'notacolor'`.
`[VO]` "So the question for CI is simple: which of those 5,345 tests matter for
*this* diff?"

---

## Scene 2 — The setup, already done (1:30–2:10)

`[SCREEN]` Terminal: Neo4j counts via cypher-shell.
`[DO]` Run the three counts.
`[VO]` "Before we analyze anything, TestRadius has instrumented the repo once:
it ran the suite under coverage and recorded which tests executed which
functions. That's an evidence graph: five thousand three hundred and twenty-nine
test nodes, twelve hundred and eighty-five symbols, and over sixty-six thousand
symbol-to-test edges — pinned to one commit, so it can't silently drift."
`[TEXT]` "5329 TestSymbols · 1285 Symbols · 66,138 EVIDENCE edges · SHA 156d85f"
`[SCREEN]` Show coverage completeness JSON (99.9%).
`[VO]` "It's also honest about coverage: fifteen hundred thirty-nine of fifteen
hundred forty test files instrumented — ninety-nine point nine percent."

---

## Scene 3 — Run TIA on the PR (2:10–3:20)

`[SCREEN]` Terminal at `apps/tia-agent`.
`[DO]` Type (don't paste) and run:

```
.venv/bin/python -m tia_agent analyze \
  --repo hbahuguna/pygments --pr 1 \
  --commit 156d85fdd18d34427fe893527e71da91dcfb0eb5 \
  --file-paths pygments/formatters/irc.py tests/test_irc_formatter.py --json
```

`[VO]` "We ask TestRadius which tests are impacted by PR number one, at the
commit the evidence was built on."
`[SCREEN]` JSON scrolls; highlight fields with an annotation overlay.
`[DO]` Point at: `tests_selected: 5`, `total_tests_in_repo: 5329`,
`impacted_ratio: 0.0009`, `confidence: high`, `fallback_used: false`,
`stale_evidence: false`.
`[VO]` "Five tests. High confidence. No fallback, evidence fresh. Not five
*arbitrary* tests — each one lists exactly which changed symbol reached it."
`[TEXT]` "5 of 5,329 · 99.9% reduction"
`[SCREEN]` Show the five nodeids and one reason path:
`changed_symbol:ircformat@pygments/formatters/irc.py -> runtime_evidence -> ...`
`[VO]` "Two existing IRC formatter tests, the two API tests parametrized over
every formatter, and a cmdline test that exercises the formatter. Everything
else in the suite cannot touch this function."

---

## Scene 4 — Prove it with a controlled regression (3:20–4:50)

`[SCREEN]` Terminal in the checkout.
`[DO]` Create throwaway branch; inject a one-character regression (off-by-one
in the color code); show the `git diff`.
`[VO]` "Selection is only useful if it actually catches bugs. So we sabotage the
function on a scratch branch — an off-by-one in the emitted color code — and run
the whole suite, exactly like CI would."
`[DO]` Run full suite. Highlight result.
`[TEXT]` "FULL SUITE → 2 failed · 5328 passed · 25.6s"
`[VO]` "Two failures, both about output." 
`[DO]` Run TIA's five selected tests.
`[TEXT]` "TIA SELECTION (5) → same 2 failed · 0.58s"
`[VO]` "Now the five tests TestRadius picked. Same two failures — the reduced
set is a superset of what's broken. Zero misses, in half a second instead of
twenty-five."
`[SCREEN]` On-screen stamp: "0 misses · 44× faster".
`[VO]` "That's the whole claim: run fewer tests, still fail when you should."

---

## Scene 5 — How it works (4:50–5:50)

`[SCREEN]` Simple animated diagram (or static) built from the real data.
`[VO]` "Under the hood: instrumentation gives a symbol-to-test graph. A PR gives
changed files. We intersect them and walk the edges — runtime evidence wins
'high' confidence, static import reachability is 'medium' — then dedupe to
canonical nodeids."
`[TEXT]` "changed files → changed symbols → EVIDENCE edges → fused test set"
`[VO]` "And it fails safe. If there's no evidence, it runs the full suite. If
the evidence was built on a different commit, it runs the full suite. If the
symbol cap would drop a symbol that has tests, it runs the full suite. Reduction
is only claimed when it's provably safe."

---

## Scene 6 — Honesty about the numbers + close (5:50–7:00)

`[SCREEN]` Terminal: collection counts side by side.
`[VO]` "And this isn't a reduction built on a convenient subset. Pygments
collects five thousand three hundred forty-five tests — and the evidence graph
models all five thousand three hundred twenty-nine that actually execute. That
includes one thousand five hundred eight data-driven golden tests generated from
sample files, which TestRadius discovers by asking pytest directly instead of
globbing for test files. The only tests not modelled are the sixteen skipped
ones, because they run no code."
`[TEXT]` "5,345 collected · 5,329 modeled (incl. 1,508 generated) · 16 skipped"
`[VO]` "For a five-thousand-test suite, TestRadius turned a twenty-five-second
full run into five targeted tests in half a second — with a demonstrated
zero-miss guarantee. Change to a lexer, a plugin, or a formatter: CI runs what
matters."
`[SCREEN]` End card: repo + PR URL + "TestRadius".
`[TEXT]` "github.com/hbahuguna/pygments/pull/1"

---

## Shot checklist / asset list

- [ ] Full-suite run recording (Scene 0 & 4): capture the `grep` summary line.
- [ ] PR files-changed scroll (Scene 1).
- [ ] Neo4j count commands + output (Scene 2), pre-run so it's instant.
- [ ] Coverage completeness JSON (Scene 2).
- [ ] `analyze` command run, live-typed, with JSON highlight overlay (Scene 3).
- [ ] Regression injection `git diff` + two pytest runs (Scene 4).
- [ ] Pipeline diagram graphic (Scene 5).
- [ ] Collection-count comparison (Scene 6).

## Exact commands used on camera (copy block)

```bash
# Scene 2
NEO() { docker compose exec -T neo4j cypher-shell -u neo4j -p testsquad_password "$1" 2>/dev/null | tail -n +2; }
NEO "MATCH (ts:TestSymbol {project_id:8}) RETURN count(ts);"
NEO "MATCH (:TestSymbol {project_id:8})-[e:EVIDENCE]->() RETURN count(e);"
curl -s "$RADIUS/projects/8/instrumentation/coverage" | jq .

# Scene 3
cd apps/tia-agent
.venv/bin/python -m tia_agent analyze --repo hbahuguna/pygments --pr 1 \
  --commit 156d85fdd18d34427fe893527e71da91dcfb0eb5 \
  --file-paths pygments/formatters/irc.py tests/test_irc_formatter.py --json

# Scene 4
git checkout -b tia/irc-regression-check tia/irc-unknown-color-fix
sed -i '' 's/str(color_code).zfill(2)/str((color_code or 0) + 1).zfill(2)/' pygments/formatters/irc.py
.venv/bin/python -m pytest tests/ -q --ignore=tests/contrast | tail -2
.venv/bin/python -m pytest -q \
  "tests/test_cmdline.py::test_L_opt" \
  "tests/test_basic_api.py::test_formatter_unicode_handling[IRCFormatter]" \
  "tests/test_basic_api.py::test_formatter_public_api[IRCFormatter]" \
  "tests/test_irc_formatter.py::test_correct_output" \
  "tests/test_irc_formatter.py::test_linecount_output" | tail -2
git checkout -q tia/irc-unknown-color-fix && git branch -D tia/irc-regression-check
```

## Narration timing budget

| Scene | Topic | Duration |
|---|---|---|
| 0 | Hook — full suite cost | 0:40 |
| 1 | The PR change | 0:50 |
| 2 | Evidence graph setup | 0:40 |
| 3 | Run TIA — 5 tests | 1:10 |
| 4 | Controlled regression | 1:30 |
| 5 | How it works | 1:00 |
| 6 | Caveats + close | 1:10 |
| | **Total** | **~7:00** |
