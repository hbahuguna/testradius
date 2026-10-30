import type {
  CreateRunInput,
  EvidenceManifest,
  ExecutionReport,
  PlanReport,
  PlanSummary,
  RunSummary,
} from "../types";

/**
 * The harness API surface. Implemented by:
 *   - HttpHarnessApi  (talks to the harness backend; STORY-H003.2)
 *   - MockHarnessApi  (clearly-labeled stub with realistic data; STORY-H001.2)
 */
export interface HarnessApi {
  readonly mode: "mock" | "http";
  listRuns(): Promise<RunSummary[]>;
  getRun(id: string): Promise<ExecutionReport | null>;
  getRunEvidence(id: string): Promise<EvidenceManifest | null>;
  listPlans(): Promise<PlanSummary[]>;
  getPlan(id: string): Promise<PlanReport | null>;
  /** Create a run: harness generates a plan, then (after STORY-H002.2 approval) executes. */
  createRun(input: CreateRunInput): Promise<RunSummary>;
}

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (res.status === 404) {
    throw new Error(`Not found: ${path}`);
  }
  if (!res.ok) {
    throw new Error(`API error ${res.status} on ${path}`);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status} on ${path}`);
  }
  return (await res.json()) as T;
}

/** Fetch-based client for the harness backend endpoints (STORY-H003.2). */
export class HttpHarnessApi implements HarnessApi {
  readonly mode = "http" as const;

  listRuns(): Promise<RunSummary[]> {
    return getJson<RunSummary[]>("/runs");
  }

  getRun(id: string): Promise<ExecutionReport | null> {
    return getJson<ExecutionReport>(`/runs/${encodeURIComponent(id)}`).catch((e: Error) => {
      if (e.message.startsWith("Not found")) return null;
      throw e;
    });
  }

  getRunEvidence(id: string): Promise<EvidenceManifest | null> {
    return getJson<EvidenceManifest>(`/runs/${encodeURIComponent(id)}/evidence`).catch((e: Error) => {
      if (e.message.startsWith("Not found")) return null;
      throw e;
    });
  }

  listPlans(): Promise<PlanSummary[]> {
    return getJson<PlanSummary[]>("/plans");
  }

  createRun(input: CreateRunInput): Promise<RunSummary> {
    return postJson<RunSummary>("/runs", input);
  }

  getPlan(id: string): Promise<PlanReport | null> {
    return getJson<PlanReport>(`/plans/${encodeURIComponent(id)}`).catch((e: Error) => {
      if (e.message.startsWith("Not found")) return null;
      throw e;
    });
  }
}
