import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { KnowledgeRecord, SourceRef } from "../api/types";
import { sourceKey, sourceTitle } from "../lib/sources";

interface SourceInspectorProps {
  source: SourceRef | null;
  onClose: () => void;
}

const FIELD_LABELS: Record<string, string> = {
  record_id: "Record ID",
  treatment_id: "Treatment ID",
  doctor_id: "Doctor ID",
  clinic_id: "Clinic ID",
  clinic_name: "Clinic name",
  name: "Name",
  category: "Category",
  specialty: "Specialty",
};

function humanize(value: string): string {
  return FIELD_LABELS[value] ?? value.replaceAll("_", " ");
}

function SourceBody({ source }: { source: SourceRef }) {
  const [record, setRecord] = useState<KnowledgeRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .knowledgeRecord(source.source_file, source.record_id)
      .then((loaded) => {
        if (!cancelled) {
          setRecord(loaded);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Could not load this source.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [source]);

  if (error) {
    return (
      <div className="msg err" role="alert">
        {error}
      </div>
    );
  }
  if (!record) {
    return (
      <p className="sub" role="status">
        Loading source...
      </p>
    );
  }
  return (
    <div className="stack">
      <div className="row">
        <span className="badge">{record.source_file}</span>
        <span className="badge acc">{record.record_id}</span>
        <span className="mono sub">{record.citation}</span>
      </div>
      <div className="kv">
        {Object.entries(record.metadata).map(([key, value]) => (
          <FragmentRow key={key} label={humanize(key)} value={value} />
        ))}
      </div>
      <p className="prose">{record.text}</p>
    </div>
  );
}

function FragmentRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="k">{label}</span>
      <span>{value}</span>
    </>
  );
}

export function SourceInspector({ source, onClose }: SourceInspectorProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    if (source && !dialog.open) {
      dialog.showModal();
    }
    if (!source && dialog.open) {
      dialog.close();
    }
  }, [source]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) {
      return;
    }
    const handleClose = () => {
      onClose();
    };
    dialog.addEventListener("close", handleClose);
    return () => {
      dialog.removeEventListener("close", handleClose);
    };
  }, [onClose]);

  return (
    <dialog
      ref={dialogRef}
      className="dlg dlg-wide"
      aria-labelledby="source-inspector-heading"
      data-testid="source-inspector"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          dialogRef.current?.close();
        }
      }}
    >
      <div className="dlg-h">
        <h3 id="source-inspector-heading">
          {source ? sourceTitle(source) : "Knowledge source"}
        </h3>
        <span className="sp" />
        <button
          type="button"
          className="iconbtn"
          aria-label="Close source details"
          onClick={() => {
            dialogRef.current?.close();
          }}
        >
          ×
        </button>
      </div>
      <div className="dlg-b">
        {source ? <SourceBody key={sourceKey(source)} source={source} /> : null}
      </div>
      <div className="dlg-f">
        <button
          type="button"
          className="btn small"
          onClick={() => {
            dialogRef.current?.close();
          }}
        >
          Close
        </button>
      </div>
    </dialog>
  );
}
