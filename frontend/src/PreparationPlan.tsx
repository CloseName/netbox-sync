import {useState} from 'react';
export type Language = 'en'|'ru';
export type PreparationField = {name:string;type:string;models:string[];status:string;differences:string[];
  mismatch_details?:{property:string;expected:string;actual:string}[];
  label:Record<Language,string>;purpose:Record<Language,string>};

export function PreparationPlan({fields,language}:{fields:PreparationField[];language:Language}) {
  const [expanded,setExpanded]=useState(false);
  const t=(en:string,ru:string)=>language==='ru'?ru:en;
  const titles:Record<string,string>={ready:t('Ready','Готово'),missing:t('Will be created','Будет создано'),
    conflict:t('Conflicts — resolve in NetBox','Конфликты — исправьте в NetBox'),provisioning:t('Waiting for NetBox','Ожидаем завершения в NetBox')};
  const models:Record<string,string>={'dcim.device':t('Devices','Устройства'),'dcim.interface':t('Device interfaces','Интерфейсы устройств'),
    'virtualization.virtualmachine':t('Virtual machines','Виртуальные машины'),'virtualization.vminterface':t('VM interfaces','Интерфейсы виртуальных машин')};
  const properties:Record<string,string>={type:t('Type','Тип'),models:t('Object types','Типы объектов'),required:t('Required','Обязательное поле'),
    unique:t('Unique','Уникальность'),duplicate:t('Definitions with this key','Определений с этим ключом'),lifecycle:t('State','Состояние'),
    validation_minimum:t('Minimum','Минимум'),validation_maximum:t('Maximum','Максимум'),validation_regex:t('Validation pattern','Шаблон проверки'),validation_schema:t('Validation schema','Схема проверки')};
  const values:Record<string,string>={json:'JSON',text:t('Text','Текст'),integer:t('Integer','Целое число'),boolean:t('Boolean','Логическое значение'),
    false:t('No','Нет'),true:t('Yes','Да'),none:t('None','Нет'),configured:t('Configured','Задано'),unrecognized:t('Unrecognized','Не распознано'),
    active:t('Active','Активно'),deleting:t('Deleting','Удаляется')};
  const value=(raw:string)=>raw.split(', ').map(v=>values[v]??models[v]??v).join(', ');
  const items=(subset:PreparationField[]) => <ul className="setup-fields">{subset.map(f=><li key={f.name} data-field={f.name}>
    <div><strong>{f.label[language]}</strong><span>{value(f.type)}</span></div>
    <p>{f.purpose[language]}</p><p className="setup-field-models">{f.models.map(m=>models[m]??m).join(', ')}</p>
    {f.status==='conflict'&&<div className="setup-field-conflict">
      {f.mismatch_details?.length?f.mismatch_details.map(d=><p key={d.property}><strong>{properties[d.property]??t('Requirement','Требование')}:</strong>{' '}
        {t('expected','ожидается')} {value(d.expected)}, {t('found','фактически:')} {value(d.actual)}</p>):<p>{t('Refresh the plan to see current differences.','Обновите план, чтобы увидеть актуальные различия.')}</p>}
    </div>}
    <details><summary>{t('Technical details','Технические подробности')}</summary><code>{f.name}</code></details>
  </li>)}</ul>;
  const subset=(status:string)=>fields.filter(f=>f.status===status);
  return <div className="setup-plan">
    <p className="setup-plan-counts" role="status">{t('Ready','Готово')}: {subset('ready').length} · {t('To create','Будет создано')}: {subset('missing').length} · {t('Conflicts','Конфликты')}: {subset('conflict').length}
      {subset('provisioning').length>0&&<> · {subset('provisioning').length} {t('pending','в подготовке')}</>}</p>
    {['conflict','provisioning'].map(status=>subset(status).length>0&&<section className="setup-plan-blocker" key={status} aria-label={titles[status]}>
      <h3>! {titles[status]} ({subset(status).length})</h3>{items(subset(status))}</section>)}
    <button type="button" onClick={()=>setExpanded(!expanded)}>{expanded?t('Collapse field lists','Свернуть списки полей'):t('Review all field details','Просмотреть все поля плана')}</button>
    {['missing','ready'].map(status=>subset(status).length>0&&<details className="setup-plan-group" key={status} open={expanded}>
      <summary>{titles[status]} ({subset(status).length})</summary>{items(subset(status))}</details>)}
    <p>{t('Expand the lists to review every field, its type and object scope before confirming.','Перед подтверждением раскройте списки и проверьте каждое поле, его тип и область применения.')}</p>
  </div>;
}
