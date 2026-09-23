import {useState} from 'react';
import {Lookup} from './CatalogLookup';
import type {CatalogItem,HostPreview} from '../api/onboarding';
export interface NetworkScopeRule {host_id:string;bridge:string;vlan_id:number|null;vrf:CatalogItem;}
export function NetworkScopeEditor({hosts,rules,onChange,readOnly,language}:{hosts:HostPreview[];rules:NetworkScopeRule[];onChange:(value:NetworkScopeRule[])=>void;readOnly:boolean;language:string}){
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 const [host,setHost]=useState(hosts[0]?.id??''),[bridge,setBridge]=useState(''),[vlan,setVlan]=useState(''),[vrf,setVrf]=useState<CatalogItem>();
 const vlanId=vlan===''?null:Number(vlan);
 const valid=!!host&&!!bridge&&bridge.length<=200&&!!vrf&&(vlanId===null||Number.isInteger(vlanId)&&vlanId>=0&&vlanId<=4094)&&!rules.some(r=>r.host_id===host&&r.bridge===bridge&&r.vlan_id===vlanId)&&rules.length<128;
 return <section className="source-panel"><h3>{t('IP network scopes','Сетевые области IP')}</h3>
 <p>{t('No rule means the global routing table. Use an existing VRF only when it represents a real isolated network. Network labels alone do not prove isolation.','Без правила используется глобальная таблица маршрутизации. Выбирайте существующую VRF только для реальной изолированной сети. Одного названия сети недостаточно для доказательства изоляции.')}</p>
 <p>{t('Changing a rule never moves or deletes existing IP assignments. Conflicting addresses require review.','Изменение правила не переносит и не удаляет существующие назначения IP. Противоречащие адреса потребуют проверки.')}</p>
 {rules.length===0?<p>{t('No explicit rules','Явных правил нет')}</p>:<ul>{rules.map((r,index)=><li key={JSON.stringify([r.host_id,r.bridge,r.vlan_id])}>{hosts.find(h=>h.id===r.host_id)?.name||r.host_id} · {r.bridge} · VLAN {r.vlan_id??t('none','нет')} → {r.vrf.name} (VRF #{r.vrf.id}) {!readOnly&&<button type="button" onClick={()=>onChange(rules.filter((_,i)=>i!==index))}>{t('Remove rule','Убрать правило')}</button>}</li>)}</ul>}
 {!readOnly&&<details><summary>{t('Add a network scope rule','Добавить правило сетевой области')}</summary><div className="form-grid">
 <label>{t('Provider host','Хост провайдера')}<select value={host} onChange={e=>setHost(e.target.value)}>{hosts.map(h=><option key={h.id} value={h.id}>{h.name||h.id}</option>)}</select></label>
 <label>{t('Exact network / bridge name from Discovery','Точное имя сети / моста из Discovery')}<input value={bridge} maxLength={200} onChange={e=>setBridge(e.target.value)}/></label>
 <label>VLAN<input type="number" min={0} max={4094} value={vlan} onChange={e=>setVlan(e.target.value)}/><small>{t('Leave empty only if Discovery has no VLAN.','Оставьте пустым, только если VLAN отсутствует в Discovery.')}</small></label>
 <Lookup kind="vrf" label="VRF" language={language} value={vrf} change={setVrf}/></div>
 <button type="button" disabled={!valid} onClick={()=>{if(valid&&vrf){onChange([...rules,{host_id:host,bridge,vlan_id:vlanId,vrf}]);setBridge('');setVrf(undefined);}}}>{t('Add to reviewed changes','Добавить к проверяемым изменениям')}</button></details>}
 </section>;
}
