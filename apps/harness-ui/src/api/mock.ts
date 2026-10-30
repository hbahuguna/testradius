import type {
  CreateRunInput,
  EvidenceManifest,
  ExecutionReport,
  PlanReport,
  PlanSummary,
  RunSummary,
} from "../types";

import type { HarnessApi } from "./client";

/**
 * Mock data derived from real harness output (run-1793356725 /
 * testradius-exec-real-20261030103857) so shapes are realistic.
 * Clearly-labeled stub for the harness API that lands in STORY-H003.2.
 */

const REAL_RUN_DIR = "artifacts/run-1793356725";
const REAL_VIDEO = `${REAL_RUN_DIR}/page@dab9a5b347c2e799d9dd7c147416c046.webm`;

function initialRuns(): RunSummary[] {
  return [
    {
      id: "20261030103857",
      target: "https://testradius.dev",
      status: "COMPLETED",
      count: 3,
      evidence: `${REAL_RUN_DIR}/manifest.json`,
      createdAt: "2026-10-30T10:38:57Z",
    },
    {
      id: "1793355958",
      target: "https://testradius.dev",
      status: "COMPLETED",
      count: 9,
      evidence: "artifacts/run-1793355958/manifest.json",
      createdAt: "2026-10-30T09:19:18Z",
    },
  ];
}

function initialPlans(): PlanSummary[] {
  return [
    {
      id: "1793353092",
      target: "https://testradius.dev",
      status: "PASS",
      createdAt: "2026-10-30T08:44:52Z",
    },
  ];
}

const execution: ExecutionReport = {
  source_plan: "reports/testradius-e2e-run-1793353092.json",
  target: "https://testradius.dev",
  test_plan_title: "Manual Test Plan for testradius.dev",
  mode: "real_browser_sandbox",
  executed: [
    {
      id: "TC_NAV_01",
      title: "Header Navigation Links & Logo Redirection",
      category: "Navigation",
      preconditions: "Desktop browser open at 1920x1080 resolution.",
      status: "EXECUTED",
      steps: [
        "Navigate to https://testradius.dev.",
        "Click on each navigation menu item in the header.",
        "Click the brand logo from a scrolled position or secondary page.",
      ],
      expectedChecks: [
        "Clicking the logo returns the user to the top of the homepage.",
        "Each menu item routes to the correct target URL or smooth-scrolls.",
      ],
      screenshots: ["TC_NAV_01.png"],
      assertions: [
        { check: "Clicking the logo returns the user to the top of the homepage.", status: "RECORDED" },
        { check: "Each menu item routes to the correct target URL or smooth-scrolls.", status: "RECORDED" },
      ],
    },
    {
      id: "TC_CTA_01",
      title: "Hero Section Primary CTA",
      category: "Call-to-Action",
      status: "EXECUTED",
      steps: [
        "Locate the primary CTA in the hero section.",
        "Hover over the button.",
        "Click the primary CTA button.",
      ],
      expectedChecks: [
        "Hover state shows an immediate visual change.",
        "Click opens the correct destination without delay.",
      ],
      screenshots: ["TC_CTA_01.png"],
      assertions: [
        { check: "Hover state shows an immediate visual change.", status: "RECORDED" },
        { check: "Click opens the correct destination without delay.", status: "RECORDED" },
      ],
    },
    {
      id: "TC_RESP_01",
      title: "Mobile Navigation (Hamburger Menu)",
      category: "Responsiveness",
      status: "EXECUTED",
      steps: [
        "Open https://testradius.dev on mobile viewport.",
        "Verify the desktop navigation is hidden and the hamburger icon is visible.",
        "Tap the hamburger menu icon.",
      ],
      expectedChecks: [
        "Hamburger icon toggle animation executes smoothly.",
        "Mobile drawer displays all primary navigation items clearly.",
      ],
      screenshots: ["TC_RESP_01.png"],
      assertions: [
        { check: "Hamburger icon toggle animation executes smoothly.", status: "RECORDED" },
        { check: "Mobile drawer displays all primary navigation items clearly.", status: "RECORDED" },
      ],
    },
  ],
  count: 3,
  status: "COMPLETED",
  video: REAL_VIDEO,
  trace: `${REAL_RUN_DIR}/trace.json`,
  evidence: `${REAL_RUN_DIR}/manifest.json`,
};

const manifest: EvidenceManifest = {
  run_id: "run-1793356725",
  artifacts: [
    { type: "video", path: `${REAL_VIDEO}` },
    { type: "screenshot", path: `${REAL_RUN_DIR}/00_homepage.png` },
    { type: "screenshot", path: `${REAL_RUN_DIR}/TC_NAV_01.png` },
    { type: "screenshot", path: `${REAL_RUN_DIR}/TC_CTA_01.png` },
    { type: "screenshot", path: `${REAL_RUN_DIR}/TC_RESP_01.png` },
    { type: "screenshot", path: `${REAL_RUN_DIR}/99_final.png` },
    { type: "console", path: `${REAL_RUN_DIR}/console.log` },
    { type: "network", path: `${REAL_RUN_DIR}/network.json` },
    { type: "trace", path: `${REAL_RUN_DIR}/trace.zip` },
  ],
};

const planReport: PlanReport = {
  target: "https://testradius.dev",
  plan: "```json\n{\n  \"testPlanTitle\": \"Manual Test Plan for testradius.dev\",\n  \"testCases\": [\"...\"]\n}\n```",
  status: "PASS",
  evidence: "artifacts/run-1793353092/manifest.json",
};

const delay = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export class MockHarnessApi implements HarnessApi {
  readonly mode = "mock" as const;
  private runs = initialRuns();
  private readonly plans = initialPlans();

  async listRuns(): Promise<RunSummary[]> {
    await delay(150);
    return this.runs;
  }

  async createRun(input: CreateRunInput): Promise<RunSummary> {
    await delay(300);
    const id = `${Date.now()}`;
    const created: RunSummary = {
      id,
      target: input.target,
      // A fresh run starts in PLANNING; the plan-review checkpoint
      // (STORY-H002.2) gates the transition to execution.
      status: "PLANNING",
      count: 0,
      evidence: "",
      createdAt: new Date().toISOString(),
      approved: false,
      planId: "1793353092",
    };
    this.runs.unshift(created);
    return created;
  }

  async approveRun(runId: string): Promise<RunSummary> {
    await delay(200);
    const idx = this.runs.findIndex((r) => r.id === runId);
    if (idx === -1) throw new Error(`Run not found: ${runId}`);
    const updated = { ...this.runs[idx], approved: true, status: "APPROVED" };
    this.runs[idx] = updated;
    return updated;
  }

  async startRun(runId: string): Promise<RunSummary> {
    await delay(200);
    const idx = this.runs.findIndex((r) => r.id === runId);
    if (idx === -1) throw new Error(`Run not found: ${runId}`);
    const updated = { ...this.runs[idx], status: "RUNNING" };
    this.runs[idx] = updated;
    return updated;
  }

  async getLiveState(runId: string): Promise<import("../types").LiveExecutionState | null> {
    await delay(100);
    if (runId === "20261030103857") {
      return {
        runId: "20261030103857",
        target: "https://testradius.dev",
        status: "COMPLETED",
        currentStepId: null,
        progress: { completed: 3, total: 3, failed: 0 },
        steps: [
          {
            id: "s1",
            testCaseId: "TC_NAV_01",
            title: "Header Navigation Links & Logo Redirection",
            status: "COMPLETED",
            startedAt: "2026-10-30T10:38:58Z",
            endedAt: "2026-10-30T10:39:04Z",
            durationMs: 6000,
          },
          {
            id: "s2",
            testCaseId: "TC_CTA_01",
            title: "Hero Section Primary CTA",
            status: "COMPLETED",
            startedAt: "2026-10-30T10:39:04Z",
            endedAt: "2026-10-30T10:39:09Z",
            durationMs: 5000,
          },
          {
            id: "s3",
            testCaseId: "TC_RESP_01",
            title: "Mobile Navigation (Hamburger Menu)",
            status: "COMPLETED",
            startedAt: "2026-10-30T10:39:09Z",
            endedAt: "2026-10-30T10:39:15Z",
            durationMs: 6000,
          },
        ],
        logs: [
          { id: "l1", ts: "2026-10-30T10:38:57Z", level: "info", message: "Starting Playwright Chromium (headless)" },
          { id: "l2", ts: "2026-10-30T10:38:58Z", level: "info", message: "Navigated to https://testradius.dev" },
          { id: "l3", ts: "2026-10-30T10:39:15Z", level: "info", message: "Run completed: 3/3 executed" },
        ],
        updatedAt: "2026-10-30T10:39:15Z",
        evidenceDir: REAL_RUN_DIR,
        video: REAL_VIDEO,
        trace: `${REAL_RUN_DIR}/trace.json`,
      };
    }
    return null;
  }

  async getRun(id: string): Promise<ExecutionReport | null> {
    await delay(150);
    return id === "20261030103857" ? execution : null;
  }

  async getRunEvidence(_id: string): Promise<EvidenceManifest | null> {
    await delay(150);
    return manifest;
  }

  async listPlans(): Promise<PlanSummary[]> {
    await delay(150);
    return this.plans;
  }

  async getPlan(id: string): Promise<PlanReport | null> {
    await delay(150);
    return id === "1793353092" ? planReport : null;
  }
}
