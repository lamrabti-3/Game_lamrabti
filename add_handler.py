# -*- coding: utf-8 -*-
path = 'index.html'
src = open(path, 'r', encoding='utf-8').read()

if "startOfflineMode(0)" in src:
    print('✅ موجود مسبقاً')
    exit()

handler = r'''
/* ═══════ MODE BUTTONS HANDLER ═══════ */
document.querySelectorAll('.mode-btn').forEach(function(btn){
  btn.addEventListener('click', function(e){
    e.preventDefault();
    try{ initAudio(); }catch(x){}
    var mode = btn.dataset.mode;
    if(dom.inName){
      S.myName = (dom.inName.value || '').trim().slice(0,16);
      if(S.myName) localStorage.setItem('ba_name', S.myName);
    }
    if(dom.inServer){
      S.serverUrl = (dom.inServer.value || '').trim();
      if(S.serverUrl) localStorage.setItem('ba_server', S.serverUrl);
      else localStorage.removeItem('ba_server');
    }
    if(mode === 'offline'){
      setScreen('loading');
      if(dom.loadTxt) dom.loadTxt.textContent = 'جاري التجهيز...';
      if(!S.mapData) S.mapData = LOCAL_MAPS;
      setTimeout(function(){
        try{ startOfflineMode(0); }
        catch(err){
          console.error(err);
          if(dom.loadTxt) dom.loadTxt.textContent = 'خطأ: ' + err.message;
          setTimeout(function(){ setScreen('menu'); }, 2500);
        }
      }, 200);
      return;
    }
    if(mode === 'lan'){
      if(!S.serverUrl){
        toast('⚠️ أدخل IP مثل 192.168.1.5:8080', 3000);
        return;
      }
      if(!/^wss?:\/\//.test(S.serverUrl)){
        S.serverUrl = 'ws://' + S.serverUrl;
        localStorage.setItem('ba_server', S.serverUrl);
      }
    }
    setScreen('loading');
    if(dom.loadTxt) dom.loadTxt.textContent = 'جاري الاتصال...';
    connectWS();
    var check = setInterval(function(){
      if(S.ws && S.ws.readyState === 1 && S.myId){
        clearInterval(check);
        setScreen('playing');
      } else if(S.ws && S.ws.readyState > 1){
        clearInterval(check);
      }
    }, 150);
    setTimeout(function(){
      if(S.mode === 'loading'){
        clearInterval(check);
        setConn('⏱️ timeout', 'off');
        if(dom.loadTxt) dom.loadTxt.textContent = 'فشل الاتصال';
        setTimeout(function(){ setScreen('menu'); }, 2000);
      }
    }, 12000);
  });
});
'''

# ═══════ نضيف قبل boot ═══════
markers = ['function boot(){', 'function boot() {', 'function boot (){', 'boot();']
done = False
for m in markers:
    if m in src:
        src = src.replace(m, handler + '\n' + m, 1)
        print('✅ انضاف قبل:', m)
        done = True
        break

if not done:
    idx = src.rfind('})();')
    if idx > 0:
        src = src[:idx] + handler + '\n' + src[idx:]
        print('✅ انضاف قبل })();')
        done = True

if done:
    open(path, 'w', encoding='utf-8').write(src)
    print('✅ تم الحفظ')
else:
    print('❌ فشل')
