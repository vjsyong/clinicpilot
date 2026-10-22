import { describe, expect, it } from "vitest";

import { DEFAULT_CONFIG, parseRuntimeConfig } from "../src/lib/config";

describe("parseRuntimeConfig", () => {
  it("parses the injected runtime configuration", () => {
    expect(
      parseRuntimeConfig('{"prefix":"/demo/","appName":"ClinicPilot"}'),
    ).toEqual({ prefix: "/demo/", appName: "ClinicPilot" });
  });

  it("accepts a generated production-style prefix", () => {
    expect(
      parseRuntimeConfig('{"prefix":"/a1b2c3d4e5f6/","appName":"ClinicPilot"}'),
    ).toEqual({ prefix: "/a1b2c3d4e5f6/", appName: "ClinicPilot" });
  });

  it("falls back on malformed JSON", () => {
    expect(parseRuntimeConfig("{not json")).toEqual(DEFAULT_CONFIG);
  });

  it("falls back on non-object payloads", () => {
    expect(parseRuntimeConfig('["/demo/","ClinicPilot"]')).toEqual(DEFAULT_CONFIG);
    expect(parseRuntimeConfig("null")).toEqual(DEFAULT_CONFIG);
  });

  it("rejects an invalid prefix and an empty app name", () => {
    expect(parseRuntimeConfig('{"prefix":"https://evil.example/","appName":"  "}')).toEqual(
      DEFAULT_CONFIG,
    );
  });

  it("keeps the default patient-facing name when appName is absent", () => {
    expect(parseRuntimeConfig('{"prefix":"/demo/"}')).toEqual(DEFAULT_CONFIG);
  });
});
