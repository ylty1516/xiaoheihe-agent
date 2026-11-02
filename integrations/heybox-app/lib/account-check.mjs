// Accept the account's actual task variants while keeping the identity check strict.
import { accountProfile } from './vendor/profile.js'
export function snapshot(result,account){
 if(String(result?.user?.userid)!==account)throw new Error('登录账号核对失败')
 if(!Array.isArray(result?.task_list)||!result.task_list.some(group=>Array.isArray(group.tasks)&&group.tasks.length))throw new Error('无法读取登录账号的任务')
 return {profile:accountProfile(result.user)}
}
