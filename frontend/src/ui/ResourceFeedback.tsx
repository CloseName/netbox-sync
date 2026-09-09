import {tr} from "./i18n";
import type { Resource } from "./useResource";
import { Alert, LoadingState, Timestamp } from "./primitives";
export function ResourceFeedback<T>({
  resource,
  label,
  table = false,
  evidenceAt,
}: {
  resource: Resource<T> & { refresh: () => void };
  label: string;
  table?: boolean;
  evidenceAt?: string;
}) {
  return (
    <>
      {resource.loading && !resource.data && (
        <LoadingState label={`${tr("Loading")} ${tr(label)}…`} table={table} />
      )}
      {resource.loading && resource.data && (
        <p role="status">{tr("Refreshing")}{" "}{tr(label)}…</p>
      )}
      {resource.error && (
        <Alert
          tone={resource.data ? "warning" : "danger"}
          retry={resource.refresh}
        >
          {resource.data ? (
            <>
              {tr("Could not refresh")}{" "}{tr(label)}{tr(". Showing data from")}{" "}{" "}
              <Timestamp value={evidenceAt ?? resource.received} />.
            </>
          ) : (
            <>{tr(label[0].toUpperCase() + label.slice(1))} {tr("could not be loaded.")}{" "}</>
          )}
        </Alert>
      )}
    </>
  );
}
