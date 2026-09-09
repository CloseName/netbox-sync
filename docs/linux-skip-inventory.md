# Linux skip inventory — c1e8b1d review

Baseline repeated on 2026-09-09: **834 passed, 91 skipped**, two existing FastAPI/httpx deprecation warnings. Linux root test container, no Docker socket/CLI, network none, read-only current checkout; pytest cache disabled. No live credentials. JUnit skip entries are transcribed below, including parameter IDs. The extra passing test versus the earlier 833 is the added SPA /system case; skip count is unchanged.

This is an inventory of the baseline, not 91 unresolved failures. Separate reruns do not alter its totals. Each row states relevance and coverage; unexecuted unrelated gates remain explicitly unverified for this diff.

| File (under tests/) | Skips | Exact gate reason | Relation / disposition |
|---|---:|---|---|
| test_api_sources_postgres.py | 5 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | No backend/storage changes in this UI diff. General disposable PostgreSQL DSN absent in baseline; not rerun for this review, remaining independent integration gate. UI fixtures do not count as its replacement. |
| test_backup_clean_debian.py | 2 | explicit clean Debian host test opt-in required; explicit disposable privileged Debian host test opt-in required | Host backup/runtime preparation unchanged. Privileged clean-Debian opt-ins not enabled; remaining independent host gate, not needed for UI diff. |
| test_backup_restore_docker.py | 1 | set NETBOX_SYNC_BACKUP_DOCKER_TEST=1 for disposable Docker smoke | Backup/restore unchanged. Explicit Docker backup gate not enabled; remaining independent integration gate. |
| test_backup_restore_postgres.py | 1 | NETBOX_SYNC_BACKUP_TEST_POSTGRES_DSN is not configured | Backup/restore unchanged. Dedicated disposable backup DSN absent; remaining independent integration gate. |
| test_container_names_docker.py | 2 | opt-in disposable production Compose naming smoke | Naming/DB transition unchanged. Explicit Docker naming gate not enabled; remaining independent integration gate. |
| test_deployment_foundation.py | 1 | Docker CLI is unavailable | Distribution prerequisite, unchanged deployment code. Docker CLI is available on the host; exact skipped Compose-render test rerun there: passed. |
| test_deployment_postgres.py | 4 | NETBOX_SYNC_DEPLOYMENT_TEST_POSTGRES_DSN is not configured | DB grants/deployment unchanged. Dedicated disposable deployment DSN absent; remaining independent integration gate. |
| test_discovery_postgres.py | 1 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | No backend/storage changes in this UI diff. General disposable PostgreSQL DSN absent in baseline; not rerun for this review, remaining independent integration gate. UI fixtures do not count as its replacement. |
| test_durable_worker_linux.py | 1 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | Directly relevant: operation polling/reconciliation. Rerun in isolated Linux + PostgreSQL: passed; real Unix transport, disconnect, duplicate start, persisted result. |
| test_esxi_live.py | 1 | live ESXi connection variables are not configured | No adapter changes. Live ESXi credentials/endpoint absent; deliberately not run (no live host access authorized). Remaining live-integration gap. |
| test_external_ingress.py | 2 | Docker CLI unavailable | Distribution prerequisite. Both exact skipped merged Compose checks rerun on host: passed. |
| test_first_run_zero_source.py | 1 | NETBOX_SYNC_DEPLOYMENT_TEST_POSTGRES_DSN is not configured | Bootstrap/deployment unchanged. Dedicated disposable deployment DSN absent; remaining independent integration gate. |
| test_migrations_postgres.py | 4 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | No backend/storage changes in this UI diff. General disposable PostgreSQL DSN absent in baseline; not rerun for this review, remaining independent integration gate. UI fixtures do not count as its replacement. |
| test_naming_migration_postgres.py | 1 | NETBOX_SYNC_NAMING_TEST_POSTGRES_DSN is not configured | Naming migration unchanged. Dedicated disposable naming DSN absent; remaining independent integration gate. |
| test_onboarding_postgres.py | 8 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | No backend/storage changes in this UI diff. General disposable PostgreSQL DSN absent in baseline; not rerun for this review, remaining independent integration gate. UI fixtures do not count as its replacement. |
| test_probe_compose_docker.py | 2 | opt-in isolated production probe smoke | Probe implementation unchanged in this diff. Both opt-in production Compose tests passed for c1e8b1d (previous evidence); not rerun or claimed as current passes. |
| test_production_proxy_docker.py | 1 | opt-in disposable production Compose proxy smoke | Proxy configuration unchanged. Separate exact production Compose tmpfs gate: result recorded in review evidence. |
| test_run_history_postgres.py | 4 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | Relevant read contract for Overview evidence. Rerun against disposable PostgreSQL: all selected cases passed. |
| test_schedule_worker_postgres.py | 1 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | No backend/storage changes in this UI diff. General disposable PostgreSQL DSN absent in baseline; not rerun for this review, remaining independent integration gate. UI fixtures do not count as its replacement. |
| test_source_lifecycle_postgres.py | 15 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | No backend/storage changes in this UI diff. General disposable PostgreSQL DSN absent in baseline; not rerun for this review, remaining independent integration gate. UI fixtures do not count as its replacement. |
| test_source_operations_postgres.py | 12 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | Directly relevant: durable operation DTO/state consumed by UI. Rerun against disposable PostgreSQL: all selected cases passed. |
| test_source_registry_postgres.py | 18 | NETBOX_SYNC_TEST_POSTGRES_DSN is not configured | No backend/storage changes in this UI diff. General disposable PostgreSQL DSN absent in baseline; not rerun for this review, remaining independent integration gate. UI fixtures do not count as its replacement. |
| test_tls_docker.py | 3 | Opt-in disposable TLS Docker smoke | Relevant built frontend delivery. Separate production Compose smoke on rebuilt image: results recorded in review evidence; three modes, not counted as baseline passes. |

## Every skipped node

### tests/test_api_sources_postgres.py (5)

- `test_postgres_empty_source_list`
- `test_postgres_source_list`
- `test_postgres_source_detail`
- `test_postgres_source_not_found`
- `test_postgres_secret_references_excluded`
### tests/test_backup_clean_debian.py (2)

- `test_clean_debian_old_release_backup`
- `test_clean_debian_optional_libpq_venv`
### tests/test_backup_restore_docker.py (1)

- `test_bundled_postgres_custom_dump_restore_transport`
### tests/test_backup_restore_postgres.py (1)

- `test_custom_dump_round_trip_preserves_multi_source_and_history`
### tests/test_container_names_docker.py (2)

- `test_old_auto_name_to_canonical_preserves_database`
- `test_fresh_all_services_and_foreign_name_fail_closed`
### tests/test_deployment_foundation.py (1)

- `test_canonical_compose_renders_without_provider_configuration`
### tests/test_deployment_postgres.py (4)

- `test_clean_bootstrap_migrate_grants_and_idempotency`
- `test_runtime_role_grants_are_column_limited`
- `test_migration_ownership_preflight_rejects_foreign_schema_owner`
- `test_ui6_writers_have_only_the_required_capabilities`
### tests/test_discovery_postgres.py (1)

- `test_discovery_reader_exact_grants_allow_lookup_and_deny_mutation`
### tests/test_durable_worker_linux.py (1)

- `test_disconnect_and_duplicate_requests_keep_one_provider_execution`
### tests/test_esxi_live.py (1)

- `test_live_esxi_connection_is_read_only_and_explicitly_opted_in`
### tests/test_external_ingress.py (2)

- `test_merged_compose_has_only_intended_publication[standalone]`
- `test_merged_compose_has_only_intended_publication[external]`
### tests/test_first_run_zero_source.py (1)

- `test_zero_source_processes_boot_without_netbox_or_provider_secrets`
### tests/test_migrations_postgres.py (4)

- `test_clean_migration_and_legacy_runtime_interoperate`
- `test_existing_populated_registry_is_preserved`
- `test_unknown_version_rolls_back_version_table`
- `test_partial_schema_is_not_stamped`
### tests/test_naming_migration_postgres.py (1)

- `test_database_schema_roles_and_rows_transition_without_drops`
### tests/test_onboarding_postgres.py (8)

- `test_postgres_registration_exact_defaults_references_and_duplicates[proxmox]`
- `test_postgres_registration_exact_defaults_references_and_duplicates[esxi]`
- `test_existing_runtime_resolves_broker_created_files[proxmox]`
- `test_existing_runtime_resolves_broker_created_files[esxi]`
- `test_registration_role_insert_select_only`
- `test_definite_database_rejection_rolls_back_secrets`
- `test_actual_commit_then_conversion_failure_reconciles[ValueError]`
- `test_actual_commit_then_conversion_failure_reconciles[TypeError]`
### tests/test_probe_compose_docker.py (2)

- `test_production_probe[bundled]`
- `test_production_probe[external]`
### tests/test_production_proxy_docker.py (1)

- `test_external_proxy_production_compose_starts_with_real_tmpfs`
### tests/test_run_history_postgres.py (4)

- `test_start_finish_duration_counts_and_snapshot_roundtrip`
- `test_listing_is_newest_first_filtered_and_bounded`
- `test_diagnostics_queries_return_latest_and_bounded_stale_runs`
- `test_narrow_run_writer_can_only_insert_and_finalize_history`
### tests/test_schedule_worker_postgres.py (1)

- `test_schedule_writer_column_privileges_and_optimistic_update`
### tests/test_source_lifecycle_postgres.py (15)

- `test_remove_retains_identity_and_stops_schedule`
- `test_id_typing_and_concurrent_configuration_fail_closed`
- `test_active_operation_blocks_removal[PLAN]`
- `test_active_operation_blocks_removal[DISCOVERY]`
- `test_unconfirmed_apply_evidence_blocks_removal[RUNNING]`
- `test_unconfirmed_apply_evidence_blocks_removal[OUTCOME_UNCERTAIN]`
- `test_unconfirmed_apply_evidence_blocks_removal[PARTIALLY_APPLIED]`
- `test_exclusive_credentials_only_after_tombstone_commit`
- `test_shared_and_legacy_credentials_are_retained`
- `test_broker_failure_does_not_roll_back_tombstone`
- `test_concurrent_removal_has_one_transition`
- `test_column_limited_lifecycle_role_can_take_credential_gate`
- `test_active_reader_excludes_only_removed_sources`
- `test_reserved_registration_and_schedule_updates_are_blocked`
- `test_removed_credential_refs_cannot_be_reassigned`
### tests/test_source_operations_postgres.py (12)

- `test_simultaneous_starts_create_exactly_one_generation`
- `test_other_source_and_other_kind_remain_independent`
- `test_ready_is_persisted_reopen_and_generation_fenced`
- `test_worker_failure_is_durable_and_sanitized`
- `test_discovery_completion_and_duplicate_executor`
- `test_orphan_recovery_does_not_resume_work`
- `test_recovery_never_replaces_still_owned_execution`
- `test_bounded_latest_result_expiry`
- `test_foreign_result_and_bad_digest_are_rejected`
- `test_unknown_and_disabled_sources_fail_closed`
- `test_stale_invalidation_cannot_touch_replacement`
- `test_late_completion_is_logged_without_replacing_new_state`
### tests/test_source_registry_postgres.py (18)

- `test_initialize_empty_database_is_idempotent`
- `test_create_get_list_and_source_config_conversion`
- `test_isolated_list_contains_malformed_row_without_blocking_valid_row`
- `test_duplicate_id_and_source_instance_fail_without_partial_rows`
- `test_secret_references_round_trip_without_resolution[env]`
- `test_secret_references_round_trip_without_resolution[file]`
- `test_settings_database_constraint_rejects_non_object`
- `test_mutable_update_and_noop_timestamp_behavior`
- `test_identity_fields_are_immutable[id]`
- `test_identity_fields_are_immutable[source_instance]`
- `test_identity_fields_are_immutable[source_type]`
- `test_invalid_update_rolls_back`
- `test_registry_has_no_delete_api`
- `test_registry_never_resolves_or_persists_secret_values`
- `test_guarded_bootstrap_create_update_and_noop_against_postgres`
- `test_runnable_source_listing_is_filtered_ordered_and_secret_opaque`
- `test_esxi_source_round_trips_without_plaintext_password`
- `test_mixed_runnable_sources_are_ordered_and_filtered`
### tests/test_tls_docker.py (3)

- `test_public_https_and_private_ca_bootstrap[standalone]`
- `test_public_https_and_private_ca_bootstrap[corporate]`
- `test_public_https_and_private_ca_bootstrap[external]`

## Reproduction boundaries

Baseline: `docker run --rm --network none --mount type=bind,source=<checkout>,target=/app,readonly netbox-sync-probe-tests:review python -m pytest -q -p no:cacheprovider`. Test image is built by tests/Dockerfile.ui6, not the application runtime.

Relevant PostgreSQL rerun: tests/test_durable_worker_linux.py, tests/test_source_operations_postgres.py, tests/test_run_history_postgres.py: **18 passed**, covering **17** baseline skips plus one non-skipped case. A uniquely named internal Docker network and PostgreSQL 16 container with tmpfs data, no host port, no persistent volume, database netbox_sync_test; only its test runner connected. Fixture uses disposable schema prefixes and finalizer removed only the created container/network. Test-only trust authentication was confined to that network; never a product setting.

Host Docker CLI rerun: test_canonical_compose_renders_without_provider_configuration and both test_merged_compose_has_only_intended_publication parameter cases: **3 passed**. TLS/proxy rerun outcomes are in [review evidence](ux-hardening-review.md).
