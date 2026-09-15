import {language} from './language.ts';
const t = (en:string, ru:string) => language()==='ru'?ru:en;
export function staleReason(reason?: string) {
  const labels: Record<string, [string,string]> = {
    OPERATION_MISSING:['The reviewed operation is missing.','Проверяемая операция отсутствует.'],
    OPERATION_VERSION:['A newer plan replaced this operation.','Эту операцию заменил новый план.'],
    OPERATION_EXPIRED:['The plan retention period ended.','Срок хранения плана истёк.'],
    OPERATION_STATUS:['This operation is no longer ready for confirmation.','Эта операция больше не готова к подтверждению.'],
    RESULT_MISSING:['The saved plan is unavailable.','Сохранённый план недоступен.'],
    REVIEW_DIGEST:['The submitted digest does not match the saved plan.','Подтверждается другой сохранённый план.'],
    PLANNER_VERSION:['The planner version changed.','Версия планировщика изменилась.'],
    PLAN_DIGEST:['Repeated reading produced a different plan.','Повторное чтение сформировало другой план.'],
    PLAN_FORBIDDEN:['Safety checks now block the plan.','Проверки безопасности теперь запрещают этот план.'],
    SOURCE_IDENTITY:['The source identity changed.','Идентичность источника изменилась.'],
  };
  const pair = labels[reason ?? ''];
  return pair ? t(...pair) : t('The reviewed plan is no longer valid.','Проверенный план больше не действителен.');
}
