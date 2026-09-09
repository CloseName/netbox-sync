import { useState } from 'react';
export type Language = 'en' | 'ru';
export const pveCommands = [
 'pveversion',
 'pveum user add netbox-sync@pve',
 'pveum role add NetBoxSyncRead --privs "Sys.Audit VM.Audit Datastore.Audit"',
 'pveum acl modify / --users netbox-sync@pve --roles NetBoxSyncRead --propagate 1',
 'pveum user token add netbox-sync@pve netbox-sync --privsep 1',
 "pveum acl modify / --tokens 'netbox-sync@pve!netbox-sync' --roles NetBoxSyncRead --propagate 1",
 'pveum user token permissions netbox-sync@pve netbox-sync',
];
const agentCommand = 'pveum role modify NetBoxSyncRead --privs "Sys.Audit VM.Audit Datastore.Audit VM.GuestAgent.Audit"';
const steps = {
 proxmox: [
  ['As an authorized operator, open Datacenter → Permissions → Users → Add. Create netbox-sync in the pve realm (Proxmox VE authentication server): netbox-sync@pve. The pam realm instead refers to an existing Linux account.', 'С правами управления пользователями откройте Datacenter → Permissions → Users → Add. Создайте netbox-sync в realm pve (Proxmox VE authentication server): netbox-sync@pve. Realm pam относится к существующему пользователю Linux.'],
  ['In Permissions → Roles create NetBoxSyncRead with Sys.Audit, VM.Audit and Datastore.Audit. Add User Permission at / with propagation. This covers the cluster inventory; narrower ACL scope intentionally reduces discovery coverage.', 'В Permissions → Roles создайте NetBoxSyncRead с Sys.Audit, VM.Audit и Datastore.Audit. Добавьте User Permission на / с наследованием. Это чтение inventory кластера; более узкие ACL ограничивают охват discovery.'],
  ['Open Permissions → API Tokens → Add. Select netbox-sync@pve, token name netbox-sync, and keep Privilege Separation enabled. Choose expiration by policy. Save the secret securely when issued: it is shown only once.', 'Откройте Permissions → API Tokens → Add. Выберите netbox-sync@pve, имя токена netbox-sync и оставьте Privilege Separation включённым. Выберите срок действия по политике. При выдаче сохраните secret безопасно: он показывается только один раз.'],
  ['Add Token Permission for netbox-sync@pve!netbox-sync using the same role, path and propagation. Effective permissions are the intersection of user and token rights; configuring only one side is insufficient.', 'Добавьте Token Permission для netbox-sync@pve!netbox-sync с той же ролью, путём и наследованием. Итоговые права — пересечение прав пользователя и токена; назначения только одной стороне недостаточно.'],
  ['Token user = netbox-sync@pve; Token name = netbox-sync; Token secret = the separately saved issued value. Do not paste user@realm!token into Token name.', 'Token user = netbox-sync@pve; Token name = netbox-sync; Token secret = отдельно сохранённое при выдаче значение. Не вставляйте user@realm!token в Token name.'],
 ],
 esxi: [
  ['In the standalone Host Client, sign in as an operator authorized to manage users and permissions. Open Manage → Security & users → Users → Add user. Create local user netbox-sync with a separate strong password.', 'В Host Client отдельного ESXi войдите с правами управления пользователями и разрешениями. Откройте Manage → Security & users → Users → Add user. Создайте локального пользователя netbox-sync с отдельным надёжным паролем.'],
  ['Right-click Host → Permissions → Add user. Select that user, Read-only and Propagate to all children. The adapter reads host, VM, device, guest-network and datastore properties; these operations do not require Administrator or root.', 'Нажмите правой кнопкой Host → Permissions → Add user. Выберите пользователя, Read-only и Propagate to all children. Адаптер читает свойства хоста, VM, устройств, гостевых сетей и хранилищ; эти операции не требуют Administrator или root.'],
  ['Username = netbox-sync, the local account name. Password = its password on this host. Do not use Proxmox realm suffixes or vCenter credentials.', 'Username = netbox-sync — имя локального пользователя. Password = его пароль на этом хосте. Не добавляйте realm Proxmox и не используйте учётные данные vCenter.'],
  ['If lockdown blocks direct API login, ask the security administrator whether this Read-only service account may be an Exception User. Keep lockdown enabled. If exceptions are forbidden, this direct-host integration cannot be used.', 'Если lockdown запрещает прямой вход в API, согласуйте с администратором безопасности добавление сервисного пользователя Read-only в Exception Users. Не отключайте lockdown. Если исключения запрещены, прямое подключение к хосту использовать нельзя.'],
  ['Repository compatibility baseline: standalone ESXi 6.7 build 20497097. Other versions, including 7/8, need separate acceptance; this guidance does not certify them. No new live hypervisor validation was performed.', 'Базовая совместимость репозитория: отдельный ESXi 6.7 build 20497097. Другие версии, включая 7/8, требуют отдельной приёмки; эта инструкция не подтверждает их поддержку. Новых проверок на живом гипервизоре не проводилось.'],
 ],
};
function Command({value, language}: {value: string; language: Language}) {
 const [status, setStatus] = useState('');
 return <div className="access-command"><pre><code>{value}</code></pre><button type="button" onClick={async () => { try { await navigator.clipboard.writeText(value); setStatus(language === 'ru' ? 'Скопировано' : 'Copied'); } catch { setStatus(language === 'ru' ? 'Скопируйте команду вручную' : 'Copy the command manually'); } }}>{language === 'ru' ? 'Копировать' : 'Copy'}</button><span role="status">{status}</span></div>;
}
export function SourceAccessHelp({provider, language}: {provider: 'proxmox' | 'esxi'; language: Language}) {
 const t = (en: string, ru: string) => language === 'ru' ? ru : en;
 return <details className="source-access-help" lang={language}>
  <summary>{t('How to prepare access', 'Как подготовить доступ')}</summary>
  <p>{t('Use netbox-sync as a consistent service username and Proxmox token name. These are examples; existing names work. The same name does not mean a shared password or token secret: issue separate credentials for each independent source.', 'Рекомендуем единое имя пользователя netbox-sync и такое же имя токена Proxmox. Это примеры: существующие имена поддерживаются. Одинаковое имя не означает общий пароль или token secret: создайте отдельные данные доступа для каждого независимого источника.')}</p>
  <ol>{steps[provider].map((step, index) => <li key={index}>{step[language === 'ru' ? 1 : 0]}</li>)}</ol>
  {provider === 'proxmox' && <>
   <p className="access-notice">{t('Guest IP discovery also calls QEMU agent network-get-interfaces. If your installed version supports VM.GuestAgent.Audit, add it to the shared user/token role. Older versions need broader VM.Monitor: do not grant it by default. Without approved guest-agent rights, guest IP inventory may be incomplete even after a successful connection test.', 'Для гостевых IP также вызывается QEMU agent network-get-interfaces. Если установленная версия поддерживает VM.GuestAgent.Audit, добавьте его в общую роль пользователя и токена. Старые версии требуют более широкое VM.Monitor: не выдавайте его по умолчанию. Без согласованных прав guest agent данные гостевых IP могут быть неполными даже при успешной проверке подключения.')}</p>
   <details><summary>{t('Proxmox CLI commands', 'Команды Proxmox CLI')}</summary>
    <p>{t('Run on Proxmox as an authorized operator. Review existing names, roles and scope first; stop on errors. Do not record token-creation output in logs.', 'Выполняйте на Proxmox с разрешёнными правами. Сначала проверьте существующие имена, роли и область доступа; при ошибке остановитесь. Не записывайте вывод создания токена в логи.')}</p>
    {pveCommands.map((value, index) => <div key={value}>{index === 4 && <p className="access-notice">{t('The next command issues the one-time secret. Save it privately now; it cannot be retrieved later.', 'Следующая команда выдаёт однократно показываемый secret. Сохраните его безопасно сразу: повторно получить его нельзя.')}</p>}<Command value={value} language={language}/></div>)}
    <p>{t('Only if the installed API supports VM.GuestAgent.Audit; this replaces the dedicated role privilege list:', 'Только если API установленной версии поддерживает VM.GuestAgent.Audit; команда заменяет список прав выделенной роли:')}</p>
    <Command value={agentCommand} language={language}/>
   </details>
  </>}
  <p>{t('Test Connection checks access, not complete discovery permissions. After registration run Discovery and review actual coverage before enabling synchronization.', 'Проверка подключения не доказывает полноту прав discovery. После регистрации запустите Discovery и проверьте фактический охват перед включением синхронизации.')}</p>
  <a href="https://github.com/CloseName/netbox-sync/blob/main/docs/source-access.md" target="_blank" rel="noreferrer">{t('Permission mapping and official references', 'Операции, права и официальные источники')}</a>
 </details>;
}
