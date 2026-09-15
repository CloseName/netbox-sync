import definitions from '../../../netbox_sync/public_errors.json' with {type:'json'};
import {language} from './language.ts';
export const knownPublicError=(code:unknown):code is keyof typeof definitions=>typeof code==='string'&&Object.hasOwn(definitions,code);
export function publicError(code:unknown){
 const value=definitions[knownPublicError(code)?code:'OPERATION_FAILED'];const lang=language()==='ru'?'ru':'en';
 return {code:knownPublicError(code)?code:'OPERATION_FAILED',stage:value.stage,message:value.message[lang],action:value.action[lang]};
}
