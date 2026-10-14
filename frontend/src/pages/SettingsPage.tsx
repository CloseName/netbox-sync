import {Link} from 'react-router-dom';
import {usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';
export function SettingsPage(){
 const [lang]=useLanguage(),t=(en:string,ru:string)=>lang==='ru'?ru:en;
 const identity=usePermission('identity.manage'),configure=usePermission('source.configure'),bootstrap=usePermission('bootstrap.manage'),policy=usePermission('identity.manage');
 const entries=[
  ...(bootstrap?[['/settings/netbox',t('NetBox connection','Подключение NetBox'),t('Address and service access','Адрес и служебный доступ')]]:[]),
  ...(identity?[['/settings?section=directory',t('Directory and access','Каталог и доступ'),t('LDAP and permitted groups','LDAP и разрешённые группы')]]:[]),
  ...(configure?[['/settings?section=teams',t('Teams','Команды'),t('Source ownership','Принадлежность источников')]]:[]),
  ...(policy?[['/settings?section=destinations',t('Source destinations','Допустимые адреса'),t('Rules for new connections','Правила новых подключений')]]:[]),
  ['/system',t('System health','Состояние системы'),t('Services and application readiness','Службы и готовность панели')],
 ];
 return <main><h1>{t('Settings','Настройки')}</h1><p className="muted">{t('Connections, access and application services.','Подключения, доступ и службы панели.')}</p><section className="panel">{entries.map(([url,title,note])=><Link className="settings-entry" key={url} to={url}><span><strong>{title}</strong><small>{note}</small></span><span aria-hidden="true">›</span></Link>)}</section></main>;
}
