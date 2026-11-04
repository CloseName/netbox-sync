"""Human-readable matching evidence; never grants permission to bind or create."""

REASONS = {
    'existing_binding': 'Сохранена связь с существующей карточкой NetBox.',
    'binding_target_missing': 'Прежняя карточка удалена или заменена. Нужно проверить сохранённую связь.',
    'stable_identity': 'Найдено однозначное соответствие по устойчивому идентификатору.',
    'identity_needs_confirmation': 'Найдены возможные совпадения. Требуется подтверждение соответствия.',
    'hardware_identity_missing': 'Аппаратный идентификатор не получен. Отсутствие кандидатов не доказывает отсутствие карточки.',
    'hardware_identity_conflict': 'Аппаратные идентификаторы противоречат друг другу.',
    'placement_missing': 'Недостаточно сведений о площадке для создания карточки.',
    'provider_state_not_ready': 'Состояние облачного сервера пока не поддерживает применение. Проверьте состояние в Selectel.',
    'provider_task_in_progress': 'В Selectel выполняется операция над облачным сервером. Дождитесь её завершения и обновите сбор.',
    'fresh_inventory_required': 'Нужен свежий успешный сбор: сведения отсутствуют, устарели или сохранены из прежнего ответа.',
    'multiple_provider_resources': 'Несколько ресурсов претендуют на одну карточку или аппаратную идентичность.',
    'operator_detached': 'Ресурс был отсоединён пользователем.',
    'no_existing_candidate': 'Кандидаты не найдены. Текущий план допускает создание при применении импорта.',
}


def explain(plan):
    """Expose only named evidence fields; do not dump the plan or raw snapshots."""
    candidates = []
    for candidate in plan.get('candidates', []):
        evidence = candidate.get('evidence') or {}
        reasons = []
        if evidence.get('stable_identity'):
            reasons.append('Совпала устойчивая идентичность')
        if evidence.get('hardware_conflict'):
            reasons.append('Есть противоречие аппаратных идентификаторов')
        if evidence.get('same_name'):
            reasons.append('Совпало полное название без учёта регистра')
        if evidence.get('public_ips'):
            reasons.append('Совпал публичный IP: ' + ', '.join(evidence['public_ips']))
        if evidence.get('observed_guest_wans'):
            reasons.append('Адрес Selectel найден на WAN гостевой pfSense с известным хостом')
        candidates.append(dict(name=candidate['name'], url=candidate['url'], reasons=reasons))
    return dict(reason=REASONS.get(plan.get('reason'), 'Причина сопоставления требует дополнительной проверки.'),
                candidates=candidates,
                private_scope_unverified=bool(plan.get('ignored_address_matches')),
                writes_performed=False)
