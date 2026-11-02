/* Authoring workspace. Two everyday inputs; secondary tasks live in dialogs. */
(() => {
  const $ = id => document.getElementById(id);
  let documentPersona=null, current = null, revision = null, brief = null, notes = '', dirty = false, serial = 0;
  let saveTimer, saveChain = Promise.resolve(), conflict = false, library = {drafts:[],archived:[],published:[]};
  let libraryTab = 'drafts', previewing = false, report = null, model = {}, aiMode = 'outline', generation = null, aiBusy = false;
  let activeNote = null, contentProfile = 'article', currentSubject='auto', currentGenre='auto', subjectExplicit=false, lastTopic='盒友杂谈';
  let autoJob=null, autoTimer, autoStartFile=null, autoStartRevision=null, autoOpened='';
  let writingOptions={subjects:[{id:'auto',name:'按本次要求',topic:'盒友杂谈'}],genres:[{id:'auto',name:'按内容组织'}],default_topic:'盒友杂谈'};
  let discoveryQuery='', discoveryTimer, discoverySeq=0, discoveryLoaded=false, operationPane='discover', discoveryFailures=0, displayedDiscovery=null;
  let selectedRange = null, replyRow = null, loginTimer = null, screen = 'writing', topicPurpose='search';
  const labels = {writing:'把精力留给内容。',library:'每一篇，都有着落。',workbench:'从社区获得下一篇灵感。',logs:'运行状态，一目了然。'};
  const date = ts => new Date(ts*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  function toast(text,bad=false) { const box=document.createElement('div'); box.className='toast'+(bad?' bad':''); box.textContent=text;box.setAttribute('role','status'); const open=document.querySelector('dialog[open]');if(open){box.classList.add('dialog-toast');open.append(box);}else $('toasts').append(box); setTimeout(()=>box.remove(),5000); }
  async function api(url,body) {
    const response=await fetch(url,body===undefined?{cache:'no-store'}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok || (data.ok===false&&!(url==='/api/preflight'&&Array.isArray(data.blockers)))) throw new Error(data.error || data.title || (data.lines||[]).join('；') || '请求没有完成');
    return data;
  }
  const run = fn => async event => {try {await fn(event);} catch(error) {toast(error.message,true);if(screen==='workbench')output(error.message);}};
  const dialog=id=>{if(!$(id).open) $(id).showModal();};
  function go(id) {location.hash=id; if(screen===id) showScreen();}
  function showScreen() {
    screen=location.hash.slice(1)||'writing'; if(!labels[screen]) screen='writing';
    document.querySelectorAll('[data-screen]').forEach(node=>node.hidden=node.id!==screen);
    document.querySelectorAll('.nav a').forEach(link=>{if(link.hash==='#'+screen)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
    $('pageTitle').textContent=labels[screen];
    if(screen==='library') renderLibrary();
    if(screen==='workbench') {loadComments().catch(error=>toast(error.message,true));if(operationPane==='discover'&&(!discoveryLoaded||$('autoDiscover').checked))discover(discoveryQuery,{automatic:true});}else clearTimeout(discoveryTimer);
  }
  function count() { const body=$('articleBody').value; const images=(body.match(/!\[[^\]]*\]\([^)]*\)/g)||[]).length; const chars=body.replace(/!\[[^\]]*\]\([^)]*\)/g,'').replace(/[\s#*`]/g,'').length; $('wordCount').textContent=`${chars} 字 · ${images} 张图`; }
  function mark() {
    if(!current)return;
    dirty=true; $('btnSaveNow').hidden=false; serial++; report=null; $('btnPublish').disabled=true; $('saveState').textContent='待保存…'; count();
    clearTimeout(saveTimer); saveTimer=setTimeout(()=>save().catch(error=>toast(error.message,true)),900);
  }
  async function save() {
    clearTimeout(saveTimer);
    saveChain=saveChain.catch(()=>{}).then(async()=>{
      if(!current)throw new Error('先新建或选择一篇草稿');
      if(conflict)throw new Error('稿件已在其他窗口修改。请先导出当前内容，再重新读取合并。');
      if(!dirty)return;
      const snapshot=serial, file=current;
      $('saveState').textContent='保存中…';
      try {
        const data=await api('/api/editorial',{action:'save',file,revision,brief,
          markdown:$('articleBody').value,metadata:{title:$('titleInput').value,topic:$('topicInput').value==='__custom'?lastTopic:$('topicInput').value,notes,profile:contentProfile,genre:currentGenre,...(documentPersona?{persona:documentPersona}:{}),...(subjectExplicit?{subject:currentSubject}:{})}});
        if(current===file) {revision=data.revision; if(snapshot===serial){dirty=false;$('btnSaveNow').hidden=true;} $('saveState').textContent=dirty?'待保存…':'已自动保存';}
        await loadLibrary();
      } catch(error) {if(error.message.includes('其他窗口'))conflict=true; $('saveState').textContent='保存失败，内容仍在本页'; throw error;}
    });
    return saveChain;
  }
  function chooseTopic(value) {
    const select=$('topicInput');
    if(![...select.options].some(x=>x.value===value)) select.add(new Option(value,value),select.options.length-1);
    select.value=value;lastTopic=value;
  }
  function updateWritingScope() {
    $('writingSubject').value=currentSubject;$('publishSubject').value=currentSubject;$('writingGenre').value=currentGenre;
    const scope=writingOptions.subjects.find(s=>s.id===currentSubject)?.name||'按本次要求',form=writingOptions.genres.find(g=>g.id===currentGenre)?.name||'按内容组织';
    $('writingScopeSummary').textContent='题材与写法 · '+scope+' · '+form;
  }
  function chooseSubject(value,{explicit=false,suggest=false}={}) {
    const old=writingOptions.subjects.find(s=>s.id===currentSubject),selected=writingOptions.subjects.find(s=>s.id===value);
    const useSuggestion=suggest&&(lastTopic===old?.topic||!subjectExplicit||lastTopic===writingOptions.default_topic);
    currentSubject=value;if(explicit)subjectExplicit=true;if(useSuggestion&&selected)chooseTopic(selected.topic);updateWritingScope();
  }
  async function loadWritingOptions() {
    writingOptions=await api('/api/writing-options');
    for(const id of ['writingSubject','publishSubject']) {$(id).replaceChildren();for(const item of writingOptions.subjects)$(id).add(new Option(item.name,item.id));}
    $('writingGenre').replaceChildren();for(const item of writingOptions.genres)$('writingGenre').add(new Option(item.name,item.id));updateWritingScope();
  }
  function chooseProfile(value) {contentProfile=value;$('aiProfile').value=value;$('publishProfile').value=value;}
  function setDocument(data) {
    documentPersona=data.metadata?.persona||null; current=data.file; revision=data.revision; brief=data.has_brief?data.brief:null; notes=data.metadata?.notes||''; dirty=false; conflict=false; serial++;
    $('titleInput').value=data.title||''; $('articleBody').value=data.markdown||''; subjectExplicit=Object.prototype.hasOwnProperty.call(data.metadata||{},'subject');currentSubject=data.metadata?.subject||'auto';currentGenre=data.metadata?.genre||'auto';chooseTopic(data.metadata?.topic||writingOptions.default_topic);chooseProfile(data.metadata?.profile||'article');updateWritingScope();
    $('saveState').textContent='所有修改已保存'; $('aiMaterial').value=notes; report=null;
    ['titleInput','articleBody','btnDuplicate','btnExport','btnArchive','btnCheck'].forEach(id=>$(id).disabled=false);
    $('btnSaveNow').hidden=true;$('moreActions').open=false;count(); renderRecent();
    if(previewing) preview().catch(error=>toast(error.message,true));
  }
  async function openDraft(file,navigate=true) {if(dirty)await save(); await saveChain.catch(()=>{}); const data=await api('/api/editorial?file='+encodeURIComponent(file));setDocument(data);if(navigate)go('writing');}
  async function newDraft() {if(dirty)await save();setDocument(await api('/api/editorial',{action:'new'}));await loadLibrary();go('writing');$('titleInput').focus();}
  async function loadLibrary() {library=await api('/api/library');renderRecent(); if(screen==='library')renderLibrary();}
  function button(text,fn,kind='text-button') {const node=document.createElement('button');node.className=kind;node.textContent=text;node.onclick=run(fn);return node;}
  const autoActive=state=>['queued','collecting','planning','writing','checking','publishing'].includes(state);
  async function autoJobs() {
    const data=await api('/api/autopilot');$('autoJobList').replaceChildren();
    if(!data.items.length)empty($('autoJobList'),'还没有自动任务。');
    for(const item of data.items)$('autoJobList').append(button((item.title||'自动选题')+' · '+item.message,()=>showAutoJob(item.id),'auto-job-row'));
    if(!autoJob&&data.items[0])await showAutoJob(data.items[0].id);
  }
  async function showAutoJob(id) {
    clearTimeout(autoTimer);
    const {job}=await api('/api/autopilot?id='+encodeURIComponent(id));autoJob=job;
    $('autoProgress').hidden=false;$('autoTaskTitle').textContent=job.title||'任务进度';$('autoTaskStatus').textContent=job.message;
    const detail=$('autoTaskDetail');detail.replaceChildren();
    const messages=[...(job.issues||[]),...(job.check?.blockers||[]).filter(x=>job.publish||!x.startsWith('现在不能发')),...(job.check?.warnings||[])];
    if(messages.length){const group=document.createElement('details'),summary=document.createElement('summary');summary.textContent='查看检查提醒（'+messages.length+'）';group.append(summary);for(const message of messages){const line=document.createElement('p');line.textContent=message;group.append(line);}detail.append(group);}
    if(job.state==='awaiting_images'){const line=document.createElement('p');line.textContent='正文已保存。插件可读取配图任务，生成后自动回填；仅运行 WebUI 时，任务会等在这里。';detail.append(line);}
    const actions=$('autoTaskActions');actions.replaceChildren();
    if(job.file)actions.append(button('查看成稿',async()=>{$('autoDialog').close();await openDraft(job.file);},'secondary'));
    if(['paused','user_paused','failed','review','ready'].includes(job.state))actions.append(button('继续处理',async()=>{await api('/api/autopilot',{action:'resume',id:job.id});await showAutoJob(job.id);},'secondary'));
    if(autoActive(job.state)&&job.state!=='publishing')actions.append(button('暂停',async()=>{await api('/api/autopilot',{action:'pause',id:job.id});await showAutoJob(job.id);},'secondary'));
    if(!['published','publishing','uncertain','cancelled'].includes(job.state))actions.append(button('取消任务',async()=>{await api('/api/autopilot',{action:'cancel',id:job.id});await showAutoJob(job.id);},'text-button'));
    if(job.state==='published')actions.append(button('获取反馈',async()=>{await api('/api/autopilot',{action:'feedback',id:job.id});toast('反馈已归档到专题素材');},'secondary'));
    $('btnStartAuto').disabled=autoActive(job.state);
    if(job.file&&['ready','published','review'].includes(job.state)&&autoOpened!==job.id&&!dirty&&current===autoStartFile&&revision===autoStartRevision){
      autoOpened=job.id;await loadLibrary();await openDraft(job.file,false);toast(job.state==='published'?'自动任务已发布':'自动成稿已保存，可直接查看');
    }
    if(autoActive(job.state)||job.state==='waiting_slot'||job.state==='awaiting_images')autoTimer=setTimeout(()=>showAutoJob(id).catch(error=>{toast(error.message,true);$('btnStartAuto').disabled=false;}),autoActive(job.state)?3000:15000);
  }
  async function startAuto() {
    if(dirty)await save();autoStartFile=current;autoStartRevision=revision;
    $('btnStartAuto').disabled=true;
    try {
      const {job}=await api('/api/autopilot',{action:'start',instruction:$('autoInstruction').value,
        material:$('autoUseMaterial').checked?notes:'',subject:subjectExplicit?currentSubject:'auto',genre:currentGenre,
        profile:$('autoProfile').value,images:$('autoImages').value,
        publish:$('autoPublish').checked,confirm:$('autoPublish').checked});
      $('autoPublish').checked=false;await showAutoJob(job.id);await autoJobs();
    }catch(error){$('btnStartAuto').disabled=false;throw error;}
  }
  function empty(target,text) {const box=document.createElement('div');box.className='empty-state';box.textContent=text;target.append(box);}
  function renderRecent() {
    const list=$('recentDrafts');list.replaceChildren();
    for(const item of library.drafts.slice(0,8)) {
      const row=button('',()=>openDraft(item.name),'draft-item'); const title=document.createElement('strong');title.textContent=item.suggested_title||'未命名草稿';
      const info=document.createElement('span');info.textContent=`${item.chars} 字 · ${date(item.modified_at)}`;row.append(title,info);if(current===item.name)row.setAttribute('aria-current','true');list.append(row);
    }
    if(!library.drafts.length)empty(list,'还没有草稿');
  }
  function row(title,sub) {const box=document.createElement('div');box.className='library-row';const main=document.createElement('div');main.className='row-body';const heading=document.createElement('h3');heading.textContent=title;const note=document.createElement('p');note.textContent=sub;main.append(heading,note);const actions=document.createElement('div');actions.className='row-actions';box.append(main,actions);return {box,main,actions};}
  function renderLibrary() {
    const list=$('libraryList');list.replaceChildren();const items=library[libraryTab]||[];
    const audit=library.diversity;$('writingHabits').hidden=libraryTab!=='published';$('habitsBody').replaceChildren();
    $('habitsSummary').textContent='最近 '+(audit?.history_count||0)+' 篇的写法习惯';
    for(const pattern of audit?.patterns||[]) {const box=document.createElement('div');box.className='issue warn';const title=document.createElement('strong');title.textContent=pattern.count+' 篇'+pattern.label;const advice=document.createElement('p');advice.textContent=pattern.suggestion;box.append(title,advice);const references=document.createElement('details');const summary=document.createElement('summary');summary.textContent='原文对照';references.append(summary);for(const sample of pattern.examples.slice(0,2)){const quote=document.createElement('blockquote');quote.textContent=sample.title+'：'+sample.text;references.append(quote);}box.append(references);$('habitsBody').append(box);}
    if(!audit?.patterns.length)empty($('habitsBody'),audit?.history_count?'暂未识别到连续重复的写法；这不代表语义或事实已通过检查。':'还没有已发布正文快照，暂时无法比较写法。');
    for(const item of items) {
      let view;
      if(libraryTab==='drafts') {view=row(item.suggested_title||'未命名草稿',`${item.chars} 字 · ${item.images} 张图 · ${date(item.modified_at)}`);view.actions.append(button('继续写作',()=>openDraft(item.name),'secondary'));}
      if(libraryTab==='archived') {view=row(item.title,'移入回收站于 '+date(item.archived_at));view.actions.append(button('恢复',async()=>{const data=await api('/api/editorial',{action:'restore',archive_id:item.archive_id});await loadLibrary();toast('已恢复到草稿箱');setDocument(data);},'secondary'));}
      if(libraryTab==='published') {view=row(item.title||'已发布文章',date(item.published_at));const link=document.createElement('a');link.textContent='查看帖子';link.href='https://www.xiaoheihe.cn/app/bbs/link/'+encodeURIComponent(item.link_id);link.target='_blank';link.rel='noopener noreferrer';view.actions.append(link);}
      list.append(view.box);
    }
    if(!items.length)empty(list,libraryTab==='published'?'暂无本机发布记录。新发布文章会自动记录在这里。':libraryTab==='archived'?'回收站是空的':'还没有草稿，点击“新建草稿”开始。');
  }
  async function duplicate() {await save();setDocument(await api('/api/editorial',{action:'duplicate',file:current,revision}));await loadLibrary();toast('已复制为一篇新草稿');}
  async function archive() {
    await save();await api('/api/editorial',{action:'archive',file:current,revision});current=null;revision=null;dirty=false;$('moreActions').open=false;
    $('titleInput').value='';$('articleBody').value='';$('previewBody').replaceChildren();$('saveState').textContent='已移入回收站';
    ['titleInput','articleBody','btnDuplicate','btnExport','btnArchive','btnCheck'].forEach(id=>$(id).disabled=true);
    count();await loadLibrary();toast('已移入回收站，可随时恢复');if(library.drafts.length)await openDraft(library.drafts[0].name);
  }
  async function importFile(file) {if(file.size>1024*1024)throw new Error('Markdown 文件不能超过 1 MB');const text=(await file.text()).replace(/^\uFEFF/,'');await newDraft();const match=text.match(/^#\s+([^\n]+)\n*/);$('titleInput').value=match?match[1].slice(0,100):file.name.replace(/\.[^.]+$/,'').slice(0,100);$('articleBody').value=match?text.slice(match[0].length):text;mark();await save();toast('已导入');}
  async function preview() {
    const file=current, stamp=serial;const data=await api('/api/preview',{markdown:$('articleBody').value});
    if(current===file&&stamp===serial)$('previewBody').innerHTML=data.html;
  }
  async function togglePreview() {if(!current)throw new Error('先新建或选择草稿');previewing=!previewing;$('articleBody').hidden=previewing;$('previewBody').hidden=!previewing;$('btnPreview').setAttribute('aria-pressed',String(previewing));$('btnPreview').textContent=previewing?'编辑':'预览';if(previewing)await preview();else $('articleBody').focus();}
  function insert(text) {const area=$('articleBody');const start=area.selectionStart,end=area.selectionEnd;area.setRangeText(text,start,end,'end');mark();area.focus();}
  async function upload(files) {
    if(!current)throw new Error('先新建或选择草稿');
    const target=current;
    for(const file of files) {if(file.size>8*1024*1024)throw new Error('单张图片不能超过 8 MB');const form=new FormData();form.append('image',file);const response=await fetch('/api/images',{method:'POST',body:form});const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'上传失败');if(current!==target)throw new Error('稿件已切换，图片未插入');insert('\n\n'+data.markdown+'\n\n');}
    await save();if(previewing)await preview();toast('配图已插入并保存');
  }
  function format(kind) {if(!current||previewing)return;const area=$('articleBody'),selection=area.value.slice(area.selectionStart,area.selectionEnd);insert(({heading:'\n\n## '+(selection||'小标题')+'\n\n',bold:'**'+(selection||'重点内容')+'**',list:'\n- '+(selection||'第一项')+'\n',quote:'\n> '+(selection||'引用内容')+'\n'})[kind]);}
  function renderIssues(data) {
    $('issues').replaceChildren();for(const [kind,items] of [['bad',data.blockers],['warn',data.warnings]])for(const text of items){const box=document.createElement('div');box.className='issue '+kind;box.textContent=text;$('issues').append(box);}
    $('warnBox').hidden=!data.warnings.length;$('warnOk').checked=false;
    $('checkSummary').replaceChildren();for(const text of [data.profile?.name||'长文',`${data.stats.chars} 字`,`${data.stats.images} 张图`,data.slot.allowed?'排期允许':'当前排期不允许']){const span=document.createElement('span');span.textContent=text;$('checkSummary').append(span);}
    $('duplicateBody').replaceChildren();$('duplicateDetails').hidden=!data.editorial?.matches.length;
    for(const match of data.editorial?.matches||[]) {const h=document.createElement('h3');h.textContent='与《'+match.title+'》的重复线索';$('duplicateBody').append(h);for(const para of match.repeated_paragraphs){const p=document.createElement('p');p.textContent='本稿：'+para.text;const old=document.createElement('blockquote');old.textContent='旧文：'+para.previous;$('duplicateBody').append(p,old);}}
    updatePublishButton();
  }
  function updatePublishButton() {$('btnPublish').disabled=!report?.ok || (report.warnings.length>0&&!$('warnOk').checked);}
  async function check() {await save();$('pubTitle').textContent=$('titleInput').value||'未填写标题';$('checkSummary').textContent='正在检查…';$('issues').replaceChildren();$('btnPublish').disabled=true;dialog('publishDialog');report=await api('/api/preflight',{file:current,title:$('titleInput').value});if(report.error)throw new Error(report.error);renderIssues(report);}
  async function publish() {
    if($('btnPublish').disabled)return;
    $('btnPublish').disabled=true;$('btnPublish').textContent='发布中…';
    try {const result=await api('/api/publish',{file:current,title:$('titleInput').value,topics:[$('topicInput').value],accept_warnings:$('warnOk').checked,confirm:true});$('publishDialog').close();report=null;toast((result.lines||[]).join('；')||'已发布');await Promise.all([loadLibrary(),refreshState()]);}
    finally {$('btnPublish').textContent='确认发布';/* Always recheck after an attempted publication. */ report=null;$('btnPublish').disabled=true;}
  }
  async function loadModel() {model=await api('/api/model');$('modelSetup').textContent=model.configured?'AI 设置':'配置 AI';$('modelURL').value=model.base_url;$('modelName').value=model.model;}
  function setAIMode(mode) {aiMode=mode;document.querySelectorAll('[data-ai-mode]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.aiMode===mode)));$('btnGenerate').textContent=({outline:'生成提纲',write:'生成正文',rewrite:'改写选段'})[mode];}
  function openAI() {
    if(!current)throw new Error('先新建或选择草稿');
    if(!model.configured){dialog('modelDialog');toast('先配置 AI 模型，其他写作功能可以直接使用');return;}
    const area=$('articleBody');selectedRange={start:area.selectionStart,end:area.selectionEnd};dialog('aiDialog');
  }
  async function generate() {
    if(aiBusy)return;const mode=aiMode,file=current,body=$('articleBody').value,title=$('titleInput').value;
    const selection=body.slice(selectedRange?.start||0,selectedRange?.end||0);
    if(mode==='rewrite'&&!selection.trim())throw new Error('先关闭窗口，在正文选中一段，再打开 AI 助手');
    notes=$('aiMaterial').value;mark();await save();
    aiBusy=true;$('btnGenerate').disabled=true;$('btnApplyAI').hidden=true;$('aiResult').hidden=true;$('aiNote').textContent='';$('aiReview').hidden=true;$('aiStatus').textContent='正在生成，原稿保持原样…';
    try {const result=await api('/api/generate',{mode,title,profile:contentProfile,subject:currentSubject,genre:currentGenre,markdown:body,selected:selection,material:notes+(brief?'\n已有选题卡：'+JSON.stringify(brief):'')});generation={file,body,title,mode,persona:result.persona,start:selectedRange?.start,end:selectedRange?.end,text:result.text};$('aiResult').textContent=result.text;$('aiResult').hidden=false;$('btnApplyAI').hidden=false;$('btnApplyAI').textContent=mode==='outline'?'插入提纲':mode==='rewrite'?'替换选中段落':'采用正文';if(mode==='outline') {
      const choices=result.text.split(/(?=^##\s*方案\s*\d+\s*[：:])/m).map(s=>s.trim()).filter(s=>/^##\s*方案\s*\d+\s*[：:]/.test(s));
      if(choices.length>0) {$('aiResult').replaceChildren();$('btnApplyAI').hidden=true;for(const choice of choices){const section=document.createElement('section');section.className='outline-pick';const text=document.createElement('div');text.textContent=choice;section.append(text,button('采用这份提纲',async()=>{generation.text=choice;await applyAI();},'secondary'));$('aiResult').append(section);}}
    }
    $('aiStatus').textContent=(result.stats?result.stats.chars+' 字 · ':'')+(result.warnings?.length?'有 '+result.warnings.length+' 项写法提醒，请审阅后采用。':'请核对事实与来源，再决定是否采用。');$('aiNote').textContent=(result.warnings||[]).join('\n\n');$('aiReview').hidden=!result.warnings?.length;if(!$('aiDialog').open)toast('AI 结果已准备好，打开 AI 助手审阅');}
    finally {aiBusy=false;$('btnGenerate').disabled=false;if($('aiStatus').textContent.startsWith('正在'))$('aiStatus').textContent='生成未完成，原稿已保留。';}
  }
  async function applyAI() {
    const g=generation;if(!g)return;
    if(current!==g.file||$('articleBody').value!==g.body)throw new Error('原稿已变化，未覆盖。请复制需要的结果到当前正文。');
    $('articleBody').value=g.mode==='rewrite'?g.body.slice(0,g.start)+g.text+g.body.slice(g.end):g.mode==='outline'?g.text+'\n\n'+g.body:g.text;
    if(g.persona)documentPersona=g.persona;mark();await save();if(previewing)await preview();$('aiDialog').close();generation=null;toast('已采用并保存，请核对内容后发布');
  }
  function output(text) {$('operationOutput').hidden=false;$('operationOutput').textContent=text;}
  async function operation(name) {output('正在处理…');const data=await api('/api/action',{name});output((data.lines||[]).join('\n')||data.title);await refreshState();if(name==='poll')await loadComments();}
  function discoveryActive() {return screen==='workbench'&&operationPane==='discover'&&!document.hidden;}
  function scheduleDiscovery() {clearTimeout(discoveryTimer);if(discoveryActive()&&$('autoDiscover').checked)discoveryTimer=setTimeout(()=>discover(discoveryQuery,{force:true,automatic:true}),Math.min(300000,60000*2**Math.min(discoveryFailures,2)));}
  function preferredDiscoveryTopic(item,data) {
    const key=value=>String(value||'').replace(/[^\p{L}\p{N}]/gu,'').toLowerCase(),topics=item.topics||[];
    const exact=topics.find(t=>key(t.name)===key(data.query));if(exact)return exact.name;
    const games=topics.filter(t=>t.topic_id!=='1'&&t.game_type==='pc');if(games.length===1)return games[0].name;
    if(games.length===0){const others=topics.filter(t=>t.topic_id!=='1'&&t.game_type);if(others.length===1)return others[0].name;}
    return data.source_board==='games'?item.text:'PC游戏';
  }
  async function discoveryDraft(item,data) {
    const title=item.title||item.text;await newDraft();$('titleInput').value=title.slice(0,100);const foundTopic=preferredDiscoveryTopic(item,data);if(data.source_board==='games'||item.topics?.some(t=>t.name===foundTopic&&t.game_type))chooseSubject('games',{explicit:true});chooseTopic(foundTopic);
    notes='选题线索：'+title+'\n数据来源：'+data.source+'\n采集时间：'+new Date(data.fetched_at*1000).toISOString()+'\n采集时间不等于话题发生时间；榜单和社区摘要仅为线索，须核对原始资料。'+(data.stale?'\n注意：此次更新失败，保留的是旧采集结果。':'')+(data.query?'\n搜索词：'+data.query+'；范围：'+(data.time_range||'不限')+'；排序：'+data.sort:'')+(item.published_at?'\n帖子发布时间：'+new Date(item.published_at*1000).toISOString():'')+(item.topics?.length?'\n原帖分区：'+item.topics.map(t=>t.name).join('、'):'')+(item.description?'\n社区摘要（须核实）：'+item.description:'')+(item.link_id?'\n来源：https://www.xiaoheihe.cn/app/bbs/link/'+item.link_id:'');
    $('aiMaterial').value=notes;mark();await save();toast('选题与来源已带入新稿，请核对资料和分区');
  }
  function renderDiscovery(data) {
    const list=$('discoverList');list.replaceChildren();$('discoverFilters').hidden=!data.query;$('discoverHeading').textContent=data.query?'关于“'+data.query+'”的讨论':data.source;
    const stamp=data.fetched_at?new Date(data.fetched_at*1000).toLocaleString('zh-CN'): '时间未知';
    $('discoverStatus').textContent=data.source+(data.query?' · '+({'1d':'近24小时','7d':'近7天','30d':'近30天','':'不限时间'}[data.time_range]||data.time_range)+' · '+({'create_date':'最新发布','award_num':'点赞优先','comment_num':'评论优先','default':'平台排序'}[data.sort]||data.sort):'')+' · 采集于 '+stamp+(data.cached?' · 缓存':'')+(data.fallback?' · 主榜缺失，使用热议子榜':'')+(data.stale?' · 更新失败，当前为旧结果':'');
    $('discoverNote').textContent=(data.warning||data.sample_note||'排名变化与上一次成功采集比较；采集时间不是话题发生时间。')+' 自动更新仅在本页可见时运行，正常每60秒采集，失败后延迟重试。';
    for(const item of data.items) {
      const title=item.title||item.text;let sub;
      if(data.query)sub=(item.published_at?date(item.published_at):'发布时间未知')+' · 评论 '+item.comment_num+' · 赞 '+(item.award_num||item.up||0);
      else sub='第 '+item.index+' 位'+(item.right_tag?' · '+item.right_tag:'')+(item.movement==='new'?' · 本次新入榜':item.movement==='up'?' · ↑'+item.change:item.movement==='down'?' · ↓'+Math.abs(item.change):'');
      const view=row(title,sub);view.box.className='content-row';if(item.description){const excerpt=document.createElement('p');excerpt.textContent=item.description;view.main.append(excerpt);}
      view.actions.append(button('带入写作',()=>discoveryDraft(item,data)));if(!data.query)view.actions.append(button('看最新讨论',()=>{$('discoverySort').value='create_date';$('discoveryWindow').value='1d';return discover(item.text,{force:true});},'secondary'));
      if(item.link_id){const link=document.createElement('a');link.textContent='查看原帖';link.href='https://www.xiaoheihe.cn/app/bbs/link/'+encodeURIComponent(item.link_id);link.target='_blank';link.rel='noopener noreferrer';view.actions.append(link);}list.append(view.box);
    }
    if(!data.items.length)empty(list,'所选时间范围暂无结果，可切换时间范围或排序。');
  }
  async function discover(query=discoveryQuery,{force=false,automatic=false}={}) {
    clearTimeout(discoveryTimer);if(automatic&&!discoveryActive())return;
    const seq=++discoverySeq;discoveryQuery=query;$('btnHot').disabled=true;$('discoverStatus').textContent='正在获取'+(query?'“'+query+'”的讨论':'当前热榜')+'…';
    try {
      const data=await api('/api/operate',{action:query?'topic':'hot',query,board:$('hotBoard').value,sort:$('discoverySort').value,time_range:$('discoveryWindow').value,refresh:force});if(seq!==discoverySeq)return;
      displayedDiscovery=data;discoveryLoaded=true;discoveryFailures=data.stale?discoveryFailures+1:0;renderDiscovery(data);
    }catch(error){if(seq!==discoverySeq)return;discoveryFailures++;if(displayedDiscovery)renderDiscovery(displayedDiscovery);$('discoverStatus').textContent='更新失败：'+error.message+(displayedDiscovery?'；仍显示上次“'+(displayedDiscovery.query||displayedDiscovery.source)+'”的结果。':'');if(!automatic)toast(error.message,true);}
    finally {if(seq===discoverySeq){$('btnHot').disabled=false;scheduleDiscovery();}}
  }
  async function loadComments() {
    const data=await api('/api/comments');$('commentCount').textContent=data.items.length||'';const list=$('commentList');list.replaceChildren();
    for(const item of data.items) {const view=row(item.sender||'评论者',item.incoming.link_title||'');view.box.className='content-row';const p=document.createElement('p');p.className='row-context';p.textContent=item.incoming.text||'';view.main.append(p);const hard=item.incoming.must_human||['sending','uncertain'].includes(item.state);if(hard){const tag=document.createElement('span');tag.className='status-tag';tag.textContent=item.state==='uncertain'?'发送结果待人工核对，请勿重发':item.state==='sending'?'正在处理':'需要人工到 App 处理';view.main.append(tag);}else view.actions.append(button('回复',()=>{replyRow=item;$('replyHeading').textContent='回复 '+(item.sender||'评论者');$('replyContext').textContent=(item.incoming.link_title||'')+(item.incoming.replied_text?'\n上文：'+item.incoming.replied_text:'');$('replyIncoming').textContent=item.incoming.text;$('replyText').value=item.draft||'';dialog('replyDialog');},'secondary'));if(!['sending','uncertain'].includes(item.state))view.actions.append(button('忽略',async()=>{await api('/api/operate',{action:'ignore',id:item.id});await loadComments();}));list.append(view.box);}
    if(!data.items.length)empty(list,'没有待处理评论。可点击“拉取新评论”查看。');
  }
  async function sendReply() {
    const text=$('replyText').value.trim();if(!text)throw new Error('先填写回复内容');
    $('btnSendReply').disabled=true;try {await api('/api/operate',{action:'send_reply',id:replyRow.id,text,confirm:true});$('replyDialog').close();toast('回复已发送');await Promise.all([loadComments(),refreshState()]);}finally {$('btnSendReply').disabled=false;}
  }
  async function refreshState() {
    try {const data=await api('/api/state');$('live').classList.remove('stale');$('conn').textContent='已连接';$('accountBadge').textContent=data.account.ok?'账号已登录':'账号未登录';$('loginButton').textContent=data.account.ok?'重新登录':'扫码登录';$('quota').textContent=`今日发布 ${data.slot.today_count} / ${data.slot.cap}`;$('accountNote').textContent=data.account.ok?'账号已连接。所有发送操作均需手动确认。':'点击右上角“扫码登录”，连接小黑盒账号。';$('logPoll').textContent=data.logs['daily-poll']||'暂无日志';$('logStudy').textContent=data.logs['daily-study']||'暂无日志';$('activityList').replaceChildren();for(const note of data.notes.latest){const view=row(note.title||'学习笔记',note.at);view.actions.append(button('阅读与拆解',async()=>{activeNote=note.name+'.md';const result=await api('/api/note?name='+encodeURIComponent(activeNote));$('noteHeading').textContent=note.title||'学习笔记';$('noteText').textContent=result.text;$('noteStatus').textContent='原始资料，拆解后会保存为可复用写法卡。';dialog('noteDialog');},'secondary'));$('activityList').append(view.box);}if(!data.notes.latest.length)empty($('activityList'),'暂无学习记录，点击“学习两篇帖子”开始。');}
    catch(error){$('live').classList.add('stale');$('conn').textContent='连接中断';}
  }
  async function login() {clearTimeout(loginTimer);dialog('loginDialog');$('loginQR').replaceChildren();$('loginStatus').textContent='正在获取二维码…';$('btnRenewQR').hidden=true;const data=await api('/api/operate',{action:'login_start'});const img=document.createElement('img');img.src=data.image;img.alt='小黑盒登录二维码';$('loginQR').append(img);$('loginStatus').textContent='请用小黑盒 App 扫码，等待确认。';const deadline=Date.now()+Math.min(data.expire,300)*1000;async function poll(){if(!$('loginDialog').open)return;try{const status=await api('/api/operate',{action:'login_poll',handle:data.handle});if(status.status==='ok'){$('loginStatus').textContent='登录成功';toast('账号已连接');await refreshState();return;}if(status.status==='expired'||Date.now()>deadline){$('loginStatus').textContent='二维码已过期';$('btnRenewQR').hidden=false;return;}loginTimer=setTimeout(poll,2000);}catch(error){$('loginStatus').textContent=error.message;$('btnRenewQR').hidden=false;}}loginTimer=setTimeout(poll,1800);}
  // Wiring. All external account actions require an explicit click.
  $('titleInput').addEventListener('input',mark);$('articleBody').addEventListener('input',mark);
  $('btnNewInline').onclick=run(newDraft);$('btnSaveNow').onclick=run(save);$('btnNewDraft').onclick=run(newDraft);$('btnNewFromLibrary').onclick=run(newDraft);$('btnDuplicate').onclick=run(duplicate);$('btnArchive').onclick=run(archive);
  $('btnExport').onclick=run(async()=>{await save();const link=document.createElement('a');link.href='/api/export?file='+encodeURIComponent(current);link.download='';document.body.append(link);link.click();link.remove();});
  $('btnImportMore').onclick=()=>$('mdFile').click();$('btnImport').onclick=()=>$('mdFile').click();$('mdFile').onchange=run(async()=>{if($('mdFile').files[0])await importFile($('mdFile').files[0]);$('mdFile').value='';});
  $('btnImage').onclick=()=>{if(current)$('imageFile').click();else toast('先新建或选择草稿',true);};$('imageFile').onchange=run(async()=>{await upload([...$('imageFile').files]);$('imageFile').value='';});
  $('articleBody').addEventListener('paste',event=>{const files=[...event.clipboardData.files];if(files.length){event.preventDefault();upload(files).catch(error=>toast(error.message,true));}});
  $('articleBody').addEventListener('dragover',event=>event.preventDefault());$('articleBody').addEventListener('drop',run(async event=>{event.preventDefault();const files=[...event.dataTransfer.files];if(files[0]?.name.match(/\.md$/i))await importFile(files[0]);else await upload(files);}));
  document.querySelectorAll('[data-format]').forEach(node=>node.onclick=()=>format(node.dataset.format));
  document.querySelectorAll('[data-go]').forEach(node=>node.onclick=()=>{if(node.hasAttribute('data-show-published')){libraryTab='published';document.querySelectorAll('[data-library]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.library==='published')));}go(node.dataset.go);});
  document.querySelectorAll('[data-library]').forEach(node=>node.onclick=()=>{libraryTab=node.dataset.library;document.querySelectorAll('[data-library]').forEach(b=>b.setAttribute('aria-pressed',String(b===node)));renderLibrary();});
  document.querySelectorAll('[data-close]').forEach(node=>node.onclick=()=>$(node.dataset.close).close());
  document.querySelectorAll('[data-ai-mode]').forEach(node=>node.onclick=()=>setAIMode(node.dataset.aiMode));
  document.querySelectorAll('[data-operation]').forEach(node=>node.onclick=run(()=>operation(node.dataset.operation)));
  document.querySelectorAll('[data-operation-view]').forEach(node=>node.onclick=()=>{document.querySelectorAll('[data-operation-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===node)));operationPane=node.dataset.operationView;document.querySelectorAll('[data-operation-pane]').forEach(p=>p.hidden=p.dataset.operationPane!==operationPane);clearTimeout(discoveryTimer);if(operationPane==='discover')discover(discoveryQuery,{automatic:true});});
  function topicDialog(purpose) {topicPurpose=purpose;$('topicMatches').replaceChildren();$('topicDialogTitle').textContent=purpose==='custom'?'选择发布分区':'搜索社区话题';$('btnConfirmTopic').textContent=purpose==='custom'?'查找分区':'搜索';$('topicQuery').value='';dialog('topicDialog');$('topicQuery').focus();}
  for(const id of ['aiProfile','publishProfile'])$(id).onchange=run(async()=>{chooseProfile($(id).value);mark();await save();if($('publishDialog').open)await check();});
  $('topicInput').onchange=()=>{if($('topicInput').value==='__custom'){topicDialog('custom');return;}lastTopic=$('topicInput').value;mark();if($('publishDialog').open)check().catch(error=>toast(error.message,true));};
  async function applyTopic(name) {chooseTopic(name);$('topicDialog').close();mark();await save();if($('publishDialog').open)await check();}
  $('btnConfirmTopic').onclick=run(async()=>{
    const query=$('topicQuery').value.trim();if(!query)throw new Error('请填写名称');
    if(topicPurpose!=='custom'){$('topicDialog').close();await discover(query);return;}
    const data=await api('/api/operate',{action:'find_topics',query});const items=data.items||[];
    const key=value=>value.normalize('NFKC').replace(/[^\p{L}\p{N}]/gu,'').toLowerCase();const exact=items.find(item=>key(item.name)===key(query));
    if(exact||items.length===1){await applyTopic((exact||items[0]).name);return;}
    $('topicMatches').replaceChildren();for(const item of items)$('topicMatches').append(button(item.name,()=>applyTopic(item.name),'secondary'));
    if(!items.length)empty($('topicMatches'),'没有找到分区，请换个关键词。');
  });
  $('topicDialog').addEventListener('close',()=>{if($('topicInput').value==='__custom')chooseTopic(lastTopic);});
  for(const id of ['writingSubject','publishSubject'])$(id).onchange=run(async()=>{chooseSubject($(id).value,{explicit:true,suggest:true});mark();await save();if($('publishDialog').open)await check();});
  $('writingGenre').onchange=()=>{currentGenre=$('writingGenre').value;updateWritingScope();mark();};
  $('topicQuery').addEventListener('keydown',event=>{if(event.key==='Enter')$('btnConfirmTopic').click();});
  $('btnPreview').onclick=run(togglePreview);$('btnCheck').onclick=run(check);$('warnOk').onchange=updatePublishButton;$('btnPublish').onclick=run(publish);
  $('btnAI').onclick=run(openAI);$('btnGenerate').onclick=run(generate);$('btnApplyAI').onclick=run(applyAI);
  $('btnAutopilot').onclick=run(async()=>{dialog('autoDialog');await autoJobs();});$('btnStartAuto').onclick=run(startAuto);
  $('modelSetup').onclick=()=>dialog('modelDialog');$('btnSaveModel').onclick=run(async()=>{await api('/api/model',{base_url:$('modelURL').value,model:$('modelName').value,api_key:$('modelKey').value,persist:$('persistModel').checked});$('modelKey').value='';await loadModel();$('modelDialog').close();toast('AI 设置已保存');});
  $('btnHot').onclick=()=>discover('',{force:true});$('hotBoard').onchange=()=>discover('',{force:true});$('autoDiscover').onchange=()=>{$('autoDiscover').checked?discover(discoveryQuery,{automatic:true}):clearTimeout(discoveryTimer);};for(const id of ['discoverySort','discoveryWindow'])$(id).onchange=()=>discover(discoveryQuery,{force:true});$('btnTopic').onclick=()=>topicDialog('search');
  $('btnStudy').onclick=run(async()=>{output('正在学习两篇帖子…');const data=await api('/api/operate',{action:'study'});output(data.summary);await refreshState();});
  $('btnQueueRefresh').onclick=run(loadComments);$('btnGenerateReply').onclick=run(async()=>{const data=await api('/api/operate',{action:'generate_reply',id:replyRow.id});$('replyText').value=data.text;});$('btnSendReply').onclick=run(sendReply);
  $('btnAnalyzeNote').onclick=run(async()=>{if(!model.configured)throw new Error('请先在 AI 设置中配置模型');$('btnAnalyzeNote').disabled=true;$('noteStatus').textContent='正在分析写法…';try{const result=await api('/api/note/analyze',{name:activeNote});$('noteText').textContent='读者问题：'+result.card.reader_question+'\n\n论证顺序：\n'+result.card.argument_order.join(' → ')+'\n\n证据用途：\n'+result.card.evidence_usage.join('\n')+'\n\n适用条件：'+result.card.applicable_when;$('noteStatus').textContent='已保存为可检索的写法卡，保留原文出处。';}catch(error){$('noteStatus').textContent='分析未完成，原文已保留。';throw error;}finally{$('btnAnalyzeNote').disabled=false;}});
  $('loginButton').onclick=run(login);$('btnRenewQR').onclick=run(login);$('loginDialog').addEventListener('close',()=>clearTimeout(loginTimer));$('btnRefreshState').onclick=run(refreshState);
  document.addEventListener('visibilitychange',()=>{clearTimeout(discoveryTimer);if(discoveryActive()&&$('autoDiscover').checked)discover(discoveryQuery,{automatic:true});});window.addEventListener('hashchange',showScreen);window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save().catch(error=>toast(error.message,true));}if((event.ctrlKey||event.metaKey)&&event.key==='Enter'&&current&&!document.querySelector('dialog[open]')){event.preventDefault();check().catch(error=>toast(error.message,true));}});
  showScreen();Promise.all([loadWritingOptions(),loadLibrary(),loadModel(),refreshState()]).then(async()=>{if(library.drafts[0])await openDraft(library.drafts[0].name,false);}).catch(error=>toast(error.message,true));
  const deskButton=button('专题素材',async()=>{dialog('deskDialog');await loadDesk();});$('modelSetup').before(deskButton);
  async function loadDesk(){const data=await api('/api/desk');$('deskItems').replaceChildren();
    for(const item of data.followups||[]){const p=document.createElement('p');p.textContent=item.event+'：'+item.reason;$('deskItems').append(p);}
    for(const item of data.items){const row=document.createElement('section'),p=document.createElement('p');p.textContent=item.event+' · '+({note:'随记',question:'读者问题',experiment:'验证记录',source:'来源资料',article:'稿件',image:'配图',feedback:'反馈'}[item.kind]||'素材')+'\n'+item.text.slice(0,400);row.append(p);
      if(['source','note','experiment','question'].includes(item.kind))row.append(button('据此成稿',async()=>{const {job}=await api('/api/autopilot',{material_id:item.id,instruction:'根据这份材料写作，说明资料归属与适用边界',profile:'flexible',images:'auto',publish:false});$('deskDialog').close();dialog('autoDialog');await showAutoJob(job.id);},'secondary'));
      $('deskItems').append(row);}
  }
  $('deskSave').onclick=run(async()=>{await api('/api/desk',{kind:$('deskKind').value,event:$('deskEvent').value.trim()||'未分类',text:$('deskText').value});$('deskText').value='';$('deskStatus').textContent='已归档，可直接用于创作';await loadDesk();});
  const verifyButton=button('验证本机环境',async()=>{await api('/api/desk',{action:'experiment',recipe:'runtime',event:$('deskEvent').value.trim()||'环境验证'});await loadDesk();},'secondary');$('deskSave').after(verifyButton);
  $('deskFetch').onclick=run(async()=>{const input=$('deskSource').value.trim(),index=input.indexOf(':');if(index<1)throw new Error('请填写 steam:AppID 或 github:作者/仓库');$('deskStatus').textContent='读取公开资料中…';await api('/api/desk',{action:'fetch',provider:input.slice(0,index),key:input.slice(index+1),event:$('deskEvent').value.trim()});$('deskStatus').textContent='已归档；服务运行期间每两小时检查变化';await loadDesk();});
  setInterval(()=>{if(!document.hidden)refreshState();},15000);
})();
