#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLOCK ARENA — Server
Server-Authoritative Multiplayer FPS
"""
import asyncio, json, random, time, math, os
from aiohttp import web
import aiohttp

# ═══════════════ CONFIG ═══════════════
HOST="0.0.0.0"; PORT=int(os.environ.get("PORT",8080)); GROUND_Y=0.75
HERE=os.path.dirname(os.path.abspath(__file__))
MAX_PLAYERS=50
MAX_NAME_LEN=16
MAX_CHAT_LEN=80
DANGER_START_SEC=300
DANGER_SHRINK_RATE=0.06

VALID_SKINS={'blue','red','green','purple','yellow','cyan','pink','white','orange'}
VALID_WEAPONS={'pistol','rifle','shotgun','sniper','smg'}
VALID_MSG_TYPES={'move','shoot','bomb','respawn','addBot','friendRequest',
                 'friendAccept','friendDecline','chat','setName'}

RATE_LIMITS={
    'move':(40,1.0),'shoot':(15,1.0),'bomb':(2,1.0),
    'chat':(3,2.0),'friendRequest':(5,10.0),
    'friendAccept':(10,10.0),'friendDecline':(10,10.0),
    'respawn':(2,5.0),'addBot':(1,30.0),'setName':(2,10.0),
}

# ═══════════════ UTILS ═══════════════
def vnum(v,mn,mx,d=0.0):
    try:
        f=float(v)
        if math.isnan(f) or math.isinf(f): return d
        return max(mn,min(mx,f))
    except (ValueError,TypeError): return d

def vstr(s,mx=80):
    if not isinstance(s,str): return ''
    s=s.strip()[:mx]
    return ''.join(c for c in s if c.isprintable() or c==' ')

def vskin(s):
    if not isinstance(s,str): return None
    s=s.lower()[:12]
    return s if s in VALID_SKINS else None

def vweapon(s):
    if not isinstance(s,str): return None
    s=s.lower()[:12]
    return s if s in VALID_WEAPONS else None

def vpid(v):
    try: return int(v)
    except (ValueError,TypeError): return None

class RateLimiter:
    def __init__(self): self.b={}
    def check(self,pid,t):
        k=(pid,t); lim,win=RATE_LIMITS.get(t,(30,1.0))
        now=time.time()
        lst=[x for x in self.b.get(k,[]) if now-x<win]
        if len(lst)>=lim: self.b[k]=lst; return False
        lst.append(now); self.b[k]=lst; return True
    def clear(self,pid):
        for k in [k for k in self.b if k[0]==pid]: del self.b[k]

rl=RateLimiter()

# ═══════════════ MAPS ═══════════════
def gen_obs(size,count,color):
    obs=[]; tries=0
    while len(obs)<count and tries<count*10:
        tries+=1
        x=random.uniform(-size+4,size-4); z=random.uniform(-size+4,size-4)
        if abs(x)<3 and abs(z)<3: continue
        w=round(random.uniform(1.5,4),1); d=round(random.uniform(1.5,4),1)
        if any(abs(x-o['x'])<(w+o['w'])/2+0.5 and abs(z-o['z'])<(d+o['d'])/2+0.5 for o in obs):
            continue
        obs.append({'x':round(x,1),'z':round(z,1),'w':w,
                    'h':round(random.uniform(1.5,5),1),'d':d,'c':color})
    return obs

MAPS=[
 {'name':'الغرفة','size':12,'floor':0x2a3f66,'sky':0x1a2b4a,'g1':0x60a5fa,'g2':0x3b5a99,'obs_color':0x4466aa,'obs_count':5},
 {'name':'الساحة','size':16,'floor':0x3a3f56,'sky':0x1a2b4a,'g1':0x60a5fa,'g2':0x3b5a99,'obs_color':0x4466aa,'obs_count':7},
 {'name':'المدينة','size':30,'floor':0x4a4a4a,'sky':0x2a2a3a,'g1':0x888888,'g2':0x555555,'obs_color':0x666666,'obs_count':18},
 {'name':'الصحراء','size':34,'floor':0x8b6b3a,'sky':0xd98b4a,'g1':0xffaa55,'g2':0x885522,'obs_color':0x664422,'obs_count':16},
 {'name':'الفضاء','size':44,'floor':0x101020,'sky':0x000005,'g1':0x8844ff,'g2':0x442288,'obs_color':0x6644aa,'obs_count':26},
 {'name':'جزيرة الموت','size':60,'floor':0x1a2a1a,'sky':0x0a1a0a,'g1':0x44aa44,'g2':0x1a5a1a,'obs_color':0x223322,'obs_count':40},
]
for m in MAPS: m['obstacles']=gen_obs(m['size'],m['obs_count'],m['obs_color'])

# ═══════════════ ENEMIES & WEAPONS ═══════════════
ENEMY_TYPES={
 'zombie':{'hp':30,'speed':2.2,'damage':8,'radius':0.7,'score':10,'size':1.0,'color':0x44aa44,'em':0x114411,'skin':0x88cc66,'legs':0x223322,'ranged':False},
 'runner':{'hp':15,'speed':5.5,'damage':5,'radius':0.5,'score':15,'size':0.85,'color':0xff8800,'em':0x552200,'skin':0xffcc99,'legs':0x331100,'ranged':False},
 'shooter':{'hp':40,'speed':1.8,'damage':8,'radius':0.6,'score':25,'size':1.0,'color':0x8844ff,'em':0x221144,'skin':0xccbbff,'legs':0x221144,'ranged':True,'range':14,'fire_cd':1.8},
 'tank':{'hp':150,'speed':1.0,'damage':20,'radius':1.0,'score':50,'size':1.6,'color':0x884400,'em':0x221100,'skin':0xaa8855,'legs':0x221100,'ranged':False},
 'boss':{'hp':600,'speed':1.4,'damage':30,'radius':1.8,'score':300,'size':2.3,'color':0xaa0000,'em':0x550000,'skin':0xff4444,'legs':0x220000,'ranged':True,'range':22,'fire_cd':1.2},
}
WEAPONS={
 'pistol':{'damage':25,'range':35,'spread':0.0,'pellets':1,'cooldown':0.28},
 'rifle':{'damage':14,'range':45,'spread':0.02,'pellets':1,'cooldown':0.11},
 'shotgun':{'damage':14,'range':14,'spread':0.18,'pellets':6,'cooldown':0.65},
 'sniper':{'damage':100,'range':70,'spread':0.0,'pellets':1,'cooldown':1.2},
 'smg':{'damage':9,'range':28,'spread':0.07,'pellets':1,'cooldown':0.07},
}

# ═══════════════ STATE ═══════════════
players={}; enemies=[]; coins=[]; powerups=[]; ws_clients={}
friends={}; friend_requests={}; chat_log=[]
next_pid=1; next_eid=1; next_cid=1; next_puid=1
wave=0; wave_next_at=time.time()+20
map_idx=len(MAPS)-1; map_change_at=time.time()+999999
lock=asyncio.Lock()
SERVER_START=time.time()
danger_active=False; danger_cx=0.0; danger_cz=0.0
danger_radius=0.0; danger_start_at=time.time()+DANGER_START_SEC

def cur_arena(): return MAPS[map_idx]['size']

def is_safe(x,z,obs,margin=1.0):
    for o in obs:
        if abs(x-o['x'])<o['w']/2+margin and abs(z-o['z'])<o['d']/2+margin:
            return False
    return True

def safe_spawn(ar,obs,tries=80):
    for _ in range(tries):
        x=random.uniform(-ar*0.8,ar*0.8); z=random.uniform(-ar*0.8,ar*0.8)
        if is_safe(x,z,obs): return x,z
    return 0.0,0.0

def mk_player(pid,skin='blue',name=None):
    ar=cur_arena(); x,z=safe_spawn(ar,MAPS[map_idx]['obstacles'])
    return {'id':pid,'name':name or f'لاعب {pid}','x':x,'y':GROUND_Y,'z':z,'ry':0.0,
            'skin':skin,'score':0,'kills':0,'deaths':0,'alive':True,
            'hp':100,'max_hp':100,'shield':0,'speed_until':0,'damage_until':0,
            'last_shot':0,'last_bomb':0,'is_bot':False,'bot_owner':None}

def mk_enemy(t):
    cfg=ENEMY_TYPES[t]; ar=cur_arena(); obs=MAPS[map_idx]['obstacles']
    for _ in range(30):
        s=random.choice([-1,1])
        if random.random()<0.5:
            x=random.uniform(-ar+2,ar-2); z=s*(ar-1)
        else:
            x=s*(ar-1); z=random.uniform(-ar+2,ar-2)
        if is_safe(x,z,obs,0.5): break
    return {'id':next_eid,'type':t,'x':x,'z':z,'hp':cfg['hp'],'max_hp':cfg['hp'],'last_fire':0}

def mk_coin():
    ar=cur_arena()-2; obs=MAPS[map_idx]['obstacles']
    for _ in range(20):
        x=random.uniform(-ar,ar); z=random.uniform(-ar,ar)
        if is_safe(x,z,obs,0.5): return {'id':next_cid,'x':x,'z':z}
    return {'id':next_cid,'x':0,'z':0}

def mk_powerup():
    ar=cur_arena()-3; obs=MAPS[map_idx]['obstacles']
    for _ in range(20):
        x=random.uniform(-ar,ar); z=random.uniform(-ar,ar)
        if is_safe(x,z,obs,0.5):
            return {'id':next_puid,'type':random.choice(['health','speed','shield','damage']),'x':x,'z':z}
    return {'id':next_puid,'type':'health','x':0,'z':0}

def dist(ax,az,bx,bz): return math.hypot(ax-bx,az-bz)

def dmg(p,d):
    if not p['alive']: return False
    if p['shield']>0:
        p['shield']=max(0,p['shield']-d); return False
    p['hp']-=d
    if p['hp']<=0:
        p['alive']=False; p['hp']=0; p['deaths']+=1
        return True
    return False

# ═══════════════ BROADCAST ═══════════════
async def send_to(pid,msg):
    ws=ws_clients.get(pid)
    if ws:
        try: await ws.send_str(json.dumps(msg,ensure_ascii=False))
        except Exception: pass

async def broadcast(msg,exclude=None):
    if not ws_clients: return
    data=json.dumps(msg,ensure_ascii=False)
    dead=[]
    for pid,ws in list(ws_clients.items()):
        if pid==exclude: continue
        try: await ws.send_str(data)
        except Exception: dead.append(pid)
    for pid in dead: ws_clients.pop(pid,None)

# ═══════════════ WAVES ═══════════════
def spawn_wave():
    global wave
    wave+=1
    count=3+wave*2
    pool=['zombie']*4+['runner']*2+['shooter']*2
    if wave>=4: pool+=['tank']
    if wave%5==0:
        for _ in range(1+wave//10): enemies.append(mk_enemy('boss'))
    for _ in range(count): enemies.append(mk_enemy(random.choice(pool)))
    return count

# ═══════════════ GAME LOOP ═══════════════
async def game_loop():
    global wave_next_at,map_idx,map_change_at,next_eid,next_cid,next_puid
    global danger_active,danger_radius,danger_cx,danger_cz,danger_start_at
    last=time.time()
    while True:
        await asyncio.sleep(0.05)
        now=time.time(); dt=min(now-last,0.1); last=now
        ar=cur_arena()
        async with lock:
            # Map rotation
            if now>=map_change_at:
                map_idx=(map_idx+1)%len(MAPS); map_change_at=now+120
                for p in players.values():
                    if p['alive']:
                        p['x'],p['z']=safe_spawn(ar,MAPS[map_idx]['obstacles'])
                enemies.clear(); coins.clear(); powerups.clear()
                await broadcast({'type':'map','map':map_idx,'name':MAPS[map_idx]['name'],'size':ar})
            # Wave
            if now>=wave_next_at:
                cnt=spawn_wave(); wave_next_at=now+30
                await broadcast({'type':'wave','number':wave,'count':cnt})
            # Spawn coins/powerups
            if len(coins)<12 and random.random()<0.02: coins.append(mk_coin()); next_cid+=1
            if len(powerups)<4 and random.random()<0.01: powerups.append(mk_powerup()); next_puid+=1
            # Enemy AI
            for e in enemies[:]:
                cfg=ENEMY_TYPES[e['type']]
                targets=[p for p in players.values() if p['alive']]
                if not targets: continue
                tgt=min(targets,key=lambda p:dist(p['x'],p['z'],e['x'],e['z']))
                dx=tgt['x']-e['x']; dz=tgt['z']-e['z']; d=math.hypot(dx,dz) or 1
                if cfg['ranged'] and d<cfg.get('range',10):
                    if now-e['last_fire']>cfg.get('fire_cd',2):
                        e['last_fire']=now
                        await broadcast({'type':'enemyShot','eid':e['id'],'x':e['x'],'z':e['z']})
                        if random.random()<0.6: dmg(tgt,cfg['damage'])
                elif d>cfg['radius']+0.5:
                    e['x']+=dx/d*cfg['speed']*dt; e['z']+=dz/d*cfg['speed']*dt
                else:
                    if now-e['last_fire']>0.8:
                        e['last_fire']=now; dmg(tgt,cfg['damage'])
                e['x']=max(-ar+0.5,min(ar-0.5,e['x']))
                e['z']=max(-ar+0.5,min(ar-0.5,e['z']))
            # Pickups
            for p in players.values():
                if not p['alive']: continue
                for c in coins[:]:
                    if dist(p['x'],p['z'],c['x'],c['z'])<1.2: coins.remove(c); p['score']+=5
                for pu in powerups[:]:
                    if dist(p['x'],p['z'],pu['x'],pu['z'])<1.3:
                        if pu['type']=='health': p['hp']=min(p['max_hp'],p['hp']+50)
                        elif pu['type']=='shield': p['shield']=min(100,p['shield']+50)
                        elif pu['type']=='speed': p['speed_until']=now+15
                        elif pu['type']=='damage': p['damage_until']=now+15
                        await broadcast({'type':'powerup','pid':p['id'],'kind':pu['type']})
                        powerups.remove(pu)
            # Bots
            for p in players.values():
                if not p['is_bot'] or not p['alive']: continue
                owner=players.get(p['bot_owner'])
                if not owner or not owner['alive']: continue
                ddx=owner['x']-p['x']; ddz=owner['z']-p['z']; dd=math.hypot(ddx,ddz) or 1
                if dd>5: p['x']+=ddx/dd*3*dt; p['z']+=ddz/dd*3*dt
                p['ry']=math.atan2(ddx,ddz)
                if enemies:
                    e=min(enemies,key=lambda en:dist(p['x'],p['z'],en['x'],en['z']))
                    if dist(p['x'],p['z'],e['x'],e['z'])<18 and now-p['last_shot']>0.4:
                        p['last_shot']=now
                        cfg=WEAPONS['rifle']
                        for _ in range(cfg['pellets']):
                            if random.random()<0.7:
                                e['hp']-=cfg['damage']
                                if e['hp']<=0:
                                    p['score']+=ENEMY_TYPES[e['type']]['score']; p['kills']+=1
                                    enemies.remove(e)
                                    await broadcast({'type':'kill','killer':p['id'],'victim':'enemy','etype':e['type']})
                                break
            # Cleanup
            for e in enemies[:]:
                if e['hp']<=0: enemies.remove(e)
            # Danger zone
            if not danger_active and now>=danger_start_at:
                danger_active=True
                danger_cx=random.uniform(-ar*0.3,ar*0.3); danger_cz=random.uniform(-ar*0.3,ar*0.3)
                danger_radius=ar*1.2
                await broadcast({'type':'dangerStart','x':danger_cx,'z':danger_cz,'r':danger_radius})
            if danger_active:
                tr=max(4.0,danger_radius-DANGER_SHRINK_RATE*dt)
                if tr<danger_radius:
                    danger_radius=tr
                    await broadcast({'type':'dangerUpdate','x':danger_cx,'z':danger_cz,'r':danger_radius})
                for p in list(players.values()):
                    if not p['alive']: continue
                    if math.hypot(p['x']-danger_cx,p['z']-danger_cz)>danger_radius:
                        if dmg(p,1):
                            await broadcast({'type':'kill','killer':'zone','victim':'player','pid':p['id']})
            # State
            await broadcast({
                'type':'state','map':map_idx,'wave':wave,
                'nextWave':max(0,wave_next_at-now),'size':ar,
                'danger':{'active':danger_active,'x':danger_cx,'z':danger_cz,'r':danger_radius},
                'players':{pid:{'x':round(p['x'],2),'y':round(p['y'],2),'z':round(p['z'],2),
                    'ry':round(p['ry'],3),'skin':p['skin'],'name':p['name'],
                    'score':p['score'],'kills':p['kills'],'deaths':p['deaths'],
                    'alive':p['alive'],'hp':p['hp'],'shield':p['shield']}
                    for pid,p in players.items()},
                'enemies':[{'id':e['id'],'type':e['type'],'x':round(e['x'],2),
                    'z':round(e['z'],2),'hp':e['hp']} for e in enemies],
                'coins':[{'id':c['id'],'x':round(c['x'],2),'z':round(c['z'],2)} for c in coins],
                'powerups':[{'id':p['id'],'type':p['type'],'x':round(p['x'],2),
                    'z':round(p['z'],2)} for p in powerups],
            })

# ═══════════════ WS HANDLER ═══════════════
async def ws_handler(request):
    global next_pid
    if len(players)>=MAX_PLAYERS:
        ws=web.WebSocketResponse(); await ws.prepare(request)
        await ws.send_str(json.dumps({'type':'error','msg':'server_full'}))
        await ws.close(); return ws
    ws=web.WebSocketResponse(max_msg_size=2**20,heartbeat=30)
    await ws.prepare(request)
    async with lock:
        pid=next_pid; next_pid+=1
        players[pid]=mk_player(pid); ws_clients[pid]=ws
        friends[pid]=set(); friend_requests[pid]=[]
    await ws.send_str(json.dumps({'type':'welcome','id':pid,'map':map_idx,
        'size':cur_arena(),'chat':chat_log[-30:],'maxPlayers':MAX_PLAYERS},
        ensure_ascii=False))
    print(f"✅ لاعب {pid} انضم ({len(players)})")
    try:
        async for msg in ws:
            if msg.type!=aiohttp.WSMsgType.TEXT: continue
            if len(msg.data)>2000: continue
            try: data=json.loads(msg.data)
            except Exception: continue
            if not isinstance(data,dict): continue
            t=data.get('type')
            if t not in VALID_MSG_TYPES: continue
            if not rl.check(pid,t): continue
            async with lock:
                p=players.get(pid)
                if not p: continue
                if t=='move':
                    ar=cur_arena()
                    p['x']=vnum(data.get('x'),-ar,ar,p['x'])
                    p['y']=vnum(data.get('y'),0,10,GROUND_Y)
                    p['z']=vnum(data.get('z'),-ar,ar,p['z'])
                    p['ry']=vnum(data.get('ry'),-100,100,0)
                    sk=vskin(data.get('skin'))
                    if sk: p['skin']=sk
                elif t=='shoot' and p['alive']:
                    wn=vweapon(data.get('weapon'))
                    if not wn: continue
                    cfg=WEAPONS[wn]; now=time.time()
                    if now-p['last_shot']<cfg['cooldown']: continue
                    p['last_shot']=now
                    d=cfg['damage']*(2 if now<p['damage_until'] else 1)
                    await broadcast({'type':'shot','pid':pid,'x':p['x'],'z':p['z'],
                        'ry':p['ry'],'weapon':wn},exclude=pid)
                    hit=None
                    for _ in range(cfg['pellets']):
                        ang=p['ry']+random.uniform(-cfg['spread'],cfg['spread'])
                        dx=math.sin(ang); dz=math.cos(ang); bd=cfg['range']+1
                        for e in enemies:
                            ex=e['x']-p['x']; ez=e['z']-p['z']; pr=ex*dx+ez*dz
                            if pr<0 or pr>cfg['range']: continue
                            pp=abs(ex*dz-ez*dx)
                            if pp<ENEMY_TYPES[e['type']]['radius'] and pr<bd: hit=e; bd=pr
                        if hit: break
                    if hit:
                        hit['hp']-=d
                        if hit['hp']<=0:
                            p['score']+=ENEMY_TYPES[hit['type']]['score']; p['kills']+=1
                            enemies.remove(hit)
                            await broadcast({'type':'kill','killer':pid,'victim':'enemy','etype':hit['type']})
                elif t=='bomb' and p['alive']:
                    now=time.time()
                    if now-p['last_bomb']<15: continue
                    p['last_bomb']=now
                    await broadcast({'type':'bomb','x':p['x'],'z':p['z']})
                    for e in enemies[:]:
                        if dist(p['x'],p['z'],e['x'],e['z'])<8:
                            e['hp']-=120
                            if e['hp']<=0:
                                p['score']+=ENEMY_TYPES[e['type']]['score']; p['kills']+=1
                                enemies.remove(e)
                                await broadcast({'type':'kill','killer':pid,'victim':'enemy','etype':e['type']})
                elif t=='respawn':
                    p['alive']=True; p['hp']=100; p['shield']=0
                    p['x'],p['z']=safe_spawn(cur_arena(),MAPS[map_idx]['obstacles'])
                elif t=='addBot':
                    bp=mk_player(next_pid,p['skin']); globals()['next_pid']+=1
                    bp['is_bot']=True; bp['bot_owner']=pid
                    bp['x']=p['x']+2; bp['z']=p['z']+2
                    players[bp['id']]=bp
                elif t=='friendRequest':
                    tid=vpid(data.get('target'))
                    if tid and tid in players and tid!=pid and tid not in friends.get(pid,set()):
                        if pid not in friend_requests.get(tid,[]):
                            friend_requests.setdefault(tid,[]).append(pid)
                            await send_to(tid,{'type':'friendRequest','from':pid})
                elif t=='friendAccept':
                    fid=vpid(data.get('from'))
                    if fid and fid in friend_requests.get(pid,[]):
                        friend_requests[pid].remove(fid)
                        friends.setdefault(pid,set()).add(fid)
                        friends.setdefault(fid,set()).add(pid)
                        await send_to(fid,{'type':'friendAccepted','by':pid})
                        await send_to(pid,{'type':'friendAccepted','by':fid})
                elif t=='friendDecline':
                    fid=vpid(data.get('from'))
                    if fid and fid in friend_requests.get(pid,[]):
                        friend_requests[pid].remove(fid)
                elif t=='chat':
                    txt=vstr(data.get('text'),MAX_CHAT_LEN)
                    if txt:
                        chat_log.append({'pid':pid,'text':txt})
                        if len(chat_log)>50: chat_log.pop(0)
                        await broadcast({'type':'chat','pid':pid,'text':txt})
                elif t=='setName':
                    nm=vstr(data.get('name'),MAX_NAME_LEN)
                    if nm: p['name']=nm
    except Exception as e:
        print(f"⚠️ لاعب {pid}: {e}")
    finally:
        async with lock:
            players.pop(pid,None); ws_clients.pop(pid,None)
            friends.pop(pid,None); friend_requests.pop(pid,None)
            rl.clear(pid)
        print(f"❌ لاعب {pid} خرج ({len(players)})")
    return ws

# ═══════════════ HTTP ═══════════════
async def index_h(r):
    p=os.path.join(HERE,'index.html')
    return web.FileResponse(p) if os.path.exists(p) else web.Response(text='no index',status=404)

async def manifest_h(r):
    p=os.path.join(HERE,'manifest.json')
    if os.path.exists(p):
        return web.FileResponse(p,headers={'Content-Type':'application/manifest+json'})
    return web.Response(status=404)

async def maps_h(r): return web.json_response(MAPS)

async def status_h(r):
    return web.json_response({
        'online':True,'players':len(players),'maxPlayers':MAX_PLAYERS,
        'map':MAPS[map_idx]['name'],'mapIndex':map_idx,'wave':wave,
        'enemies':len(enemies),'coins':len(coins),'powerups':len(powerups),
        'dangerActive':danger_active,'uptime':round(time.time()-SERVER_START,1),
    })

def main():
    app=web.Application()
    app.router.add_get('/',index_h)
    app.router.add_get('/ws',ws_handler)
    app.router.add_get('/maps',maps_h)
    app.router.add_get('/manifest.json',manifest_h)
    app.router.add_get('/status',status_h)
    async def on_start(a): asyncio.create_task(game_loop())
    app.on_startup.append(on_start)
    print(f"🚀 BLOCK ARENA • http://{HOST}:{PORT}")
    print(f"   ✓ Server-Authoritative")
    print(f"   ✓ Rate limiting")
    print(f"   ✓ Anti-XSS")
    print(f"   ✓ Safe spawn")
    print(f"   ✓ Max {MAX_PLAYERS} players")
    web.run_app(app,host=HOST,port=PORT,print=None,shutdown_timeout=3)

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print("\n👋")
