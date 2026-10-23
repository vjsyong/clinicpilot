import { useEffect, useRef, useState } from "react";

interface ModelSettingsDialogProps {
  configured: boolean;
  hint: string | null;
  onClose: () => void;
  onSave: (apiKey: string) => Promise<boolean>;
  onClear: () => Promise<void>;
}

export function ModelSettingsDialog({
  configured,
  hint,
  onClose,
  onSave,
  onClear,
}: ModelSettingsDialogProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
    }
  }, []);

  async function save() {
    const key = apiKey.trim();
    if (!key) {
      setError("Enter a DeepSeek API key.");
      return;
    }
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const verified = await onSave(key);
      setApiKey("");
      setStatus(
        verified
          ? "Saved. DeepSeek is available for this process."
          : "Saved. The verification call did not succeed, so check the key before relying on it.",
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save the key.");
    } finally {
      setBusy(false);
    }
  }

  async function clear() {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      await onClear();
      setStatus("Cleared. The local model remains available.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not clear the key.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="dlg"
      aria-labelledby="model-settings-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={onClose}
    >
      <div className="dlg-h">
        <h3 id="model-settings-title">Model settings</h3>
        <button
          type="button"
          className="btn ghost small sp"
          onClick={onClose}
          aria-label="Close model settings"
        >
          Close
        </button>
      </div>
      <div className="dlg-b">
        <p className="sub">
          The DeepSeek key is kept in this server process only. It is never written to the
          database or environment, and it is cleared when the app restarts.
        </p>
        <p className="sub" data-testid="deepseek-status">
          {configured
            ? `DeepSeek key configured (${hint ?? "hidden"}).`
            : "DeepSeek is not configured; the local model is the only available provider."}
        </p>
        <label htmlFor="deepseek-api-key">DeepSeek API key</label>
        <input
          id="deepseek-api-key"
          data-testid="deepseek-api-key"
          type="password"
          value={apiKey}
          autoComplete="off"
          spellCheck={false}
          aria-describedby="deepseek-key-help"
          aria-invalid={error ? true : undefined}
          onChange={(event) => {
            setApiKey(event.target.value);
          }}
        />
        <p className="sub" id="deepseek-key-help">
          Paste the key from the DeepSeek console. Use the Key button any time to replace or
          clear it.
        </p>
        {error ? (
          <span className="field-err" role="alert">
            {error}
          </span>
        ) : null}
        {status ? (
          <p className="sub" role="status">
            {status}
          </p>
        ) : null}
      </div>
      <div className="dlg-f">
        {configured ? (
          <button
            type="button"
            className="btn danger"
            data-testid="deepseek-clear"
            onClick={() => {
              void clear();
            }}
            disabled={busy}
          >
            Clear key
          </button>
        ) : null}
        <button type="button" className="btn" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button
          type="button"
          className="btn primary"
          data-testid="deepseek-save"
          onClick={() => {
            void save();
          }}
          disabled={busy}
        >
          {busy ? "Saving…" : "Save key"}
        </button>
      </div>
    </dialog>
  );
}
