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
export type MetricStats={count:number;min:number;max:number;mean:number;std:number;p10:number;p25:number;p50:number;p75:number;p90:number;iqr:number};
export type DecisionBreakdown={accept_count:number;accept_rate:number;review_count:number;review_rate:number;reject_count:number;reject_rate:number};
export type LabelAlignment={total_labeled:number;good_count:number;bad_count:number;unlabeled_count:number;concordant_count:number;discordant_count:number;review_count:number;agreement_rate:number|null};
export type FailureFrequency={check:string;count:number;frequency:number};
export type DatasetDistribution={total_images:number;decisions:DecisionBreakdown;labels:LabelAlignment;metrics:Record<string,MetricStats>;top_failures:FailureFrequency[];health_status:'healthy'|'degraded'|'critical'|'empty'};
export type KSResult={metric:string;statistic:number;p_value:number;sample_a_count:number;sample_b_count:number;drift_detected:boolean};
export type DriftComparison={batch_a:string;batch_b:string;total_a:number;total_b:number;ks_results:KSResult[];overall_drift:boolean};
