"""NetBox v1/v2 syntax from the official 4.7 authentication contract."""
import re


def token_key(token):
    if token.startswith('nbt_'):
        match = re.fullmatch(r'nbt_([A-Za-z0-9]{12})\.([A-Za-z0-9]+)', token)
        if not match: raise ValueError('invalid v2 token syntax')
        return match.group(1)
    return None


def authorization(token):
    return ('Bearer ' if token_key(token) is not None else 'Token ') + token
