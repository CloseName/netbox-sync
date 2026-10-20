"""CLI mode selection, dispatch and reporting without provider execution logic."""

# Explicit callbacks preserve the package entrypoint's late-bound dependencies.
# pylint: disable=too-many-arguments,too-many-positional-arguments
import os
import sys

from .source_bootstrap import LEGACY_MODE, REGISTRY_ALL_MODE

VALID_SYNC_MODES = {"inventory", "plan", "apply"}


def _get_sync_mode() -> str:
    sync_mode = os.getenv("SYNC_MODE", "inventory").strip().lower()

    if sync_mode not in VALID_SYNC_MODES:
        print(f'Invalid SYNC_MODE="{sync_mode}". ' f'Allowed values: {", ".join(sorted(VALID_SYNC_MODES))}.')
        sys.exit(2)

    return sync_mode


def _print_multi_source_result(result):
    for source_result in result.results:
        if source_result.success:
            print(f"SOURCE {source_result.source_id} SUCCESS")
        else:
            print(
                f"SOURCE {source_result.source_id} FAILED "
                f"{source_result.error_type}: "
                f"{source_result.error_summary}"
            )
        if source_result.history_error_code:
            print(
                f"SOURCE {source_result.source_id} HISTORY "
                f"{source_result.history_status.value} "
                f"{source_result.history_error_code}"
            )
    print()
    print("MULTI-SOURCE SUMMARY")
    print(f"total={result.total}")
    print(f"succeeded={result.succeeded}")
    print(f"failed={result.failed}")
    print(f"history_failures={result.history_failures}")


def run(
    *,
    _get_sync_mode,
    runtime_source_mode,
    _source_dispatch,
    postgres_run_repository,
    _print_multi_source_result,
    load_runtime_source_config,
    execute_proxmox_source,
):
    """NetBox Sync main entrypoint."""

    sync_mode = _get_sync_mode()
    print(f"SYNC_MODE={sync_mode}")
    source_mode = runtime_source_mode(os.environ)
    if source_mode == REGISTRY_ALL_MODE:
        from .scheduler_runtime import (
            run_scheduler_tick,  # pylint: disable=import-outside-toplevel
            scheduler_summary_lines,
        )
        from .source_bootstrap import load_scheduler_source_configs  # pylint: disable=import-outside-toplevel
        from .application.scheduling import stale_threshold  # pylint: disable=import-outside-toplevel

        configs = load_scheduler_source_configs()
        dispatch = _source_dispatch(sync_mode)
        history = postgres_run_repository(
            (
                os.environ.get("NETBOX_SYNC_RUN_WRITER_DSN", "")
                if sync_mode == "apply"
                else os.environ.get("NETBOX_SYNC_REGISTRY_DSN", "")
            ),
            os.environ["NETBOX_SYNC_REGISTRY_SCHEMA"],
        )
        from contextlib import redirect_stdout

        def scheduled_execute(config):
            with open(os.devnull, "w") as sink, redirect_stdout(sink):
                return dispatch.execute(config)

        tick = run_scheduler_tick(
            configs,
            scheduled_execute,
            history,
            stale_seconds=stale_threshold(os.environ.get("NETBOX_SYNC_DIAGNOSTICS_STALE_SECONDS", "7200")),
            execute_due=sync_mode == "apply",
        )
        result = tick.execution
        _print_multi_source_result(result)
        for line in scheduler_summary_lines(tick):
            print(line)
        if tick.failed:
            raise SystemExit(1)
        return

    source_config = load_runtime_source_config()
    if source_mode == LEGACY_MODE:
        execute_proxmox_source(
            source_config,
            sync_mode,
            legacy_secrets=True,
        )
        return
    _source_dispatch(sync_mode).execute(source_config)
