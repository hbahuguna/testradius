/**
 * Wire contracts shared by the cell, the control plane, and the web app.
 *
 * The JSON Schema in `contracts/` is the source of truth. This module mirrors it
 * for TypeScript consumers and the Python cell validates the same schema in
 * `apps/cell/tests/test_event_contract.py`.
 */

export const RUN_EVENT_SCHEMA_VERSION = "1" as const;

export const PHASES = [
  "isolate",
  "select",
  "generate",
  "execute",
  "prove",
  "gate",
  "report",
] as const;
export type Phase = (typeof PHASES)[number];

export const RUN_STATUSES = [
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const RUN_EVENT_TYPES = [
  "phase",
  "step",
  "tool",
  "verdict",
  "log",
  "stream_lagged",
] as const;
export type RunEventType = (typeof RUN_EVENT_TYPES)[number];

export const DEPENDENCY_STATUSES = ["ok", "degraded", "unreachable", "not_configured"] as const;
export type DependencyStatus = (typeof DEPENDENCY_STATUSES)[number];

export interface RunEvent {
  schema_version: typeof RUN_EVENT_SCHEMA_VERSION;
  run_id: string;
  seq: number;
  ts: string;
  type: RunEventType;
  phase?: Phase | null;
  payload: Record<string, unknown>;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface AgentStep {
  schema_version: "1";
  step_id: string;
  thought: string;
  action: string | null;
  args: Record<string, unknown>;
  observation: string;
  citations: string[];
  usage: TokenUsage;
}

export interface HealthResponse {
  ready: boolean;
  aut_status: DependencyStatus;
  graph_status: DependencyStatus;
  version: string;
}
