/** Non-secret identity hints only; never manufacture a realm. */
export interface TokenIdentity {user:string;token:string;edited:boolean;parsed:boolean;}
export function updateTokenUser(previous:TokenIdentity, input:string):TokenIdentity {
  const full=/^([^\s@!]+@[^\s@!]+)!([^\s@!]+)$/.exec(input);
  if(full)return {user:full[1],token:full[2],edited:true,parsed:true};
  const user=/^([^\s@!]+)@[^\s@!]+$/.exec(input);
  return {...previous,user:input,token:previous.edited?previous.token:(user?.[1]??''),parsed:false};
}
