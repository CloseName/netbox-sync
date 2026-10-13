import {TeamsSettings} from './pages/TeamsSettings';
import {SourceNavigation} from './ui/SourceNavigation';
import {PfSensePage} from './pages/PfSensePage';
import {DirectoryUsersPage} from './pages/DirectoryUsersPage';
import {SessionControls,Permission,usePermission} from './AuthGate';
import {AuthenticationSettings} from './pages/AuthenticationSettings';
import {DestinationPolicyPage} from "./pages/DestinationPolicyPage";
import {tr} from "./ui/i18n";
import {useLanguage} from "./ui/language";
import {Brand} from "./ui/Brand";
import {SystemHealthPage} from "./pages/SystemHealthPage";
import { useEffect, useRef, useState } from "react";
import {
  Navigate,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { SourcesPage } from "./pages/SourcesPage";
import { SelectelPage } from "./pages/SelectelPage";
import { SourcesListPage } from "./pages/SourcesListPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RunsPage } from "./pages/RunsPage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { AddSourcePage } from "./pages/AddSourcePage";
import { breadcrumbs, navigation } from "./ui/routes";
import { NavIcon } from "./ui/NavIcon";
function SourceRoute() {
  const { sourceInstance } = useParams();
  return <SourcesPage key={sourceInstance} />;
}
function RunRoute() {
  const { runId } = useParams();
  return <RunsPage key={runId ?? "list"} />;
}
function OverviewWorkspace(){
 const {hash}=useLocation();
 if(hash==='#diagnostics')return <Navigate replace to="/diagnostics"/>;
 if(hash==='#health')return <Navigate replace to="/system"/>;
 return <OverviewPage/>;
}

export function App() {
  const [language] = useLanguage();
  const manageIdentity = usePermission('identity.manage');
  const configureSources = usePermission('source.configure');
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const navToggle = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const crumbs = breadcrumbs(location.pathname);
  const sourceDetail = /^\/sources\/(?!(?:add|pfsense|selectel)(?:\/|$))[^/]+/.test(
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
        <SessionControls/>
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
          {navigation.map((item) => (item.to==='/sources'?<SourceNavigation key={item.to}/>:
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              <NavIcon path={item.to} />
              {item.to==='/runs'?(language==='ru'?'История запусков':'Run history'):tr(item.label)}
            </NavLink>
          ))}
          {(manageIdentity||configureSources)&&<div className="nav-administration">
            <p className="nav-section">{language==='ru'?'Управление':'Administration'}</p>
            <NavLink to={manageIdentity?'/settings':'/settings?section=teams'}><NavIcon path="/settings"/>{language==='ru'?'Настройки':'Settings'}</NavLink>
            {manageIdentity&&<NavLink to="/users"><NavIcon path="/users"/>{language==='ru'?'Пользователи':'Users'}</NavLink>}
          </div>}
          <div className="nav-footer">NetBox Sync<span>{language==='ru'?'Инфраструктура под контролем':'Infrastructure synchronization'}</span></div>
        </nav>
        <div className="app-content" id="content" ref={content} tabIndex={-1}>
          {!sourceDetail && crumbs.length>1 && location.pathname!=='/settings' && (
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
            <Route path="/" element={<OverviewWorkspace/>} />
            <Route path="/sources" element={<SourcesListPage />} />
            <Route path="/sources/pfsense" element={<PfSensePage/>} />
            <Route path="/sources/selectel" element={<Permission permission="bootstrap.manage"><SelectelPage/></Permission>} />
            <Route path="/sources/add" element={<Permission permission="source.register"><AddSourcePage /></Permission>} />
            <Route
              path="/sources/:sourceInstance/*"
              element={<SourceRoute />}
            />
            <Route path="/runs" element={<RunRoute />} />
            <Route path="/runs/:runId" element={<RunRoute />} />
            <Route path="/users" element={<Permission permission="identity.manage"><DirectoryUsersPage/></Permission>}/>
            <Route path="/settings" element={new URLSearchParams(location.search).get("section")==="teams"?<Permission permission="source.configure"><TeamsSettings/></Permission>:<Permission permission="identity.manage">{location.search.includes('section=destinations')?<DestinationPolicyPage/>:<AuthenticationSettings/>}</Permission>} />
            <Route path="/policy" element={<Navigate replace to="/settings?section=destinations"/>} />
            <Route path="/system" element={<><nav className="source-tabs"><Link to="/diagnostics">{tr('Diagnostics')}</Link><Link to="/system" aria-current="page">{tr('System health')}</Link></nav><SystemHealthPage/></>} />
            <Route path="/diagnostics" element={<><nav className="source-tabs"><Link to="/diagnostics" aria-current="page">{tr('Diagnostics')}</Link><Link to="/system">{tr('System health')}</Link></nav><DiagnosticsPage/></>} />
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
