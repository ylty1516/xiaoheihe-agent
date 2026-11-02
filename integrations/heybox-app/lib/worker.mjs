import { createInterface } from 'node:readline'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { NativeService, safeError, NativeError } from './service.mjs'
const root=resolve(process.argv[2]||'.'),service=new NativeService(root),require=createRequire(import.meta.url)
const input=createInterface({input:process.stdin,crlfDelay:Infinity,terminal:false})
for await(const line of input){
 let request
 try{
  if(Buffer.byteLength(line)>8192)throw new NativeError('invalid_request','请求内容过大。')
  request=JSON.parse(line)
  const expected=request.expected_account??''
  if(typeof expected!=='string'||!/^\d*$/.test(expected))throw new NativeError('invalid_request','账号格式无效。')
  let data
  switch(request.action){
   case 'status':{
    let runtimeReady=true
    try{require.resolve('jsdom');require.resolve('fingerprint-generator')}catch{runtimeReady=false}
    data={...service.status(expected),runtime_ready:runtimeReady};break
   }
   case 'send_code':data=await service.send(request.phone,expected);break
   case 'verify_code':data=await service.verify(request.login_id,request.code,expected);break
   case 'read':data=await service.read(expected);break
   case 'run':
    if(request.confirm!==true)throw new NativeError('confirmation_required','执行每日签到和分享流程需要明确授权。')
    data=await service.run(expected);break
   default:throw new NativeError('invalid_request','不支持的操作。')
  }
  process.stdout.write(JSON.stringify({id:request.id,ok:true,data})+'\n')
 }catch(error){process.stdout.write(JSON.stringify({id:request?.id,ok:false,...safeError(error)})+'\n')}
}
