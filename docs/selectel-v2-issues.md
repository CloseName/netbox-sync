# Журнал доработок и ошибок Selectel v2

Приёмка: только тестовый NetBox. Новые результаты пользователя записывать сюда;
не объявлять проблему исправленной без проверки соответствующего сценария.

| ID | Наблюдение / требование | Статус | Проверка |
|---|---|---|---|
| S01 | WAN из pfsense_network не участвовал в поиске кандидатов | Локально добавлены кандидаты с проверкой VM, текущего MAC и свежести; на стенде не проверено | T06–T07 |
| S02 | На production облачные VM попали в реестр, native-карточки не созданы | Причина подтверждена кодом: account import не вызывал reconcile. Добавлен opt-in этап в общей транзакции; интеграционная проверка ожидается | T01 |
| S03 | Обратное принятие Selectel-карточки при добавлении гипервизора | Локально добавлено по свежим аппаратным ID; Proxmox без DMI и конфликт площадки требуют проверки | T04 |
| S04 | Приоритет Selectel для управляемых полей и защита от обратного sync | Добавлены native claims, матрица и исключение provider-полей из Sync; SQL-проверка на стенде ожидается | T08 |
| S05 | Суточное/месячное/датированное расписание Selectel | Локально реализованы календарь, API, UI и worker; стендовый перезапуск ещё не проверен | T10 |
| S06 | Отключение, отсоединение и удаление аккаунта по происхождению объектов | Локально добавлены API/UI, план, журнал, идемпотентный повтор, очистка секрета; старые IPAM/network links блокируют удаление | T11–T14 |
| S07 | Полнота регионов/площадок | Стабильные ключи и обновление названий добавлены; конфликты размещения сохраняются для проверки | T09 |
| S08 | UI должен показывать причины и действия, а не общую ошибку | Добавлены причины lifecycle/размещения и действия после потери ответа; нужна приёмка полного UI | T01,T05,T15,T16 |
| S09 | Устаревшая pfSense запись №252 без карточки | Зафиксировано на production; в этом этапе не менять | Отдельная задача |
| S10 | Build Agent 2: WAN 45.92.176.97 есть в снимке VM912, не в IPAM | Подтверждённый пример S01, новая привязка не применена | T06 |
| S11 | Сверка неподтверждённого импорта Selectel | Повторные автоматические записи остановлены; отдельное восстановление по квитанции ещё требуется | T16 |
| S12 | Обновление теста 1fe352a остановилось: NameError PLUGINS_CONFIG в zzzz_selectel_v2_test.py | Подтверждено выводом пользователя; не исправлено, блокирует приёмку | Подготовка T01–T02 |

## S12 — результат установки на netbox-test, 2026-10-14

- Коммит: 1fe352a3b6aac51701c9fa23ced52815bb56d909.
- Источник: присланный лог обновления, каталог /var/tmp/selectel-v2-github.Z3QwOY.
- Guard image собран, netbox и netbox-worker остановлены. Команда migrate завершилась при загрузке конфигурации: NameError: name 'PLUGINS_CONFIG' is not defined, /etc/netbox/config/zzzz_selectel_v2_test.py:1.
- Причина: созданный updater файл обращается к переменной, не определённой в области этого модуля конфигурации. Это ошибка нашего скрипта установки.
- Обновление целиком НЕ завершено; успешное выполнение миграций, обновление Sync и готовность importer не подтверждены. Скрипт ранее остановил bootstrap worker и таймер; текущее состояние требует проверки.
- Логи сервера: /var/tmp/selectel-servers-test-20261014T180543Z.log и /var/tmp/selectel-v2-test-update.Hl627X.
- T01 и T02: NOT RUN / BLOCKED. По запросу пользователя только фиксация, без исправления и без действий на production.

## Локальная проверка 2026-10-14

- 18 тестов Python прошли; 1 проверка root-owned Linux storage пропущена на Windows.
- TypeScript проверен, UI собран успешно; 93 теста интерфейса прошли.
- Добавлены интеграционные сценарии атомарного native import, replay, прав
  отдельного импортёра и происхождения объектов. Они **не запускались**:
  локальный Docker Engine недоступен, база тестового NetBox не подключена.
- Production и тестовый NetBox не изменялись. Приёмка T01–T17 не начата.

## Продолжение разработки 2026-10-14

- 162 теста Python прошли; 33 пропущены (Linux/root storage и отдельная БД).
- 93 существующих теста UI прошли; TypeScript и сборка UI прошли.
- Проверен полный путь ESXi plan → apply на имитаторе: provider-карточка без
  кластера принимается с прежним PK, новым sync identity и сохранёнными Selectel refs.
  Это не проверка SQL-триггеров настоящего NetBox.
- Проверены потеря ответа lifecycle, повтор с тем же nonce, запрет подмены
  ожидающей операции, окончательный rollback и очистка локального секрета.
- Планировщик переведён на `web-5a-19`: старые планы после обновления нужно перестроить.
- Добавлены настоящие DB-сценарии обновления CPU/RAM/имени, SQL-защиты, стабильной
  площадки и отдельный `tests/netbox_selectel_lifecycle_scenario.py` с независимыми
  транзакциями. Они **NOT RUN**: Docker Engine на ноутбуке не запущен
  (`docker_engine` pipe отсутствует). Сценарии разрешают только disposable БД
  `netbox_sync_guard_test` на localhost, не рабочую БД тестового сервера.
- Удаление унаследованных ProviderIPAMObject без происхождения, сетевые provider
  links и автоматический перенос общего кластера остаются явными блокировками.
  Не считать эти случаи реализованным полным удалением/переносом.
- Production и тестовый сервер не изменялись; все изменения находятся в локальном checkout.

## Шаблон новой ошибки (для последующей приёмки)

- ID / сценарий:
- Версии Sync и Guard:
- Ожидалось / получено:
- Время, run ID, безопасный код:
- Файл отчёта (без секретов):
- Влияние на данные:
- Статус: зафиксировано / исправлено локально / проверено на тестовом.


## Тестовая приёмка 2026-10-14 — пакет обновления

По запросу пользователя обновление только netbox-test (10.24.0.6:22336), без бэкапа. Production исключён. Подготовлен deploy/update-selectel-v2-test.sh: проверки окружения, ожидание активных операций, миграции, native/lifecycle permissions, проверка importer. Сам сбор updater не запускает; существующие расписания после запуска сервисов продолжают действовать.

T01–T17 остаются NOT RUN до получения вывода пользователя. Ошибки записываем здесь с ID сценария, версией, временем, run_id, ожидаемым и фактическим результатом; исправления после завершения согласованной серии. Начальная проверка удаления — только review; выполнение на одноразовых тестовых ресурсах после проверки списка. Изолированные DB-сценарии пока не запускались.

Обновление процесса: пользователь подтвердил публикацию доработок в GitHub. Дальнейшая установка — из конкретного коммита ветки feat/selectel-guard-bindings; локальный архив больше не используется. Уже загруженный архив удалять не требуется. Проверка config mount допускает read-only mount контейнера: файл конфигурации записывается на хосте в /netbox-test.

### S12 — подтверждённое состояние после остановки

По выводу пользователя: netbox и netbox-worker Exited (0), старый image aa8d21ee1b03; netbox-sync-bootstrap-worker Exited (0). Остальные Sync workers и API работают на ffb2b3ea40d94e301c8b99d0605075568ac3bae7. netbox-sync.timer и netbox-sync.service inactive/dead. PostgreSQL и Redis работают. Обновление Sync не выполнено, тестовые сборы заблокированы. Исправления и перезапуски не выполнялись.


### S12 — исправление для повторного тестового обновления

Конфигурационный модуль теперь копирует последнюю загруженную PLUGINS_CONFIG с сохранением настроек остальных плагинов. Проверка bootstrap.json выполняется на хосте без запуска остановленного worker и без вывода секретов. Конфигурация заменяется атомарно и проверяется одноразовым manage.py check перед сборкой/миграциями. Три регрессионных теста прошли (изолированные модули, приоритет и повторная загрузка, отсутствие конфигурации, fallback на основной файл); bash -n пройден. Статус: исправлено локально, подтверждение на netbox-test ожидается.

### S12 — повторная ошибка стенда и второе исправление

342e167 на netbox-test остановился до миграций: RuntimeError: Selectel test: no previous PLUGINS_CONFIG definition. Лог /var/tmp/selectel-v2-test-update.Z2dr2Y. Прошлые тесты ошибочно предполагали регистрацию загруженных конфигураций в sys.modules; это предположение не подтверждено на стенде.

Новый подход не использует sys.modules: на хосте выбирается последнее явное определение PLUGINS_CONFIG в конфигурационных файлах, туда добавляется идемпотентный блок. Ошибочный zzzz_selectel_v2_test.py заменяется комментарием. Сохраняются остальные настройки, права и владелец файлов; запись атомарная. Четыре регрессионных теста прошли, включая загрузчик без регистрации модулей, порядок определения, повтор и отказ без изменений при некорректном файле. bash -n пройден. Состояние: исправлено локально, стенд ещё не подтверждён. Production не затрагивался.

### S12 — третья попытка на стенде

Коммит 81366d4: configure() завершился RuntimeError: No module-level PLUGINS_CONFIG definition; no files changed. Каталог /var/tmp/selectel-v2-s12-retry.1yD2MO, лог /var/tmp/selectel-v2-test-update.wdhG5N. Миграции не запускались этой попыткой. Нужна диагностика структуры конфигурационных файлов и загрузчика без значений настроек. Новое исправление до получения фактической структуры не применяется. Статус S12: OPEN, тестовые сборы BLOCKED.


### S12 — структура конфигурации подтверждена пользователем

В configuration.py, extra.py и zz_local_ldaps.py нет ссылок на PLUGINS_CONFIG; plugins.py задаёт только PLUGINS через globals() и добавляет netbox_guard. PLUGINS_CONFIG отсутствует, кроме ошибочного файла нашего updater. Исправлен случай отсутствия необязательной настройки: создаётся пустой словарь в существующем plugins.py и добавляется только selectel_native_reconcile. Остальной текст и список плагинов сохраняются, ошибочный override нейтрализуется. Шесть тестов прошли, включая присланную структуру, повторную установку и сохранение существующих настроек. Статус: исправление готово, выполнение на стенде ожидается.

### S12 — подтверждено на тестовом стенде

Получен полный лог установки 11a48eb: миграции 0013/0014 OK, netbox и netbox-worker healthy, system check без ошибок, 45 существующих provider bindings, native mode подтверждён, importer preflight OK, TEST UPDATE COMPLETE. Лог сервера /var/tmp/selectel-v2-test-update.0HgoYL. S12: исправление подтверждено для установки; T01/T02 ещё NOT RUN.

### S13 — шумная проверка готовности во время запуска

При первом health probe API напечатан FileNotFoundError для Unix socket из web_runtime.py. install.py проверяет готовность в цикле до 30 попыток с интервалом 2 секунды; успешное завершение установки означает последующее прохождение health/proxy/auth проверок. Зафиксировать UX-дефект: ожидаемое ожидание сокета выводится как traceback. Исправление пока не выполнялось.

## Test updater without automatic backups — 2026-10-26

Operator requested removing backups from test updates, including Guard. Removed
Sync backup preflight/create/verify and Guard database/configuration archives.
Kept host/target checks, pause before migrations, runtime/HTTPS verification and
schedules-off contract. Standalone backup/restore and production are unchanged.
Validation: 114 passed, 1 platform skip in updater/Guard/backup-restore tests.
No server update was executed.

## S15 — historical baseline recovery, 2026-10-26

User confirmed both old test runs remain uncertain with missing receipts: account
29916 / f5f3efcc-436a-4caf-8d21-d5492ba94f4c and account 435835 /
85c0013b-6464-4d8a-aa66-2604623ffbcf. Added explicit disabled-account baseline review
and acceptance, persistent unknown-outcome history and old-run import fence.
No live state has been cleared. Pending acceptance retains the lifecycle gate.
Schedules stay off and old resources/IP/bindings remain untouched. Test deployment
and actual historical decisions remain NOT RUN. See operations/selectel-recovery.md.

Local verification (2026-10-26): Windows/Python 3.14: 2741 passed,
491 skipped (platform/opt-in dependencies), 2 dependency deprecation warnings.
Two additional lifecycle regressions were then included in a focused 9/9 pass.
Frontend: 96 unit tests and 5 Playwright Selectel scenarios passed; build passed.
Black 25.1.0: 231 files unchanged. Pylint: 9.41/10 (existing style/cycle warnings).
Docker engine unavailable locally: the independent PostgreSQL/NetBox lifecycle
scenario is included in Guard CI and remains required before rollout.
No test-server or production state was changed by this implementation work.

## Test Guard preflight CONFIG_DRIFT — 2026-10-26

Operator selected 672fc1446c9402287b0b94dda8a113e8a99483ec; read-only preflight
returned GUARD_CONFIG_DRIFT before apply. No stopped services or deployment are
established by this output. Root cause is not established: the original check
provided no service/format/version/environment comparison.
Added a closed, read-only report to the saved updater; drift still blocks apply.
Docker Compose v5.3.1 runHash loads with WithoutEnvironmentResolution:
https://github.com/docker/compose/blob/v5.3.1/cmd/compose/config.go#L408
This is a possible explanation for env-file installations, not proof of the
operator's current cause. Test-host report remains required. No server changed.

## Test Guard resolved configuration hashes — 2026-10-26

23efd3df preflight: both services use Compose 5.3.1, valid but mismatching
hashes, one env file each, 35 declared environment keys and matching image refs.
The old equality diagnostic did not undo Compose dollar escaping. The hash gate
now hashes the fully resolved model through Compose itself and compares the exact
stored label, including env-file contents. Real drift remains blocked. No server,
account, IP, resource binding or scheduling state changed during development.
Disposable Compose 5.3.1 CI checks label equality and env/command drift. Live
test-host preflight and Selectel acceptance remain pending.

## S16 — new test import unconfirmed, 2026-10-26

Operator confirmed UPDATE_OK for a46fa57e and historical baseline acceptance for
29916. New manual run 08cd3347-a976-4dd9-a043-f4d591796e30 ended IMPORT_UNCONFIRMED
(displayed 19:41:04 MSK); receipt lookup at 19:50:16 MSK returned not_found.
No fresh baseline acceptance/replay is justified. Root cause is still unknown.
Collector/runner currently collapse transport/child/validation failures into one
saved error; the historical detail cannot be reconstructed from account state.
Added a read-only updater evidence option for existing logs before any new import.
Its time-window categories are leads, not write-outcome proof. Test/prod untouched.
Also observed: old reconciliation wording still says import blocked after baseline
acceptance; label this historical in a later UI correction.

## S17 — distinguish atomic refusal and uncertain response

Read-only evidence for 08cd3347 showed one HTTP 409 in the time window. Source review
confirmed PROVIDER_IMPORT_REFUSED was not recognized by transport and the underlying
exception was discarded. Added an explicit exact-run rollback contract and sanitized
reason propagation to UI, plus disposable NetBox rollback and post-commit response
failure tests. Do not reinterpret the old run: its actual response body is unavailable.
No server has been changed by this implementation. Old baseline acceptance is not
repeated; schedules stay off. Root cause investigation remains open.
