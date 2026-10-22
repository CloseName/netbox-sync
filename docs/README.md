# Documentation map

Start here when changing the project. Documents describe different generations
of the application; an old acceptance report is evidence for its recorded revision,
not proof that today's checkout or deployment passes those checks.

## Maintained entry points

- [Agent working agreement](../AGENTS.md) and [chat project instructions](operations/chat-project.md).
- [Known test operations](operations/test.md) and [production discovery requirements](operations/production.md):
  environment-specific entry points before any deployment commands.

- [Development](development.md): local setup and verification commands.
- [Frontend](frontend.md): current routes and browser behavior, followed by older
  implementation notes. [Verification baseline](verification-baseline.md) records
  the current test limitations and the checks required for refactoring.
- [Architecture](architecture.md): process boundaries and implementation history.
  Its early foundation sections are historical; validate implementation details
  against the code before using them as current contracts.
- [Deployment](deployment.md), [containers](containers.md),
  [deployment paths](deployment-paths.md), [migrations](migrations.md), and
  [backup/restore](backup-restore.md): installation and operator procedures.
  Reading or changing these guides does not authorize running them on production.
- [Incremental refactoring](refactoring-plan.md): scope and order of changes. See the [completion report](refactoring-completion-20261020.md) for the current module map, audit and validation results.
- [Selectel status](selectel-status.md): experimental integration and unresolved
  acceptance limits. Start here before the individual Selectel design reports.

## Contracts by subject

- Identity and ownership: [hardware identity](hardware-identity.md),
  [host registration](host-identity-registration.md),
  [conflicts and recovery](inventory-conflicts-and-source-recovery.md).
- Operations: [prerequisites](prerequisite-contract.md),
  [coordination](reconciliation-coordination.md),
  [worker continuation](worker-bundles-and-continuation.md).
- Access: [source access](source-access.md), [teams](source-teams.md),
  [local administrators](local-admin-policy.md), [LDAPS/RBAC](ldaps-rbac.md).
- Networking: [observations](network-observations.md),
  [primary IP](host-primary-ip.md), [provider automation](provider-network-automation.md).

## Historical evidence and proposals

Files named `*-acceptance*`, `*-progress*`, `*-audit*`, `*-review*`, and dated
reports retain their original scope and revision. Some contain useful operational
instructions, but a historical passing result must not be reused as a current one.
The [October consolidation report](consolidation-20261019.md) records the baseline
before the first refactoring PR, including incomplete browser verification.

[Future product architecture](future-product-architecture.md),
[source authorization proposal](web-source-authorization-proposal.md), and
[retirement guard proposal](retirement-guard-proposal.md) are design inputs;
their presence does not establish that every proposed feature is implemented.

Keep existing filenames and links stable. When changing behavior, update the
relevant contract and add dated validation evidence; do not overwrite old results.
