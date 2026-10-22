# Instructions to paste into the chat project's settings

The repository is the versioned source of rules. Project settings provide the
entry point for clients that do not automatically read repository instructions.
Upload/reference copies only as a fallback; mark their revision and refresh them.
A new chat must not treat a stale uploaded copy as the current main branch.

## Copyable project instruction

Работаем с репозиторием https://github.com/CloseName/netbox-sync.
Перед изменениями прочитай актуальный AGENTS.md в корне репозитория,
docs/development.md и нужные документы из docs/README.md. Перед командами для
серверов обязательно прочитай docs/operations/test.md или
docs/operations/production.md. Используй актуальную версию документов из
репозитория; старые отчёты и историю чата не считай текущим состоянием среды.
Если доступа к правилам нет, сообщи об этом и не угадывай команды развёртывания.

Сохраняй архитектуру, поведение и различия VM/LXC, если изменение поведения не
запрошено явно. Исправления сопровождай тестами и оформляй отдельными PR от
актуального main. Объединение и развёртывание выполняй в рамках моего разрешения;
объединённый PR сам по себе не означает разрешения обновить сервер.

Тестовая установка Sync: /netbox-sync-test на netbox-test. Для её обновления
используй проверенный deploy/update_test.py с закреплённым коммитом и резервной
копией, а не заново составленные блоки обновления через стандартный ввод.
Расписания теста не включай; учитывай отдельные расписания Selectel внутри
bootstrap-worker. Selectel остаётся экспериментальным. Прод не трогай без моего
явного разрешения, данные производственных серверов не угадывай. Не сохраняй
секреты в репозитории или чате. Различай локальные тесты, объединение PR,
установку версии и подтверждённую проверку на сервере.
