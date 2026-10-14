import {useState, type FormEvent} from 'react';

export type ProviderSchedule = {kind:'off'|'days'|'monthly'|'dates';days?:number;day?:number;start_date?:string;time?:string;timezone?:string;dates?:string[]};

export function SelectelSchedule({value, disabled, save}:{value?:ProviderSchedule;disabled:boolean;save:(value:ProviderSchedule)=>Promise<void>}){
 const [kind,setKind]=useState(value?.kind||'off');
 const [days,setDays]=useState(value?.days||1),[day,setDay]=useState(value?.day||1);
 const today=new Date();
 const localDate=[today.getFullYear(),String(today.getMonth()+1).padStart(2,'0'),String(today.getDate()).padStart(2,'0')].join('-');
 const [start,setStart]=useState(value?.start_date||localDate);
 const [time,setTime]=useState(value?.time||'03:00'),[zone,setZone]=useState(value?.timezone||'Europe/Moscow');
 const [dates,setDates]=useState(value?.dates?.join(', ')||'');
 async function submit(event:FormEvent){event.preventDefault();
  const common={kind,time,timezone:zone};
  await save(kind==='off'?{kind}:kind==='days'?{...common,days,start_date:start}:kind==='monthly'?{...common,day}:{...common,dates:dates.split(',').map(x=>x.trim()).filter(Boolean)});
 }
 return <details><summary>Расписание Selectel</summary><form onSubmit={submit}>
 <label>Периодичность<select value={kind} onChange={e=>setKind(e.target.value as ProviderSchedule['kind'])} disabled={disabled}>
 <option value="off">Вручную</option><option value="days">Каждые N дней</option><option value="monthly">Ежемесячно</option><option value="dates">Выбранные даты</option></select></label>
 {kind==='days'&&<><label>Интервал, дней<input required type="number" min={1} max={366} value={days} onChange={e=>setDays(Number(e.target.value))}/></label><label>Начиная с даты<input required type="date" value={start} onChange={e=>setStart(e.target.value)}/></label></>}
 {kind==='monthly'&&<><label>Число месяца<input required type="number" min={1} max={31} value={day} onChange={e=>setDay(Number(e.target.value))}/></label><p>Если такого числа нет, запуск состоится в последний день месяца.</p></>}
 {kind==='dates'&&<label>Даты через запятую (ГГГГ-ММ-ДД)<input required value={dates} onChange={e=>setDates(e.target.value)}/></label>}
 {kind!=='off'&&<><label>Время<input required type="time" value={time} onChange={e=>setTime(e.target.value)}/></label><label>Часовой пояс<input required value={zone} onChange={e=>setZone(e.target.value)}/></label><p>Пропущенные запуски объединяются в один. При неподтверждённом импорте автоматические запуски приостанавливаются.</p></>}
 <button disabled={disabled} type="submit">Сохранить расписание</button>
 </form></details>;
}
