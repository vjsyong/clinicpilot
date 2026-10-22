import { useCallback, useEffect, useMemo, useState } from "react";

import { API_PATHS, ApiError, api } from "./api/client";
import type { BookingView } from "./api/types";
import { AppHeader } from "./components/AppHeader";
import { BookingsPanel } from "./components/BookingsPanel";
import { ChatPanel } from "./components/ChatPanel";
import { ExplorerPanel } from "./components/ExplorerPanel";
import { useAssistant } from "./hooks/useAssistant";
import { readRuntimeConfig } from "./lib/config";

type WorkbenchView = "chat" | "bookings" | "explorer";

function initialView(): WorkbenchView {
  if (window.location.hash === "#bookings-panel") {
    return "bookings";
  }
  if (window.location.hash === "#explorer-panel") {
    return "explorer";
  }
  return "chat";
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error && error.message.length > 0) {
    return error.message;
  }
  return "Something went wrong. Please try again.";
}

export function App() {
  const config = useMemo(() => readRuntimeConfig(), []);
  const [view, setView] = useState<WorkbenchView>(initialView);
  const [bookings, setBookings] = useState<BookingView[]>([]);
  const [bookingsLoading, setBookingsLoading] = useState(true);
  const [bookingsError, setBookingsError] = useState<string | null>(null);

  const refreshBookings = useCallback(async () => {
    setBookingsLoading(true);
    setBookingsError(null);
    try {
      const loaded = await api.listBookings();
      setBookings(loaded);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        return;
      }
      setBookingsError(describeError(error));
    } finally {
      setBookingsLoading(false);
    }
  }, []);

  const assistant = useAssistant({ onBookingCreated: refreshBookings });

  useEffect(() => {
    document.title = config.appName;
  }, [config.appName]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const loaded = await api.listBookings();
        if (!cancelled) {
          setBookings(loaded);
          setBookingsError(null);
        }
      } catch (error) {
        if (!cancelled && !(error instanceof ApiError && error.status === 401)) {
          setBookingsError(describeError(error));
        }
      } finally {
        if (!cancelled) {
          setBookingsLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const logout = useCallback(async () => {
    await api.logout();
    window.location.assign(API_PATHS.login);
  }, []);

  const showView = useCallback((next: WorkbenchView) => {
    setView(next);
    const hash =
      next === "bookings"
        ? "#bookings-panel"
        : next === "explorer"
          ? "#explorer-panel"
          : "#chat-panel";
    window.history.replaceState(null, "", hash);
  }, []);

  return (
    <div className="app" data-testid="workbench">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside className="side" id="workbench-side" aria-label="ClinicPilot">
        <div className="side-top">
          <span className="brand">
            <span className="brand-mark" aria-hidden="true">
              CP
            </span>
            <span className="brand-name">ClinicPilot</span>
          </span>
          <div className="brand-sub">Patient P001</div>
        </div>
        <nav className="nav" aria-label="Workbench">
          <div className="nav-label">Workbench</div>
          <button
            type="button"
            className={view === "chat" ? "nav-item active" : "nav-item"}
            data-testid="nav-chat"
            aria-current={view === "chat" ? "page" : undefined}
            onClick={() => {
              showView("chat");
            }}
          >
            Assistant
          </button>
          <button
            type="button"
            className={view === "bookings" ? "nav-item active" : "nav-item"}
            data-testid="nav-bookings"
            aria-current={view === "bookings" ? "page" : undefined}
            onClick={() => {
              showView("bookings");
            }}
          >
            Bookings
          </button>
          <button
            type="button"
            className={view === "explorer" ? "nav-item active" : "nav-item"}
            data-testid="nav-explorer"
            aria-current={view === "explorer" ? "page" : undefined}
            onClick={() => {
              showView("explorer");
            }}
          >
            Explorer
          </button>
        </nav>
        <div className="side-foot">
          <div className="sf-row">
            <span className="dot ok" aria-hidden="true" />
            <span>Session active</span>
          </div>
          <div className="sf-row">
            <span>Shared demo patient</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <main className="content" id="main" data-view={view}>
          <AppHeader
            appName={config.appName}
            compact={view === "chat"}
            onLogout={() => {
              void logout();
            }}
          />

          <div className="tabs mobile-tabs">
            <div className="tablist" role="tablist" aria-label="Workbench views">
              <button
                id="tab-chat"
                type="button"
                className="tab"
                role="tab"
                aria-selected={view === "chat"}
                aria-controls="view-chat"
                data-testid="tab-chat"
                onClick={() => {
                  showView("chat");
                }}
              >
                Assistant
              </button>
              <button
                id="tab-bookings"
                type="button"
                className="tab"
                role="tab"
                aria-selected={view === "bookings"}
                aria-controls="view-bookings"
                data-testid="tab-bookings"
                onClick={() => {
                  showView("bookings");
                }}
              >
                Bookings
              </button>
              <button
                id="tab-explorer"
                type="button"
                className="tab"
                role="tab"
                aria-selected={view === "explorer"}
                aria-controls="view-explorer"
                data-testid="tab-explorer"
                onClick={() => {
                  showView("explorer");
                }}
              >
                Explorer
              </button>
            </div>
          </div>

          <div
            className="view-slot"
            id={`view-${view}`}
            role="tabpanel"
            aria-labelledby={`tab-${view}`}
          >
            {view === "chat" ? (
              <ChatPanel
                sessions={assistant.sessions}
                activeId={assistant.activeId}
                messages={assistant.messages}
                draft={assistant.draft}
                input={assistant.input}
                inFlight={assistant.inFlight}
                canRetry={assistant.failed !== null}
                error={assistant.error}
                loading={assistant.loading}
                historyError={assistant.historyError}
                onInputChange={assistant.setInput}
                onSend={assistant.send}
                onPrompt={assistant.sendText}
                onStop={assistant.stop}
                onRetry={assistant.retry}
                onRegenerate={assistant.regenerate}
                onConfirm={assistant.confirmBooking}
                onChooseSlot={assistant.chooseSlot}
                onReset={() => {
                  void assistant.resetWorkspace().catch((error: unknown) => {
                    setBookingsError(describeError(error));
                  });
                }}
                onNew={assistant.newConversation}
                onLogout={() => {
                  void logout();
                }}
                onSelect={(id) => {
                  void assistant.selectConversation(id);
                }}
                onDelete={(id) => {
                  void assistant.deleteConversation(id);
                }}
              />
            ) : view === "explorer" ? (
              <ExplorerPanel
                onOpenConversation={(id) => {
                  showView("chat");
                  void assistant.selectConversation(id);
                }}
                onReset={async () => {
                  try {
                    await assistant.resetWorkspace();
                  } catch (error) {
                    setBookingsError(describeError(error));
                  }
                }}
              />
            ) : (
              <BookingsPanel
                bookings={bookings}
                loading={bookingsLoading}
                error={bookingsError}
                onRefresh={() => {
                  void refreshBookings();
                }}
                onEdit={(booking) => {
                  showView("chat");
                  assistant.sendText(`Edit booking ${booking.booking_id}`);
                }}
                onDelete={async (booking) => {
                  try {
                    await api.deleteBooking(booking.booking_id);
                    await refreshBookings();
                  } catch (error) {
                    setBookingsError(describeError(error));
                  }
                }}
                onReset={async () => {
                  try {
                    await assistant.resetWorkspace();
                  } catch (error) {
                    setBookingsError(describeError(error));
                  }
                }}
              />
            )}
          </div>

          <div className="foot">
            Patient P001 · conversations are private to this browser session; bookings are
            shared.
          </div>
        </main>
      </div>
    </div>
  );
}
