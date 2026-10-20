"""Versioned ownership metadata; deliberately independent of role/LDAP membership."""

from copy import deepcopy
import json
import uuid
from .source_config import SOURCE_INSTANCE_PATTERN


def teams_action(service, action, payload, actor):
    """Authorize and apply versioned ownership metadata without changing roles.

    Require an exact integer revision before payload validation; validate a copy
    and its encoded size before committing and auditing. Reads migrate missing
    metadata additively. Return a detached copy so callers cannot mutate state.
    """
    from .auth_policy import AuthError

    service.session(payload.get("session"), "source.read" if action == "teams" else "source.configure")
    current = service.state.get("source_teams", {"version": 1, "revision": 0, "teams": {}, "assignments": {}})
    if current.get("version") != 1:
        raise AuthError("AUTH_UNAVAILABLE")
    # Existing auth state migrates additively under its existing DB row lock.
    if action == "teams":
        service.state.setdefault("source_teams", deepcopy(current))
        return deepcopy(current)
    if type(payload.get("revision")) is not int or payload["revision"] != current["revision"]:
        raise AuthError("TEAM_CONFLICT")
    updated = deepcopy(current)
    team = payload.get("team_id")
    if team is not None and not isinstance(team, str):
        raise AuthError("TEAM_INVALID")
    if action in ("teams.create", "teams.rename"):
        team = _name_team(updated, action, payload, team, error_type=AuthError)
    elif action == "teams.assign":
        _assign_team(updated, payload, team, error_type=AuthError)
    else:
        raise AuthError("TEAM_INVALID")
    updated["revision"] += 1
    if len(json.dumps(updated).encode()) > 24576:
        raise AuthError("TEAM_INVALID")
    service.state["source_teams"] = updated
    service.event(
        action, actor, team_id=team, source_instance=payload.get("source_instance"), revision=updated["revision"]
    )
    return deepcopy(updated)


def _name_team(updated, action, payload, team, *, error_type):
    """Create or rename in the pending copy, preserving validation/UUID order.

    Trim names, compare uniqueness with casefold, and apply the 100-team limit
    only to creation. Return the generated or existing identifier for auditing.
    """
    name = payload.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
        raise error_type("TEAM_INVALID")
    name = name.strip()
    if action == "teams.create":
        if len(updated["teams"]) >= 100:
            raise error_type("TEAM_INVALID")
        team = str(uuid.uuid4())
    elif team not in updated["teams"]:
        raise error_type("TEAM_INVALID")
    if any(key != team and row["name"].casefold() == name.casefold() for key, row in updated["teams"].items()):
        raise error_type("TEAM_INVALID")
    updated["teams"][team] = {"id": team, "name": name}
    return team


def _assign_team(updated, payload, team, *, error_type):
    """Validate a source and team, then update only the pending assignment map.

    None removes an assignment, including a missing one; revision advancement
    and audit of that no-op remain the responsibility of the outer transaction.
    """
    source = payload.get("source_instance")
    if not isinstance(source, str) or not SOURCE_INSTANCE_PATTERN.fullmatch(source):
        raise error_type("TEAM_INVALID")
    if team is not None and team not in updated["teams"]:
        raise error_type("TEAM_INVALID")
    if team is None:
        updated["assignments"].pop(source, None)
    else:
        updated["assignments"][source] = team
