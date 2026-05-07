/*
  Shadow Ebook - 主题系统
  统一管理日/夜/跟随系统主题
*/
(function(){
  var T={
    day:  {'--primary':'#6366F1','--primary-light':'#818CF8','--secondary':'#10B981','--bg':'#F8FAFC','--card':'#FFFFFF','--text':'#1E293B','--sub':'#64748B','--border':'#E2E8F0','--accent':'#F59E0B','--nav':'#FFFFFF','--shadow':'0 4px 20px rgba(0,0,0,0.1)','--body':'linear-gradient(135deg,#E0E7FF 0%,#F0FDF4 100%)','--input':'#F1F5F9','--btn-hover':'#4F46E5'},
    night:{'--primary':'#818CF8','--primary-light':'#A78BFA','--secondary':'#34D399','--bg':'#0F172A','--card':'#1E293B','--text':'#F1F5F9','--sub':'#94A3B8','--border':'#334155','--accent':'#FBBF24','--nav':'#1E293B','--shadow':'0 4px 20px rgba(0,0,0,0.5)','--body':'linear-gradient(135deg,#0F172A 0%,#1E1B4B 100%)','--input':'#334155','--btn-hover':'#6366F1'}
  };
  var apply=function(m){
    if(m==='system'){document.documentElement.removeAttribute('data-theme');localStorage.removeItem('shTheme');}
    else if(T[m]){Object.entries(T[m]).forEach(function(e){document.documentElement.style.setProperty(e[0],e[1]);});localStorage.setItem('shTheme',m);}
    updateBtn(m||'system');
  };
  var updateBtn=function(m){
    var b=document.getElementById('themeBtn');
    if(b){
      var labels={day:'日',night:'夜',system:'系'};
      b.textContent=labels[m]||'系';
      b.title={day:'日间模式',night:'夜间模式',system:'跟随系统'}[m]||'跟随系统';
    }
  };
  window.setTheme=apply;
  window.cycleTheme=function(){
    var s=localStorage.getItem('shTheme')||'system';
    var order=['day','night','system'];
    var idx=(order.indexOf(s)+1)%3;
    apply(order[idx]);
  };
  window.addEventListener('DOMContentLoaded',function(){
    var s=localStorage.getItem('shTheme')||'system';
    apply(s);
    var mq=window.matchMedia('(prefers-color-scheme:dark)');
    mq.addEventListener('change',function(){if(!localStorage.getItem('shTheme'))apply('system');});
  });
})();
