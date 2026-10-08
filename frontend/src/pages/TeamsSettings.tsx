import {Link} from 'react-router-dom';
import {TeamEditor} from '../components/SourceTeams';
import {usePermission} from '../AuthGate';
import {useLanguage} from '../ui/language';
export function TeamsSettings(){
 const [language]=useLanguage(),admin=usePermission('identity.manage');
 return <main><h1>{language==='ru'?'Настройки — команды':'Settings — Teams'}</h1>{admin&&<Link to="/settings">{language==='ru'?'Аутентификация и доступ':'Authentication and access'}</Link>}<TeamEditor/></main>;
}
