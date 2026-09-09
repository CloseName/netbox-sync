// Inventory of source-authored JSX copy; never inspects or translates provider data.
import ts from 'typescript';
import fs from 'node:fs';
import path from 'node:path';
export function entries(file){
 const source=fs.readFileSync(file,'utf8'), tree=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX), found=[];
 const add=(node,text,kind)=>{if(/[A-Za-z]/.test(text))found.push({start:node.getStart(tree),end:node.end,text,kind});};
 function outputs(node){
  if(ts.isStringLiteral(node))add(node,node.text,'expression');
  else if(ts.isParenthesizedExpression(node))outputs(node.expression);
  else if(ts.isConditionalExpression(node)){outputs(node.whenTrue);outputs(node.whenFalse);}
 }
 function visit(node){
  if(ts.isJsxText(node)){const text=node.text.replace(/\s+/g,' ').trim();if(text)add(node,text,'text');}
  if(ts.isJsxAttribute(node)&&['title','description','label','placeholder','aria-label','alt'].includes(node.name.getText(tree))&&node.initializer&&ts.isStringLiteral(node.initializer))add(node.initializer,node.initializer.text,'attribute');
  if(ts.isJsxExpression(node)&&node.expression&&(!ts.isJsxAttribute(node.parent)||['title','description','label','placeholder','aria-label','alt'].includes(node.parent.name.getText(tree))))outputs(node.expression);
  ts.forEachChild(node,visit);
 }
 visit(tree);return found;
}
const excluded=new Set(['BootstrapGate.tsx','PreparationPlan.tsx','SourceAccessHelp.tsx','ThemeControl.tsx','LanguageControl.tsx','Brand.tsx','OperationFeedback.tsx']);
export const files=fs.readdirSync('src',{recursive:true}).filter(f=>f.endsWith('.tsx')&&!excluded.has(path.basename(f))).map(f=>path.join('src',f));
if(process.argv.includes('--list'))console.log(JSON.stringify([...new Set(files.flatMap(f=>entries(f).map(e=>e.text)))].sort(),null,2));
