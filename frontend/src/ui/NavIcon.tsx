const paths: Record<string, string> = {
  "/": "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  "/sources": "M4 3h16v7H4z M4 14h16v7H4z M7 6h1 M7 17h1 M12 10v4",
  "/runs": "M3 11a9 9 0 1 1 2 7 M3 4v7h7 M12 7v5l3 2",
  "/diagnostics": "M2 12h5l3-8 4 16 3-8h5",
  "/settings": "M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M9 15v6",
  "/users": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8 M17 4a4 4 0 0 1 0 7 M22 21v-2a4 4 0 0 0-3-4",
};
export function NavIcon({ path }: { path: string }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={paths[path]} />
    </svg>
  );
}
