# Worker bundles and durable lifecycle continuation

## Permanent services

The bundled PostgreSQL deployment has ten permanent containers:

| Service | Responsibility and retained boundary |
| --- | --- |
| proxy | Standalone TLS or private external-ingress socket; no app credentials |
| api | Authenticated UI/API, DB readers and narrow registration writer, Unix RPC; no provider/NetBox secret reads or external egress |
| auth-worker | Sessions, per-user roles, policy and bounded LDAPS; exclusive bind-secret mount |
| probe-worker | Bounded source probe, transient request credentials, destination policy/DNS pinning; no registry DB writer |
| secret-broker | Local credential files and Unix sockets; literal network_mode none, no DB |
| lifecycle-worker | Narrow source lifecycle DB writes and root broker cleanup; no provider credentials or NetBox token/egress |
| schedule-worker | Narrow schedule writer; private DB and Unix interface |
| apply-worker | Supervised discovery + apply processes; individual DB-role environments, original sockets, shared write lock |
| bootstrap-worker | Supervised bootstrap + retirement processes; NetBox-only egress; retirement socket remains private to lifecycle |
| postgres | Private bundled Sync database, no published port |

External Sync PostgreSQL removes the postgres container (nine permanent services).
The scheduled sync entrypoint remains an on-demand container launched by the host
timer under the same apply lock; migration/grant/init containers are short-lived.
No product container receives Docker socket or systemd control.

Discovery/apply already used the same provider secret and network boundary.
Bootstrap/retirement already used the same protected NetBox configuration boundary.
Their process supervisors reduce twelve permanent containers to ten without adding
API access to the retirement socket. They filter child DSNs, detect member death,
stop the peer, terminate only their own process groups and reap children. Health
checks use peer-authorized Unix replies; bounded evidence of an active apply is the
only permitted busy exception, not an unlimited healthy state.

Further merging broker/API/lifecycle/auth/probe would combine materially different
filesystem, credential, database or egress privileges. Those separations remain
intentional. Old discovery/retirement service definitions exist only in the
legacy-workers profile for upgrade compatibility; the installer removes exactly
its own superseded services before starting the bundles.

## Confirmed registration

Migration 0015 adds an immutable actor/nonce-bound request, safe metadata, opaque
broker references and a closed state machine. Only the existing registration role
can insert jobs/update state. The lifecycle role can attest the exact DB-bound
broker ownership; API cannot supply arbitrary paths or read file contents.
A server loop completes one fair-selected job at a time after API restart without
a browser session. It neither grants new permissions nor changes the approved
placement. Unknown remote creation uses the exact Guard receipt/idempotency protocol.
Missing secrets before staging require re-entry; unknown identities fail closed.

## Confirmed removal waiting

Migration 0016 persists Admin confirmation and pauses new schedules atomically.
Existing admitted reads or writes can finish; subsequent admission is fenced by
source gates and a DB trigger protecting stale scheduler snapshots. A row lock
serializes the queue commit with run INSERT. Unknown/partial write outcomes block
removal and remain available for evidence reconciliation. Expired read-only
Discovery/Plan can be marked interrupted only after its process ownership lock is
free. No timeout is treated as proof of absence of writes.

The lifecycle server continues a reviewed deletion, closes the NetBox generation,
attests its full receipt, removes only exclusively owned files/credentials, and
uses the constrained atomic purge. Shared credentials, other sources and external
NetBox audit survive. Repeated completion resolves the exact final receipt.
A queued conflict needs a fresh explicit review/confirmation; no automatic consent
is inferred from elapsed time or a reopened browser. Source-local queue/jobs are
removed by the same purge transaction, with no general runtime DELETE grants.

## Evidence scope

See product-lifecycle-20260927-progress.md for executed checks and remaining gates.
Local synthetic provider inventory and real NetBox/PostgreSQL checks do not claim
acceptance on a live ESXi, Proxmox or Microsoft AD installation.


## Why Guard remains

Ordinary NetBox CRUD does not atomically prove the full dependent-object closure,
record an exact idempotent creation/retirement receipt and permanently fence a
closed source generation. Removing Guard would move these checks across multiple
HTTP transactions and permit a crash or late writer between them. This release
therefore retains the small NetBox-side integration. It is a plugin/process inside
the independently managed NetBox, not another permanent Sync container.
Its installation identity and external audit survive Sync reset. Runtime users
receive constrained model permissions plus once-only installation-prefix Guard
permissions, never superuser or arbitrary model DELETE.

## Operator-visible flow

Add source stores a non-secret draft and shows automatic continuation after a
confirmed request. A missing never-stored secret requires re-entry; the application
cannot recreate it. A definite identity/placement conflict remains blocked with a
review explanation. Temporary integration permissions or availability failures
retain the exact request and continue after the external cause is corrected.

For ordinary removal, confirm once. If work is already admitted, new runs pause,
existing work finishes, and the server reviews its final resource set. The browser
can close. A previous unknown write is not presumed safe, and manual changes or
foreign dependencies may require review. There is no automatic selection of a
foreign object, no hidden partial successful deletion and no timeout-based waiver.

Fresh sources use these paths without SQL or internal control calls. Historical
objects without creation evidence still require the separately documented,
explicit Admin review; this release does not fabricate ownership for old data.
