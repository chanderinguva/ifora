import {getChatGPTUser} from '../../chatgpt-auth';
export async function GET(){const user=await getChatGPTUser();return Response.json(user?{name:user.displayName,email:user.email}:{error:'Sign in required'},{status:user?200:401,headers:{'Cache-Control':'private, no-store'}})}
