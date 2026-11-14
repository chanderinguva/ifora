import {eq,and} from 'drizzle-orm';import {getDb} from '../db';import {ideas} from '../db/schema';import {ideaSchema} from './ideas';
export async function listIdeas(owner:string){return (await getDb().select().from(ideas).where(eq(ideas.owner,owner))).map(r=>({...JSON.parse(r.data),revision:r.revision}));}
export async function resolvePrimaryOwner(configuredOwner:string){
  const rows=await getDb().select({owner:ideas.owner}).from(ideas);
  if(!rows.length)return configuredOwner;
  const counts=new Map<string,number>();
  for(const row of rows)counts.set(row.owner,(counts.get(row.owner)||0)+1);
  const ranked=[...counts.entries()].sort((a,b)=>b[1]-a[1]);
  if(ranked.length>1&&ranked[0][1]===ranked[1][1])throw new Error('Discovery owner is ambiguous');
  return ranked[0][0];
}
export async function recoverIdeaOwner(id:string,owner:string){
  const db=getDb();
  const row=(await db.select().from(ideas).where(eq(ideas.id,id)))[0];
  if(!row)return null;
  if(row.owner!==owner)await db.update(ideas).set({owner,updatedAt:new Date().toISOString()}).where(eq(ideas.id,id));
  return {...JSON.parse(row.data),revision:row.revision};
}
export async function saveIdea(owner:string,input:unknown,revision?:number){const data=ideaSchema.parse(input);for(const url of [data.sourceUrl,...data.links.map(l=>l.url)])if(url&&!['https:','http:'].includes(new URL(url).protocol))throw new Error('Use HTTP or HTTPS links');const db=getDb();const where=and(eq(ideas.id,data.id),eq(ideas.owner,owner));const old=(await db.select().from(ideas).where(where))[0];const now=new Date().toISOString();if(old){if(revision!==old.revision)throw new Error('Conflict: this idea changed. Refresh before saving.');const result=await db.update(ideas).set({data:JSON.stringify(data),revision:old.revision+1,updatedAt:now}).where(and(where,eq(ideas.revision,revision))).returning();if(!result.length)throw new Error('Conflict: refresh before saving');return {...data,revision:old.revision+1}}await db.insert(ideas).values({id:data.id,owner,data:JSON.stringify(data),updatedAt:now});return {...data,revision:1}}
