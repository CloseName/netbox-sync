import {tr} from "./i18n";
import { health } from "./status";
import type { sourceQuery } from "./operations";
export function SourceFilters({
  query,
  sites,
  change,
  clear,
}: {
  query: ReturnType<typeof sourceQuery>;
  sites: string[];
  change: (key: string, value: string) => void;
  clear: () => void;
}) {
  return (
    <div className="table-toolbar" role="search" aria-label={tr("Filter sources")}>
      <label className="search-field">
        {tr("Search sources")}{" "}<input
          type="search"
          value={query.q}
          placeholder={tr("Name, source ID, address or target")}
          onChange={(e) => change("q", e.target.value)}
        />
      </label>
      <div className="filter-field">
        <label htmlFor="filter-provider">{tr("Provider")}{" "}</label>
        <select
          id="filter-provider"
          value={query.provider}
          onChange={(e) => change("provider", e.target.value)}
        >
          <option value="">{tr("All providers")}{" "}</option>
          <option value="proxmox">{tr("Proxmox VE")}{" "}</option>
          <option value="esxi">{tr("VMware ESXi")}{" "}</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-sync-status">{tr("Sync status")}{" "}</label>
        <select
          id="filter-sync-status"
          value={query.health}
          onChange={(e) => change("health", e.target.value)}
        >
          <option value="">{tr("All states")}{" "}</option>
          {Object.entries(health).map(([key, value]) => (
            <option key={key} value={key}>
              {tr(value.label)}
            </option>
          ))}
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-automatic-sync">{tr("Automatic sync")}{" "}</label>
        <select
          id="filter-automatic-sync"
          value={query.schedule}
          onChange={(e) => change("schedule", e.target.value)}
        >
          <option value="">{tr("On and off")}{" "}</option>
          <option value="on">{tr("On")}{" "}</option>
          <option value="off">{tr("Off")}{" "}</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-attention">{tr("Attention")}{" "}</label>
        <select
          id="filter-attention"
          value={query.attention}
          onChange={(e) => change("attention", e.target.value)}
        >
          <option value="">{tr("All sources")}{" "}</option>
          <option value="yes">{tr("Needs attention")}{" "}</option>
          <option value="no">{tr("None reported")}{" "}</option>
          <option value="unknown">{tr("Not available")}{" "}</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-site">{tr("Site")}{" "}</label>
        <select
          id="filter-site"
          value={query.site}
          onChange={(e) => change("site", e.target.value)}
        >
          <option value="">{tr("All sites")}{" "}</option>
          {Array.from(new Set([...sites, ...(query.site ? [query.site] : [])]))
            .sort()
            .map((site) => (
              <option key={site}>{site}</option>
            ))}
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-sort-by">{tr("Sort by")}{" "}</label>
        <select
          id="filter-sort-by"
          value={query.sort}
          onChange={(e) => change("sort", e.target.value)}
        >
          <option value="name">{tr("Source name")}{" "}</option>
          <option value="last">{tr("Last run")}{" "}</option>
          <option value="next">{tr("Next expected")}{" "}</option>
          <option value="attention">{tr("Attention")}{" "}</option>
        </select>
      </div>
      <div className="filter-field">
        <label htmlFor="filter-order">{tr("Order")}{" "}</label>
        <select
          id="filter-order"
          value={query.direction}
          onChange={(e) => change("direction", e.target.value)}
        >
          <option value="asc">{tr("Ascending")}{" "}</option>
          <option value="desc">{tr("Descending")}{" "}</option>
        </select>
      </div>
      <button onClick={() => clear()}>{tr("Clear filters")}{" "}</button>
    </div>
  );
}
