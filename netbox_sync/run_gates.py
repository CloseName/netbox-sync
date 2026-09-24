"""Read-only blocker selection, preserving pre-migration conservative behavior."""
from psycopg import sql

def blocking_runs(connection,schema):
    present=connection.execute('SELECT to_regclass(%s)',(schema+'.blocking_sync_runs',)).fetchone()
    exists=(present.get('to_regclass') if isinstance(present,dict) else present[0]) if present else None
    return sql.Identifier(schema,'blocking_sync_runs' if exists else 'sync_runs')
