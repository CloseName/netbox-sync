import {tr} from "./i18n";
import type { Resource } from "./useResource";
import { Alert, Timestamp } from "./primitives";
export function ResourceNotice({
  resource,
  name,
  retry,
}: {
  resource: Resource<unknown>;
  name: string;
  retry: () => void;
}) {
  return resource.error ? (
    <Alert tone={resource.data ? "warning" : "danger"} retry={retry}>
      {resource.data ? (
        <>
          {tr("Could not refresh")}{" "}{tr(name)}{tr(". Showing data from")}{" "}{" "}
          <Timestamp value={resource.received} />.
        </>
      ) : (
        <>{tr(name)} {tr("unavailable. This section could not be loaded.")}{" "}</>
      )}
    </Alert>
  ) : null;
}
