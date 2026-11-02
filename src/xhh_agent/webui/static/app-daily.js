(() => {
 const $=id=>document.getElementById(id),dialog=$('appDailyDialog')
 let loginId='',busy=false,timer,configured=false,executing=false,report={}
 async function api(url,body){
  const response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
  const data=await response.json()
  if(!response.ok||data.ok===false)throw new Error(data.error||'请求没有完成，请刷新核对。')
  return data
 }
 const error=message=>{$('appDailyError').textContent=message||''}
 function setBusy(value){busy=value;for(const id of ['btnAppSend','btnAppVerify','btnAppRun','btnAppRefresh','appDailyAuto'])$(id).disabled=value||(id==='btnAppRun'&&(!configured||executing))}
 function codePhase(pending){
  loginId=pending?.login_id||'';$('appPhoneForm').hidden=!!loginId;$('appCodeForm').hidden=!loginId
  $('appPhoneHint').textContent=loginId?'验证码已发送至 '+pending.phone_hint:''
 }
 async function load(){
  clearTimeout(timer)
  const [state,data]=await Promise.all([api('/api/app-session'),api('/api/daily-tasks')]);report=data;configured=state.configured===true;executing=state.running||data.running
  $('appDailyState').textContent=state.running||data.running?'每日任务正在后台执行，关闭窗口后继续。':configured?'App账号已连接；任务按平台真实状态核对。':state.runtime_ready?'尚未连接App账号；当前网页版登录不受影响。':state.message||'App组件未准备好，请检查主机安装。'
  $('btnAppRun').disabled=busy||!configured||state.running||data.running
  $('appDailyAuto').checked=data.settings?.auto_execute===true
  $('appDailyTasks').replaceChildren()
  for(const task of data.tasks||[]){const line=document.createElement('p');line.textContent=(task.finished?'✓ ':'○ ')+task.title+' · '+(task.finished?'已完成':task.reason||'待完成');$('appDailyTasks').append(line)}
  if(data.execution_error)error(data.execution_error)
  if(!configured&&state.pending_login&&!busy){$('appLoginFields').hidden=false;codePhase(state.pending_login)}
  if(dialog.open&&(state.running||data.running))timer=setTimeout(()=>load().catch(e=>error(e.message)),2000)
 }
 async function action(work){if(busy)return;setBusy(true);error('');try{await work()}catch(e){error(e.message)}finally{setBusy(false)}}
 $('btnAppDaily').onclick=()=>{dialog.showModal();error('');load().catch(e=>error(e.message))}
 $('btnAppConnect').onclick=()=>{$('appLoginFields').hidden=false;if(!loginId)$('appPhone').focus()}
 $('appPhoneForm').onsubmit=event=>{event.preventDefault();action(async()=>{
  const phone=$('appPhone').value.trim();if(!phone)throw new Error('请填写手机号。')
  $('appDailyState').textContent='正在准备设备授权并请求短信，请勿重复点击…'
  const result=await api('/api/app-session',{action:'send_code',phone});$('appPhone').value='';codePhase(result);$('appCode').focus();$('appDailyState').textContent='短信已请求，请输入收到的验证码。'
 })}
 $('appCodeForm').onsubmit=event=>{event.preventDefault();action(async()=>{
  const code=$('appCode').value.trim();if(!/^\d{4,8}$/.test(code))throw new Error('请输入4至8位验证码。')
  $('appCode').value='';await api('/api/app-session',{action:'verify_code',login_id:loginId,code})
  codePhase(null);$('appLoginFields').hidden=true;await load()
 })}
 $('btnAppReset').onclick=()=>{codePhase(null);$('appCode').value='';$('appPhone').focus()}
 $('btnAppRefresh').onclick=()=>action(async()=>{await api('/api/daily-tasks',{action:'refresh'});await load()})
 $('btnAppRun').onclick=()=>action(async()=>{await api('/api/daily-tasks',{action:'start',confirm:true});await load()})
 $('appDailyAuto').onchange=()=>action(async()=>{await api('/api/daily-tasks',{action:'settings',enabled:true,auto_execute:$('appDailyAuto').checked,confirm:true});await load()})
 dialog.addEventListener('close',()=>{clearTimeout(timer);$('appPhone').value='';$('appCode').value=''})
})()
