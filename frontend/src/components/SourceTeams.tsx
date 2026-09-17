import {useState} from 'react';
import {authRequest,usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';
import {useResource} from '../ui/useResource';
export type Teams={version:1;revision:number;teams:Record<string,{id:string;name:string}>;assignments:Record<string,string>};
async function fetchTeams():Promise<Teams>{const value=await authRequest('teams');if(value.version!==1||!Number.isInteger(value.revision)||!value.teams||!value.assignments)throw Error('Invalid teams');return value;}
export function useTeams(){return useResource(fetchTeams);}
export function TeamEditor({source}:{source?:string}){
 const data=useTeams(),canEdit=usePermission('source.configure');const [language]=useLanguage(),t=(en:string,ru:string)=>language==='ru'?ru:en;
 const [name,setName]=useState(''),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 async function save(operation:string,values:Record<string,unknown>){if(busy||!data.data||error)return;setBusy(true);try{await authRequest('teams',{operation,revision:data.data.revision,...values});data.refresh();setName('');}catch{setError(t('Change not confirmed or another administrator changed teams. Reload before retrying.','Изменение не подтверждено или команды изменены другим администратором. Обновите перед повтором.'));}finally{setBusy(false);}}
 const options=Object.values(data.data?.teams??{}).sort((a,b)=>a.name.localeCompare(b.name));
 return <section className="source-panel"><h3>{t('Responsible team','Ответственная команда')}</h3><p className="muted">{t('Ownership only: access roles and LDAP groups do not change. No notifications are sent.','Только принадлежность: роли доступа и группы LDAP не меняются. Уведомления не отправляются.')}</p>
 {data.loading&&!data.data&&<p role="status">{t('Loading teams…','Загрузка команд…')}</p>}{data.error&&<p role="alert">{t('Teams unavailable','Команды недоступны')}</p>}{error&&<p role="alert">{error}</p>}
 <button type="button" disabled={busy} onClick={()=>{setError('');data.refresh();}}>{t('Reload teams','Обновить команды')}</button>
 {source&&data.data&&<label>{t('Assigned team','Назначенная команда')}<select disabled={!canEdit||busy||!!error} value={data.data.assignments[source]??''} onChange={e=>void save('assign',{source_instance:source,team_id:e.target.value||null})}><option value="">{t('No team','Без команды')}</option>{options.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>}
 {canEdit&&data.data&&<details><summary>{t('Manage teams','Управление командами')}</summary><fieldset disabled={busy||!!error}><label>{t('Team to rename','Команда для переименования')}<select value={selected} onChange={e=>{setSelected(e.target.value);setName(data.data?.teams[e.target.value]?.name??'');}}><option value="">{t('New team','Новая команда')}</option>{options.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label>{t('Team name','Название команды')}<input maxLength={80} value={name} onChange={e=>setName(e.target.value)}/></label><button type="button" disabled={!name.trim()} onClick={()=>void save(selected?'rename':'create',{name,...(selected?{team_id:selected}:{})})}>{selected?t('Rename team','Переименовать команду'):t('Create team','Создать команду')}</button></fieldset></details>}
 </section>;
}
