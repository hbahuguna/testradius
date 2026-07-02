# Story 3.2: DOM Tree View

**Status**: Complete
**Epic**: 3 — Page Viewer Shell
**Effort**: 2d

---

## Summary

Collapsible tree view of parsed DOM elements in the left panel. Users can click any element to select it, triggering COM generation for that element via the backend.

## Implementation

- **`TreeNode` component**: Recursive React component rendering each element with tag, ID badge, class badges, role badge, text preview
- **Depth-based indentation**: 16px per level
- **Collapse/expand**: ▸/▾ toggle arrows; first 2 levels auto-expanded
- **Element selection**: Click highlights the element and calls `POST /com-gen`
- **Interactive indicator**: Green left border on interactive elements (buttons, inputs, links)
- **Node count**: Header shows total element count

## Files

- `apps/workbench/src/App.tsx` — `TreeNode` component, `.tree-panel`, `.code-panel`
- `apps/workbench/src/App.css` — `.tree-node`, `.tag`, `.badge`, `.toggle`, `.text-preview`

## Verification

1. Analyze a page
2. Expand/collapse tree nodes
3. Click an input element inside a form
4. Verify the right panel shows generated COM Python code
