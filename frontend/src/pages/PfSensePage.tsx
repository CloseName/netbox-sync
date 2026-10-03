import {useState} from 'react';
import {fetchPfSense} from '../api/pfsense';
import {useResource} from '../ui/useResource';
import {useLanguage} from '../ui/language';
export function PfSensePage(){
 const resource=useResource(fetchPfSense),[q,setQ]=useState(''),[language]=useLanguage();
 const t=(en:string,ru:string)=>language==='ru'?ru:en;
 return <main><h1>pfSense ({resource.data?.count??'…'})</h1><p>{t('Virtual machines whose name contains pfsense, regardless of letter case. Select the correct cluster before connecting.','Виртуальные машины, имя которых содержит pfsense без учёта регистра. Перед подключением проверьте кластер.')}</p>
 <button onClick={resource.refresh}>{t('Refresh','Обновить')}</button>
 <label>{t('Search','Поиск')}<input value={q} onChange={e=>setQ(e.target.value)}/></label>
 {resource.error&&<p role="alert">{t('List unavailable. Retry refresh.','Список недоступен. Повторите обновление.')}</p>}
 <div className="scroll-region"><table><thead><tr><th>{t('VM','ВМ')}</th><th>{t('Cluster','Кластер')}</th><th>{t('Site','Площадка')}</th><th>{t('Address','Адрес')}</th><th>{t('Synchronization','Синхронизация')}</th></tr></thead><tbody>
 {resource.data?.items.filter(vm=>(vm.name+' '+vm.cluster+' '+vm.site).toLowerCase().includes(q.toLowerCase())).map(vm=><tr key={vm.id}><td><a href={vm.url} target="_blank" rel="noreferrer">{vm.name}</a> (#{vm.id})</td><td>{vm.cluster}</td><td>{vm.site}</td><td>{vm.address||'—'}</td><td><PfSenseConnect vm={vm}/></td></tr>)}
 </tbody></table></div>{resource.data?.count===0&&<p>{t('No matching virtual machines.','Подходящих виртуальных машин нет.')}</p>}</main>;
}
import {PfSenseConnect} from '../components/PfSenseConnect';
