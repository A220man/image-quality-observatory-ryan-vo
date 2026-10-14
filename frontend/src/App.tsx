import {ExportLink} from './ExportLink';
import {useEffect,useState,type FormEvent} from 'react';
import {api,ApiError,setCsrf,type User,type ImageRow,type Policy,type Group,type Cluster,type Advice,type DatasetDistribution,type DriftComparison,type KSResult} from './api';

const policyLabels:Record<keyof Policy,string>={blur_min:'Minimum sharpness',luma_min:'Minimum luminance',luma_max:'Maximum luminance',clip_max:'Maximum clipped fraction',contrast_min:'Minimum contrast',review_margin:'Review margin'};

function Badge({label, variant}:{label:string;variant:'accept'|'reject'|'review'}){
  return <span className={'badge '+variant}>{label}</span>;
}

function DriftTab({driftBatchA, driftBatchB, setDriftBatchA, setDriftBatchB, loadDrift, drift, busy}:{
  driftBatchA:string;driftBatchB:string;setDriftBatchA:(v:string)=>void;setDriftBatchB:(v:string)=>void;
  loadDrift:()=>void;drift:DriftComparison|null;busy:boolean
}){
  if(!drift) return <form onSubmit={e=>{e.preventDefault();loadDrift()}}><label>Batch A<input value={driftBatchA} onChange={e=>setDriftBatchA(e.target.value)} placeholder="Batch name" required/></label><label>Batch B<input value={driftBatchB} onChange={e=>setDriftBatchB(e.target.value)} placeholder="Batch name" required/></label><button disabled={busy||!driftBatchA.trim()||!driftBatchB.trim()} type="submit">Compare</button></form>;

  const driftBadge = drift.overall_drift ? 'reject' : 'accept';
  const driftLabel = drift.overall_drift ? 'Detected' : 'None';

  const ksRows = drift.ks_results.map((ks:KSResult,i)=>{
    if(ks.sample_a_count===0||ks.sample_b_count===0) return null;
    const ksVariant = ks.drift_detected ? 'reject' : 'accept';
    const ksLabel = ks.drift_detected ? 'Yes' : 'No';
    return <tr key={i}><td>{ks.metric}</td><td>{ks.statistic.toFixed(4)}</td><td>{ks.p_value.toFixed(4)}</td><td>{ks.sample_a_count}</td><td>{ks.sample_b_count}</td><td><Badge label={ksLabel} variant={ksVariant}/></td></tr>;
  });

  return (
    <>
      <form onSubmit={e=>{e.preventDefault();loadDrift()}}>
        <label>Batch A<input value={driftBatchA} onChange={e=>setDriftBatchA(e.target.value)} placeholder="Batch name" required/></label>
        <label>Batch B<input value={driftBatchB} onChange={e=>setDriftBatchB(e.target.value)} placeholder="Batch name" required/></label>
        <button disabled={busy||!driftBatchA.trim()||!driftBatchB.trim()} type="submit">Compare</button>
      </form>
      <div className="health-badge-row">
        <Badge label={'Drift: '+driftLabel} variant={driftBadge}/>
        <span>Batch A: {drift.batch_a} ({drift.total_a} images)</span>
        <span>Batch B: {drift.batch_b} ({drift.total_b} images)</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Metric</th><th>KS Statistic</th><th>P-value</th><th>Batch A count</th><th>Batch B count</th><th>Drift</th></tr></thead>
          <tbody>{ksRows}</tbody>
        </table>
      </div>
      <p className="muted">P-value &lt; 0.05 indicates statistically significant distribution drift.</p>
    </>
  );
}

export function App(){
 const [user,setUser]=useState<User|null>(null),[loading,setLoading]=useState(true),[mode,setMode]=useState('oidc');
 const [error,setError]=useState(''),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[tab,setTab]=useState('Review');
 const [rows,setRows]=useState<ImageRow[]>([]),[total,setTotal]=useState(0),[offset,setOffset]=useState(0);
 const [batch,setBatch]=useState(''),[filter,setFilter]=useState(''),[decision,setDecision]=useState('');
 const [policy,setPolicy]=useState<Policy|null>(null),[groups,setGroups]=useState<Group[]>([]),[clusters,setClusters]=useState<Cluster[]>([]);
 const [advice,setAdvice]=useState<Advice|null>(null),[analysis,setAnalysis]=useState<unknown>(null),[audit,setAudit]=useState<unknown[]>([]);
 const [dist,setDist]=useState<DatasetDistribution|null>(null);
 const [drift,setDrift]=useState<DriftComparison|null>(null);
 const [driftBatchA,setDriftBatchA]=useState(''),[driftBatchB,setDriftBatchB]=useState('');
 const admin=user?.roles.includes('admin'),reviewer=admin||user?.roles.includes('reviewer');
 function acceptUser(value:User){setCsrf(value.csrf_token);setUser(value)}
 async function task(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn()}catch(e){setError(e instanceof Error?e.message:'Unexpected error');if(e instanceof ApiError&&e.status===401){setUser(null);setCsrf('')}}finally{setBusy(false)}}
 async function loadRows(page=offset,selected=filter,status=decision){const q=new URLSearchParams({limit:'25',offset:String(page)});if(selected)q.set('batch',selected);if(status)q.set('decision',status);const data=await api<{items:ImageRow[];total:number}>('/images?'+q);setRows(data.items);setTotal(data.total);setOffset(page)}
 const batchQuery=filter?'?batch='+encodeURIComponent(filter):'';
 useEffect(()=>{(async()=>{try{setMode((await api<{mode:string}>('/auth/mode')).mode);try{acceptUser(await api<User>('/auth/me'))}catch(e){if(!(e instanceof ApiError&&e.status===401))throw e}}catch(e){setError(String(e))}finally{setLoading(false)}})()},[]);
 useEffect(()=>{if(user)void task(async()=>{await loadRows(0);setPolicy(await api<Policy>('/policy'))})},[user]);
 async function upload(event:FormEvent<HTMLFormElement>){event.preventDefault();const form=event.currentTarget;const input=form.elements.namedItem('images') as HTMLInputElement;const files=Array.from(input.files??[]);if(!files.length)return;await task(async()=>{let created=0,duplicates=0;const failures:string[]=[];for(const file of files){const data=new FormData();data.set('file',file);data.set('batch',batch.trim()||'default');try{const result=await api<{created:boolean}>('/images',{method:'POST',body:data});result.created?created++:duplicates++}catch(e){failures.push(`${file.name}: ${e instanceof Error?e.message:String(e)}`)}}await loadRows(0);setNotice(`${created} imported; ${duplicates} already present.`);if(failures.length)setError(failures.join('\n'));})}
 async function showTab(next:string){setTab(next);setAnalysis(null);setDrift(null);await task(async()=>{if(next==='Analysis'){const [g,c,d]=await Promise.all([api<{groups:Group[]}>('/analysis/groups'+batchQuery),api<{clusters:Cluster[]}>('/analysis/clusters'+batchQuery),api<DatasetDistribution>('/analysis/distribution'+batchQuery)]);setGroups(g.groups);setClusters(c.clusters);setDist(d)}if(next==='Audit')setAudit((await api<{events:unknown[]}>('/audit')).events)})}
 async function loadDrift(){if(!driftBatchA.trim()||!driftBatchB.trim())return;await task(async()=>{const d=await api<DriftComparison>(`/analysis/drift?batch_a=${encodeURIComponent(driftBatchA)}&batch_b=${encodeURIComponent(driftBatchB)}`);setDrift(d)})}
 if(loading)return <main><p role="status">Loading session…</p></main>;
 return <><header><div><span className="eyebrow">DATASET OPERATIONS / RYAN VO</span><h1>Image Quality Observatory</h1><p>Find weak images. Understand patterns. Review with evidence.</p></div>{user&&<div className="identity"><span>{user.username} · {user.roles.join(', ')}</span><button disabled={busy} onClick={()=>void task(async()=>{await api('/auth/logout',{method:'POST'});setCsrf('');setUser(null);setRows([])})}>Sign out</button></div>}</header>
 <main>{error&&<div role="alert" className="error">{error}</div>}{notice&&<div role="status" className="notice">{notice}</div>}
 {!user?<section className="login"><h2>Review your image datasets</h2><p>Measure sharpness, exposure and contrast. Group quality failures, label examples and calibrate a review policy.</p>{mode==='demo'?<><p>Local demo session — development only.</p><button disabled={busy} onClick={()=>void task(async()=>acceptUser(await api<User>('/auth/demo',{method:'POST'})))}>Enter local workspace</button></>:<a className="button" href="/api/auth/login">Sign in with your organization</a>}</section>:<>
 <nav aria-label="Workspace">{['Review','Analysis','Drift','Policy',...(admin?['Audit']:[])].map(name=><button key={name} aria-current={tab===name?'page':undefined} disabled={busy} onClick={()=>void showTab(name)}>{name}</button>)}</nav>
 <form className="filters" onSubmit={e=>{e.preventDefault();void task(async()=>{await loadRows(0,batch,decision);setFilter(batch);setAdvice(null);setAnalysis(null);setDist(null);setDrift(null);setTab('Review')})}}><label>Batch<input value={batch} onChange={e=>setBatch(e.target.value)} maxLength={100} placeholder="All batches"/></label><label>Decision<select value={decision} onChange={e=>setDecision(e.target.value)}><option value="">All decisions</option>{['accept','review','reject'].map(d=><option key={d}>{d}</option>)}</select></label><button disabled={busy}>Apply filters</button><span className="muted">Analysis scope: {filter||'all batches'}</span></form>
 {tab==='Review'&&<><section><h2>Image review queue <span className="count">{total}</span></h2>{reviewer&&<form className="upload" onSubmit={upload}><label>Import images into {batch.trim()||'default'}<input name="images" type="file" accept="image/*" multiple required/></label><button disabled={busy}>Measure & import</button></form>}<ExportLink batch={filter}/><p className="muted">Images are measured in memory. Only metrics and metadata are retained.</p><div className="table-wrap"><table><thead><tr><th>Image</th><th>Decision</th><th>Quality</th><th>Failed checks</th><th>Human label</th>{admin&&<th>Manage</th>}</tr></thead><tbody>{rows.map(row=><tr key={row.id}><td><strong>{row.filename}</strong><small>{row.width} × {row.height} · {row.batch}</small></td><td><Badge label={row.decision} variant={row.decision==='accept'?'accept':row.decision==='reject'?'reject':'review'}/></td><td>{row.quality_score.toFixed(1)}</td><td>{row.failures.join(', ')||'—'}</td><td>{row.label||'—'}</td>{admin&&<td><button disabled={busy} onClick={()=>void task(async()=>{await api(`/images/${row.id}`,{method:'DELETE'});await loadRows()})}>Delete</button></td>}</tr>)}</tbody></table></div></section></>}
 {tab==='Analysis'&&<><section><h2>Quality distribution & health</h2>{dist&&dist.total_images>0?<><div className="health-badge-row"><Badge label={'Health: '+dist.health_status} variant={dist.health_status==='healthy'?'accept':dist.health_status==='critical'?'reject':'review'}/><span>Pass: {(dist.decisions.accept_rate*100).toFixed(1)}%</span><span>Review: {(dist.decisions.review_rate*100).toFixed(1)}%</span><span>Reject: {(dist.decisions.reject_rate*100).toFixed(1)}%</span>{dist.labels.agreement_rate!==null&&<span>Label agreement: {(dist.labels.agreement_rate*100).toFixed(1)}%</span>}</div><div className="table-wrap"><table><thead><tr><th>Metric</th><th>Mean ± Std</th><th>Median (IQR)</th><th>Min – Max</th><th>p10 – p90</th></tr></thead><tbody>{Object.entries(dist.metrics).map(([key,stat])=><tr key={key}><td>{key}</td><td>{stat.mean.toFixed(2)} ± {stat.std.toFixed(2)}</td><td>{stat.p50.toFixed(2)} ({stat.iqr.toFixed(2)})</td><td>{stat.min.toFixed(2)} – {stat.max.toFixed(2)}</td><td>{stat.p10.toFixed(2)} – {stat.p90.toFixed(2)}</td></tr>)}</tbody></table></div><h3>Top failure checks</h3><div className="table-wrap"><table><thead><tr><th>Check</th><th>Count</th><th>Frequency</th></tr></thead><tbody>{dist.top_failures.map((f,i)=><tr key={i}><td>{f.check}</td><td>{f.count}</td><td>{(f.frequency*100).toFixed(1)}%</td></tr>)}</tbody></table></div></>:<p className="muted">No images in the selected batch scope.</p>}</section><section><h2>Failure signatures</h2>{groups.length>0?<div className="table-wrap"><table><thead><tr><th>Signature</th><th>Count</th><th>Mean quality</th><th>Image IDs</th></tr></thead><tbody>{groups.map(g=><tr key={g.signature}><td>{g.signature}</td><td>{g.count}</td><td>{g.mean_quality.toFixed(1)}</td><td>{g.image_ids.join(', ')}</td></tr>)}</tbody></table></div>:<p className="muted">No failure groups in the selected batch scope.</p>}</section><section><h2>Metric clusters</h2>{clusters.length>0?<div className="table-wrap"><table><thead><tr><th>Cluster</th><th>Size</th><th>Dominant failure</th><th>Failure rate</th><th>Description</th></tr></thead><tbody>{clusters.map(c=><tr key={c.index}><td>{c.index}</td><td>{c.size}</td><td>{c.dominant_failure}</td><td>{(c.failure_rate*100).toFixed(1)}%</td><td>{c.description}</td></tr>)}</tbody></table></div>:<p className="muted">No clusters in the selected batch scope.</p>}</section></>}
 {tab==='Drift'&&<section><h2>Dataset drift comparison</h2><p>Compare quality distributions between two batches using two-sample Kolmogorov-Smirnov tests.</p><DriftTab driftBatchA={driftBatchA} driftBatchB={driftBatchB} setDriftBatchA={setDriftBatchA} setDriftBatchB={setDriftBatchB} loadDrift={loadDrift} drift={drift} busy={busy}/></section>}
 {tab==='Policy'&&policy&&<section><h2>Quality policy</h2><p>Saving re-evaluates every retained image and records an audit event. Human labels stay unchanged.</p><form onSubmit={e=>{e.preventDefault();if(confirm('Re-evaluate all images using these thresholds?'))void task(async()=>{await api('/policy',{method:'PUT',body:JSON.stringify(policy)});await loadRows();setNotice('Policy saved; all images re-evaluated.')})}}><div className="policy-grid">{(Object.keys(policyLabels) as (keyof Policy)[]).map(key=><label key={key}>{policyLabels[key]}<input type="number" step="any" required disabled={!admin||busy} value={policy[key]} onChange={e=>setPolicy({...policy,[key]:e.target.valueAsNumber})}/></label>)}</div>{admin?<button disabled={busy}>Save policy</button>:<p>Only administrators can modify the policy.</p>}</form></section>}
 {tab==='Audit'&&admin&&<section><h2>Audit trail</h2><p>Latest 100 events, including retained records of deleted images.</p><pre>{JSON.stringify(audit,null,2)}</pre></section>}
 </>}{busy&&<p role="status" className="working">Working…</p>}</main><footer>Built by Ryan Vo · <a href="mailto:ryandtvo@gmail.com">ryandtvo@gmail.com</a> · v1.0.0</footer></>;
}