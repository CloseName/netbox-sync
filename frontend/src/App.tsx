import {DestinationPolicyPage} from "./pages/DestinationPolicyPage";
import {tr} from "./ui/i18n";
import {useLanguage} from "./ui/language";
import {LanguageControl} from "./ui/LanguageControl";
import {Brand} from "./ui/Brand";
import {SystemHealthPage} from "./pages/SystemHealthPage";
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
  const [language] = useLanguage();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const navToggle = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const crumbs = breadcrumbs(location.pathname);
  const sourceDetail = /^\/sources\/(?!add(?:\/|$))[^/]+/.test(
    location.pathname,
  );
  useEffect(() => {
    if (!sourceDetail)
      document.title = `${tr(breadcrumbs(location.pathname).at(-1)?.label ?? "NetBox Sync")} | NetBox Sync`;
  }, [location.pathname, sourceDetail, language]);
  useEffect(()=>{setOpen(false);content.current?.focus();},[location.pathname]);
  return (
    <>
      <a className="skip-link" href="#content">
        {tr("Skip to content")}{" "}</a>
      <header className="app-header">
        <Link className="app-brand" to="/">
          <Brand />
        </Link>
        <span className="muted">{tr("Source synchronization")}{" "}</span>
        <LanguageControl /><ThemeControl language={language} />
        <button
          ref={navToggle}
          className="nav-toggle"
          aria-expanded={open}
          aria-controls="primary-nav"
          onClick={() => setOpen(!open)}
        >
          {tr("Navigation")}{" "}</button>
      </header>
      <div className="app-layout">
        <nav
          id="primary-nav"
          aria-label={tr("Main navigation")}
          className={`sidebar ${open ? "is-open" : ""}`}
          onKeyDown={(event) => {
            if (event.key === "Escape" && open) {
              setOpen(false);
              navToggle.current?.focus();
            }
          }}
        >
          <p className="nav-section">{tr("Operations")}{" "}</p>
          {navigation.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              <NavIcon path={item.to} />
              {tr(item.label)}
            </NavLink>
          ))}
          <p className="nav-section">{tr("System")}</p>
          <NavLink to="/policy">{tr("Source destinations")}</NavLink>
          <NavLink to="/system">{tr("System health")}{" "}</NavLink>
          <Link to="/setup">{tr("NetBox connection")}{" "}</Link>
        </nav>
        <div className="app-content" id="content" ref={content} tabIndex={-1}>
          {!sourceDetail && (
            <nav aria-label={tr("Breadcrumb")}>
              <ol className="breadcrumbs">
                {crumbs.map((crumb, i) => (
                  <li key={crumb.to}>
                    {i === crumbs.length - 1 ? (
                      <span aria-current="page">{tr(crumb.label)}</span>
                    ) : (
                      <Link to={crumb.to}>{tr(crumb.label)}</Link>
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
            <Route path="/policy" element={<DestinationPolicyPage />} />
            <Route path="/system" element={<SystemHealthPage />} />
            <Route path="/diagnostics" element={<DiagnosticsPage />} />
            <Route
              path="*"
              element={
                <main>
                  <h1>{tr("Page not found")}{" "}</h1>
                  <Link to="/">{tr("Open Overview")}{" "}</Link>
                </main>
              }
            />
          </Routes>
        </div>
      </div>
    </>
  );
}
