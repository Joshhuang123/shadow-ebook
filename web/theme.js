/*
  Shadow Ebook - 主题系统
  统一管理日/夜/跟随系统主题
*/
(function(){
  var T={
    day:  {'--primary':'#B86A4E','--primary-light':'#D89B7E','--secondary':'#6B8A52','--bg':'#FAF9F6','--card':'#FFFFFF','--text':'#2D2A26','--sub':'#5A544C','--border':'#D6CFC0','--accent':'#D4A574','--nav':'#FFFFFF','--shadow':'0 4px 20px rgba(115,99,78,0.15)','--body':'linear-gradient(135deg,#F5EDE5 0%,#EDE3D6 100%)','--input':'#F5F2EC','--btn-hover':'#A55E42'},
    night:{'--primary':'#D89B7E','--primary-light':'#E8C4B0','--secondary':'#8FAA7A','--bg':'#2A2520','--card':'#352F28','--text':'#F5F2EC','--sub':'#A39A8E','--border':'#5A5048','--accent':'#D4A574','--nav':'#352F28','--shadow':'0 4px 20px rgba(0,0,0,0.5)','--body':'linear-gradient(135deg,#2A2520 0%,#1F1B17 100%)','--input':'#352F28','--btn-hover':'#CC785C'}
  };
  var apply=function(m){
    if(m==='system'){document.documentElement.removeAttribute('data-theme');localStorage.removeItem('shTheme');}
    else if(T[m]){Object.entries(T[m]).forEach(function(e){document.documentElement.style.setProperty(e[0],e[1]);});localStorage.setItem('shTheme',m);}
    updateBtn(m||'system');
  };
  var updateBtn=function(m){
    var b=document.getElementById('themeBtn');
    if(b){
      var icons={day:'☀',night:'☾',system:'◐'};
      b.textContent=icons[m]||'◐';
      b.title={day:'日间模式',night:'夜间模式',system:'跟随系统'}[m]||'跟随系统';
      b.style.minWidth='36px';
      b.style.textAlign='center';
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
