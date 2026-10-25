"""Unprivileged collection/import child. Input via pipe, bounded output to private file."""

import json
import sys
from contextlib import redirect_stdout
from .selectel_payload import bounded_json, inventory_document, import_payload
from .retirement_transport import GuardTransportError
from tools.selectel_audit.collector import Collector, Credentials
from tools.selectel_audit.account import account_overview
from tools.selectel_audit.resource_registry import registry
from tools.selectel_audit.client import AuditError


def summary(document):
    """Project account coverage counts and product summaries without raw audit responses."""

    value = account_overview(document)
    return {
        "projects": value["projects_visible"],
        "observed_at": value["observed_at"],
        "products": [
            {k: p[k] for k in ("product", "title", "state", "state_label", "observations_by_collection")}
            for p in value["products"]
        ],
    }


def run(value):
    """Collect experimental Selectel inventory or send one configured guard operation."""

    if value["operation"] == "collect":
        credential = Credentials(value["account"], username=value["username"], password=value["password"])
        document = Collector(credential, profile="all", progress=lambda _: None).run()
        result = {
            "document": inventory_document(document),
            "registry": registry(document),
            "summary": summary(document),
        }
        # Check the actual import envelope before reporting successful collection.
        import_payload(value["account"], "00000000-0000-0000-0000-000000000000", result)
        return result
    import requests
    from .netbox_tls import configure_session
    from .retirement_transport import GuardClient
    from .netbox_auth import authorization

    with requests.Session() as session:
        configure_session(session)
        client = GuardClient(session, value["url"], authorization(value["token"]), value["guard_instance"])
        if value["operation"] == "preflight":
            return client._request("GET", "providers/account-import/")
        if value["operation"] in ("lifecycle-review", "lifecycle-execute"):
            suffix = "review" if value["operation"] == "lifecycle-review" else "execute"
            return client._request("POST", "providers/lifecycle/" + suffix + "/", value["payload"])
        bounded_json(value["payload"])
        return client._request("POST", "providers/account-import/", value["payload"])


def main():
    """Keep stdout as a bounded JSON protocol and retain uncertainty after possible writes."""

    value = {}
    operation = None
    try:
        value = json.load(sys.stdin)
        operation = value.get("operation")
        # stdout is a JSON protocol, including when a dependency prints progress.
        with redirect_stdout(sys.stderr):
            result = run(value)
    except AuditError as exc:
        code = str(exc)
        result = {
            "error": (
                code
                if code
                in {
                    "HTTP_401",
                    "HTTP_403",
                    "ACCOUNT_SCOPE_MISMATCH_USE_ACCOUNT_IAM_TOKEN",
                    "REQUEST_BUDGET_EXCEEDED",
                    "INVALID_AUTH_RESPONSE",
                }
                else "COLLECTION_FAILED"
            )
        }
    except GuardTransportError as exc:
        if operation == "import":
            result = {"error": "IMPORT_UNCONFIRMED" if exc.uncertain else "NETBOX_IMPORT_REFUSED"}
        else:
            result = {
                "error": "IMPORT_UNCONFIRMED" if operation == "lifecycle-execute" else "NETBOX_IMPORT_SETUP_FAILED"
            }
    except ValueError as exc:
        result = {
            "error": (
                "SELECTEL_RESULT_TOO_LARGE"
                if str(exc) == "SELECTEL_RESULT_TOO_LARGE"
                else (
                    "IMPORT_UNCONFIRMED"
                    if operation in ("import", "lifecycle-execute")
                    else "NETBOX_IMPORT_SETUP_FAILED" if operation == "preflight" else "COLLECTION_FAILED"
                )
            )
        }
    except Exception:
        result = {
            "error": (
                "IMPORT_UNCONFIRMED"
                if operation in ("import", "lifecycle-execute")
                else "NETBOX_IMPORT_SETUP_FAILED" if operation == "preflight" else "COLLECTION_FAILED"
            )
        }
    try:
        encoded = bounded_json(result)
    except (ValueError, MemoryError):
        encoded = bounded_json(
            {
                "error": (
                    "IMPORT_UNCONFIRMED"
                    if operation in ("import", "lifecycle-execute")
                    else "SELECTEL_RESULT_TOO_LARGE"
                )
            }
        )
    sys.stdout.write(encoded.decode("ascii"))


if __name__ == "__main__":
    main()
