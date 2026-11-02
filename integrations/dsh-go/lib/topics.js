// Use one optional native search field; older clients retain the v1 topic picker.
const presets = ['GitHub', 'AI', 'PC游戏']
const key = value => value.toLocaleLowerCase()
const validTopics = values => Array.isArray(values) && values.length > 0 && values.length <= 5
  && values.every(value => typeof value === 'string' && value.trim() && value.length <= 100)

export const topicsView = {
  v: 2, accent: 'app', type: 'stack', title: '发布分区', children: [
    {type:'text',text:{$:'data.status'}},
    {type:'text',text:{$:'data.summary'}},
    {type:'text',text:'点已选分区可移除；至少保留一个，最多五个。已有任务保持创建时的分区。',tone:'muted'},
    {type:'list',items:{$:'data.selected'}},
    {type:'actions',items:{$:'data.presets'}},
    {type:'form',submit:'search-topics',submitLabel:'搜索分区',children:[
      {type:'textField',label:'其他分区',placeholder:'例如：软件',bind:'data.search.query',maxLength:100,required:true},
    ]},
    {type:'text',text:{$:'data.searchStatus'},tone:'muted'},
    {type:'list',items:{$:'data.results'}},
    {type:'actions',items:[
      {label:'跟随默认',action:'inherit-topics',icon:'refresh'},
      {label:'设为默认',action:'save-topics',icon:'save'},
    ]},
    {type:'actions',items:[
      {label:'刷新默认',action:'reload-topics',icon:'refresh'},
      {label:'返回创作台',action:'back-desk',icon:'write'},
    ]},
  ],
}
export const legacyTopicsView = {
  type:topicsView.type,title:topicsView.title,children:topicsView.children.map(node=>node.type==='form'
    ? {type:'text',text:'当前客户端可使用快捷分区和后端默认值；更新 DSH Go 后可在这里搜索其他分区。',tone:'muted'} : node),
}

export function installTopics(ctx, client, stateFor) {
  const state = scope => {
    const owner = stateFor(scope)
    return owner.topics ||= {selected:null,defaults:[],loaded:false,results:[],query:'',searchError:'',sequence:0,saving:false}
  }
  const effective = data => data.selected ?? data.defaults
  const summary = scope => {
    const data=state(scope)
    return (data.selected ? '本对话分区：' : '跟随后端默认：')
      + (effective(data).join(' / ') || '打开「发布分区」查看')
  }
  const options = scope => {
    const data=state(scope)
    return {...stateFor(scope).options,...(data.selected ? {topics:data.selected.slice()} : {})}
  }
  const update = (scope, name, remove=false) => {
    const data=state(scope)
    if(!data.loaded)return {toast:'请先连接后端并刷新默认分区'}
    const current=effective(data)
    const next=remove ? current.filter(x=>key(x)!==key(name)) : [...current,name]
    if(!validTopics(next))return {toast:remove?'至少保留一个分区':'最多选择五个分区'}
    data.selected=next
    return {refresh:true}
  }
  const search=async(scope,query)=>{
    if(typeof query!=='string'||query.trim().length>100)return {toast:'在输入框写分区名称，最多一百字'}
    const data=state(scope), value=query.trim()
    if(!value)return {toast:'请填写分区名称'}
    const sequence=++data.sequence
    data.query=value;data.results=[];data.searchError=''
    try{
      const response=await client.findTopics(value)
      if(sequence!==data.sequence)return {toast:'已有更新的分区搜索'}
      const seen=new Set()
      data.results=(response.items||[]).filter(item=>{
        if(!item||typeof item.name!=='string'||!item.name.trim()||item.name.length>100
          ||!/^\d{1,20}$/.test(String(item.topic_id)))return false
        if(seen.has(String(item.topic_id)))return false
        seen.add(String(item.topic_id));return true
      }).slice(0,8).map(item=>({name:item.name.trim(),id:String(item.topic_id)}))
    }catch{
      if(sequence!==data.sequence)return {toast:'已有更新的分区搜索'}
      data.searchError='搜索暂不可用，请确认已登录并启动 0.7.0 或更新的小黑盒后端。'
    }
    return {refresh:true}
  }
  ctx.dshGo.panel('topics',{
    view:(_scope,caps)=>caps?.components?.includes('textField')&&caps.components.includes('form')?topicsView:legacyTopicsView,
    data:(scope,emit)=>{
      const controller=new AbortController();let closed=false
      void(async()=>{
        const data=state(scope)
        let status='设置用于本对话的新任务。'
        try{
          const defaults=await client.preferences(controller.signal)
          if(closed)return
          if(!validTopics(defaults.topics))throw new Error('invalid defaults')
          data.defaults=defaults.topics.slice();data.loaded=true
        }catch{
          if(closed)return
          data.loaded=false
          status='默认分区读取失败，请启动 0.7.0 或更新的后端后刷新。'
        }
        if(closed)return
        const current=effective(data)
        emit({status,summary:summary(scope),search:{query:data.query},
          selected:current.map(name=>({title:name,subtitle:'点击移除',action:{id:'remove-topic',args:{name}}})),
          presets:data.loaded?presets.map(name=>({label:(current.some(x=>key(x)===key(name))?'✓ ':'+ ')+name,action:{id:'toggle-topic',args:{name}}})):[],
          searchStatus:data.searchError||(data.query?`「${data.query}」的搜索结果${data.results.length?' · 点击添加':' · 未找到分区'}`:''),
          results:data.results.map(item=>({title:item.name,subtitle:'ID '+item.id+' · 点击添加',action:{id:'add-topic',args:item}})),
        })
      })()
      return()=>{closed=true;controller.abort()}
    },
    actions:{
      'back-desk':()=>({open:'panel:desk'}),
      'search-topics':(scope,event)=>search(scope,event.value?.values?.['data.search.query']),
      'reload-topics':()=>({refresh:true}),
      'inherit-topics':scope=>{state(scope).selected=null;return {refresh:true,toast:'后续新任务跟随后端默认分区'}},
      'toggle-topic':(scope,event)=>{
        const name=event.value?.name
        if(!presets.includes(name))return {toast:'请选择有效分区'}
        return update(scope,name,effective(state(scope)).some(x=>key(x)===key(name)))
      },
      'remove-topic':(scope,event)=>{
        const name=event.value?.name
        if(!effective(state(scope)).includes(name))return {toast:'分区已变化，请刷新'}
        return update(scope,name,true)
      },
      'add-topic':(scope,event)=>{
        const data=state(scope), item=data.results.find(x=>x.id===event.value?.id&&x.name===event.value?.name)
        if(!item)return {toast:'搜索结果已变化，请重新搜索'}
        if(effective(data).some(x=>key(x)===key(item.name)))return {toast:'已经选择这个分区'}
        return update(scope,item.name)
      },
      'save-topics':async scope=>{
        const data=state(scope)
        if(!data.loaded)return {toast:'请先连接后端并刷新默认分区'}
        if(data.saving)return {toast:'正在保存，请稍候刷新核对'}
        const topics=effective(data).slice()
        if(!validTopics(topics))return {toast:'请选择一至五个分区'}
        data.saving=true
        try{
          const response=await client.savePreferences(topics)
          if(!validTopics(response.topics))throw new Error('invalid defaults')
          data.defaults=response.topics.slice()
          return {refresh:true,toast:'已设为默认，网页和手机的新任务共用'}
        }catch{return {toast:'保存未确认，请刷新默认分区核对'}}
        finally{data.saving=false}
      },
    },
  })
  return {options,summary}
}
