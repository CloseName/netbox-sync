"""Portable offline report. HTML escapes all provider/user supplied text."""
import html
import json
import os
from pathlib import Path

from .review import inventory, match_candidates
from .contextual_review import contextual_review
from .coverage import summarize, resource_counts
from .field_contract import ownership_review, CUSTOM_FIELDS
from .account import account_overview, LABELS
from .dns_storage import export as dns_storage_export


def account_html(document):
    esc = lambda value: html.escape(str(value), quote=True)
    overview = account_overview(document)
    names = {p['id']: p.get('name', p['id']) for p in document.get('projects', [])}
    rows = []
    for product in overview['products']:
        counts = ', '.join(f'{k}: {v}' for k, v in product['observations_by_collection'].items()) or '—'
        scopes = ''.join('<li>' + esc(names.get(s['project'], s['project']) or 'Аккаунт') +
            ' / ' + esc(s['region'] or 'Область без региона') + ': ' + esc(LABELS[s['state']]) +
            '<ul>' + ''.join('<li>' + esc(f"{r['kind']}: {r['code']} ({r['observations']})") + '</li>'
                            for r in s['sections']) + '</ul></li>' for s in product['scopes'])
        detail = ('<details><summary>Области и результаты запросов</summary><ul>' + scopes +
                  '</ul></details>') if scopes else ''
        rows.append('<tr><td>' + esc(product['title']) + '</td><td>' +
            esc('Частичная поддержка' if product['adapter'] == 'partial' else 'Не реализован') +
            '<br>' + esc(product['limitations']) + '</td><td>' + esc(product['state_label']) +
            detail + '</td><td>' + esc(counts) + '</td><td>' + esc(product['netbox_target']) + '</td></tr>')
    unknown = ', '.join(overview['unmapped_catalog_services']) or 'Нет в полученном снимке'
    return ('<h2>Аккаунт: продукты и возможности сбора</h2><p>Профиль: <b>' + esc(overview['profile']) +
            '</b>. Успешный сбор относится только к реализованным разделам. '
            'Счётчики — наблюдения списков; их нельзя складывать в общее число ресурсов.</p>'
            '<div class="table"><table><thead><tr><th>Продукт</th><th>Возможности и ограничения</th>'
            '<th>Результат сбора</th><th>Наблюдения</th><th>Представление в NetBox</th></tr></thead>'
            '<tbody>' + ''.join(rows) + '</tbody></table></div><p>Другие сервисы каталога: ' + esc(unknown) +
            '. Наличие сервиса в каталоге не доказывает наличие ресурсов. '
            'Этот отчёт не применяет изменения в NetBox.</p>')


def html_report(document, rows):
    esc = lambda x: html.escape(str(x), quote=True)
    coverage = document['coverage']
    overview = summarize(coverage)
    bad = overview['requires_attention']
    tr = []
    for row in rows:
        details = '<br>'.join(esc(f"{c['type']} #{c['id']} {c['name']}: " +
            ', '.join(x['type'] + (' ' + x['address'] if 'address' in x else '')
                      for x in c['evidence'])) for c in row.get('proposed_candidates', row['candidates'])) or '—'
        if row.get('related_vms'):
            details += '<br>Связанные гостевые VM: ' + esc(', '.join(str(x['id']) + ' ' + x['name'] for x in row['related_vms']))
        if row.get('unscoped_ip_matches'):
            details += '<br>Совпадения частных IP без карты сетей: ' + esc(', '.join(x['name'] for x in row['unscoped_ip_matches']))
        contract = ownership_review(row)
        details += '<details><summary>Иерархия и владельцы полей</summary><p>' + esc(' → '.join(contract['hierarchy'])) + '</p>'
        details += '<p>' + esc(contract['prerequisite']) + '</p><p>Связь не подтверждена; запись запрещена.</p><ul>'
        details += ''.join('<li>' + esc(f"{r['field']}: {r['authority']}. {r['rule']}") + '</li>' for r in contract['field_rules']) + '</ul></details>'
        tr.append('<tr>' + ''.join('<td>' + esc(row[k]) + '</td>' for k in
            ('kind', 'name', 'project', 'region', 'provider_id')) +
            '<td>' + '<br>'.join(map(esc, row['addresses'])) + '</td><td><span class="badge">' +
            esc(row.get('analysis_status', row['match_status'])) + '</span><br>' + details + '</td></tr>')
    names = {p['id']: p.get('name', p['id']) for p in document['projects']}
    ct = ''.join('<tr>' + ''.join('<td>' + esc(v) + '</td>' for v in
                 (x['service'], names.get(x['project'], x['project']), x['region'],
                  ', '.join(f'{k}: {v}' for k, v in x['categories'].items()),
                  ', '.join(f'{k}: {v}' for k, v in x['statuses'].items()))) + '</tr>' for x in overview['scopes'])
    category_labels = {'collected': 'Прочитано', 'partial': 'Частично прочитано',
        'access_denied': 'Отказ доступа', 'unavailable': 'API недоступен (404)',
        'unsupported': 'Не реализовано', 'skipped': 'Повтор / старая версия пропущены',
        'blocked_endpoint': 'Адрес не разрешён', 'not_in_catalog': 'Нет в каталоге', 'error': 'Ошибка'}
    category_html = '<ul>' + ''.join('<li>' + esc(category_labels.get(k, k)) + ': ' + str(v) + '</li>'
        for k, v in overview['categories'].items()) + '</ul>'
    nb = document.get('netbox')
    nb_state = document.get('netbox_read', {}).get('status', 'collected' if nb else 'not_requested')
    nb_html = '<p>Чтение NetBox: <b>' + esc(nb_state) + '</b></p>'
    if nb:
        nb_html += '<ul>' + ''.join('<li>' + esc(f"{x['kind']}: {x['status']}, {x['count']}") + '</li>' for x in nb['coverage']) + '</ul>'
        bindings = sum(x.get('source_bindings', {}).get('status') == 'exported' for k in ('devices', 'vms') for x in nb['datasets'].get(k, []))
        nb_html += '<p>Объектов с прочитанным полем sync_identities: ' + str(bindings) + '. Идентификаторы сохранены в inventory.json; привязка автоматически не выполняется.</p>'
    return '''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src 'none'; connect-src 'none'">
<title>Selectel · Инвентаризация</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#152238;font:15px system-ui,sans-serif}
header{background:#10263c;color:white;padding:34px 5vw}header small{color:#88d8d0;letter-spacing:.12em}
h1{font-size:30px;margin:10px 0}main{margin:24px 4vw 60px}.cards{display:flex;gap:16px;flex-wrap:wrap}
.card{background:white;border:1px solid #dce3ec;border-radius:12px;padding:20px;min-width:200px}
.card strong{display:block;font-size:30px;color:#007f79}.note{background:#e7f3f1;border-left:4px solid #00877c;padding:18px;margin:24px 0;line-height:1.6}
.table{overflow:auto;background:white;border:1px solid #dce3ec;border-radius:10px}table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;vertical-align:top;padding:13px;border-bottom:1px solid #e7ecf2;min-width:100px;max-width:440px;overflow-wrap:anywhere}
th{background:#eaf0f6;white-space:nowrap}.badge{display:inline-block;background:#fff2d1;color:#6f4c00;padding:4px 7px;border-radius:5px;font-size:11px;margin-bottom:5px}
input{padding:12px;border:1px solid #c2ccd9;border-radius:8px;min-width:320px;margin:0 0 14px}summary{cursor:pointer;font-size:20px;font-weight:600;margin:26px 0 16px}
h2{margin-top:30px}.muted{color:#53657b}footer{margin-top:24px;color:#53657b}
</style><header><small>NETBOX SYNC / SELECTEL AUDIT</small><h1>Инвентаризация аккаунта ''' + esc(document['account']) + '''</h1>
<div>Снимок для проектирования синхронизации · только чтение</div></header><main><div class="cards">
<div class="card"><strong>''' + str(len(document['projects'])) + '''</strong>доступных проектов</div>
<div class="card"><strong>''' + str(len(rows)) + '''</strong>ресурсов в обзоре</div>
<div class="card"><strong>''' + str(bad) + '''</strong>разделов требуют внимания</div></div>
<div class="note">Полнота всего аккаунта ещё не подтверждена. Данные ограничены правами учётной записи и поддержанными API.
«Кандидат» не означает привязку. Имя и публичный IP — подсказки; приватный IP требует сопоставления сетевых областей.
Ни одна запись NetBox не создана и не изменена.</div>
''' + account_html(document) + '''
<h2>Ресурсы и кандидаты NetBox</h2><input id="search" placeholder="Имя, адрес, проект или статус" aria-label="Поиск">
<div class="table"><table id="resources"><thead><tr><th>Тип</th><th>Имя</th><th>Проект</th><th>Регион</th><th>ID Selectel</th><th>IP</th><th>Сопоставление</th></tr></thead><tbody>''' + ''.join(tr) + '''</tbody></table></div>
<h2>NetBox</h2>''' + nb_html + '''
<details open><summary>Покрытие сбора по продуктам, проектам и регионам</summary>''' + category_html + '''<p class="muted">Неподдержанный сервис в каталоге не означает купленную услугу. Успешный ответ не доказывает полноту аккаунта. Полный журнал разделов — в summary.json.</p>
<div class="table"><table><thead><tr><th>API</th><th>Проект</th><th>Регион</th><th>Категории</th><th>Результаты разделов</th></tr></thead><tbody>''' + ct + '''</tbody></table></div></details>
<footer>Поля и типы значений: fields.json. Все собранные разделы: inventory.json. Выгрузка содержит внутреннюю инфраструктурную информацию.</footer>
</main><script>document.getElementById('search').addEventListener('input',function(){const q=this.value.toLocaleLowerCase();document.querySelectorAll('#resources tbody tr').forEach(r=>r.hidden=!r.textContent.toLocaleLowerCase().includes(q));});</script></html>'''


def write_report(document, directory, netbox=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = inventory(document)
    if netbox:
        match_candidates(rows, netbox)
        rows = contextual_review(rows, netbox)
    document['review'] = rows
    document['integration_contract'] = {
        'stage': 'review_only', 'writes_enabled': False,
        'resources': [ownership_review(row) for row in rows],
        'custom_field_manifest': CUSTOM_FIELDS,
        'schema_status': 'not_checked',
    }
    if netbox:
        document['netbox'] = netbox
    def write(name, value):
        path = directory / name
        with path.open('x', encoding='utf-8', newline='') as stream:
            stream.write(value)
        os.chmod(path, 0o600)
    write('inventory.json', json.dumps(document, ensure_ascii=False, indent=2))
    account = account_overview(document)
    write('account.json', json.dumps(account, ensure_ascii=False, indent=2))
    write('dns-storage.json', json.dumps(dns_storage_export(document), ensure_ascii=False, indent=2))
    fields = [{k: x.get(k) for k in ('service', 'kind', 'project', 'region', 'fields')}
              for x in document['datasets']]
    write('fields.json', json.dumps(fields, ensure_ascii=False, indent=2))
    summary = {
        'account': document['account'], 'account_verified': document.get('account_verified', False),
        'account_completeness': 'not_proven', 'projects_visible': len(document['projects']),
        'resources_in_review': len(rows), 'coverage': document['coverage'],
        'collector_version': document.get('collector_version', 'unknown'),
        'coverage_summary': summarize(document['coverage']),
        'resource_counts': resource_counts(document),
        'account_overview': {'schema': account['schema'], 'states': account['states'],
            'unmapped_catalog_services': account['unmapped_catalog_services'],
            'products': [{k: p[k] for k in ('product', 'adapter', 'state', 'observations_by_collection')}
                         for p in account['products']]},
        'netbox_read': document.get('netbox_read', {'requested': bool(netbox), 'status': 'provided_snapshot' if netbox else 'not_requested'}),
        'netbox_coverage': netbox['coverage'] if netbox else document.get('netbox_read', {}).get('status', 'not_requested'),
        'limitations': document['limitations'],
    }
    write('summary.json', json.dumps(summary, ensure_ascii=False, indent=2))
    write('report.html', html_report(document, rows))
    lines = ['Selectel audit — только чтение', f"Аккаунт: {document['account']}",
             f"Доступных проектов: {len(document['projects'])}", f'Ресурсов в обзоре: {len(rows)}',
             'Полнота аккаунта НЕ подтверждена: см. coverage в summary.json.',
             'Продукты и пробелы: account.json и раздел аккаунта в report.html.',
             'Секреты и свободные поля маскируются; файлы всё равно содержат внутренние данные.',
             'Нет записи в Selectel/NetBox. Кандидаты требуют проверки человеком.']
    write('summary.txt', '\n'.join(lines) + '\n')
    return rows
