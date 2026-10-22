import type { SourceRef } from "../api/types";

const SOURCE_LABELS: Record<string, string> = {
  "clinics.csv": "Clinic",
  "doctors.csv": "Doctor",
  "treatments.csv": "Treatment",
};

export function sourceLabel(source: SourceRef): string {
  return SOURCE_LABELS[source.source_file] ?? source.source_file;
}

export function sourceKey(source: SourceRef): string {
  return `${source.source_file}:${source.record_id}`;
}

export function sourceTitle(source: SourceRef): string {
  return `${sourceLabel(source)} ${source.record_id}`;
}
