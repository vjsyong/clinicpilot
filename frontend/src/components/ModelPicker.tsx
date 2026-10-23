import type { ModelInfo, ModelProvider } from "../api/types";

interface ModelPickerProps {
  model: ModelProvider;
  models: ModelInfo[];
  disabled?: boolean;
  notice?: string | null;
  onChange: (model: ModelProvider) => void;
  onConfigure: () => void;
}

export function ModelPicker({
  model,
  models,
  disabled = false,
  notice = null,
  onChange,
  onConfigure,
}: ModelPickerProps) {
  const local = models.find((item) => item.id === "local");
  const deepseek = models.find((item) => item.id === "deepseek");
  const deepseekAvailable = deepseek?.available === true;

  return (
    <div className="model-bar">
      <div className="row">
        <label className="sub" htmlFor="model-picker">
          Model
        </label>
        <select
          id="model-picker"
          data-testid="model-picker"
          className="select-inline"
          value={model}
          disabled={disabled}
          onChange={(event) => {
            onChange(event.target.value === "deepseek" ? "deepseek" : "local");
          }}
        >
          <option value="local">
            {local?.label ?? "Gemma 26B-A4B (local)"}
            {local?.model ? ` · ${local.model}` : ""}
          </option>
          <option value="deepseek" disabled={!deepseekAvailable}>
            {deepseek?.label ?? "DeepSeek (backup)"}
            {deepseekAvailable ? "" : " · add a key"}
          </option>
        </select>
        <button
          type="button"
          className="btn small"
          data-testid="model-settings"
          onClick={onConfigure}
          disabled={disabled}
        >
          Key
        </button>
      </div>
      {notice ? (
        <p className="sub" role="status" data-testid="model-notice">
          {notice}
        </p>
      ) : null}
    </div>
  );
}
