import type { KeyboardEvent } from "react";

interface ComposerProps {
  input: string;
  inFlight: boolean;
  disabled?: boolean;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
}

export function Composer({
  input,
  inFlight,
  disabled = false,
  onInputChange,
  onSend,
  onStop,
}: ComposerProps) {
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      onSend();
    }
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <label className="vh" htmlFor="chat-input">
        Message
      </label>
      <textarea
        id="chat-input"
        data-testid="chat-input"
        name="message"
        rows={1}
        value={input}
        disabled={disabled || inFlight}
        onChange={(event) => {
          onInputChange(event.target.value);
        }}
        onKeyDown={handleKeyDown}
        aria-describedby="chat-input-hint"
        placeholder="Ask about clinics, treatments, or appointments…"
        enterKeyHint="send"
      />
      <div className="comp-row">
        <span className="sub" id="chat-input-hint">
          Enter sends · Shift+Enter for a new line
        </span>
        <span className="row comp-actions">
          {inFlight ? (
            <button
              className="btn danger"
              type="button"
              data-testid="chat-stop"
              onClick={onStop}
            >
              Stop
            </button>
          ) : null}
          <button
            className="btn primary"
            type="submit"
            data-testid="chat-send"
            disabled={disabled || inFlight || input.trim().length === 0}
          >
            Send
          </button>
        </span>
      </div>
    </form>
  );
}
