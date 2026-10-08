import {tr} from "./i18n";
import { health } from "./status";
import type { sourceQuery } from "./operations";
export function SourceFilters({
  query,
  change,
}: {
  query: ReturnType<typeof sourceQuery>;
  change: (key: string, value: string) => void;
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
    </div>
  );
}
