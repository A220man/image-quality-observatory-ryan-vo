import {afterEach,expect,it,vi} from 'vitest';
import {api,ApiError,setCsrf} from './api';
afterEach(()=>{vi.unstubAllGlobals();setCsrf('')});
it('sends session credentials and CSRF with JSON mutations',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify({ok:true})));
 vi.stubGlobal('fetch',fetcher);setCsrf('csrf-test');
 expect(await api('/policy',{method:'PUT',body:'{}'})).toEqual({ok:true});
 const [url,options]=fetcher.mock.calls[0];expect(url).toBe('/api/policy');
 expect(options.credentials).toBe('same-origin');expect(options.headers.get('X-CSRF-Token')).toBe('csrf-test');
 expect(options.headers.get('Content-Type')).toBe('application/json');
});
it('lets the browser set the multipart boundary',async()=>{
 const fetcher=vi.fn().mockResolvedValue(new Response('{}'));vi.stubGlobal('fetch',fetcher);
 const data=new FormData();data.set('batch','qa');await api('/images',{method:'POST',body:data});
 expect(fetcher.mock.calls[0][1].headers.has('Content-Type')).toBe(false);
});
it('handles successful empty delete responses',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(null,{status:204})));
 expect(await api('/images/1',{method:'DELETE'})).toBeUndefined();
});
it('preserves status and server error message',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({error:{message:'Session expired'}}),{status:401})));
 await expect(api('/images')).rejects.toMatchObject({status:401,message:'Session expired'});
});
it('handles reverse proxy HTML errors without leaking the body',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('<h1>internal host</h1>',{status:502})));
 await expect(api('/images')).rejects.toEqual(new ApiError(502,'Request failed (502)'));
});
