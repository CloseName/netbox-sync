import {tr} from "../ui/i18n";
import { useEffect, useRef, useState } from "react";
import {
  ScheduleRequestError,
  updateSchedule,
  fetchSchedule,
} from "../api/schedule";
import type { Schedule } from "../api/schedule";
import type { SourceDiagnostic } from "../api/diagnostics";
import { Badge, Timestamp, Alert, LoadingState } from "../ui/primitives";
import { interval } from "../ui/format";
import { scheduleStates, runStatus } from "../ui/status";
import {
  intervalDraft,
  intervalSeconds,
  schedulePresets,
} from "../ui/scheduleForm";
import type { TimeUnit } from "../ui/scheduleForm";
import type { Resource } from "../ui/useResource";

type ScheduleResource = Resource<Schedule> & {
  refresh: () => void;
  replaceData: (value: Schedule) => void;
};
export function ScheduleSummary({
  schedule,
  evidence,
}: {
  schedule: Schedule;
  evidence?: SourceDiagnostic;
}) {
  const last = evidence?.latest_scheduled_run;
  return (
    <dl className="source-facts">
      <div>
        <dt>{tr("Automatic sync")}{" "}</dt>
        <dd>{schedule.sync_enabled ? tr("On") : tr("Off")}</dd>
      </div>
      <div>
        <dt>{tr("Frequency")}{" "}</dt>
        <dd>{tr("Every")}{" "}{interval(schedule.sync_interval_seconds)}</dd>
      </div>
      <div>
        <dt>{tr("Scheduled activity")}{" "}</dt>
        <dd>
          <Badge
            value={scheduleStates[schedule.scheduler_state]}
            code={schedule.scheduler_state}
          />
        </dd>
      </div>
      <div>
        <dt>{tr("Last scheduled run")}{" "}</dt>
        <dd>
          {last ? (
            <>
              <Badge value={runStatus(last.status)} />{" "}
              <Timestamp value={last.started_at} />
            </>
          ) : schedule.last_scheduled_run_at ? (
            <>
              <Timestamp value={schedule.last_scheduled_run_at} /> {tr("· Outcome unavailable")}{" "}</>
          ) : evidence ? (
            tr("No scheduled run recorded")
          ) : (
            tr("Unavailable")
          )}
        </dd>
      </div>
      <div>
        <dt>{tr("Next expected")}{" "}</dt>
        <dd>
          {schedule.next_expected_at ? (
            <Timestamp value={schedule.next_expected_at} />
          ) : (
            tr("Not scheduled")
          )}
        </dd>
      </div>
    </dl>
  );
}
export function SourceSchedule({
  instance,
  sourceEnabled,
  resource,
  evidence,
  afterSave,
}: {
  instance: string;
  sourceEnabled: boolean;
  resource: ScheduleResource;
  evidence?: SourceDiagnostic;
  afterSave: () => void;
}) {
  const schedule = resource.data;
  const [phase, setPhase] = useState<
    "idle" | "editing" | "saving" | "saved" | "conflict" | "error"
  >("idle");
  const [baseline, setBaseline] = useState<Schedule | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [draft, setDraft] = useState(intervalDraft(600));
  const [message, setMessage] = useState("");
  const [reloadPending, setReloadPending] = useState(false);
  const busy = useRef(false);
  const alive = useRef(true);
  const feedback = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (message && feedback.current?.offsetParent) feedback.current.focus();
  }, [message]);
  async function reloadLatest() {
    if (busy.current) return;
    busy.current = true;
    setReloadPending(true);
    setMessage("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const latest = await fetchSchedule(instance, controller.signal);
      if (!alive.current) return;
      resource.replaceData(latest);
      setBaseline(latest);
      setEnabled(latest.sync_enabled);
      setDraft(intervalDraft(latest.sync_interval_seconds));
      setPhase("editing");
      setMessage("Latest schedule loaded. Review it before saving.");
    } catch {
      if (alive.current)
        setMessage(
          "Latest schedule could not be loaded. Reload before saving again.",
        );
    } finally {
      window.clearTimeout(timeout);
      busy.current = false;
      if (alive.current) setReloadPending(false);
    }
  }
  const editing = ["editing", "saving", "conflict", "error"].includes(phase);
  const seconds = intervalSeconds(draft);
  const invalid = seconds === null;
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (
      busy.current ||
      invalid ||
      !baseline ||
      phase === "conflict" ||
      reloadPending
    )
      return;
    busy.current = true;
    setPhase("saving");
    setMessage("");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const updated = await updateSchedule(
        instance,
        {
          sync_enabled: enabled,
          sync_interval_seconds: seconds!,
          expected_sync_enabled: baseline.sync_enabled,
          expected_sync_interval_seconds: baseline.sync_interval_seconds,
        },
        controller.signal,
      );
      if (!alive.current) return;
      resource.replaceData(updated);
      setPhase("saved");
      setMessage("Saved");
      afterSave();
    } catch (failure) {
      if (!alive.current) return;
      setPhase(
        failure instanceof ScheduleRequestError &&
          failure.code === "SCHEDULE_CONFLICT"
          ? "conflict"
          : "error",
      );
      setMessage(
        failure instanceof Error
          ? failure.message
          : "Scheduling update failed.",
      );
    } finally {
      window.clearTimeout(timeout);
      busy.current = false;
    }
  }
  return (
    <section
      className="source-panel schedule-panel"
      aria-labelledby="schedule-title"
    >
      <h2 id="schedule-title">{tr("Schedule")}{" "}</h2>
      {resource.loading && <LoadingState label={tr("Loading schedule…")} />}
      {resource.error && (
        <Alert retry={!editing ? resource.refresh : undefined}>
          {tr("Schedule unavailable.")}{" "}{resource.data && tr(" Showing the last loaded schedule.")}
        </Alert>
      )}
      {schedule && (
        <>
          {!editing && (
            <>
              <ScheduleSummary schedule={schedule} evidence={evidence} />
              <div className="page-actions">
                <button
                  disabled={resource.loading || resource.error}
                  onClick={() => {
                    setBaseline(schedule);
                    setEnabled(schedule.sync_enabled);
                    setDraft(intervalDraft(schedule.sync_interval_seconds));
                    setMessage("");
                    setPhase("editing");
                  }}
                >
                  {tr("Edit schedule")}{" "}</button>
                <button disabled={resource.loading} onClick={resource.refresh}>
                  {tr("Refresh schedule")}{" "}</button>
              </div>
            </>
          )}
          {editing && (
            <form onSubmit={save} aria-label={tr("Edit schedule")} noValidate>
              <fieldset disabled={phase === "saving" || reloadPending}>
                <legend>{tr("Automatic sync")}{" "}</legend>
                <label className="schedule-toggle">
                  <input
                    autoFocus
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />{" "}
                  {tr("Automatic sync")}{" "}</label>
                <p>
                  {enabled
                    ? tr("After saving, this source can be picked up by the scheduler on a future scheduler cycle.")
                    : tr("Future automatic runs are disabled. A run that has already started is not cancelled.")}
                </p>
                <label htmlFor="schedule-preset">{tr("Frequency")}{" "}</label>
                <select
                  id="schedule-preset"
                  value={draft.preset}
                  onChange={(e) => {
                    setDraft(
                      e.target.value === "custom"
                        ? { ...draft, preset: "custom" }
                        : intervalDraft(Number(e.target.value)),
                    );
                  }}
                >
                  {schedulePresets.map((value) => (
                    <option key={value} value={value}>
                      {tr("Every")}{" "}{interval(value)}
                    </option>
                  ))}
                  <option value="custom">{tr("Custom")}{" "}</option>
                </select>
                {draft.preset === "custom" && (
                  <div className="schedule-custom">
                    <div>
                      <label htmlFor="schedule-amount">{tr("Custom interval")}{" "}</label>
                      <input
                        id="schedule-amount"
                        inputMode="decimal"
                        type="text"
                        value={draft.amount}
                        aria-invalid={invalid}
                        aria-describedby="schedule-range"
                        onChange={(e) =>
                          setDraft({ ...draft, amount: e.target.value })
                        }
                      />
                    </div>
                    <div>
                      <label htmlFor="schedule-unit">{tr("Unit")}{" "}</label>
                      <select
                        id="schedule-unit"
                        value={draft.unit}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            unit: e.target.value as TimeUnit,
                          })
                        }
                      >
                        <option value="seconds">{tr("Seconds")}{" "}</option>
                        <option value="minutes">{tr("Minutes")}{" "}</option>
                        <option value="hours">{tr("Hours")}{" "}</option>
                      </select>
                    </div>
                  </div>
                )}
                <p
                  id="schedule-range"
                  className={invalid ? "source-error" : "muted"}
                >
                  {invalid
                    ? tr("Enter an exact whole-second interval from 1 minute to 24 hours. The stored value has not been changed.")
                    : tr("Allowed: 1 minute to 24 hours, with exact whole-second precision.")}
                </p>
                {baseline &&
                  (baseline.sync_interval_seconds < 60 ||
                    baseline.sync_interval_seconds > 86400) && (
                    <p className="alert alert-warning">
                      {tr("Stored frequency: every")}{" "}{" "}
                      {interval(baseline.sync_interval_seconds)}{tr(". Registration accepts a wider range than schedule updates. Choose a supported value explicitly to save, or cancel to preserve it.")}{" "}</p>
                  )}
              </fieldset>
              <div className="page-actions">
                <button
                  className="primary"
                  disabled={
                    phase === "saving" ||
                    phase === "conflict" ||
                    reloadPending ||
                    invalid
                  }
                  type="submit"
                >
                  {phase === "saving" ? tr("Saving…") : tr("Save schedule")}
                </button>
                <button
                  type="button"
                  disabled={phase === "saving" || reloadPending}
                  onClick={() => {
                    setPhase("idle");
                    setMessage("");
                  }}
                >
                  {tr("Cancel")}{" "}</button>
                {phase === "conflict" && (
                  <button
                    type="button"
                    disabled={reloadPending}
                    onClick={reloadLatest}
                  >
                    {tr("Reload latest schedule")}{" "}</button>
                )}
              </div>
            </form>
          )}
        </>
      )}
      {message && (
        <p
          ref={feedback}
          tabIndex={-1}
          role={phase === "error" || phase === "conflict" ? "alert" : "status"}
        >
          {tr(message)}
        </p>
      )}
      {!sourceEnabled && (
        <p className="alert alert-warning">
          {tr("Source disabled. Automatic runs cannot start while the source is disabled, even if automatic sync is configured on.")}{" "}</p>
      )}
      <p className="muted">
        {tr("Next expected is an estimate, not a guaranteed start. Schedule state is derived from persisted runs, not a live scheduler heartbeat.")}{" "}</p>
    </section>
  );
}
