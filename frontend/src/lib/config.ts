export interface RuntimeConfig {
  prefix: string;
  appName: string;
}

export const DEFAULT_CONFIG: RuntimeConfig = {
  prefix: "/demo/",
  appName: "ClinicPilot",
};

const PREFIX_PATTERN = /^\/[A-Za-z0-9][A-Za-z0-9/_-]*\/$/;

export function parseRuntimeConfig(raw: string | null | undefined): RuntimeConfig {
  if (typeof raw !== "string" || raw.length === 0) {
    return DEFAULT_CONFIG;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return DEFAULT_CONFIG;
  }

  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return DEFAULT_CONFIG;
  }

  const record = parsed as Record<string, unknown>;
  const prefix =
    typeof record.prefix === "string" && PREFIX_PATTERN.test(record.prefix)
      ? record.prefix
      : DEFAULT_CONFIG.prefix;
  const appName =
    typeof record.appName === "string" &&
    record.appName.trim().length > 0 &&
    record.appName.length <= 80
      ? record.appName.trim()
      : DEFAULT_CONFIG.appName;

  return { prefix, appName };
}

export function readRuntimeConfig(doc: Document = document): RuntimeConfig {
  const element = doc.getElementById("clinicpilot-config");
  return parseRuntimeConfig(element?.textContent ?? null);
}
