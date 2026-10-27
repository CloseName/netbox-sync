type Pending={operation:string;key?:string|null;fingerprint:string};
type Account={account:string;deleted?:boolean;connection_generation?:string;lifecycle_pending?:Pending};
type Request=(path:string,body?:unknown)=>Promise<any>;

// Deleted accounts have no card. A fresh explicit connection form performs the
// existing fenced activation; a lost response resumes only its durable intent.
export async function connectionGeneration(account:Account|undefined,request:Request){
 if(!account?.deleted)return account?.connection_generation??null;
 let plan=account.lifecycle_pending;
 if(plan&&plan.operation!=='activate')throw new Error('Удаление ещё не подтверждено. Проверьте результат операции.');
 if(!plan)plan=await request('/'+account.account+'/lifecycle-review',{operation:'activate',key:null});
 await request('/'+account.account+'/lifecycle-execute',{operation:'activate',key:null,fingerprint:plan!.fingerprint,confirmed:true});
 const fresh=await request('');
 const activated:Account|undefined=fresh.items.find((a:Account)=>a.account===account.account);
 if(!activated||activated.deleted||activated.lifecycle_pending||!activated.connection_generation){
  throw new Error('Подключение ещё не подтверждено. Обновите страницу и повторите сохранение доступа.');
 }
 return activated.connection_generation;
}
