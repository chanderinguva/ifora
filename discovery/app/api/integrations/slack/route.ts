import {blank} from '../../../../lib/ideas';
import {recoverIdeaOwner,resolvePrimaryOwner,saveIdea} from '../../../../lib/idea-store';

export const dynamic='force-dynamic';

type SlackCapture={
  ideaId:string;
  title:string;
  raw:string;
  sourceUrl:string;
  eventKey:string;
  files?:Array<{id?:string;name?:string;mimetype?:string;size?:number}>;
};

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

async function sameSecret(provided:string,expected:string){
  if(!provided||!expected)return false;
  const enc=new TextEncoder();
  const [a,b]=await Promise.all([
    crypto.subtle.digest('SHA-256',enc.encode(provided)),
    crypto.subtle.digest('SHA-256',enc.encode(expected)),
  ]);
  const aa=new Uint8Array(a),bb=new Uint8Array(b);
  let diff=aa.length^bb.length;
  for(let i=0;i<Math.max(aa.length,bb.length);i++)diff|=(aa[i]||0)^(bb[i]||0);
  return diff===0;
}

function validCapture(value:unknown):value is SlackCapture{
  if(!value||typeof value!=='object')return false;
  const v=value as Record<string,unknown>;
  return typeof v.ideaId==='string'&&uuid.test(v.ideaId)&&
    typeof v.title==='string'&&v.title.trim().length>0&&v.title.length<=180&&
    typeof v.raw==='string'&&v.raw.trim().length>0&&v.raw.length<=50000&&
    typeof v.sourceUrl==='string'&&v.sourceUrl.length<=2000&&
    typeof v.eventKey==='string'&&v.eventKey.length>0&&v.eventKey.length<=300;
}

export async function POST(req:Request){
  const expected=process.env.IFORA_DISCOVERY_INGEST_TOKEN||'';
  const configuredOwner=process.env.IFORA_DISCOVERY_OWNER_ID||'';
  const auth=req.headers.get('authorization')||'';
  const token=auth.startsWith('Bearer ')?auth.slice(7):'';
  if(!expected||!configuredOwner)return Response.json({error:'Slack ingestion is not configured'},{status:503});
  if(!(await sameSecret(token,expected)))return Response.json({error:'Unauthorized'},{status:401});
  if(Number(req.headers.get('content-length')||0)>65536)return Response.json({error:'Payload too large'},{status:413});
  let body:unknown;
  try{body=await req.json()}catch{return Response.json({error:'Invalid JSON'},{status:400})}
  if(!validCapture(body))return Response.json({error:'Invalid capture'},{status:422});
  if(body.sourceUrl){
    let source:URL;
    try{source=new URL(body.sourceUrl)}catch{return Response.json({error:'Invalid Slack link'},{status:422})}
    if(source.protocol!=='https:'||!source.hostname.endsWith('.slack.com'))return Response.json({error:'Invalid Slack link'},{status:422});
  }
  const owner=await resolvePrimaryOwner(configuredOwner);
  const existing=await recoverIdeaOwner(body.ideaId,owner);
  if(existing)return Response.json({id:existing.id,revision:existing.revision,deduplicated:true});
  const now=new Date().toISOString();
  const idea=await saveIdea(owner,{
    ...blank(),id:body.ideaId,title:body.title.trim(),raw:body.raw,source:'Slack',sourceUrl:body.sourceUrl,
    links:body.sourceUrl?[{label:'Open original Slack message',url:body.sourceUrl}]:[],
    history:[{at:now,text:`Captured from Slack message ${body.eventKey}`}],
  });
  return Response.json({id:idea.id,revision:idea.revision,deduplicated:false},{status:201});
}
