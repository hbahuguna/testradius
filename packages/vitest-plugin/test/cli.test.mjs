import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { parseIstanbul, findTestFiles } from "../dist/cli.js";

// --- parseIstanbul: Istanbul JSON -> {sourceFile: [coveredLines]} ----------- //

test("parseIstanbul maps hit statements to their line ranges", () => {
  const data = {
    "./src/a.ts": {
      s: { "1": 1, "2": 0 },
      statementMap: {
        "1": { start: { line: 10 }, end: { line: 11 } },
        "2": { start: { line: 20 }, end: { line: 20 } },
      },
    },
  };
  assert.deepEqual(parseIstanbul(data), { "./src/a.ts": [10, 11] });
});

test("parseIstanbul expands multi-line statements (several symbols in one file)", () => {
  const data = {
    "./src/c.ts": {
      s: { "1": 3 },
      statementMap: { "1": { start: { line: 1 }, end: { line: 4 } } },
    },
  };
  assert.deepEqual(parseIstanbul(data), { "./src/c.ts": [1, 2, 3, 4] });
});

test("parseIstanbul skips files without a statement map", () => {
  assert.deepEqual(parseIstanbul({ "./src/b.ts": { f: {} } }), {});
});

test("parseIstanbul returns lines sorted and de-duplicated", () => {
  const data = {
    "./src/d.ts": {
      s: { "1": 1, "2": 1 },
      statementMap: {
        "1": { start: { line: 5 }, end: { line: 6 } },
        "2": { start: { line: 3 }, end: { line: 5 } },
      },
    },
  };
  assert.deepEqual(parseIstanbul(data), { "./src/d.ts": [3, 4, 5, 6] });
});

// --- findTestFiles: discovery + node_modules exclusion ---------------------- //

test("findTestFiles finds nested test/spec files and skips node_modules", () => {
  const root = mkdtempSync(join(tmpdir(), "tsp-"));
  try {
    mkdirSync(join(root, "src", "nested"), { recursive: true });
    mkdirSync(join(root, "src", "node_modules", "dep"), { recursive: true });
    writeFileSync(join(root, "src", "a.test.ts"), "");
    writeFileSync(join(root, "src", "nested", "b.spec.tsx"), "");
    writeFileSync(join(root, "src", "node_modules", "dep", "c.test.ts"), "");

    const found = findTestFiles(root, "src").map((p) => p.slice(root.length + 1));
    assert.deepEqual(found, ["src/a.test.ts", "src/nested/b.spec.tsx"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("findTestFiles returns [] for a missing test directory", () => {
  const root = mkdtempSync(join(tmpdir(), "tsp-"));
  try {
    assert.deepEqual(findTestFiles(root, "does-not-exist"), []);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
