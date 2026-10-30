#!/usr/bin/env node
/**
 * Executable check for STORY-H001.2: verifies that the on-disk harness
 * reports and evidence manifests conform to the shapes encoded in
 * src/types.ts. Keep the checks below in sync with src/types.ts.
 *
 * Usage: node scripts/validate-shapes.mjs   (or: pnpm validate:shapes)
 */
import { readdirSync, readFileSync, existsSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const reportsDir = join(repoRoot, "reports");
const artifactsDir = join(repoRoot, "artifacts");

let checked = 0;
const failures = [];

function fail(file, msg) {
  failures.push(`${file}: ${msg}`);
}

function readJson(file) {
  return JSON.parse(readFileSync(file, "utf8"));
}

function isPlainObject(x) {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

/* ---- Plan reports: reports/testradius-e2e-run-*.json -> PlanReport ---- */
function checkPlanReport(file, d) {
  if (typeof d.target !== "string") fail(file, "target must be a string");
  if (typeof d.plan !== "string" && !isPlainObject(d.plan)) fail(file, "plan must be a string or object");
  if (typeof d.status !== "string") fail(file, "status must be a string");
  if (typeof d.evidence !== "string") fail(file, "evidence must be a string");
}

/* ---- Execution reports: reports/testradius-exec*.json -> ExecutionReport ---- */
function checkExecutionReport(file, d) {
  if (typeof d.target !== "string") fail(file, "target must be a string");
  if (!Array.isArray(d.executed)) fail(file, "executed must be an array");
  if (typeof d.count !== "number") fail(file, "count must be a number");
  if (typeof d.status !== "string") fail(file, "status must be a string");
  if (typeof d.evidence !== "string") fail(file, "evidence must be a string");
  for (const [i, tc] of (d.executed ?? []).entries()) {
    if (typeof tc.id !== "string") fail(file, `executed[${i}].id must be a string`);
    if (typeof tc.status !== "string") fail(file, `executed[${i}].status must be a string`);
    if (!Array.isArray(tc.steps)) fail(file, `executed[${i}].steps must be an array`);
    if (!Array.isArray(tc.expectedChecks)) fail(file, `executed[${i}].expectedChecks must be an array`);
    if (tc.screenshots !== undefined && !Array.isArray(tc.screenshots)) {
      fail(file, `executed[${i}].screenshots must be an array when present`);
    }
    if (tc.assertions !== undefined) {
      if (!Array.isArray(tc.assertions)) fail(file, `executed[${i}].assertions must be an array when present`);
      for (const [j, a] of tc.assertions.entries()) {
        if (typeof a.check !== "string" || typeof a.status !== "string") {
          fail(file, `executed[${i}].assertions[${j}] must have {check, status} strings`);
        }
      }
    }
  }
}

/* ---- Smoke reports: reports/smoke-run-*.json -> SmokeReport ---- */
function checkSmokeReport(file, d) {
  if (typeof d.ticket !== "string") fail(file, "ticket must be a string");
  if (typeof d.context !== "string") fail(file, "context must be a string");
  if (typeof d.status !== "string") fail(file, "status must be a string");
  if (typeof d.evidence !== "string") fail(file, "evidence must be a string");
}

/* ---- Evidence manifests: artifacts/run-<id>/manifest.json -> EvidenceManifest ---- */
function checkManifest(file, d) {
  if (typeof d.run_id !== "string") fail(file, "run_id must be a string");
  if (!Array.isArray(d.artifacts)) fail(file, "artifacts must be an array");
  for (const [i, a] of (d.artifacts ?? []).entries()) {
    if (!isPlainObject(a) || typeof a.type !== "string" || typeof a.path !== "string") {
      fail(file, `artifacts[${i}] must have {type, path} strings`);
    }
  }
}

/* ---- Scan ---- */
let plans = 0;
let execs = 0;
let smokes = 0;
let manifests = 0;

if (existsSync(reportsDir)) {
  for (const name of readdirSync(reportsDir)) {
    if (!name.endsWith(".json")) continue;
    const file = join(reportsDir, name);
    let d;
    try {
      d = readJson(file);
    } catch (e) {
      fail(name, `unparseable JSON (${e.message})`);
      continue;
    }
    checked++;
    if (name.startsWith("testradius-e2e-run-")) {
      plans++;
      checkPlanReport(name, d);
    } else if (name.startsWith("testradius-exec")) {
      execs++;
      checkExecutionReport(name, d);
    } else if (name.startsWith("smoke-run-")) {
      smokes++;
      checkSmokeReport(name, d);
    }
    // a11y-report.json and others: not part of this story's surface.
  }
}

if (existsSync(artifactsDir)) {
  for (const name of readdirSync(artifactsDir)) {
    const runDir = join(artifactsDir, name);
    if (!name.startsWith("run-") || !statSync(runDir).isDirectory()) continue;
    const manifestPath = join(runDir, "manifest.json");
    if (!existsSync(manifestPath)) {
      fail(`${name}/manifest.json`, "missing manifest");
      continue;
    }
    let d;
    try {
      d = readJson(manifestPath);
    } catch (e) {
      fail(`${name}/manifest.json`, `unparseable JSON (${e.message})`);
      continue;
    }
    checked++;
    manifests++;
    checkManifest(`${name}/manifest.json`, d);
  }
}

console.log(
  `validated ${checked} files: ${plans} plan reports, ${execs} execution reports, ${smokes} smoke reports, ${manifests} evidence manifests`,
);

if (failures.length > 0) {
  console.error(`\nSHAPE MISMATCH (${failures.length}):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}

console.log("OK: all reports and manifests match src/types.ts shapes");
