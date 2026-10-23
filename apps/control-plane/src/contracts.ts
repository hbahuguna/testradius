import type { RunEvent, RunStatus } from "@testradius/shared-types";

export type { RunEvent, RunStatus };

/**
 * Local mirror of the contract version, type-checked against the shared package.
 * Keeping it local means the runtime image has no dependency on a workspace
 * package; changing the shared type without changing this fails `tsc`.
 */
export const RUN_EVENT_SCHEMA_VERSION: RunEvent["schema_version"] = "1";

const TERMINAL_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
]);

export function isTerminalStatus(status: RunStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}
