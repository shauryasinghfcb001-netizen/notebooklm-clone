self.addEventListener('install',e=>{self.skipWaiting()});
self.addEventListener('fetch',e=>{
  if(e.request.method!=='GET')return;
  e.respondWith(caches.open('nb-v1').then(c=>c.match(e.request).then(r=>{
    const f=fetch(e.request).then(res=>{if(res.ok)c.put(e.request,res.clone());return res}).catch(()=>r);
    return r||f;
  })));
});
