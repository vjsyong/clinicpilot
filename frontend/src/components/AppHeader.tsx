interface AppHeaderProps {
  appName: string;
  onLogout: () => void;
  compact?: boolean;
}

export function AppHeader({ appName, onLogout, compact = false }: AppHeaderProps) {
  const actions = (
    <div className="row">
      <span className="badge">Patient P001</span>
      <span className="status-chip">Session active</span>
      <button className="btn small" type="button" data-testid="logout" onClick={onLogout}>
        Log out
      </button>
    </div>
  );

  if (compact) {
    return (
      <header className="page-head app-toolbar">
        <span />
        {actions}
      </header>
    );
  }

  return (
    <header className="page-head">
      <div>
        <h1 className="page-title">{appName}</h1>
        <div className="page-desc">
          Ask about clinics and treatments, then book an appointment for the shared
          demo patient.
        </div>
      </div>
      {actions}
    </header>
  );
}
