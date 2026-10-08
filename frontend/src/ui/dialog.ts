import type {MouseEvent} from 'react';
export function closeOnBackdrop(event:MouseEvent<HTMLDialogElement>){
 if(event.target!==event.currentTarget)return;
 const box=event.currentTarget.getBoundingClientRect();
 if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)event.currentTarget.close();
}
