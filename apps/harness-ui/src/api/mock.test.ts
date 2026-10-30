import { describe, expect, it } from "vitest";

import { MockHarnessApi } from "./mock";

describe("MockHarnessApi", () => {
  it("lists runs and includes known mock runs", async () => {
    const api = new MockHarnessApi();
    const runs = await api.listRuns();
    expect(Array.isArray(runs)).toBe(true);
    expect(runs.length).toBeGreaterThan(0);
    expect(runs[0]).toHaveProperty("id");
    expect(runs[0]).toHaveProperty("target");
    expect(runs[0]).toHaveProperty("status");
    expect(runs[0]).toHaveProperty("count");
    expect(runs[0]).toHaveProperty("evidence");
  });

  it("createRun creates a PLANNING run and prepends it", async () => {
    const api = new MockHarnessApi();
    const before = await api.listRuns();
    const beforeLen = before.length;
    const created = await api.createRun({
      target: "https://example.com",
      goal: "Verify login, logout, and session expiry flows",
      context: "T-42",
      model: "gemini-2.5-flash",
    });

    expect(created.id).toBeTruthy();
    expect(created.target).toBe("https://example.com");
    expect(created.status).toBe("PLANNING");
    expect(created.count).toBe(0);
    expect(typeof created.evidence).toBe("string");
    expect(created.createdAt).toBeTruthy();

    const after = await api.listRuns();
    expect(after.length).toBe(beforeLen + 1);
    expect(after[0].id).toBe(created.id);
    expect(after[0].status).toBe("PLANNING");
  });

  it("getRun returns null for unknown run ids", async () => {
    const api = new MockHarnessApi();
    expect(await api.getRun("does-not-exist")).toBeNull();
  });

  it("getRunEvidence returns the manifest mock for known ids", async () => {
    const api = new MockHarnessApi();
    const manifest = await api.getRunEvidence("20261030103857");
    expect(manifest).not.toBeNull();
    expect(manifest?.run_id).toBe("run-1793356725");
    expect(Array.isArray(manifest?.artifacts)).toBe(true);
    expect(manifest!.artifacts.length).toBeGreaterThan(0);
  });
});
