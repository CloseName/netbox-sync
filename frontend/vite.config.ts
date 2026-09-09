import { defineConfig } from 'vite';
import {createHash} from 'node:crypto';
import {readFileSync,readdirSync} from 'node:fs';
import path from 'node:path';
// Content identity, not a claim that the checkout is a committed release.
const hash=createHash('sha256');
for(const root of ['src','public'])for(const file of readdirSync(root,{recursive:true}).map(String).sort()){
 try {const bytes=readFileSync(path.join(root,file));hash.update(root+'/'+file+'\0');hash.update(bytes);} catch(error){if(error.code!=='EISDIR')throw error;}
}
for(const file of ['index.html','package-lock.json','vite.config.ts'])hash.update(readFileSync(file));
const buildId='ui-'+hash.digest('hex').slice(0,16);
export default defineConfig({
 define:{__UI_BUILD_ID__:JSON.stringify(buildId)},
 plugins:[{name:'ui-build-identity',transformIndexHtml:()=>[{tag:'meta',attrs:{name:'netbox-sync-ui-build',content:buildId},injectTo:'head'}]}],
 server: {host:'127.0.0.1',strictPort:true,proxy:{'/api':{target:'http://127.0.0.1:8000'}}},
});
