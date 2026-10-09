export class ApiError extends Error {constructor(public status:number,message:string){super(message)}}
let csrf='';
export function setCsrf(token:string){csrf=token}
export async function api<T>(path:string, options:RequestInit={}):Promise<T>{
  const headers=new Headers(options.headers);
  if(options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
  if(csrf)headers.set('X-CSRF-Token',csrf);
  const response=await fetch('/api'+path,{...options,headers,credentials:'same-origin'});
  if(!response.ok){const body=await response.json().catch(()=>null);throw new ApiError(response.status,body?.error?.message ?? `Request failed (${response.status})`)}
  return response.status===204?undefined as T:response.json();
}
export type User={username:string;roles:string[];csrf_token:string};
export type ImageRow={id:number;filename:string;batch:string;width:number;height:number;decision:string;quality_score:number;failures:string[];label:'good'|'bad'|null;blur_score:number;mean_luma:number;signature:string};
export type Policy={blur_min:number;luma_min:number;luma_max:number;clip_max:number;contrast_min:number;review_margin:number};
export type Group={signature:string;count:number;mean_quality:number;image_ids:number[]};
export type Cluster={index:number;size:number;description:string;dominant_failure:string;failure_rate:number};
export type Advice={text:string;source:string;warning:string|null;advisory_only:boolean};
