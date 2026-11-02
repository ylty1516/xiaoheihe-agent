/* Local expression settings shared by every writer; no account permissions. */
(() => {
  const $=id=>document.getElementById(id), cache=new Map();
  let current=null, loading=false, busy=false;
  const scenes={article:'长文',short:'短帖',tutorial:'教程',comment:'评论'};
  const status=text=>{$('personaStatus').textContent=text;};
  async function api(body,query='') {
    const response=await fetch('/api/personas'+query,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{cache:'no-store'});
    const result=await response.json();if(!response.ok||result.ok===false)throw new Error(result.error||'人设操作未完成');return result;
  }
  const run=fn=>async()=>{if(busy)return;try{await fn();}catch(error){status(error.message);}};
  function exampleText(examples){return examples.map(x=>'素材/要求：'+x.input+'\n参考成稿：'+x.output+(x.avoid?'\n修改前：'+x.avoid:'')).join('\n---\n');}
  function parseExamples(text){
    if(!text.trim())return [];
    return text.trim().split(/\n---\s*\n/).map(block=>{
      if(!/^(素材\/要求|参考成稿|修改前)：/m.test(block))return {input:'根据给定材料写一段，参考以下表达方式。',output:block.trim(),avoid:''};
      const fields={input:[],output:[],avoid:[]},names={'素材/要求':'input','参考成稿':'output','修改前':'avoid'};let key='input';
      for(const line of block.split('\n')){const match=line.match(/^(素材\/要求|参考成稿|修改前)：(.*)$/);if(match){key=names[match[1]];fields[key].push(match[2]);}else fields[key].push(line);}
      const item=Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.join('\n').trim()]));if(!item.input||!item.output)throw new Error('每组示例需要素材/要求和参考成稿');return item;
    });
  }
  function edited(){if(!current)throw new Error('先选择人设');const card={...current.card,name:$('personaName').value.trim(),system_prompt:$('personaPrompt').value,examples:parseExamples($('personaExamples').value),scenes:{}};for(const key of Object.keys(scenes)){const value=$('personaScene-'+key).value.trim();if(value)card.scenes[key]=value;}const character=$('personaCharacter').value.trim(),direction=$('personaArtDirection').value.trim();if(character||direction)card.visual={character,direction};else delete card.visual;return card;}
  function fill(snapshot,defaults={}){
    current=snapshot;const card=snapshot.card;$('personaName').value=card.name;$('personaPrompt').value=card.system_prompt;$('personaExamples').value=exampleText(card.examples);
    $('personaCharacter').value=card.visual?.character||'';$('personaArtDirection').value=card.visual?.direction||'';
    $('personaVisual').querySelector('summary').textContent='配图与角色'+(card.visual?' · 已配置':'');
    $('personaVersion').textContent=card.name+' · 修订 '+snapshot.revision;
    for(const key of Object.keys(scenes)){$('personaScene-'+key).value=card.scenes[key]||'';$('personaScene-'+key).placeholder=defaults[key]||'留空使用该场景的默认表达要求';}
  }
  async function badge(){const data=await api(null,'?summary=1');button.textContent='人设 · '+data.active.name;button.title='当前修订 '+data.active.revision;}
  async function load(id){
    if(loading)return;loading=true;
    try{const data=await api(null,id?'?id='+encodeURIComponent(id):'');$('personaSelect').replaceChildren();for(const row of data.items)$('personaSelect').add(new Option(row.name+(row.active?' · 当前':''),row.id));$('personaSelect').value=data.snapshot.card.id;
      fill(cache.get(data.snapshot.card.id)||data.snapshot,data.default_scenes);
      $('personaRevision').replaceChildren();for(const row of data.revisions)$('personaRevision').add(new Option('修订 '+row.revision,row.revision));status('人设只影响表达。试写不会改正文或发布。');
    }finally{loading=false;}
  }
  function download(card,format){const blob=new Blob([JSON.stringify(card,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=(card.id||card.persona_id||'persona')+'.'+format+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  for(const [key,label] of Object.entries(scenes)){const field=document.createElement('div');field.className='field';const title=document.createElement('label'),input=document.createElement('textarea');input.rows=3;input.id='personaScene-'+key;title.htmlFor=input.id;title.textContent=label+'表达';field.append(title,input);$('personaScenes').append(field);}
  const button=document.createElement('button');button.className='text-button';button.id='personaSetup';button.textContent='人设';$('modelSetup').before(button);
  button.onclick=run(async()=>{$('personaDialog').showModal();await load();});
  $('personaSelect').onchange=run(async()=>{if(current)cache.set(current.card.id,{...current,card:edited()});await load($('personaSelect').value);});
  $('personaSave').onclick=run(async()=>{const card=edited();const data=await api({action:'save',card,expected_revision:current.revision,activate:true});cache.delete(card.id);await load(data.snapshot.card.id);await badge();status('已保存并使用；新任务采用此版本，正在运行的任务保持原版本。');});
  $('personaRollback').onclick=run(async()=>{const data=await api({action:'rollback',id:current.card.id,revision:Number($('personaRevision').value),expected_revision:current.revision});cache.delete(current.card.id);await load(data.snapshot.card.id);await badge();status('已恢复为新修订，历史版本仍保留。');});
  $('personaImport').onclick=()=>$('personaFile').click();
  $('personaFile').onchange=run(async()=>{const file=$('personaFile').files[0];if(!file)return;if(file.size>256000)throw new Error('文件超过256KB');const data=await api({action:'import',card:JSON.parse((await file.text()).replace(/^\uFEFF/,''))});await load(data.snapshot.card.id);status('已导入，保存并使用后生效。'+(data.snapshot.ignored_fields.length?'未导入字段：'+data.snapshot.ignored_fields.join('、'):''));$('personaFile').value='';});
  $('personaExport').onclick=run(async()=>{const format=$('personaExportFormat').value;const data=await api(null,'?export='+format+'&id='+encodeURIComponent(current.card.id));download(data.card,format);status(format==='astrbot'?'已导出已保存版本：人格描述和示例对话；场景补充、配图设定及修改前示例仅在完整格式中保留。':'已导出完整的已保存版本。');});
  $('personaTrialStart').onclick=run(async()=>{
    const card=edited(),material=$('personaTrialMaterial').value;if(!material.trim())throw new Error('先附上同一份试写材料与要求');busy=true;$('personaTrialStart').disabled=true;status('正在试写两版，仅预览…');
    try{const response=await fetch('/api/personas/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({card,material,scene:$('personaTrialScene').value})});const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'试写未完成');$('personaTrialResults').replaceChildren();for(const result of data.results){const section=document.createElement('section'),title=document.createElement('h3'),text=document.createElement('div');title.textContent=result.label+(result.label==='已保存版本'?' · 修订 '+result.persona.revision:'');text.textContent=result.text;text.className='context-text';section.append(title,text);$('personaTrialResults').append(section);}status('两版试写完成，原稿与人设保存状态未变。');}
    finally{busy=false;$('personaTrialStart').disabled=false;}
  });
  $('personaDialog').querySelector('[data-close]').addEventListener('click',()=>{if(current){try{cache.set(current.card.id,{...current,card:edited()});}catch{}}});
  badge().catch(()=>{button.title='点击读取或配置人设';});
})();
