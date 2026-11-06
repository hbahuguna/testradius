# Jira Setup for Live E2E (Real Projects + Tickets → MCP Context)

> **Goal:** Create a real Jira project + 2–3 tickets that a real tester would use,
> then drive the harness with them **live** (no mocks): Jira issue → normalized
> `context_bundle.json` → live Gemini compile → E2B computer-use run vs `https://testradius.dev`.
>
> This guide pairs with `docs/MANUAL_TEST_PLAN_E2B_COMPUTER_USE_E2E.md` (§3, Phase 1).
> Secrets (`JIRA_API_TOKEN` / password) stay in env only — never in tickets, bundles, or commits.

---

## 1. What the harness expects from Jira

| Jira piece | Harness mapping (`JiraContextAdapter`) |
|---|---|
| `key` (e.g. `TRQA-101`) | `ContextBundle.ticket_id` + `source_refs[ref]` |
| `fields.summary` | `title` / `summary` |
| `fields.description` (Cloud ADF or DC plain text) | `description` + **acceptance criteria extraction** |
| `## Acceptance Criteria` section (markdown) | `acceptance_criteria[]` — **must use this exact header** (see §3 template) |
| URLs in description with `figma.com` | `figma_links[]` + `ui_design_refs[]` |
| `fields.labels`, `components[].name` | `risk_areas[]` |
| `fields.issuelinks` (outward/inward) | `prior_bugs[]` (linked issue keys) |
| `fields.project.key/type/status/priority` | `env_build_info[]` |
| `self` / URL | `source_refs[uri]`, tool `mcp.jira` (or your tool name) |

**Critical (do not skip):** the adapter only reliably extracts ACs from a description
block headed by `## Acceptance Criteria` (or `## AC`). Titles that say it in prose do not count.
See §3 templates for copy-paste content.

---

## 2. Prerequisites

- [ ] Jira **Cloud** (or Server/DC) site you can administer: `https://<you>.atlassian.net`
- [ ] Atlassian account email (the user who owns the API token).
- [ ] **API token** (Cloud; never the account password in scripts):
  1. Open <https://id.atlassian.com/manage-profile/security> → **Create and manage API tokens** → **Create API token**.
  2. Label it `testradius-e2e`. Copy the token **once**; do not paste it into any file/doc.
- [ ] `curl`, Python 3.12 venv (`apps/cell/.venv`) with `httpx` (present) — the helper script in §5 handles HTTP.
- [ ] Optional: a Figma link and a GitHub issue URL to paste into tickets for multi-source merge.

### 2.1 Env (shell only — value never printed/committed)

```bash
export JIRA_SITE="https://your-site.atlassian.net"   # no trailing slash
export JIRA_EMAIL="you@example.com"
export JIRA_API_TOKEN="..."                          # from §2, shell only
# Server/Data Center instead? Use PAT or basic-auth password:
#   JIRA_SITE="https://jira.example.com"; export JIRA_PAT="..."
test -n "$JIRA_API_TOKEN" && echo "JIRA token present" || echo "JIRA token NOT set"
```

> Record **site + project key + issue keys** in your test notes (§0 of the E2E plan).
> Never record the token.

---

## 3. Create the project + tickets

### 3.1 Create project (UI, 2 minutes)

1. Jira home → **Projects → Create project** → **Team-managed** (simplest) or **Company-managed** if required.
2. Template: **Software development** (gives Story/Bug/Task).
3. Set:
   - **Name:** `TestRadius Manual QA`
   - **Key:** `TRQA` (keys are unique + immutable; pick short uppercase; do not reuse a live/product key you care about).
   - **Lead:** yourself. **Access:** Private.
4. Create. Open the project → ** Board** confirms empty.
5. Optional but recommended: add labels/components used by the harness — go to project → **Settings → Components** → add `web`, `mobile`, `auth`. Labels can be arbitrary strings on issues.

### 3.2 Ticket templates (copy-paste; replace `TRQA-101` note as needed)

Create **3 issues** (Story/Bug as available). Each description must contain the `## Acceptance Criteria` header.

#### Ticket 1 — Happy-path homepage CTA (drive the golden live run)

- **Summary:** `Homepage hero CTA routes to contact form`
- **Labels:** `smoke, homepage`
- **Components:** `web`
- **Priority:** High
- **Description (paste verbatim, keep headers):**
  ```markdown
  As a visitor on testradius.dev, I can click the primary hero CTA and reach the contact flow.

  ## Acceptance Criteria
  - Clicking primary CTA navigates to /contact
  - Form renders with name/email/message
  - Mobile viewport preserves CTA visibility

  Design: https://www.figma.com/file/demo123/Homepage?node-id=10-20

  ## Notes
  - SUT: https://testradius.dev (staging). No auth required.
  - Out of scope: billing flows.
  ```
- **Expected:** `normalize_context_bundle.py` demo parity (`QA-812` analog) once fetched: `ticket_id=<TRQA-101>`, title above, 3 ACs, 1 Figma link, `risk_areas` containing `smoke,homepage,web`.

#### Ticket 2 — Mobile navigation edge (edge case)

- **Summary:** `Mobile navigation opens from hamburger on small viewport`
- **Labels:** `mobile, edge`
- **Description:**
  ```markdown
  ## Acceptance Criteria
  - At 390px width, hamburger icon is visible
  - Tapping it opens the nav menu
  - Menu links navigate to correct sections
  ```
- **Expected:** 3 ACs; run with `viewport 390x844` in `sut` config (or leave default and let Gemini cover hero-only plan; this ticket is for manual/compile breadth, not the golden run).

#### Ticket 3 — Negative/validation (follow-up)

- **Summary:** `Contact form validates empty submit`
- **Labels:** `validation, negative`
- **Description:**
  ```markdown
  ## Acceptance Criteria
  - Submitting with empty fields shows inline errors
  - No request is sent on invalid submit
  - Fixing fields clears errors without reload
  ```

### 3.3 Link tickets (optional, powers `prior_bugs[]`)

Ticket 1 → **More (…) → Link → Relates to** → Ticket 3. After fetch, `prior_bugs` includes the linked key.

### 3.4 (Programmatic) create via REST — optional

If you prefer API creation (Cloud, `JIRA_SITE` + Basic Auth `$JIRA_EMAIL:$JIRA_API_TOKEN`):

```bash
# Create project (Team-managed requires template flow; UI in §3.1 is the guaranteed path).
# Issue create (ADF description; Cloud v3):
curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -H "Accept: application/json" -H "Content-Type: application/json" \
  -X POST "$JIRA_SITE/rest/api/3/issue" -d "{
    \"fields\": {
      \"project\": {\"key\": \"TRQA\"},
      \"issuetype\": {\"name\": \"Story\"},
      \"summary\": \"Homepage hero CTA routes to contact form\",
      \"labels\": [\"smoke\", \"homepage\"],
      \"priority\": {\"name\": \"High\"},
      \"description\": {
        \"type\": \"doc\", \"version\": 1,
        \"content\": [
          {\"type\": \"paragraph\", \"content\": [{\"type\": \"text\", \"text\": \"As a visitor on testradius.dev, I can click the primary hero CTA and reach the contact flow.\"}]},
          {\"type\": \"heading\", \"attrs\": {\"level\": 2}, \"content\": [{\"type\": \"text\", \"text\": \"Acceptance Criteria\"}]},
          {\"type\": \"bulletList\", \"content\": [
            {\"type\": \"listItem\", \"content\": [{\"type\": \"paragraph\", \"content\": [{\"type\": \"text\", \"text\": \"Clicking primary CTA navigates to /contact\"}]}]},
            {\"type\": \"listItem\", \"content\": [{\"type\": \"paragraph\", \"content\": [{\"type\": \"text\", \"text\": \"Form renders with name/email/message\"}]}]},
            {\"type\": \"listItem\", \"content\": [{\"type\": \"paragraph\", \"content\": [{\"type\": \"text\", \"text\": \"Mobile viewport preserves CTA visibility\"}]}]}
          ]},
          {\"type\": \"paragraph\", \"content\": [{\"type\": \"link\", \"attrs\": {\"url\": \"https://www.figma.com/file/demo123/Homepage?node-id=10-20\"}, \"content\": [{\"type\": \"text\", \"text\": \"Figma: Homepage\"}]}]}
        ]
      }
    }
  }" | python3 -m json.tool
```

- **Expected:** `{"key": "TRQA-101", …}`. Create Tickets 2–3 the same way (duplicate block, change summary/body/labels).
- Server/DC: use `/rest/api/2/issue` with plain-text `description` instead of ADF.

---

## 4. Fetch a real issue as JSON

### 4.1 Cloud REST v3 (recommended)

```bash
curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -H "Accept: application/json" \
  "$JIRA_SITE/rest/api/3/issue/TRQA-101?fields=*all" \
  | python3 -m json.tool | head -100
```

- **Expected:** `key`, `fields.summary`, `fields.description` (ADF object), `fields.project`, `fields.labels`, `fields.self`.
- Save the raw JSON (no tokens inside — auth is the header) to a temp file:
  ```bash
  curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -H "Accept: application/json" \
    "$JIRA_SITE/rest/api/3/issue/TRQA-101?fields=*all" > /tmp/jira-TRQA-101.json
  ```
- Server/DC: `…/rest/api/2/issue/TRQA-101?fields=*all` (description is plain text).

### 4.2 Search / list (optional)

```bash
curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" -H "Accept: application/json" -H "Content-Type: application/json" \
  -X POST "$JIRA_SITE/rest/api/3/search" \
  -d '{"jql":"project = TRQA ORDER BY created DESC","maxResults":10,"fields":["summary","status","labels"]}'
```

---

## 5. Feed the real ticket into the harness (live)

### 5.1 Helper (preferred — one command)

`scripts/fetch_jira_context.py` fetches the issue with env auth, runs `JiraContextAdapter`, and saves a normalized bundle (no token persisted):

```bash
PYTHONPATH=. apps/cell/.venv/bin/python scripts/fetch_jira_context.py \
  --jira-url "$JIRA_SITE" --issue-key TRQA-101 \
  --out "$RUN_ROOT/01-mcp/context_bundle.json" 2>&1 | tee "$RUN_ROOT/01-mcp/fetch-stdout.txt"
```

- **Expected:** `{"saved": "…/context_bundle.json", "ticket_id": "TRQA-101", "source_types": ["jira"], …}`.
- Verify:
  ```bash
  python3 - <<'PY'
  import json, pathlib
  d = json.loads(pathlib.Path("$RUN_ROOT/01-mcp/context_bundle.json").read_text())
  assert d["ticket_id"] == "TRQA-101", d["ticket_id"]
  assert len(d["acceptance_criteria"]) >= 3
  assert any("figma.com" in str(u) for u in d["figma_links"]), d["figma_links"]
  print("real Jira bundle OK:", d["title"], "| ACs:", d["acceptance_criteria"])
  PY
  ```

### 5.2 Manual-file fallback (if helper/network fails)

If `fetch_jira_context.py` cannot reach Jira (offline/VPN), export the issue (Jira UI → `…` → **Export → XML/JSON** or the §4.1 `curl` output) and normalize the file:

```python
from harness.integrations.mcp_context import ContextIntake, ContextSourceConfig
import json
payload = json.loads(open("/tmp/jira-TRQA-101.json").read())
bundle = ContextIntake().ingest([ContextSourceConfig(type="jira", ref="TRQA-101", payload=payload, tool="mcp.jira/get_issue")])
bundle.to_compiler_input()  # inspect before save; ContextIntake.save path redacts
```

> The committed demo `scripts/normalize_context_bundle.py` intentionally uses **mocked** payloads for offline use. For **live E2E**, use §5.1 (or §5.2) so provenance shows your real `TRQA-*` keys.

### 5.3 Continue live (unchanged downstream)

```bash
# Live compile from the real bundle (Gemini) -> validated plan
PYTHONPATH=. apps/cell/.venv/bin/python scripts/compile_test_plan.py \
  --context "$RUN_ROOT/01-mcp/context_bundle.json" \
  --out-dir "$RUN_ROOT/02-compile" --run-id run-live-compile-001 \
  --base-url https://testradius.dev --mode local_spike --live
# Then E2B probe/template/spike/runner/integration/evals per MANUAL_TEST_PLAN steps 5-10.
```

- **Expected:** compiled plan `source_refs[0].ref = TRQA-101`; runner trace contains **no** raw Jira JSON (only compiled plan + step contracts).

---

## 6. Multi-source merge (optional, real-user depth)

Add a Figma or GitHub source to the same bundle (real payloads, not mocks):

```python
from harness.integrations.mcp_context import ContextIntake, ContextSourceConfig
intake = ContextIntake()
bundle = intake.ingest([
    ContextSourceConfig(type="jira", ref="TRQA-101", payload=jira_json, tool="mcp.jira/get_issue"),
    ContextSourceConfig(type="figma", payload=figma_json, tool="mcp.figma/get_file"),
    ContextSourceConfig(type="github", payload=github_json, tool="mcp.github/get_issue"),
])
intake.normalizer.save_bundle(bundle, "$RUN_ROOT/01-mcp/context_bundle.json")
```

- **Expected:** `source_types` covers all acquired sources; ACs union; Figma frames appear as `user_flows`/design refs; provenance lists each tool.

---

## 7. Cleanup

- Close tickets (`Done`) or leave them open as E2E fixtures; **do not delete** the project unless the team agrees (keys are shared history).
- Rotate the API token if it was ever pasted anywhere; `JIRA_API_TOKEN` must **never** appear in `artifacts/`, bundles, or commits (`grep -r "$JIRA_API_TOKEN" artifacts/ || echo clean` — manual check only).

---

## 8. Verification checklist (this guide)

- [ ] Project `TRQA` exists; Tickets 1–3 are `To Do`/`In Progress` with `## Acceptance Criteria` headers.
- [ ] `curl …/issue/TRQA-101?fields=*all` returns ADF + labels.
- [ ] `fetch_jira_context.py --issue-key TRQA-101` saves bundle with `ticket_id=TRQA-101` and ≥3 ACs + Figma link.
- [ ] Live compile + runner complete against `https://testradius.dev` with the real ticket in provenance.

*End of guide. Next: `docs/MANUAL_TEST_PLAN_E2B_COMPUTER_USE_E2E.md` Phase 1 (real Jira bundle) → Phase 2 (live compile) → …*
