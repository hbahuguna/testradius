# Epic 2: COM Generation Engine

**Theme**: "The brain." Backend that takes a URL + element selector and generates Playwright COM Python code.

**Dependencies**: Epic 1

---

## Stories

| # | Story | Effort |
|---|-------|--------|
| 2.1 | HTML parser — extract structured element info from HTML | 2d |
| 2.2 | Selector strategy engine — generate stable Playwright selectors | 2d |
| 2.3 | Heuristic component classifier — identify 16 component types | 3d |
| 2.4 | Element descriptor mapping — DOM element → Python descriptor | 1d |
| 2.5 | Jinja2 COM template — render Component Object Python class | 2d |
| 2.6 | CLI: `testradius com-gen <url> <selector>` | 1d |
| 2.7 | Jinja2 POM template — render Page Object class | 2d |
| 2.8 | Jinja2 test template — render pytest smoke/flow tests | 2d |
| 2.9 | CLI: `testradius generate <url>` — full suite generation | 1d |

---

## Component Types

LoginForm, DataTable, NavBar, SearchBox, Modal, Card, Tabs, Alert, Breadcrumb, Pagination, Sidebar, FormGroup, Dropdown, Accordion, Chart, GenericComponent

---

## Acceptance Criteria

- [ ] `testradius com-gen <url> <selector>` prints valid Python COM
- [ ] Generated COM has: typed locators, action methods, `is_loaded()`
- [ ] `testradius generate <url>` outputs runnable test suite
- [ ] All 16 component types have templates
- [ ] Selector strategy: data-testid > aria-label > role+text > id > CSS path
