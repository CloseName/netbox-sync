"""Operator-only read of the saved plan for one run; no credentials/provider/API use."""
import argparse
import hashlib
import json
import os
import sys
from uuid import UUID
import psycopg
from psycopg import sql
from psycopg.rows import dict_row


def envelope(plan, run_id, source, digest):
    if not isinstance(plan, dict) or plan.get('source_instance')!=source or plan.get('digest')!=digest:
        raise ValueError('SAVED_PLAN_UNAVAILABLE_OR_REPLACED')
    canonical = {k:v for k,v in plan.items() if k!='digest'}
    if hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()!=digest:
        raise ValueError('SAVED_PLAN_DIGEST_INVALID')
    candidates = [{'external_id':item['external_id'], 'data':dict(item['after'])}
        for item in plan['items'] if item['object_kind']=='virtualization.virtual_machines' and item['action']=='CREATE']
    return dict(format='sync-guard-candidates-v1', run_id=str(UUID(str(run_id))),
                source_instance=source, plan_digest=digest, candidates=candidates)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--run-id', type=UUID, required=True)
    args=parser.parse_args()
    try:
        schema=os.environ['NETBOX_SYNC_REGISTRY_SCHEMA']
        with psycopg.connect(os.environ['NETBOX_SYNC_LIFECYCLE_WRITER_DSN'], row_factory=dict_row, connect_timeout=5) as db:
            db.execute('SET TRANSACTION READ ONLY')
            db.execute("SET LOCAL statement_timeout = '10000ms'")
            run=db.execute(sql.SQL('SELECT plan_digest FROM {} WHERE run_id=%s AND source_instance=%s').format(
                sql.Identifier(schema,'sync_runs')), (args.run_id,args.source)).fetchone()
            row=db.execute(sql.SQL("SELECT result FROM {} WHERE source_instance=%s AND operation_kind='PLAN'").format(
                sql.Identifier(schema,'source_operations')), (args.source,)).fetchone()
            result=envelope(row['result'] if row else None,args.run_id,args.source,run['plan_digest'] if run else None)
        sys.stdout.write(json.dumps(result,ensure_ascii=True))
    except Exception:
        sys.stderr.write('CANDIDATES_UNAVAILABLE: saved plan may be replaced/absent or database read refused. Do not retry Apply.\n')
        return 1
    return 0

if __name__=='__main__': raise SystemExit(main())
