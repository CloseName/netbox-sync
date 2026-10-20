"""Connect and discover one Proxmox source before shared reconciliation."""


def _get_pve_token_name(pve_user: str, token_id: str) -> str:
    if "!" not in token_id:
        return token_id

    token_user, token_name = token_id.split("!", 1)

    if token_user != pve_user:
        raise RuntimeError(f'PVE token belongs to "{token_user}", ' f'but PVE_API_USER is "{pve_user}"')

    if not token_name:
        raise RuntimeError("PVE token name is empty")

    return token_name


def execute_proxmox_source(
    source_config,
    sync_mode,
    legacy_secrets=False,
    *,
    _scheduled_stage,
    LegacyFileSecretResolver,
    FileSecretResolver,
    ProxmoxAPI,
    _get_pve_token_name,
    discover_hosts,
    execute_discovered_source,
):
    """Execute the existing validated pipeline for one Proxmox source."""

    _scheduled_stage("credentials")
    resolver_class = LegacyFileSecretResolver if legacy_secrets else FileSecretResolver
    pve_credentials = resolver_class().resolve_credentials(source_config.credentials)

    # Instantiate connection to the Proxmox VE API
    pve_user = pve_credentials.username

    _scheduled_stage("provider")
    pve_api = ProxmoxAPI(
        host=source_config.address,
        user=pve_user,
        token_name=_get_pve_token_name(pve_user, pve_credentials.token_id),
        token_value=pve_credentials.token_secret,
        verify_ssl=source_config.verify_ssl,
        port=source_config.api_port,
    )

    from .source_tls import configure_proxmox

    configure_proxmox(pve_api, source_config.verify_ssl)
    from .host_primary_ip import select_endpoint

    hosts = select_endpoint(discover_hosts(pve_api, source_config), source_config)
    return execute_discovered_source(
        source_config,
        hosts,
        sync_mode,
        pve_api=pve_api,
    )
