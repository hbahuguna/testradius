import { HttpHarnessApi, type HarnessApi } from "./client";
import { MockHarnessApi } from "./mock";

export type { HarnessApi } from "./client";

/**
 * Client factory. Mock is the default until the harness backend API lands
 * (STORY-H003.2). Set VITE_USE_MOCKS=0 to point at the real backend.
 */
export function createHarnessApi(): HarnessApi {
  return import.meta.env.VITE_USE_MOCKS === "0"
    ? new HttpHarnessApi()
    : new MockHarnessApi();
}

let singleton: HarnessApi | null = null;

/** Lazily-created shared client (stable across renders). */
export function getHarnessApi(): HarnessApi {
  if (!singleton) {
    singleton = createHarnessApi();
  }
  return singleton;
}
