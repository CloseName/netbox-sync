import {language} from "./language.ts";
export function interval(seconds: number): string {
  const hours = Math.floor(seconds / 3600),
    minutes = Math.floor((seconds % 3600) / 60),
    rest = seconds % 60;
  return (
    [hours && `${hours} ${language()==="ru"?"ч":"h"}`, minutes && `${minutes} ${language()==="ru"?"мин":"min"}`, rest && `${rest} ${language()==="ru"?"с":"s"}`]
      .filter(Boolean)
      .join(" ") || (language()==="ru"?"0 с":"0 s")
  );
}
export function duration(ms: number | null): string {
  return ms === null ? (language()==="ru"?"Не записано":"Not recorded") : interval(Math.round(ms / 1000));
}
export function exactTime(value: string): string {
  return new Date(value).toLocaleString(language(), { timeZoneName: "short" });
}
export function relativeTime(value: string, now = Date.now()): string {
  const seconds = Math.round((new Date(value).getTime() - now) / 1000);
  const magnitude = Math.abs(seconds);
  const unit =
    magnitude >= 86400
      ? "day"
      : magnitude >= 3600
        ? "hour"
        : magnitude >= 60
          ? "minute"
          : "second";
  const scale =
    unit === "day"
      ? 86400
      : unit === "hour"
        ? 3600
        : unit === "minute"
          ? 60
          : 1;
  return new Intl.RelativeTimeFormat(language(), { numeric: "auto" }).format(
    Math.round(seconds / scale),
    unit,
  );
}
