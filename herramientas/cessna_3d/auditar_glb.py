import json,struct,re,collections,math
import numpy as np
import os; p=os.environ.get("GLB","/Users/lucastravecedo/Documents/Control y seguimiento matenimieno UAV/Informacion /Informacion Drones/C188/3D/cessna-188-despiece.glb")
b=open(p,'rb').read(); n=struct.unpack('<I',b[12:16])[0]; j=json.loads(b[20:20+n]); N=j['nodes']
par={}
for i,x in enumerate(N):
    for c in x.get('children',[]): par[c]=i
def mat_local(x):
    if 'matrix' in x: return np.array(x['matrix']).reshape(4,4).T
    T=np.eye(4); t=x.get('translation',[0,0,0]); r=x.get('rotation',[0,0,0,1]); s=x.get('scale',[1,1,1])
    qx,qy,qz,qw=r
    R=np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],[2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],[2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])
    T[:3,:3]=R*np.array(s); T[:3,3]=t; return T
cache={}
def mundo(i):
    if i in cache: return cache[i]
    M=mat_local(N[i]); 
    if i in par: M=mundo(par[i])@M
    cache[i]=M; return M
def anc(i,pre):
    while i in par:
        i=par[i]
        if N[i].get('name','').startswith(pre): return N[i]['name']
    return ''
piezas=[]
for i,x in enumerate(N):
    if 'mesh' not in x: continue
    pr=j['meshes'][x['mesh']]['primitives']
    lo=np.array([1e9]*3); hi=-lo; cnt=0; mats=set()
    M=mundo(i)
    for q in pr:
        a=j['accessors'][q['attributes']['POSITION']]; cnt+=a['count']
        mn,mx=np.array(a['min']),np.array(a['max'])
        esq=np.array([[X,Y,Z,1] for X in (mn[0],mx[0]) for Y in (mn[1],mx[1]) for Z in (mn[2],mx[2])])
        w=(M@esq.T).T[:,:3]; lo=np.minimum(lo,w.min(0)); hi=np.maximum(hi,w.max(0))
        mats.add(j['materials'][q.get('material',0)].get('name',''))
    piezas.append(dict(i=i,nombre=x.get('name',''),lo=lo,hi=hi,c=(lo+hi)/2,t=hi-lo,v=cnt,mats=mats,fig=anc(i,'FIG_'),mod=anc(i,'MOD_')))
allo=np.min([p['lo'] for p in piezas],0); alhi=np.max([p['hi'] for p in piezas],0)
print('caja avión',allo.round(2),alhi.round(2))
# ejes: envergadura = eje más largo
ext=alhi-allo; eje_env=int(np.argmax(ext)); print('eje envergadura',eje_env,'ext',ext.round(2))
res=collections.defaultdict(list)
# 1) degeneradas
for p in piezas:
    if p['t'].max()<0.002: res['degenerada (casi sin tamaño)'].append(p['nombre'])
# 2) fuera de su grupo: lejos del centro de su FIG
porfig=collections.defaultdict(list)
for p in piezas: porfig[p['fig']].append(p)
for f,ps in porfig.items():
    C=np.median([p['c'] for p in ps],0); d=[np.linalg.norm(p['c']-C) for p in ps]; md=np.median(d)+1e-3
    for p,di in zip(ps,d):
        if di>max(1.2, 6*md) and len(ps)>4: res['lejos de su grupo'].append(f"{p['nombre']} · {di:.2f} m del centro de {f}")
# 3) duplicadas superpuestas (mismo nombre base y misma caja)
vis=collections.defaultdict(list)
for p in piezas: vis[(p['nombre'].split(' (')[0], tuple(p['c'].round(3)), tuple(p['t'].round(3)))].append(p['nombre'])
for k,v in vis.items():
    if len(v)>1: res['duplicadas en el mismo sitio'].append(f"{k[0]} ×{len(v)}")
# 4) pares LH/RH no simétricos
def base(nm): return re.sub(r'\b(LH|RH|izquierd[oa]|derech[oa]|izq\.|der\.)\b','#',nm.split(' — ')[0],flags=re.I)
lados=collections.defaultdict(dict)
for p in piezas:
    nm=p['nombre'].split(' — ')[0]
    lado='L' if re.search(r'\bLH\b|izquierd|\(izq',nm,re.I) else 'R' if re.search(r'\bRH\b|derech|\(der',nm,re.I) else None
    if lado: lados[(base(p['nombre']),p['fig'],p['nombre'].split('(')[-1] if '(' in p['nombre'] else '')][lado]=p
for k,d in lados.items():
    if 'L' in d and 'R' in d:
        a,bb=d['L'],d['R']; ca=a['c'].copy(); cb=bb['c'].copy(); cb[eje_env]*=-1
        err=np.linalg.norm(ca-cb); dt=np.abs(a['t']-bb['t']).max()
        if err>0.08 or dt>0.08: res['izquierda/derecha no simétricas'].append(f"{a['nombre'].split(' — ')[0]} ↔ {bb['nombre'].split(' — ')[0]} · desvío {err:.2f} m, tamaño {dt:.2f} m")
# 5) tamaños imposibles por tipo
reglas=[(r'^(perno|tornillo|remache|tuerca|arandela|pasador|chaveta)',0.35,'demasiado grande para tornillería'),
        (r'^(rueda|neum[aá]tico)',1.3,'rueda demasiado grande')]
for p in piezas:
    nm=p['nombre'].lower()
    for rx,lim,msg in reglas:
        if re.search(rx,nm) and p['t'].max()>lim: res[msg].append(f"{p['nombre']} · {p['t'].max():.2f} m")
# 6) por debajo del suelo
suelo=allo[1]
# 7) materiales raros
for p in piezas:
    nm=p['nombre'].lower()
    if re.search(r'^(neum[aá]tico|llanta|c[aá]mara)',nm) and not any(re.search('caucho|negro',m,re.I) for m in p['mats']): res['neumático sin caucho'].append(p['nombre'])
    if re.search(r'^(parabrisas|ventan|lente)',nm) and not any(re.search('metacril|lente|transp|vidrio',m,re.I) for m in p['mats']): res['vidrio opaco'].append(f"{p['nombre']} · {','.join(p['mats'])}")
# 8) cilindros de pocas caras (piezas redondas groseras)
for p in piezas:
    nm=p['nombre'].lower()
    if re.search(r'^(rueda|neum|llanta|disco de freno|tambor|spinner|cono de la h|cilindro)',nm) and p['v']<80: res['pieza redonda con muy pocos vértices'].append(f"{p['nombre']} · {p['v']} vértices")
for k,v in res.items():
    print(f'\n## {k}: {len(v)}'); [print('  -',x) for x in v[:25]]
json.dump({k:v for k,v in res.items()}, open('/private/tmp/claude-501/-Users-lucastravecedo-Documents-Control-y-seguimiento-matenimieno-UAV/175f5db8-f854-4aae-8fdd-3aeae92d64aa/scratchpad/auditoria_glb.json','w'), ensure_ascii=False, indent=1)
