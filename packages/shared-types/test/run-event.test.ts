import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

import { PHASES, RUN_EVENT_SCHEMA_VERSION, RUN_EVENT_TYPES, type RunEvent } from "../src/index";

const here = path.dirname(fileURLToPath(import.meta.url));
const readJson = (relative: string): unknown =>
  JSON.parse(readFileSync(path.join(here, "..", relative), "utf8"));

const schema = readJson("contracts/run-event.v1.json") as {
  required: string[];
  properties: {
    schema_version: { const: string };
    type: { enum: string[] };
    phase: { enum: Array<string | null> };
  };
};
const valid = readJson("fixtures/run-event.valid.json") as Record<string, unknown>;
const invalid = readJson("fixtures/run-event.invalid.json") as Record<string, unknown>;

const ajv = new Ajv2020({ allErrors: true, strict: false });
addFormats(ajv);
const validate = ajv.compile(schema);

describe("run-event.v1 contract", () => {
  it("accepts the shared valid fixture", () => {
    expect(validate(valid)).toBe(true);
  });

  it("rejects the shared invalid fixture", () => {
    expect(validate(invalid)).toBe(false);
  });

  it("rejects an unknown schema version", () => {
    expect(validate({ ...valid, schema_version: "2" })).toBe(false);
  });

  it("accepts a TypeScript-typed event", () => {
    const event: RunEvent = {
      schema_version: RUN_EVENT_SCHEMA_VERSION,
      run_id: "run_ts_typed",
      seq: 2,
      ts: "2026-10-23T12:00:01Z",
      type: "step",
      phase: "select",
      payload: { step: "select-tests" },
    };

    expect(validate(event)).toBe(true);
  });

  it("rejects additional properties", () => {
    expect(validate({ ...valid, unexpected: true })).toBe(false);
  });

  it("keeps the TypeScript enums in lockstep with the JSON schema", () => {
    expect(schema.properties.schema_version.const).toBe(RUN_EVENT_SCHEMA_VERSION);
    expect(schema.properties.type.enum).toEqual([...RUN_EVENT_TYPES]);
    expect(schema.properties.phase.enum).toEqual([...PHASES, null]);
    expect(schema.required).toEqual(["schema_version", "run_id", "seq", "ts", "type", "payload"]);
  });
});
