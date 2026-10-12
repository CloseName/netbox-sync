# Selectel bindings: тестовый этап Guard

Работать только на netbox-test, NetBox root `/netbox-test`. Этот этап обновляет
Guard и его схему; основной Sync UI и планировщик Selectel пока не подключены.
Production не обновлять. Бэкап в тестовый процесс не добавляется по запросу пользователя.

## Что устанавливается

- Миграции 0006/0007: привязки, закреплённые значения полей, журнал и SQL-триггеры.
- Post-migrate создаёт selectel_refs (JSON) и selectel_summary (text) для
  Device/VirtualMachine. При повторе сохраняются IDs; при несовместимой схеме
  подготовка останавливается, существующие поля не переконфигурируются.
- Провайдерская сводка отображается стандартным NetBox в группе Selectel.
  Подробные refs скрыты; отдельная страница управления привязками в Sync ещё не готова.
- SQL запрещает перезапись закреплённых значений, подделку проекции и удаление
  связанного объекта. Обновление незакреплённых полей продолжает работать.

Проверить до обновления: CI `Selectel Guard integration` должен успешно пройти
именно для устанавливаемого commit. Образ должен включать весь каталог Guard;
миграции выполняются штатным запуском NetBox. Одна публикация кода не обновляет сервер.
Не откатывать эти миграции после принятия реальных связей без отдельного плана:
откат удаляет таблицы связей и защиту.

## Принятие связи

Это административная операция, не доказательство совпадения из IP/имени. Сначала
проверить конкретную пару в отчёте аудита, затем записать JSON spec без credentials.
Вычислить SHA256 использованного файла evidence и указать его в evidence_digest.
Не использовать примерные UUID или тестовые объекты для реальной привязки.

Формат spec:

```json
{
  "resource": "device",
  "object_id": 123,
  "identity": {
    "account": "ACCOUNT_NUMBER",
    "kind": "dedicated",
    "native_id": "RESOURCE_UUID",
    "project": "PROJECT_ID_OR_EMPTY",
    "region": "REGION_OR_EMPTY"
  },
  "serial": null,
  "reason": "Подтверждена пара по отчёту и данным гипервизора",
  "evidence_digest": "SHA256_OF_REVIEWED_EVIDENCE_FILE"
}
```

Для cloud VM: resource=vm, kind=cloud_vm, обязательны project и region.
Для dedicated project и region могут быть пустыми и не входят в стабильный ключ.
`serial=null` сохраняет текущий serial и не снимает существующий claim. Значение
serial передавать только при явной передаче этого поля Selectel и проверенных
аппаратных данных. Site, name, management IP, cluster и sync_identities здесь
изменить невозможно. Provider metadata не означает новую hypervisor identity.

Предпросмотр в контейнере NetBox (файл spec должен быть предварительно скопирован
туда оператором; `--actor` — существующий пользователь):

```bash
docker exec netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py \
  provider_binding --actor ADMIN_USERNAME --request /tmp/selectel-binding.json
```

Он возвращает target/name, старые значения, proposed_claims и fingerprint.
После проверки повторить команду с `--apply --fingerprint REVIEW_FINGERPRINT
--nonce NEW_UUID`. При сетевом обрыве повторять с тем же nonce и теми же параметрами.
Новый fingerprint после изменения объекта требует нового review; старый не применяется.
Для изменения данных уже принятой связи нужен новый review и новый nonce.

API эквиваленты (относительно Guard API): POST providers/review/ с `{spec}` и
POST providers/apply/ с `{nonce,spec,fingerprint}`. Нужны namespace header,
write-enabled token, manage_providerbinding и view/change права на target.
Обычным scheduled apply пользователям новая административная permission не выдаётся.

## Приёмка

1. Проверить автоматическое появление двух custom fields и повторный migrate.
2. На отдельном тестовом объекте принять связь: ID, created и прежние identities
   остаются прежними; новые связь, claims и запись журнала появляются вместе.
3. Повтор того же запроса/nonce не создаёт дубликатов.
4. Изменение объекта между review/apply даёт отказ; новый review учитывает изменения.
5. Обычный API/bulk/ORM не меняет claimed serial/проекцию и не удаляет bound object.
6. Изменение обычного не закреплённого поля разрешено; штатный цикл ESXi/Proxmox
   сохраняет провайдерские custom fields. Конфликт сообщает отказ, а не принимает
   значения и не запускает бесконечные повторы.
7. Второй аккаунт/ресурс не присваивает target; один provider key не связан с двумя
   объектами. Все несвязанные объекты остаются без Selectel-владения.

Автоматический изолированный сценарий использует временную PostgreSQL БД
`netbox_sync_guard_test` и NetBox 4.7; он запрещён вне специального harness.
Он не предназначен для запуска в shell работающего test/prod NetBox.
