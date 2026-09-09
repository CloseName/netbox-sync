import {language} from './language.ts';
import {ru} from './ru.ts';
/** Source-authored UI messages only. Never use this on provider/user values. */
export function tr(message:string){return language()==='ru' && Object.hasOwn(ru,message) ? ru[message] : message.replaceAll('&quot;','"');}
