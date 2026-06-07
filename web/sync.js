/*
  Shadow Ebook - 数据上报到 server
  child 端 (ebook/tutor/grammar/stats) 调用 shadowReport(payload) 把 stats/vocab
  同步到 server, 让家长 dashboard 跨设备 / 跨 session 也能看到
*/
(function(){
  function report(payload){
    if(!navigator.onLine || !payload) return;
    try{
      fetch('/api/parent/data',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),
        credentials:'omit',
        keepalive:true
      }).catch(()=>{});
    }catch(e){}
  }
  window.shadowReport=report;
})();
