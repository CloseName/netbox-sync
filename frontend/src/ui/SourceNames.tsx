import {createContext,useContext,type ReactNode} from 'react';
import {fetchSources,type Source} from '../api/sources';
import {useResource} from './useResource';
const Sources=createContext<Source[]>([]);
export function SourceNames({children}:{children:ReactNode}){const data=useResource(fetchSources);return <Sources.Provider value={data.data??[]}>{children}</Sources.Provider>;}
export function useSourceNames(){return useContext(Sources);}
export function SourceName({id}:{id:string}){const source=useSourceNames().find(s=>s.source_instance===id);return <span title={id}>{source?.name??id}</span>;}
