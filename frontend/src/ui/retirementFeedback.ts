/** Closed local messages; never render Guard exception or response text. */
export function retirementReason(code?: string | null): [string, string] | null {
  switch (code) {
    case 'RETIREMENT_SERVER_BUSY': return ['Waiting for the original NetBox operation. Its receipt will be checked automatically; do not start another removal.', 'Ожидаем исходную операцию NetBox. Квитанция будет проверена автоматически; не начинайте новое удаление.'];
    case 'RETIREMENT_BUDGET_EXCEEDED': return ['NetBox exceeded the removal time limit and rolled back this attempt. Check Guard diagnostics before retrying.', 'NetBox превысил лимит удаления и откатил эту попытку. Перед повтором проверьте диагностику Guard.'];
    case 'RETIREMENT_DATABASE_REFUSAL': return ['The NetBox database refused the transaction; this attempt was rolled back. Check Guard diagnostics.', 'База NetBox отклонила транзакцию; эта попытка отменена. Проверьте диагностику Guard.'];
    default: return null;
  }
}
export function retirementProgress(state?: string, code?: string | null): [string, string] {
  const reason = retirementReason(code);
  if (reason) return reason;
  switch (state) {
    case 'SUBMITTING': return ['Sending the confirmed removal request…', 'Передаём подтверждённый запрос удаления…'];
    case 'WAITING': return ['Waiting for the active operation to finish safely…', 'Ожидаем безопасного завершения текущей операции…'];
    case 'READY': return ['The removal list is ready; execution has not started.', 'Список удаления готов; выполнение ещё не началось.'];
    case 'UNCERTAIN': return ['The outcome is not confirmed. The server is checking the original receipt; do not repeat removal.', 'Результат ещё не подтверждён. Сервер проверяет исходную квитанцию; не повторяйте удаление.'];
    case 'SUCCEEDED': return ['NetBox removal is confirmed. Finishing local cleanup…', 'Удаление в NetBox подтверждено. Завершаем локальную очистку…'];
    case 'FINALIZED': return ['Source removal is complete.', 'Удаление источника завершено.'];
    default: return ['Removal is in progress on the server…', 'Удаление выполняется на сервере…'];
  }
}
