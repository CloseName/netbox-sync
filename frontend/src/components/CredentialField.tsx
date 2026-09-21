import {useId,useState,type InputHTMLAttributes} from 'react';
import {useLanguage} from '../ui/language';
type Props=InputHTMLAttributes<HTMLInputElement>&{label:string;secret?:boolean;visible?:boolean;onVisibilityChange?:(visible:boolean)=>void};
/** Native named input: values and autocomplete remain owned by the form/browser. */
export function CredentialField({label,secret=false,visible,onVisibilityChange,id,...input}:Props){
 const generated=useId(),[localVisible,setLocalVisible]=useState(false),[language]=useLanguage();
 const shown=visible??localVisible,inputId=id??generated;
 const toggle=()=>{if(onVisibilityChange)onVisibilityChange(!shown);else setLocalVisible(!shown);};
 const text=language==='ru'?(shown?'Скрыть пароль':'Показать пароль'):(shown?'Hide password':'Show password');
 return <div className={'credential-field'+(secret?' has-secret':'')}>
  <input {...input} id={inputId} placeholder=" " type={secret?(shown?'text':'password'):(input.type??'text')}/>
  <label htmlFor={inputId}>{label}</label>
  {secret&&<button className="credential-eye" type="button" aria-label={text} aria-pressed={shown} onClick={toggle} aria-describedby={inputId+'-tip'}>
   <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>{shown&&<path d="m3 3 18 18"/>}</svg>
   <span role="tooltip" id={inputId+'-tip'}>{text}</span>
  </button>}
 </div>;
}
