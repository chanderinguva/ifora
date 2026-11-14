import {env} from 'cloudflare:workers';
import {getChatGPTUser} from '../../../chatgpt-auth';
import {attachmentKey} from '../../../../lib/attachments';
const headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; sandbox"};
export async function GET(_req:Request,{params}:{params:Promise<{id:string}>}){const user=await getChatGPTUser();if(!user)return new Response('Sign in to view this attachment',{status:401,headers});if(!env.BUCKET)return new Response(null,{status:503,headers});let key;try{key=await attachmentKey(user.userId,(await params).id)}catch{return new Response(null,{status:404,headers})}const image=await env.BUCKET.get(key);if(!image)return new Response(null,{status:404,headers});return new Response(image.body,{headers:{...headers,'Content-Type':'image/webp'}})}
