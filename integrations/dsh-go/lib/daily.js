const clip=(text,n)=>String(text??'').slice(0,n)
export function dailyPanel(client){
 return {
  view:{type:'stack',title:'签到与每日任务',children:[
   {type:'text',text:{$:'data.status'}},
   {type:'text',text:'首次短信授权在运行后端的主机控制台完成。授权后可在这里执行和设置自动任务。',tone:'muted'},
   {type:'list',items:{$:'data.items'}},
   {type:'options',id:'set-daily-auto',selected:{$:'data.auto'},options:[{value:'on',label:'上线自动执行'},{value:'off',label:'只检查进度'}]},
   {type:'text',text:'分享流程上报不会发送微信或QQ消息。未知任务保留待处理。',tone:'muted'},
   {type:'actions',items:{$:'data.actions'}},
   {type:'actions',items:[{label:'复制主机控制台地址',action:'copy-console',icon:'copy'},{label:'创作设置',action:'back-writing',icon:'settings'}]},
  ]},
  data:(scope,emit)=>{
   const controller=new AbortController();let closed=false,timer
   const poll=async()=>{
    try{
     const [report,app]=await Promise.all([client.dailyTasks(controller.signal),client.appSession(controller.signal)])
     if(closed)return
     emit({status:clip(report.execution_error||(report.running||app.running?'每日任务正在主机后台执行。':app.configured?'App已连接；进度由平台确认。':'请先在主机控制台连接App账号。'),500),
      auto:report.settings?.auto_execute?'on':'off',
      items:(report.tasks||[]).slice(0,20).map(task=>({title:clip((task.finished?'✓ ':'○ ')+task.title,100),subtitle:clip(task.finished?'已完成':task.reason||'待完成',300)})),
      actions:[...(app.configured&&!report.running&&!app.running?[{label:'执行每日任务',action:'run-daily',icon:'play'}]:[]),{label:'刷新进度',action:'reload-daily',icon:'refresh'}]})
    }catch{if(!closed)emit({status:'每日任务连接失败，请确认已更新并启动后端。',items:[],actions:[],auto:'off'})}
    finally{if(!closed){timer=setTimeout(poll,4000);timer.unref?.()}}
   };void poll();return()=>{closed=true;clearTimeout(timer);controller.abort()}
  },
  actions:{
   'back-desk':()=>({open:'panel:desk'}),
   'reload-daily':()=>({refresh:true}),
   'copy-console':()=>({copy:client.consoleURL||'http://127.0.0.1:8765/',toast:'在运行后端的主机浏览器打开此地址'}),
   'run-daily':async()=>{try{await client.startDaily();return {refresh:true,toast:'已交给主机后台执行'}}catch{return {toast:'启动未确认，请先刷新核对，勿重复执行'}}},
   'set-daily-auto':async(_scope,event)=>{
    const value=event.value?.value;if(!['on','off'].includes(value))return {toast:'无效选项'}
    try{await client.dailySettings(value==='on');return {refresh:true,toast:'已更新后续每日任务设置'}}catch{return {toast:'设置未确认，请刷新核对'}}
   },
  },
 }
}
