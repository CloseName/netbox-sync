"""Bounded retirement timings and query counts; never SQL, parameters or objects."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import logging
import time
from uuid import UUID
from django.db import connection
from .dependencies import DependencyGuardBlocked

_current = ContextVar('guard_retirement_profile', default=None)
_log = logging.getLogger(__name__)

class Profile:
    def __init__(self, nonce, action):
        self.nonce, self.action = str(UUID(str(nonce))), action
        self.queries = 0
        self.sql_seconds = 0.0
        self.sqlstate = None
        self.deadline = None

    def query(self, execute, sql, params, many, context):
        # Check between Collector/signal queries, not only between VM batches.
        # Never block rollback or the session advisory-unlock outside the fence.
        if self.deadline is not None and connection.in_atomic_block and time.monotonic()>=self.deadline:
            raise DependencyGuardBlocked('RETIREMENT_DEADLINE')
        self.queries += 1
        started = time.monotonic()
        try:
            return execute(sql, params, many, context)
        except Exception as error:
            cause = getattr(error, '__cause__', None)
            state = getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None)
            if state in {'57014', '55P03', '40P01', '40001', '23503', '23505'}:
                self.sqlstate = state
            raise
        finally:
            self.sql_seconds += time.monotonic() - started

    @contextmanager
    def phase(self, name, count=0):
        started, queries, sql_seconds = time.monotonic(), self.queries, self.sql_seconds
        _log.warning('retirement_operation=%s action=%s phase=%s status=started objects=%d',
                  self.nonce, self.action, name, count)
        code = 'OK'
        try:
            yield
        except Exception as error:
            code = str(error) if isinstance(error, DependencyGuardBlocked) else 'UNEXPECTED_FAILURE'
            if len(code)>64 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ_' for c in code):
                code = 'UNEXPECTED_FAILURE'
            raise
        finally:
            _log.warning('retirement_operation=%s action=%s phase=%s code=%s duration_ms=%d queries=%d sql_ms=%d objects=%d sqlstate=%s',
                self.nonce, self.action, name, code, round((time.monotonic()-started)*1000),
                self.queries-queries, round((self.sql_seconds-sql_seconds)*1000), count, self.sqlstate or 'none')

def profiled(action):
    def decorate(function):
        @wraps(function)
        def call(user, nonce, *args, **kwargs):
            profile = Profile(nonce, action)
            token = _current.set(profile)
            try:
                with connection.execute_wrapper(profile.query), profile.phase('total'):
                    return function(user, nonce, *args, **kwargs)
            finally:
                _current.reset(token)
        return call
    return decorate

@contextmanager
def phase(name, count=0):
    profile = _current.get()
    if profile is None:
        yield
    else:
        with profile.phase(name, count):
            yield


def set_deadline(deadline):
    profile = _current.get()
    if profile is not None:profile.deadline = deadline
