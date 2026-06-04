#!/usr/bin/env node
import { execSync, spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve, join, relative, dirname, basename } from "node:path";

export interface PerTestCoverage {
  [testName: string]: Record<string, number[]>;
}

export function parseIstanbul(istanbulData: Record<string, unknown>): Record<string, number[]> {
  const result: Record<string, Set<number>> = {};
  for (const [filePath, fileCov] of Object.entries(istanbulData)) {
    const fc = fileCov as Record<string, unknown>;
    const s = fc.s as Record<string, number> | undefined;
    const sm = fc.statementMap as Record<string, { start: { line: number }; end: { line: number } }> | undefined;
    if (!s || !sm) continue;
    if (!result[filePath]) result[filePath] = new Set();
    for (const [stmtId, hitCount] of Object.entries(s)) {
      if (hitCount > 0) {
        const stmt = sm[stmtId];
        if (stmt) {
          for (let l = stmt.start.line; l <= stmt.end.line; l++) result[filePath].add(l);
        }
      }
    }
  }
  return Object.fromEntries(
    Object.entries(result).map(([k, v]) => [k, [...v].sort((a, b) => a - b)])
  );
}

export function findTestFiles(root: string, testDir: string): string[] {
  const searchPath = resolve(root, testDir);
  if (!existsSync(searchPath)) return [];
  const result = spawnSync("find", [
    searchPath,
    "(", "-name", "*.test.ts", "-o", "-name", "*.test.tsx",
    "-o", "-name", "*.spec.ts", "-o", "-name", "*.spec.tsx",
    "-o", "-name", "*.test.js", "-o", "-name", "*.test.jsx",
    ")", "-not", "-path", "*/node_modules/*",
  ], { encoding: "utf-8", timeout: 30000 });
  if (result.status !== 0) return [];
  return result.stdout.split("\n").filter(Boolean).sort();
}

function runSingleTest(root: string, testFilePath: string, covDir: string): Record<string, number[]> {
  const tmpDir = join(root, covDir, basename(testFilePath).replace(/\.(ts|tsx|js|jsx)$/, ""));
  if (existsSync(tmpDir)) rmSync(tmpDir, { recursive: true });
  mkdirSync(tmpDir, { recursive: true });

  const relPath = relative(root, testFilePath);

  const result = spawnSync("npx", [
    "vitest", "run", relPath,
    "--reporter=verbose",
    "--coverage.enabled",
    "--coverage.provider=v8",
    `--coverage.reportsDirectory=${relative(root, tmpDir)}`,
    "--coverage.reporter=json",
    "--coverage.clean=true",
    "--coverage.cleanOnRerun=true",
  ], { cwd: root, encoding: "utf-8", timeout: 120000, stdio: "pipe" });

  const coverageFile = join(tmpDir, "coverage-final.json");
  if (!existsSync(coverageFile)) return {};

  const data = JSON.parse(readFileSync(coverageFile, "utf-8"));
  return parseIstanbul(data);
}

function main(): void {
  const [, , cmd, ...args] = process.argv;

  if (cmd === "run") {
    let maxFiles = Infinity;
    const filteredArgs = args.filter(a => {
      if (a.startsWith("--max=")) { maxFiles = parseInt(a.slice(6), 10); return false; }
      return true;
    });

    const root = resolve(filteredArgs[0] || ".");
    const testDir = filteredArgs[1] || "src";
    const covDirName = filteredArgs[2] || ".testsquad-cov";

    console.error(`test-squad: scanning ${testDir} in ${root}`);

    const testFiles = findTestFiles(root, testDir);
    console.error(`test-squad: found ${testFiles.length} test files`);

    const perTest: PerTestCoverage = {};
    let ok = 0;

    const files = testFiles.slice(0, maxFiles);
    for (let i = 0; i < files.length; i++) {
      const tf = files[i];
      const rel = relative(root, tf);
      console.error(`[${i + 1}/${files.length}] ${rel}`);
      const fileCov = runSingleTest(root, tf, covDirName);
      if (Object.keys(fileCov).length > 0) {
        perTest[rel] = fileCov;
        ok++;
      }
    }

    const outPath = join(root, "testsquad-per-test-coverage.json");
    writeFileSync(outPath, JSON.stringify(perTest, null, 2));
    console.error(`test-squad: ${ok}/${files.length} with coverage → ${outPath}`);

    // Cleanup temp dirs
    const tmpCovDir = join(root, covDirName);
    if (existsSync(tmpCovDir)) rmSync(tmpCovDir, { recursive: true });

    process.stdout.write(outPath);
  } else {
    console.error(`
testsquad-cov — Per-test coverage collector for TypeScript/JavaScript

Usage:
  testsquad-cov run <project-root> [test-dir] [temp-coverage-dir] [--max=N]

Runs vitest per test file with @vitest/coverage-v8 (source-map correct),
aggregates per-test-file Istanbul JSON, and outputs to
testsquad-per-test-coverage.json.

Options:
  --max=N    Limit to N test files (useful for testing)

Compatible: vitest >= 3.0.0 with @vitest/coverage-v8 installed.
`);
  }
}

main();
