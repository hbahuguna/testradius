import { describe, expect, it } from "vitest";

import { isTerminalStatus } from "../src/contracts.js";

describe("shared contract adapter", () => {
  it("treats only terminal run states as terminal", () => {
    expect(isTerminalStatus("succeeded")).toBe(true);
    expect(isTerminalStatus("failed")).toBe(true);
    expect(isTerminalStatus("cancelled")).toBe(true);
    expect(isTerminalStatus("timed_out")).toBe(true);
  });

  it("does not treat in-flight states as terminal", () => {
    expect(isTerminalStatus("queued")).toBe(false);
    expect(isTerminalStatus("running")).toBe(false);
  });
});
