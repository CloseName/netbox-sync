import { useSyncExternalStore } from 'react';
export type Language = 'en' | 'ru';
export const languageKey = 'netbox-sync.language';
function initial(): Language {
 try { const value=localStorage.getItem(languageKey); if(value==='en'||value==='ru')return value; } catch { /* optional storage */ }
 return typeof window!=='undefined' && typeof navigator!=='undefined' && navigator.language.startsWith('ru') ? 'ru' : 'en';
}
let current=initial();
const listeners=new Set<()=>void>();
export function language(){ return current; }
export function setLanguage(value:Language){
 current=value; if(typeof document!=='undefined')document.documentElement.lang=value;
 try { localStorage.setItem(languageKey,value); } catch { /* works in memory */ }
 listeners.forEach(listener=>listener());
}
function subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener);};}
export function useLanguage(){return [useSyncExternalStore(subscribe,language,()=> 'en' as Language),setLanguage] as const;}
if(typeof window!=='undefined'){
 document.documentElement.lang=current;
 window.addEventListener('storage',event=>{if(event.key===languageKey||event.key===null){current=initial();document.documentElement.lang=current;listeners.forEach(listener=>listener());}});
}
