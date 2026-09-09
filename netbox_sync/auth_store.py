"""Narrow PostgreSQL auth/policy writer. No registry or provider access."""
import re
from psycopg import connect, sql
from psycopg.types.json import Jsonb
from .auth_policy import AuthPolicy, AuthError, initial_state


class AuthStore:
    def __init__(self, dsn, schema, baseline=None):
        if not re.fullmatch(r'[a-z][a-z0-9_]{2,62}', schema):
            raise ValueError('Invalid auth schema')
        self.dsn, self.schema, self.baseline = dsn, schema, baseline

    def call(self, payload, *, root=False):
        error = None
        try:
            with connect(self.dsn, connect_timeout=5) as connection:
                connection.execute("SET LOCAL lock_timeout='5s'")
                table = sql.Identifier(self.schema, 'auth_state')
                row = connection.execute(sql.SQL('SELECT value FROM {} WHERE id=1 FOR UPDATE').format(table)).fetchone()
                if row is None:
                    raise AuthError('AUTH_UNAVAILABLE')
                service = AuthPolicy(row[0], self.baseline)
                try:
                    result = service.root(payload.get('action'), payload) if root else service.call(payload)
                except AuthError as exc:
                    error = exc
                    result = None
                connection.execute(sql.SQL('UPDATE {} SET value=%s WHERE id=1').format(table), (Jsonb(service.state),))
                for event in service.audit:
                    connection.execute(sql.SQL('INSERT INTO {} (event) VALUES (%s)').format(
                        sql.Identifier(self.schema, 'auth_audit')), (Jsonb(event),))
            if error:
                raise error
            return result
        except AuthError:
            raise
        except Exception:
            raise AuthError('AUTH_UNAVAILABLE') from None
