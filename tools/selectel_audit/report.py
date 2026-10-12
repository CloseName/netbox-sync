"""Portable offline report. HTML escapes all provider/user supplied text."""
import html
import json
import os
from pathlib import Path

from .review import inventory, match_candidates


def html_report(document, rows):
    esc = lambda x: html.escape(str(x), quote=True)
    coverage = document['coverage']
    bad = sum(x['status'] != 'collected' for x in coverage)
    tr = []
    for row in rows:
        details = '<br>'.join(esc(f"{c['type']} #{c['id']} {c['name']}: " +
            ', '.join(x['type'] + (' ' + x['address'] if 'address' in x else '')
                      for x in c['evidence'])) for c in row['candidates']) or '—'
        tr.append('<tr>' + ''.join('<td>' + esc(row[k]) + '</td>' for k in
            ('kind', 'name', 'project', 'region', 'provider_id')) +
            '<td>' + '<br>'.join(map(esc, row['addresses'])) + '</td><td><span class="badge">' +
            esc(row['match_status']) + '</span><br>' + details + '</td></tr>')
    ct = ''.join('<tr>' + ''.join('<td>' + esc(x.get(k, '')) + '</td>' for k in
                 ('service', 'kind', 'project', 'region', 'status', 'count')) + '</tr>' for x in coverage)
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
<h2>Ресурсы и кандидаты NetBox</h2><input id="search" placeholder="Имя, адрес, проект или статус" aria-label="Поиск">
<div class="table"><table id="resources"><thead><tr><th>Тип</th><th>Имя</th><th>Проект</th><th>Регион</th><th>ID Selectel</th><th>IP</th><th>Сопоставление</th></tr></thead><tbody>''' + ''.join(tr) + '''</tbody></table></div>
<details open><summary>Покрытие сбора</summary><p class="muted">collected — запросы раздела завершены; HTTP_403 — нет прав; NOT_IN_CATALOG — нет в каталоге; UNSUPPORTED_SERVICE — адаптер ещё не реализован. Это не доказательство отсутствия услуги.</p>
<div class="table"><table><thead><tr><th>API</th><th>Раздел</th><th>Проект</th><th>Регион</th><th>Результат</th><th>Записей</th></tr></thead><tbody>''' + ct + '''</tbody></table></div></details>
<footer>Поля и типы значений: fields.json. Все собранные разделы: inventory.json. Выгрузка содержит внутреннюю инфраструктурную информацию.</footer>
</main><script>document.getElementById('search').addEventListener('input',function(){const q=this.value.toLocaleLowerCase();document.querySelectorAll('#resources tbody tr').forEach(r=>r.hidden=!r.textContent.toLocaleLowerCase().includes(q));});</script></html>'''


def write_report(document, directory, netbox=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    rows = inventory(document)
    if netbox:
        match_candidates(rows, netbox)
    document['review'] = rows
    if netbox:
        document['netbox'] = netbox
    def write(name, value):
        path = directory / name
        with path.open('x', encoding='utf-8', newline='') as stream:
            stream.write(value)
        os.chmod(path, 0o600)
    write('inventory.json', json.dumps(document, ensure_ascii=False, indent=2))
    fields = [{k: x.get(k) for k in ('service', 'kind', 'project', 'region', 'fields')}
              for x in document['datasets']]
    write('fields.json', json.dumps(fields, ensure_ascii=False, indent=2))
    summary = {
        'account': document['account'], 'account_verified': document.get('account_verified', False),
        'account_completeness': 'not_proven', 'projects_visible': len(document['projects']),
        'resources_in_review': len(rows), 'coverage': document['coverage'],
        'netbox_coverage': netbox['coverage'] if netbox else 'not_requested',
        'limitations': document['limitations'],
    }
    write('summary.json', json.dumps(summary, ensure_ascii=False, indent=2))
    write('report.html', html_report(document, rows))
    lines = ['Selectel audit — только чтение', f"Аккаунт: {document['account']}",
             f"Доступных проектов: {len(document['projects'])}", f'Ресурсов в обзоре: {len(rows)}',
             'Полнота аккаунта НЕ подтверждена: см. coverage в summary.json.',
             'Секреты и свободные поля маскируются; файлы всё равно содержат внутренние данные.',
             'Нет записи в Selectel/NetBox. Кандидаты требуют проверки человеком.']
    write('summary.txt', '\n'.join(lines) + '\n')
    return rows
