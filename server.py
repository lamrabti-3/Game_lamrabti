#!/usr/bin/env python3
import asyncio, json, random, time, math, os
from aiohttp import web
import aiohttp

HOST="0.0.0.0"; PORT=8080; GROUND_Y=0.75
HERE=os.path.dirname(os.path.abspath(__file__))

def gen_obs(size,count,color):
    obs=[]
    for _ in range(count*4):
        if len(obs)>=count: break
        x=random.uniform(-size+4,size-4); z=random.uniform(-size+4,size-4)
        if abs(x)<3 and abs(z)<3: continue
        obs.append({'x':round(x,1),'z':round(z,1),
            'w':round(random.uniform(1.5,4),1),
            'h':round(random.uniform(1.5,5),1),
            'd':round(random.uniform(1.5,4),1),'c':color})
    return obs

MAPS=[
 {'name':'الغرفة','size':12,'floor':0x2a3f66,'sky':0x1a2b4a,'g1':0x60a5fa,'g2':0x3b5a99,'obs_color':0x4466aa,'obs_count':5},
 {'name':'الساحة','size':16,'floor':0x3a3f56,'sky':0x1a2b4a,'g1':0x60a5fa,'g2':0x3b5a99,'obs_color':0x4466aa,'obs_count':7},
 {'name':'المدينة','size':30,'floor':0x4a4a4a,'sky':0x2a2a3a,'g1':0x888888,'g2':0x555555,'obs_color':0x666666,'obs_count':18},
 {'name':'الصحراء الكبرى','size':34,'floor':0x8b6b3a,'sky':0xd98b4a,'g1':0xffaa55,'g2':0x885522,'obs_color':0x664422,'obs_count':16},
 {'name':'الفضاء','size':44,'floor':0x101020,'sky':0x000005,'g1':0x8844ff,'g2':0x442288,'obs_color':0x6644aa,'obs_count':26},
 {'name':'البركان','size':48,'floor':0x2a0a0a,'sky':0x1a0000,'g1':0xff4400,'g2':0x881100,'obs_color':0x441100,'obs_count':30},
]
MAPS.append({'name':'جزيرة الموت','size':60,'floor':0x1a2a1a,'sky':0x0a1a0a,'g1':0x44aa44,'g2':0x1a5a1a,'obs_color':0x223322,'obs_count':0,'obstacles':[]})
for m in MAPS:
    if m['name']=='جزيرة الموت':
        m['obstacles']=gen_obs(60,40,0x223322)
    else:
        m['obstacles']=gen_obs(m['size'],m['obs_count'],m['obs_color'])
# إجبار البداية على الماب الضخم
DANGER_START_SEC=300  # 5 دقائق
DANGER_SHRINK_SEC=600  # 10 دقائق للانكماش الكامل
MAX_PLAYERS=50

ENEMY_TYPES={
 'zombie':{'hp':30,'speed':2.2,'damage':8,'radius':0.7,'score':10,'size':1.0,'color':0x44aa44,'em':0x114411,'skin':0x88cc66,'legs':0x223322,'ranged':False},
 'runner':{'hp':15,'speed':5.5,'damage':5,'radius':0.5,'score':15,'size':0.85,'color':0xff8800,'em':0x552200,'skin':0xffcc99,'legs':0x331100,'ranged':False},
 'shooter':{'hp':40,'speed':1.8,'damage':8,'radius':0.6,'score':25,'size':1.0,'color':0x8844ff,'em':0x221144,'skin':0xccbbff,'legs':0x221144,'ranged':True,'range':14,'fire_cd':1.8},
 'tank':{'hp':150,'speed':1.0,'damage':20,'radius':1.0,'score':50,'size':1.6,'color':0x884400,'em':0x221100,'skin':0xaa8855,'legs':0x221100,'ranged':False},
 'boss':{'hp':600,'speed':1.4,'damage':30,'radius':1.8,'score':300,'size':2.3,'color':0xaa0000,'em':0x550000,'skin':0xff4444,'legs':0x220000,'ranged':True,'range':22,'fire_cd':1.2},
}
WEAPONS={
 'pistol':{'damage':25,'range':35,'spread':0,'pellets':1},
 'rifle':{'damage':14,'range':45,'spread':0.02,'pellets':1},
 'shotgun':{'damage':14,'range':14,'spread':0.18,'pellets':6},
 'sniper':{'damage':100,'range':70,'spread':0,'pellets':1},
 'smg':{'damage':9,'range':28,'spread':0.07,'pellets':1},
}
POWERUP_TYPES=['health','speed','shield','damage']

players={}; enemies=[]; coins=[]; powerups=[]; ws_clients={}
friends={}; friend_requests={}; chat_log=[]
next_pid=1; next_eid=1; next_cid=1; next_puid=1
wave=0; wave_next_at=time.time()+20
danger_active=False; danger_center_x=0; danger_center_z=0
danger_radius=80; danger_start_at=time.time()+DANGER_START_SEC
game_started_at=time.time()
map_idx=len(MAPS)-1; map_change_at=time.time()+999999
lock=asyncio.Lock()

def cur_arena(): return MAPS[map_idx]['size']

def make_player(pid,skin='blue'):
    ar=cur_arena()*0.4
    return {'id':pid,'x':random.uniform(-ar,ar),'z':random.uniform(-ar,ar),
        'y':GROUND_Y,'ry':0,'skin':skin,'score':0,'alive':True,'hp':100,
        'max_hp':100,'shield':0,'speed_until':0,'damage_until':0,
        'last_shot':0,'is_bot':False,'bot_owner':None}

def make_enemy(t):
    cfg=ENEMY_TYPES[t]; ar=cur_arena(); side=random.choice([-1,1])
    if random.random()<0.5: x=random.uniform(-ar+2,ar-2); z=side*(ar-1)
    else: x=side*(ar-1); z=random.uniform(-ar+2,ar-2)
    return {'id':next_eid,'type':t,'x':x,'z':z,'hp':cfg['hp'],'max_hp':cfg['hp'],'last_fire':0}

def make_coin():
    ar=cur_arena()-2
    return {'id':next_cid,'x':random.uniform(-ar,ar),'z':random.uniform(-ar,ar)}

def make_powerup():
    ar=cur_arena()-3
    return {'id':next_puid,'type':random.choice(POWERUP_TYPES),
        'x':random.uniform(-ar,ar),'z':random.uniform(-ar,ar)}

async def send_to(pid,msg):
    ws=ws_clients.get(pid)
    if ws:
        try: await ws.send_str(json.dumps(msg))
        except Exception: pass

async def broadcast(msg,exclude=None):
    if not ws_clients: return
    data=json.dumps(msg); dead=[]
    for pid,ws in list(ws_clients.items()):
        if pid==exclude: continue
        try: await ws.send_str(data)
        except Exception: dead.append(pid)
    for pid in dead: ws_clients.pop(pid,None)

def spawn_wave():
    global wave
    wave+=1; count=3+wave*2
    types=['zombie']*4+['runner']*2+['shooter']*2
    if wave>=4: types+=['tank']
    if wave%5==0:
        for _ in range(1+wave//10): enemies.append(make_enemy('boss'))
    for _ in range(count): enemies.append(make_enemy(random.choice(types)))
    return count

def dist(ax,az,bx,bz): return math.hypot(ax-bx,az-bz)

def dmg_player(p,d):
    if p['shield']>0:
        p['shield']=max(0,p['shield']-d); return False
    p['hp']-=d
    if p['hp']<=0: p['alive']=False; p['hp']=0; return True
    return False

async def game_loop():
    global wave_next_at,map_idx,map_change_at,next_eid,next_cid,next_puid
    last=time.time()
    while True:
        await asyncio.sleep(0.05)
        now=time.time(); dt=now-last; last=now
        ar=cur_arena()
        async with lock:
            # ===== منطقة الموت =====
            global danger_active, danger_radius
            if not danger_active and now>=danger_start_at:
                danger_active=True
                ar_cur=cur_arena()
                danger_center_x=random.uniform(-ar_cur*0.3,ar_cur*0.3)
                danger_center_z=random.uniform(-ar_cur*0.3,ar_cur*0.3)
                danger_radius=ar_cur*1.2
                await broadcast({'type':'dangerStart',
                    'x':danger_center_x,'z':danger_center_z,'r':danger_radius})
            if danger_active:
                elapsed_d=now-danger_start_at
                target_r=max(4,danger_radius-elapsed_d*0.06)
                if target_r<danger_radius:
                    danger_radius=target_r
                    await broadcast({'type':'dangerUpdate',
                        'x':danger_center_x,'z':danger_center_z,'r':danger_radius})
                # ضرر خارج المنطقة
                for pid,p in list(players.items()):
                    if not p['alive']: continue
                    dx=p['x']-danger_center_x; dz=p['z']-danger_center_z
                    if math.hypot(dx,dz)>danger_radius:
                        p['hp']-=1
                        if p['hp']<=0:
                            p['alive']=False; p['hp']=0
                            await broadcast({'type':'kill','killer':'zone',
                                'victim':'player','pid':pid})
            if now>=map_change_at:
                map_idx=(map_idx+1)%len(MAPS)
                map_change_at=now+120
                await broadcast({'type':'map','map':map_idx,'name':MAPS[map_idx]['name'],'size':ar})
            if now>=wave_next_at:
                cnt=spawn_wave(); wave_next_at=now+30
                await broadcast({'type':'wave','number':wave,'count':cnt})
            if len(coins)<12 and random.random()<0.02:
                coins.append(make_coin()); next_cid+=1
            if len(powerups)<4 and random.random()<0.01:
                powerups.append(make_powerup()); next_puid+=1
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
                        if random.random()<0.6: dmg_player(tgt,cfg['damage'])
                elif d>cfg['radius']+0.5:
                    e['x']+=dx/d*cfg['speed']*dt; e['z']+=dz/d*cfg['speed']*dt
                else:
                    if now-e['last_fire']>0.8:
                        e['last_fire']=now; dmg_player(tgt,cfg['damage'])
                e['x']=max(-ar+0.5,min(ar-0.5,e['x']))
                e['z']=max(-ar+0.5,min(ar-0.5,e['z']))
            for p in players.values():
                if not p['alive']: continue
                for c in coins[:]:
                    if dist(p['x'],p['z'],c['x'],c['z'])<1.2:
                        coins.remove(c); p['score']+=5
                for pu in powerups[:]:
                    if dist(p['x'],p['z'],pu['x'],pu['z'])<1.3:
                        if pu['type']=='health': p['hp']=min(p['max_hp'],p['hp']+50)
                        elif pu['type']=='shield': p['shield']=50
                        elif pu['type']=='speed': p['speed_until']=now+15
                        elif pu['type']=='damage': p['damage_until']=now+15
                        await broadcast({'type':'powerup','pid':p['id'],'kind':pu['type']})
                        powerups.remove(pu)
            for p in players.values():
                if not p['is_bot'] or not p['alive']: continue
                owner=players.get(p['bot_owner'])
                if not owner or not owner['alive']: continue
                ddx=owner['x']-p['x']; ddz=owner['z']-p['z']; dd=math.hypot(ddx,ddz)
                if dd>5: p['x']+=ddx/dd*3*dt; p['z']+=ddz/dd*3*dt
                p['ry']=math.atan2(ddx,ddz)
                if enemies:
                    e=min(enemies,key=lambda en:dist(p['x'],p['z'],en['x'],en['z']))
                    if dist(p['x'],p['z'],e['x'],e['z'])<18 and now-p['last_shot']>0.4:
                        p['last_shot']=now; cfg=WEAPONS['rifle']
                        for _ in range(cfg['pellets']):
                            if random.random()<0.7:
                                e['hp']-=cfg['damage']
                                if e['hp']<=0:
                                    p['score']+=ENEMY_TYPES[e['type']]['score']
                                    enemies.remove(e)
                                    await broadcast({'type':'kill','killer':p['id'],'victim':'enemy','etype':e['type']})
                                break
            for e in enemies[:]:
                if e['hp']<=0:
                    enemies.remove(e)
            await broadcast({'type':'state','map':map_idx,'wave':wave,
                'danger':{'active':danger_active,'x':danger_center_x,
                          'z':danger_center_z,'r':danger_radius},
                'nextWave':max(0,wave_next_at-now),'size':ar,
                'players':{pid:{'x':round(p['x'],2),'y':p['y'],'z':round(p['z'],2),
                    'ry':round(p['ry'],3),'skin':p['skin'],'score':p['score'],
                    'alive':p['alive'],'hp':p['hp'],'shield':p['shield']} for pid,p in players.items()},
                'enemies':[{'id':e['id'],'type':e['type'],'x':round(e['x'],2),'z':round(e['z'],2),'hp':e['hp']} for e in enemies],
                'coins':[{'id':c['id'],'x':round(c['x'],2),'z':round(c['z'],2)} for c in coins],
                'powerups':[{'id':p['id'],'type':p['type'],'x':round(p['x'],2),'z':round(p['z'],2)} for p in powerups]})

async def ws_handler(request):
    global next_pid
    if len(players)>=MAX_PLAYERS:
        return web.Response(status=503,text='السيرفر ممتلئ')
    ws=web.WebSocketResponse(max_msg_size=2**20)
    await ws.prepare(request)
    async with lock:
        pid=next_pid; next_pid+=1
        players[pid]=make_player(pid)
        ws_clients[pid]=ws
        friends[pid]=set(); friend_requests[pid]=[]
    await ws.send_str(json.dumps({'type':'welcome','id':pid,'map':map_idx,
        'size':cur_arena(),'chat':chat_log[-30:]}))
    print(f"✅ لاعب {pid} انضم ({len(players)})")
    try:
        async for msg in ws:
            if msg.type!=aiohttp.WSMsgType.TEXT: continue
            try: data=json.loads(msg.data)
            except Exception: continue
            async with lock:
                p=players.get(pid)
                if not p: continue
                t=data.get('type')
                if t=='move':
                    ar=cur_arena()
                    p['x']=max(-ar+0.5,min(ar-0.5,data.get('x',0)))
                    p['y']=data.get('y',GROUND_Y)
                    p['z']=max(-ar+0.5,min(ar-0.5,data.get('z',0)))
                    p['ry']=data.get('ry',0)
                    if 'skin' in data: p['skin']=data['skin']
                elif t=='shoot' and p['alive']:
                    wn=data.get('weapon','pistol'); cfg=WEAPONS.get(wn,WEAPONS['pistol'])
                    dmg=cfg['damage']*(2 if time.time()<p['damage_until'] else 1)
                    await broadcast({'type':'shot','pid':pid,'x':p['x'],'z':p['z'],'ry':p['ry'],'weapon':wn},exclude=pid)
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
                        hit['hp']-=dmg
                        if hit['hp']<=0:
                            p['score']+=ENEMY_TYPES[hit['type']]['score']
                            enemies.remove(hit)
                            await broadcast({'type':'kill','killer':pid,'victim':'enemy','etype':hit['type']})
                elif t=='bomb' and p['alive']:
                    await broadcast({'type':'bomb','x':p['x'],'z':p['z']})
                    for e in enemies[:]:
                        if dist(p['x'],p['z'],e['x'],e['z'])<8:
                            e['hp']-=120
                            if e['hp']<=0:
                                p['score']+=ENEMY_TYPES[e['type']]['score']
                                enemies.remove(e)
                                await broadcast({'type':'kill','killer':pid,'victim':'enemy','etype':e['type']})
                elif t=='respawn':
                    p['alive']=True; p['hp']=100; p['shield']=0
                    ar=cur_arena()*0.4
                    p['x']=random.uniform(-ar,ar); p['z']=random.uniform(-ar,ar)
                elif t=='addBot':
                    bp=make_player(next_pid,p['skin'])
                    globals()['next_pid']+=1
                    bp['is_bot']=True; bp['bot_owner']=pid
                    bp['x']=p['x']+2; bp['z']=p['z']+2
                    players[bp['id']]=bp
                elif t=='friendRequest':
                    tid=data.get('target')
                    if tid in players and tid!=pid and tid not in friends.get(pid,set()):
                        if pid not in friend_requests.get(tid,[]):
                            friend_requests.setdefault(tid,[]).append(pid)
                            await send_to(tid,{'type':'friendRequest','from':pid})
                elif t=='friendAccept':
                    from_id=data.get('from')
                    if from_id in friend_requests.get(pid,[]):
                        friend_requests[pid].remove(from_id)
                        friends.setdefault(pid,set()).add(from_id)
                        friends.setdefault(from_id,set()).add(pid)
                        await send_to(from_id,{'type':'friendAccepted','by':pid})
                        await send_to(pid,{'type':'friendAccepted','by':from_id})
                elif t=='friendDecline':
                    from_id=data.get('from')
                    if from_id in friend_requests.get(pid,[]):
                        friend_requests[pid].remove(from_id)
                elif t=='chat':
                    txt=str(data.get('text',''))[:80]
                    if txt:
                        entry={'pid':pid,'text':txt}
                        chat_log.append(entry)
                        if len(chat_log)>50: chat_log.pop(0)
                        await broadcast({'type':'chat','pid':pid,'text':txt})
                elif t=='emote':
                    await broadcast({'type':'emote','pid':pid,'e':data.get('e','?')})
    except Exception as e:
        print(f"⚠️ {pid}: {e}")
    finally:
        async with lock:
            players.pop(pid,None); ws_clients.pop(pid,None)
            friends.pop(pid,None); friend_requests.pop(pid,None)
        print(f"❌ {pid} خرج")

async def index_h(r):
    p=os.path.join(HERE,'index.html')
    return web.FileResponse(p) if os.path.exists(p) else web.Response(text='no index',status=404)
async def maps_h(r): return web.json_response(MAPS)
async def status_h(r): return web.json_response({'players':len(players),'wave':wave,'enemies':len(enemies),'map':map_idx})

def main():
    app=web.Application()
    app.router.add_get('/',index_h)
    app.router.add_get('/ws',ws_handler)
    app.router.add_get('/maps',maps_h)
    app.router.add_get('/status',status_h)
    async def on_start(a): asyncio.create_task(game_loop())
    app.on_startup.append(on_start)
    print(f"🚀 http://{HOST}:{PORT}")
    web.run_app(app,host=HOST,port=PORT,print=None)

if __name__=='__main__':
    try: main()
    except KeyboardInterrupt: print("\n👋")
