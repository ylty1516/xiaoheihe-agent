import { stripTypeScriptTypes } from 'node:module'
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { createHash } from 'node:crypto'
const source = new URL('./vendor/',import.meta.url), output = new URL('./lib/vendor/',import.meta.url)
mkdirSync(output,{recursive:true})
const manifest=JSON.parse(readFileSync(new URL('SOURCE.json',source),'utf8'))
for(const [name,digest] of Object.entries(manifest.sha256)){
  let text=readFileSync(new URL(name,source),'utf8').replace(/\r\n/g,'\n')
  if(createHash('sha256').update(text).digest('hex')!==digest)throw new Error('Vendored source digest mismatch: '+name)
  // Login validates identity and a task list, not one hard-coded set of task IDs.
  if(name==='login-core.ts')text=text.replace("import { snapshot } from './tasks.js';","import { snapshot } from '../account-check.mjs';")
  const compiled=stripTypeScriptTypes(text,{mode:'strip'}).replace(/[ \t]+$/gm,'').trimEnd()
  writeFileSync(new URL(name.replace(/\.ts$/,'.js'),output),compiled?compiled+'\n':'// Type-only source; no runtime exports.\n')
}
console.log('Native runtime built from reviewed source '+manifest.commit)
