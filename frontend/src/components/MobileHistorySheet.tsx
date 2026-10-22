import { useEffect, type ReactNode } from "react";

interface MobileHistorySheetProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function MobileHistorySheet({ open, onClose, children }: MobileHistorySheetProps) {
  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
    };
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="sheet-ov"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby="history-sheet-heading"
      >
        <div className="sheet-h">
          <b id="history-sheet-heading">Chats</b>
          <button type="button" className="iconbtn" aria-label="Close chat history" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="sheet-b">{children}</div>
      </div>
    </div>
  );
}
