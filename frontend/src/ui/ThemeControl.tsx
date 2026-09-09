import { useEffect, useState } from "react";
import { applyTheme, readTheme, themeKey, themePreference } from "./theme";
export function ThemeControl({language="en"}:{language?:"en"|"ru"}) {
  const [preference, setPreference] = useState(readTheme);
  useEffect(() => {
    applyTheme(preference);
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () => applyTheme(preference);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [preference]);
  useEffect(() => {
    const update = (event: StorageEvent) => {
      if (event.key === themeKey || event.key === null)
        setPreference(readTheme());
    };
    window.addEventListener("storage", update);
    return () => window.removeEventListener("storage", update);
  }, []);
  return (
    <label className="theme-control">
      {language==="ru"?"Тема":"Theme"}
      <select
        value={preference}
        onChange={(event) => {
          const next = themePreference(event.target.value);
          setPreference(next);
          applyTheme(next);
          try {
            localStorage.setItem(themeKey, next);
          } catch {
            /* Theme still works without persistence. */
          }
        }}
      >
        <option value="light">{language==="ru"?"Светлая":"Light"}</option>
        <option value="dark">{language==="ru"?"Тёмная":"Dark"}</option>
        <option value="system">{language==="ru"?"Системная":"System"}</option>
      </select>
    </label>
  );
}
