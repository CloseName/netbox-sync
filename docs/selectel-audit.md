# Selectel: первый аудит аккаунта

В версии 0.4.0 добавлены `account.json`, единая таблица 20 групп продуктов и
`deploy/audit-selectel-account-test.sh ACCOUNT` для отдельного тестового запуска.
Возможности адаптера отделены от успешности чтения конкретного аккаунта;
см. [контракт инвентаризации аккаунта](selectel-account-inventory.md).

Статус: отдельный контейнер чтения. Он не регистрирует новый источник в рабочем
Sync, не меняет схему БД, NetBox Guard, расписания или объекты NetBox. Базовый код —
`618a4e43a9fba82565b21341c6a43d46f0fdf9a5`. Следующий этап требует реальных снимков.

## Доступ

Обычный статический ключ из «Профиль → Доступ → API-ключи» (`X-Token`) не подходит
для современных API облака и выделенных серверов. Для первого запуска:

1. В нужном аккаунте Selectel открыть «Профиль → Доступ → IAM-токен».
2. Нажать «Скопировать», выбрать область «Аккаунт», скопировать токен.
3. Ввести номер этого аккаунта и токен в интерактивном контейнере.

IAM-токен действует 24 часа. При отказе в переключении области проекта сборщик
сохранит явный результат отказа; такой проект не считается пустым. Второй режим —
имя и пароль существующего сервисного пользователя, с разрешениями чтения нужных
проектов/услуг. Сборщик не создаёт пользователя и не изменяет права. Привязку
номера аккаунта к области токена проверяет Identity API до начала сбора.

Для второго аккаунта запускается тот же контейнер повторно с другими доступами.
Секреты вводятся через TTY без отображения; не нужны env-файлы и параметры с
паролями. Они не сохраняются в отчёте или образе. Для будущей фоновой интеграции
нужен отдельный сервисный пользователь и хранение через существующий secret broker.

## Состав снимка и пределы полноты

- IAM и Cloud Projects: видимые проекты, их ID/имена и доступные атрибуты.
- Dedicated API: заказанные ресурсы всех типов, их состояния/тарифные атрибуты,
  детали, дополнительные заказанные ресурсы, локации, сети, порты, IP и подсети.
  Каталог доступных для заказа услуг не приравнивается к купленным ресурсам.
- Для каждого доступного проекта: отдельный scoped token и публичный service
  catalog; регионы берутся из него, а не из фиксированного списка.
- Nova: VM и flavors; Neutron: сети, подсети, порты, floating IP, роутеры,
  security groups; Cinder: volumes/snapshots; Glance: доступные образы;
  Octavia: load balancers; Swift: бакеты/контейнеры без объектов внутри.
- Selectel DNS: зоны без содержимого записей; Global Router: список роутеров.
- Каталог сохраняет неподдержанные сервисы с явным статусом. Managed Kubernetes,
  DBaaS, Registry, VMware Cloud Director, CDN, 1C, почта и mobile farm пока имеют
  `PRODUCT_ADAPTER_NOT_IMPLEMENTED`: их отсутствие **не установлено**.
- Это не аудит платежей, договоров, тикетов, пользовательских данных или секретов.
  Даже успешно прочитанный аккаунт не доказывает полноту прав. Число проектов и
  ресурсов нужно сравнить с панелью обоих аккаунтов.

`collected` означает успешную пагинацию данного endpoint в рамках текущих прав.
`HTTP_401`, `HTTP_403`, `HTTP_404`, ошибки TLS, ограничения страниц/запросов и
неожиданная форма ответа сохраняются раздельно. Уже прочитанные страницы остаются
в снимке при сбое следующей. Проекты с отказом авторизации не пропускаются молча.
При нестандартной форме ответа структура сохраняется для уточнения адаптера.

## Запуск на тестовом сервере

Контейнер не требует остановки Sync/NetBox или резервного копирования. Не запускать
установщик `deploy/install.py`: это отдельный инструмент, а не обновление приложения.
Образ собирается из `tools/selectel_audit/Dockerfile`; Python standard library,
дополнительных пакетов нет. Контейнеру нужен исходящий HTTPS и запись только в output.

```bash
docker build -f tools/selectel_audit/Dockerfile \
  --build-arg VCS_REF="$(git rev-parse HEAD)" -t netbox-sync-selectel-audit:local .
install -d -m 0700 -o 65532 -g 65532 /netbox-sync-test/selectel-audit/output
docker run --rm -it --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --pids-limit 64 --memory 1g --cpus 1 \
  --mount type=bind,src=/netbox-sync-test/selectel-audit/output,dst=/output \
  netbox-sync-selectel-audit:local
```

При вопросе о NetBox можно ответить `n`: собрать Selectel сначала. При `y` вводится
токен с правами чтения тестового NetBox. Нужно видеть все сравниваемые объекты,
иначе отсутствие кандидата не доказывает отсутствие объекта. Даже HTTP 200 может
содержать ограниченную правами выборку. TLS-проверка всегда включена. Если системный
CA не доверяет внутреннему сертификату, добавить mount существующего PEM CA и
`--netbox-ca /ca/netbox-ca.pem`; не отключать проверку и не монтировать приватные ключи.
Нет автоматического обращения к production. `--netbox-url` — явный выбор оператора;
по умолчанию используется известный тестовый адрес.

## Результаты

В отдельной папке `<account>-<UTC timestamp>`:

| Файл | Содержание |
|---|---|
| `summary.json` | Покрытие по API/проекту/региону, ошибки, ограничения |
| `inventory.json` | Собранные записи, очищенные ответы API и кандидаты NetBox |
| `fields.json` | Пути полей и встреченные типы для будущего отображения |
| `report.html` | Локальный отчёт с поиском, ресурсами и объяснениями кандидатов |
| `summary.txt` | Краткое резюме |

Для первого разбора передать `summary.json`, затем при необходимости остальные
файлы через согласованный канал. Снимки содержат внутренние IP/имена, ID и сведения
об услугах. Права файлов 0600, каталогов 0700; не коммитить их в публичный GitHub.
Пароли/токены, credentials, user-data, metadata, свободные description/comments и
PEM private keys маскируются. Это не универсальная DLP: произвольное имя ресурса
может содержать чувствительную информацию. Файлы остаются внутренними.

Отчёт — обзор; `inventory.json` содержит больше видов объектов, чем таблица хостов
и VM. HTML ничего не отправляет в сеть. Сбор не атомарен: инфраструктура может
измениться между запросами; перед будущим apply обязательна новая проверка.

## Сопоставление первого этапа

Все совпадения только предлагаются человеку, `auto_apply=false` всегда:

- `NOT_COMPARED`: NetBox не запрашивался;
- `REVIEW_REQUIRED`: один кандидат по имени/серийному номеру/IP, нужна проверка;
- `CONFLICT`: несколько кандидатов, несовпадение типа Device/VM или несколько
  объектов Selectel претендуют на один NetBox объект;
- `INCOMPLETE_NETBOX_READ`: хотя бы один раздел чтения NetBox не завершён;
- `NO_CANDIDATE`: в прочитанном наборе кандидата нет; это не разрешение создавать;
- `NOT_A_HOST_OR_VM`: услуга другого типа, её не превращаем в фиктивную VM.

Приватные IP явно отмечены как `private_ip_unmapped`. Маска удаляется только для
поиска кандидатов; исходные маски и VRF сохранены. Floating/public IP могут быть
NAT, поэтому не являются идентичностью. MAC и DNS-поиск пока не добавлены в
критерии: сначала требуется проверить семантику реальных данных.

## Проверки и публикация

```bash
python -m unittest tools.selectel_audit.test_audit -v
git diff --check
```

Тесты автономные, не используют реальные доступы. GitHub Actions workflow
`Selectel audit container` запускает их на Python 3.12, собирает Linux-образ,
проверяет `--version/--help`, публикует GHCR тег с полным commit SHA и сохраняет
portable tar.gz как artifact. Успех локальных тестов не равен успешной сборке образа,
а сборка не равна приёмке на живом аккаунте. Доступность GHCR зависит от настроек
пакета; сборка из зафиксированного коммита на тестовом сервере остаётся альтернативой.

## Основания API

- [Авторизация и совместимость токенов](https://docs.selectel.ru/api/authorization/).
- [Копирование IAM-токена](https://docs.selectel.ru/account/manage-keys/).
- [URL продуктов](https://docs.selectel.ru/api/urls/).
- [Dedicated](https://docs.selectel.ru/api/dedicated/),
  [IAM](https://docs.selectel.ru/api/users-and-roles/),
  [Cloud Projects](https://docs.selectel.ru/api/cloud-projects-and-resources/),
  [DNS](https://docs.selectel.ru/api/dns-actual/),
  [Global Router](https://docs.selectel.ru/api/global-router/).
- [Keystone](https://docs.openstack.org/api-ref/identity/v3/),
  [Nova](https://docs.openstack.org/api-ref/compute/),
  [Neutron](https://docs.openstack.org/api-ref/network/v2/),
  [Cinder](https://docs.openstack.org/api-ref/block-storage/v3/),
  [Swift](https://docs.openstack.org/api-ref/object-store/).
# Audit 0.2.0: follow-up to the first inventory

This remains an isolated **read-only audit**, not a synchronization provider.
No live database migrations, NetBox writes, or changes to the installed Sync services.

- Glance pagination preserves Selectel's `/image` proxy prefix for the exact
  service-root link `/v2/images?...`; host/path restrictions remain enforced.
- Cinder v3 (including the catalog's `volume` alias) is collected once per
  endpoint/region. Legacy v2 is skipped only when an allowed v3 endpoint exists
  in that region; failures of v3 remain visible, never treated as an empty inventory.
- Coverage separates collected, partial, access denied, unavailable, unsupported,
  skipped, missing catalog and blocked endpoint categories. Product/project/region
  summaries and the original per-section log are both retained. Unsupported
  technical catalog entries are never contacted. No additional endpoint domains
  or ports are trusted by this revision.
- Resource counters distinguish project-owned networks from visible provider
  networks, and Swift containers from names carrying a multipart-upload suffix.
  A suffix is a classification hint, not proof of a user-visible S3 bucket count.
- `--with-netbox` requires the hidden NetBox token prompt; `--without-netbox`
  explicitly skips it. Unrecognized interactive answers are retried. Summary and
  HTML distinguish a failed requested read from an intentional skip.
- NetBox records include a narrow `source_bindings` projection of `sync_identities`
  (schema/type/instance/kind/external_id only). Other custom fields remain excluded.
  Missing identity data is explicit; existing bindings are not modified/adopted.
- Review distinguishes public IPs on guest VMs from physical host identity.
  An explicit VM → Device relation suggests a host candidate requiring review.
  Private IPs without mapped network scopes are kept as separate hints. The original
  matcher result and the contextual analysis are both retained; `auto_apply` stays false.
- `--account 29916` can select a non-secret account number. Each run creates its own
  timestamped output directory. A second account still requires its own token.

Offline regression checks:

```bash
python -m unittest discover -s tools/selectel_audit -t . -p 'test_*.py' -v
```

The synthetic tests contain no production snapshots. Validation against local
operator snapshots is read-only and those snapshots must not be committed.
Online acceptance still requires a new run: check image pagination, Cinder v3,
NetBox identity export and all partial/denied scopes. Account-wide completeness
remains `not_proven`; unsupported products and hidden resources are not ruled out.

API references: [Glance v2](https://docs.openstack.org/api-ref/image/v2/),
[Cinder v3](https://docs.openstack.org/api-ref/block-storage/v3/).

