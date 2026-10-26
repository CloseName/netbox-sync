#!/usr/bin/env python3
"""Update the known test Sync only; read-only preflight unless --apply is given."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys

try:
    from .guard_update_test import GuardUpdate, GuardUpdateError
except ImportError:  # Saved on-disk entrypoint, not an installed package.
    from guard_update_test import GuardUpdate, GuardUpdateError

ROOT = Path("/netbox-sync-test")
PUBLIC_URL = "https://netbox-sync-test.indeed-id.hq"
NETBOX_URL = "https://netbox-test.indeed-id.hq"
SERVICES = tuple(
    "netbox-sync-" + name
    for name in (
        "secret-broker",
        "auth-worker",
        "probe-worker",
        "bootstrap-worker",
        "lifecycle-worker",
        "apply-worker",
        "api",
        "proxy",
    )
)
SCHEDULER = "netbox-sync-schedule-worker"


class UpdateError(RuntimeError):
    """An operator-facing failure without private configuration contents."""


def run(*command):
    """Disconnect child stdin, including grandchildren, from the operator terminal."""
    return subprocess.run(
        command, check=True, text=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=1800,
    ).stdout.strip()


def env_file(path):
    """Read installer-generated assignments without shell evaluation."""
    result = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in result:
            raise UpdateError("Malformed or duplicate configuration assignment.")
        result[key] = value
    return result


def check_configuration(root):
    """Reject other targets and Selectel schedules before starting any worker."""
    config = env_file(root / "config/compose.env")
    api = env_file(root / "config/api.env")
    if (
        config.get("NETBOX_SYNC_INGRESS_MODE") != "external"
        or api.get("NETBOX_SYNC_PUBLIC_URL") != PUBLIC_URL
        or config.get("NETBOX_SYNC_NETBOX_SECRET_DIR") != str(root / "secrets/netbox")
    ):
        raise UpdateError("Unexpected test installation configuration; inspect privately.")
    state = json.loads((root / "secrets/netbox/bootstrap.json").read_text())
    if (
        not isinstance(state, dict)
        or state.get("url") not in (NETBOX_URL, NETBOX_URL + "/")
        or state.get("status") != "READY"
        or state.get("completed") is not True
    ):
        raise UpdateError("Test NetBox target or bootstrap readiness differs.")
    for path in (root / "secrets/netbox/selectel").glob("*.json"):
        if not re.fullmatch(r"[0-9]{1,20}", path.stem):
            continue
        account = json.loads(path.read_text())
        if not isinstance(account, dict) or not isinstance(account.get("schedule", {}), dict):
            raise UpdateError("Malformed Selectel account state; inspect privately.")
        if (
            account.get("schedule", {}).get("kind", "off") != "off"
            or account.get("next_run") is not None
            or account.get("status") == "running"
            or account.get("lifecycle_pending")
        ):
            raise UpdateError("Selectel has scheduled/running/pending work; keep it paused.")


def compose(root, *args):
    """Use the installed mode-aware Compose wrapper with an explicit service list."""
    return run(sys.executable, str(root / "current/deploy/compose.py"), "--root", str(root), *args)


def check_schedulers(root):
    """Verify that neither scheduling entrypoint is running."""
    if run("systemctl", "show", "netbox-sync.timer", "-p", "ActiveState", "--value") != "inactive":
        raise UpdateError("Test timer must be inactive before and after updating.")
    if SCHEDULER in compose(root, "ps", "--status", "running", "--services").split():
        raise UpdateError("Test schedule worker must be stopped.")


def preflight(root, source, commit):
    """Validate identity, pinned clean source and prerequisites without mutations."""
    if os.name != "posix" or os.geteuid() != 0 or socket.gethostname().split(".")[0] != "netbox-test":
        raise UpdateError("Run as root on netbox-test only.")
    if root.resolve() != ROOT or source.resolve() != ROOT / "repo":
        raise UpdateError("Only the canonical test root and repository are supported.")
    current = (root / "current").resolve(strict=True)
    if current.parent != root / "releases":
        raise UpdateError("Current release is outside the test release directory.")
    if run("git", "-C", str(source), "status", "--porcelain"):
        raise UpdateError("Repository is dirty; preserve changes before updating.")
    if run("git", "-C", str(source), "rev-parse", "HEAD") != commit:
        raise UpdateError("Checkout does not match --commit.")
    if run("git", "-C", str(source), "remote", "get-url", "origin") not in (
        "https://github.com/CloseName/netbox-sync",
        "https://github.com/CloseName/netbox-sync.git",
        "git@github.com:CloseName/netbox-sync.git",
    ):
        raise UpdateError("Unexpected Git origin.")
    run("git", "-C", str(source), "merge-base", "--is-ancestor", commit, "origin/main")
    if shutil.disk_usage(root).free < 3 * 1024**3:
        raise UpdateError("Less than 3 GiB free; inspect disk usage, do not auto-prune.")
    check_configuration(root)
    check_schedulers(root)
    run(sys.executable, str(source / "deploy/install.py"), "--root", str(root), "--ingress-mode", "external", "--check")
    return current


def update(root, source, commit, *, with_guard=False):
    """Update test services without backups; never roll back databases implicitly."""
    stage = "preflight"
    try:
        previous = preflight(root, source, commit)
        guard = GuardUpdate(run, source, commit) if with_guard else None
        if guard:
            stage = "guard-preflight"
            guard.preflight()
        print("PREVIOUS_RELEASE:", previous, flush=True)
        stage = "pause"
        print("STAGE:", stage, flush=True)
        run("systemctl", "stop", "netbox-sync.timer")
        compose(root, "stop", SCHEDULER, *SERVICES)
        if guard:
            stage = "guard"
            guard.apply()
        stage = "install"
        print("STAGE:", stage, flush=True)
        run(
            sys.executable,
            str(source / "deploy/install.py"),
            "--root",
            str(root),
            "--source",
            str(source),
            "--release-id",
            commit,
            "--ingress-mode",
            "external",
            "--no-start",
        )
        if (root / "current").resolve() != root / "releases" / commit:
            raise UpdateError("Installed release does not match requested commit.")
        check_configuration(root)
        check_schedulers(root)
        stage = "start"
        print("STAGE:", stage, flush=True)
        compose(root, "up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", *SERVICES)
        stage = "verify"
        print("STAGE:", stage, flush=True)
        verify_runtime(root, commit)
        if guard:
            stage = "selectel-reconciliation"
            report = json.loads(run("docker", "exec", "netbox-sync-bootstrap-worker", "python", "-B", "-m",
                                    "netbox_sync.selectel_recovery"))
            if report.get("compatible") is not True:
                raise UpdateError("SELECTEL_GUARD_INCOMPATIBLE")
            print("SELECTEL_RECONCILIATION:", json.dumps(report), flush=True)
            check_configuration(root)
            check_schedulers(root)
        print("UPDATE_OK:", commit, flush=True)
    except (UpdateError, GuardUpdateError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print("UPDATE_FAILED_STAGE:", stage, file=sys.stderr)
        print(
            "Do not rerun blindly or enable schedules. See docs/operations/test.md. "
            "No automatic rollback; services may remain stopped.",
            file=sys.stderr,
        )
        raise


def verify_runtime(root, commit):
    """Check actual container images and public HTTPS, not just build success."""
    containers = json.loads(run("docker", "inspect", *SERVICES))
    for container in containers:
        state = container["State"]
        if not state["Running"] or state.get("Health", {}).get("Status", "healthy") != "healthy":
            raise UpdateError("A selected service is not healthy/running.")
        if (
            container["Name"].lstrip("/") != "netbox-sync-proxy"
            and container["Config"]["Image"] != "netbox-sync:" + commit
        ):
            raise UpdateError("A service is running the wrong image.")
    check_schedulers(root)
    status = run(
        "curl",
        "--silent",
        "--show-error",
        "--max-time",
        "30",
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code}",
        PUBLIC_URL + "/",
    )
    if status != "200":
        raise UpdateError("Public HTTPS did not return 200; inspect proxy/API and external ingress.")


def main(argv=None):
    """Require an explicit immutable release and idle acknowledgement for mutation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--with-guard", action="store_true", help="Update the known test Guard without backups, then reconcile receipts")
    parser.add_argument("--diagnose-selectel", nargs=2, metavar=('ACCOUNT', 'RUN_UUID'),
                        help="Read existing test run evidence without importing or changing state")
    parser.add_argument("--diagnose-selectel-matching", metavar='ACCOUNT',
                        help="Explain pending dedicated matches from stored test inventory; no writes or collection")
    parser.add_argument("--diagnose-selectel-hardware", metavar='ACCOUNT',
                        help="Read stored dedicated hardware field states without exposing their values")
    parser.add_argument("--probe-selectel-hardware", nargs=2, metavar=('ACCOUNT', 'RESOURCE_UUID'),
                        help="Read one Selectel server's live metadata; no import or state changes")
    parser.add_argument(
        "--idle-confirmed",
        action="store_true",
        help="Operator checked no running sync or pending lifecycle work; no concurrent operators",
    )
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        parser.error("--commit must be the reviewed full 40-character SHA")
    if args.apply and not args.idle_confirmed:
        parser.error("--apply requires --idle-confirmed")
    if args.diagnose_selectel and (args.apply or args.with_guard):
        parser.error("--diagnose-selectel cannot be combined with apply or Guard update")
    if args.diagnose_selectel_matching and (args.apply or args.with_guard or args.diagnose_selectel):
        parser.error("--diagnose-selectel-matching must be a separate read-only check")
    if args.diagnose_selectel_hardware and (args.apply or args.with_guard or args.diagnose_selectel or args.diagnose_selectel_matching):
        parser.error("--diagnose-selectel-hardware must be a separate read-only check")
    if args.probe_selectel_hardware and (args.apply or args.with_guard or args.diagnose_selectel
                                       or args.diagnose_selectel_matching or args.diagnose_selectel_hardware):
        parser.error("--probe-selectel-hardware must be a separate provider read")
    try:
        if args.apply:
            if args.with_guard:
                update(ROOT, ROOT / "repo", args.commit, with_guard=True)
            else:
                update(ROOT, ROOT / "repo", args.commit)
        else:
            preflight(ROOT, ROOT / "repo", args.commit)
            if args.probe_selectel_hardware:
                try:
                    from .selectel_hardware_probe import report as probe_report
                except ImportError:
                    from selectel_hardware_probe import report as probe_report
                GuardUpdate(run, ROOT / "repo", args.commit).preflight()
                print('SELECTEL_POINT_PROBE:', json.dumps(
                    probe_report(run, *args.probe_selectel_hardware), ensure_ascii=False, indent=2))
            if args.diagnose_selectel_hardware:
                try:
                    from .selectel_hardware_evidence import report as hardware_report
                except ImportError:
                    from selectel_hardware_evidence import report as hardware_report
                guard = GuardUpdate(run, ROOT / "repo", args.commit)
                guard.preflight()
                print('SELECTEL_HARDWARE_EVIDENCE:', json.dumps(
                    hardware_report(guard.manage, args.diagnose_selectel_hardware), ensure_ascii=False, indent=2))
            if args.diagnose_selectel_matching:
                try:
                    from .selectel_matching_evidence import report as matching_report
                except ImportError:
                    from selectel_matching_evidence import report as matching_report
                guard = GuardUpdate(run, ROOT / "repo", args.commit)
                guard.preflight()
                print('SELECTEL_MATCHING_EVIDENCE:', json.dumps(
                    matching_report(guard.manage, args.diagnose_selectel_matching), ensure_ascii=False, indent=2))
            if args.diagnose_selectel:
                try:
                    from .selectel_run_evidence import report
                except ImportError:
                    from selectel_run_evidence import report
                print('SELECTEL_RUN_EVIDENCE:', json.dumps(report(ROOT, *args.diagnose_selectel)))
            if args.with_guard:
                GuardUpdate(run, ROOT / "repo", args.commit).preflight()
            print("PREFLIGHT_OK: no services or configuration changed")
    except (UpdateError, GuardUpdateError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(
            (
                str(error)
                if isinstance(error, (UpdateError, GuardUpdateError))
                else "Command/configuration check failed. Preserve the stage report for release review."
            ),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
