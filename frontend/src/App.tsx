import { useEffect, useRef, useState } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { SourcesPage } from "./pages/SourcesPage";
import { SourcesListPage } from "./pages/SourcesListPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RunsPage } from "./pages/RunsPage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { AddSourcePage } from "./pages/AddSourcePage";
import { breadcrumbs, navigation } from "./ui/routes";
import { ThemeControl } from "./ui/ThemeControl";
import { NavIcon } from "./ui/NavIcon";
function SourceRoute() {
  const { sourceInstance } = useParams();
  return <SourcesPage key={sourceInstance} />;
}
function RunRoute() {
  const { runId } = useParams();
  return <RunsPage key={runId ?? "list"} />;
}
export function App() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const navToggle = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const crumbs = breadcrumbs(location.pathname);
  const sourceDetail = /^\/sources\/(?!add(?:\/|$))[^/]+/.test(
    location.pathname,
  );
  useEffect(() => {
    setOpen(false);
    if (!sourceDetail)
      document.title = `${breadcrumbs(location.pathname).at(-1)?.label} | NetBox Sync`;
    content.current?.focus();
  }, [location.pathname, sourceDetail]);
  return (
    <>
      <a className="skip-link" href="#content">
        Skip to content
      </a>
      <header className="app-header">
        <Link className="app-brand" to="/">
          NetBox <strong>Sync</strong>
        </Link>
        <span className="muted">Source synchronization</span>
        <ThemeControl />
        <button
          ref={navToggle}
          className="nav-toggle"
          aria-expanded={open}
          aria-controls="primary-nav"
          onClick={() => setOpen(!open)}
        >
          Navigation
        </button>
      </header>
      <div className="app-layout">
        <nav
          id="primary-nav"
          aria-label="Main navigation"
          className={`sidebar ${open ? "is-open" : ""}`}
          onKeyDown={(event) => {
            if (event.key === "Escape" && open) {
              setOpen(false);
              navToggle.current?.focus();
            }
          }}
        >
          <p className="nav-section">Operations</p>
          {navigation.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              <NavIcon path={item.to} />
              {item.label}
            </NavLink>
          ))}
          <Link to="/setup">NetBox connection</Link>
        </nav>
        <div className="app-content" id="content" ref={content} tabIndex={-1}>
          {!sourceDetail && (
            <nav aria-label="Breadcrumb">
              <ol className="breadcrumbs">
                {crumbs.map((crumb, i) => (
                  <li key={crumb.to}>
                    {i === crumbs.length - 1 ? (
                      <span aria-current="page">{crumb.label}</span>
                    ) : (
                      <Link to={crumb.to}>{crumb.label}</Link>
                    )}
                  </li>
                ))}
              </ol>
            </nav>
          )}
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/sources" element={<SourcesListPage />} />
            <Route path="/sources/add" element={<AddSourcePage />} />
            <Route
              path="/sources/:sourceInstance/*"
              element={<SourceRoute />}
            />
            <Route path="/runs" element={<RunRoute />} />
            <Route path="/runs/:runId" element={<RunRoute />} />
            <Route path="/diagnostics" element={<DiagnosticsPage />} />
            <Route
              path="*"
              element={
                <main>
                  <h1>Page not found</h1>
                  <Link to="/">Open Overview</Link>
                </main>
              }
            />
          </Routes>
        </div>
      </div>
    </>
  );
}
