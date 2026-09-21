import {useState} from 'react';
type Failure={id:string;message:string};
export function useFormValidation(language:string){
 const [errors,setErrors]=useState<Failure[]>([]);
 function validate(form:HTMLFormElement){
  form.querySelectorAll('[data-field-error]').forEach(node=>node.remove());
  const failures:Failure[]=[];
  const controls=Array.from(form.elements).filter((node):node is HTMLInputElement|HTMLSelectElement=>node instanceof HTMLInputElement||node instanceof HTMLSelectElement);
  for(const [index,input] of controls.entries()){
   input.removeAttribute('aria-invalid');
   input.setAttribute('aria-describedby',(input.getAttribute('aria-describedby')||'').split(' ').filter(x=>x&&!x.endsWith('-error')).join(' '));
   if(!input.willValidate||input.validity.valid)continue;
   input.id ||= 'required-field-'+index;
   const label=(input.labels?.[0]?.textContent||input.name||'').trim().replace(/\s+/g,' ');
   const message=input.validity.valueMissing?(language==='ru'?'Заполните поле «'+label+'».':'Enter '+label+'.'):(language==='ru'?'Проверьте значение поля «'+label+'».':'Check '+label+'.');
   failures.push({id:input.id,message});input.setAttribute('aria-invalid','true');
   const hint=document.createElement('p');hint.dataset.fieldError='true';hint.id=input.id+'-error';hint.className='field-error';hint.textContent=message;
   (input.closest('.credential-field')||input.closest('label')||input).insertAdjacentElement('afterend',hint);
   input.setAttribute('aria-describedby',Array.from(new Set([...(input.getAttribute('aria-describedby')||'').split(' ').filter(x=>x&&!x.endsWith('-error')),hint.id])).join(' '));
  }
  setErrors(failures);
  if(failures.length)requestAnimationFrame(()=>document.getElementById('form-error-summary')?.focus());
  return !failures.length;
 }
 const summary=errors.length?<section id="form-error-summary" tabIndex={-1} role="alert" className="source-error"><h2>{language==='ru'?'Проверьте поля':'Check your entries'}</h2><ul>{errors.map(error=><li key={error.id}><a href={'#'+error.id} onClick={e=>{e.preventDefault();document.getElementById(error.id)?.focus();}}>{error.message}</a></li>)}</ul></section>:null;
 return {validate,summary};
}
