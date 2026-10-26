const reasons:Record<string,string> = {
 PROVIDER_COMPLETE_NETBOX_VISIBILITY_REQUIRED:'Импортёр не видит все необходимые объекты NetBox. Проверьте ограничения прав просмотра.',
 PROVIDER_NATIVE_SCOPE_CONFLICT:'Ресурс конфликтует с областью размещения или владения существующей карточки.',
 PROVIDER_PLACEMENT_IDENTITY_REQUIRED:'Недостаточно данных для определения размещения ресурса.',
 PROVIDER_IDENTITY_INVALID:'Идентификатор ресурса не прошёл проверку.',
 DATABASE_CONSTRAINT:'NetBox отклонил запись из-за ограничения базы данных.',
 OBJECT_VALIDATION:'Поля объекта не прошли проверку NetBox.',
 INPUT_OR_POLICY_REJECTED:'Данные импорта или правила сопоставления не прошли проверку.',
 INPUT_SHAPE_INVALID:'Структура данных не соответствует ожидаемой схеме импорта.',
 POLICY_REJECTED:'Запись запрещена правилами защиты объектов.',
 PERMISSION_DENIED:'У импортёра недостаточно прав.',
 PROVIDER_NATIVE_PERMISSIONS_REQUIRED:'Не хватает прав для создания ресурсов Selectel.',
 PROVIDER_ACCOUNT_MISMATCH:'Аккаунт в данных не совпадает с аккаунтом запроса.',
 PROVIDER_NONCE_CONFLICT:'Идентификатор запуска уже связан с другим запросом.',
 PROVIDER_ACCOUNT_DELETED:'Аккаунт ранее удалён; импорт запрещён.',
 PROVIDER_HISTORICAL_RUN_RETIRED:'Старый запуск закрыт для повторной записи.',
 PROVIDER_REVIEW_STALE:'Данные изменились после проверки.',
 PROVIDER_FIELD_OWNED:'Поле принадлежит другому источнику данных.',
 PROVIDER_PROJECTION_UNCLAIMED:'Нет подтверждённого права обновлять поле ресурса.',
 PROVIDER_IPAM_FIELD_OWNED:'Сетевое поле защищено другим источником данных.',
};
export function selectelImportReason(code?:string):string {
 return code?reasons[code]||'Guard отклонил импорт; подробная причина не установлена.':'Причина не уточнена.';
}
