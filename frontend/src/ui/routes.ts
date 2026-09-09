export const sourcePath = (instance: string) =>
  `/sources/${encodeURIComponent(instance)}`;
export const runPath = (id: string) => `/runs/${encodeURIComponent(id)}`;
export const navigation = [
  { to: "/", label: "Overview" },
  { to: "/sources", label: "Sources" },
  { to: "/runs", label: "Runs" },
  { to: "/diagnostics", label: "Diagnostics" },
];
export function breadcrumbs(pathname: string) {
  if(pathname === "/system")return [{label:"System health",to:"/system"}];
  const parts = pathname.split("/").filter(Boolean);
  const section = navigation.find((item) => item.to === "/" + parts[0]);
  if (!parts.length) return [{ label: "Overview", to: "/" }];
  if (!section) return [{ label: "Page not found", to: pathname }];
  const result = [{ label: section.label, to: section.to }];
  if (parts[1]) {
    let label = parts[1];
    try {
      label = decodeURIComponent(label);
    } catch {
      /* display literal */
    }
    result.push({
      label:
        parts[0] === "runs"
          ? "Run details"
          : parts[0] === "sources" && parts[1] === "add"
            ? "Add source"
            : label,
      to: pathname,
    });
  }
  return result;
}
