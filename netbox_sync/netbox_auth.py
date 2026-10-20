"""NetBox v1/v2 syntax from the official 4.7 authentication contract."""

import re


def token_key(token):
    """Extract the public key of a valid v2 token, returning None for legacy tokens."""

    if token.startswith("nbt_"):
        match = re.fullmatch(r"nbt_([A-Za-z0-9]{12})\.([A-Za-z0-9]+)", token)
        if not match:
            raise ValueError("invalid v2 token syntax")
        return match.group(1)
    return None


def authorization(token):
    """Choose Bearer authentication for v2 tokens and Token for legacy tokens."""

    return ("Bearer " if token_key(token) is not None else "Token ") + token
