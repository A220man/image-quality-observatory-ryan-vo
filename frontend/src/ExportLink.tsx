export function ExportLink({batch}:{batch:string}){
 const query=batch?'?batch='+encodeURIComponent(batch):'';
 return <a className="button" href={'/api/exports/decisions.csv'+query}>Export batch decisions</a>;
}
