import json,struct,os,re,glob,collections,sys
import numpy as np
RUTA=sys.argv[1]
b=open(RUTA,'rb').read(); n=struct.unpack('<I',b[12:16])[0]; g=json.loads(b[20:20+n])
nodes=g['nodes']; acc=g['accessors']; meshes=g['meshes']
def mat(nd):
    if 'matrix' in nd: return np.array(nd['matrix']).reshape(4,4).T
    T=np.eye(4); t=nd.get('translation',[0,0,0]); r=nd.get('rotation',[0,0,0,1]); s=nd.get('scale',[1,1,1])
    x,y,z,w=r; R=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],[2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],[2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    T[:3,:3]=R*np.array(s); T[:3,3]=t; return T
padre={}
for i,nd in enumerate(nodes):
    for c in nd.get('children',[]): padre[c]=i
W={}
def mundo(i):
    if i in W: return W[i]
    M=mat(nodes[i]); 
    if i in padre: M=mundo(padre[i])@M
    W[i]=M; return M
def anc(i):
    out=[]
    while i in padre: i=padre[i]; out.append(nodes[i].get('name',''))
    return out
piezas=[]
for i,nd in enumerate(nodes):
    if 'mesh' not in nd: continue
    lo=np.full(3,np.inf); hi=np.full(3,-np.inf)
    for p in meshes[nd['mesh']]['primitives']:
        a=acc[p['attributes']['POSITION']]; lo=np.minimum(lo,a['min']); hi=np.maximum(hi,a['max'])
    M=mundo(i); cs=np.array([[x,y,z,1] for x in (lo[0],hi[0]) for y in (lo[1],hi[1]) for z in (lo[2],hi[2])])@M.T
    piezas.append(dict(i=i,nombre=nd.get('name',''),anc=anc(i),lo=cs[:,:3].min(0),hi=cs[:,:3].max(0)))
lo=np.min([p['lo'] for p in piezas],0); hi=np.max([p['hi'] for p in piezas],0); dim=hi-lo
print(f"MALLAS {len(piezas)} | caja total X {dim[0]:.2f} m · Y {dim[1]:.2f} m · Z {dim[2]:.2f} m | min {lo.round(2)} max {hi.round(2)}")
# Robusto a piezas sueltas: percentiles de los centros
C=np.array([(p['lo']+p['hi'])/2 for p in piezas])
nombres=[p['nombre'] for p in piezas]
rep=[k for k,v in collections.Counter(nombres).items() if v>1]
sinmod=[p['nombre'] for p in piezas if not any(a.upper().startswith('MOD_') for a in p['anc'])]
sinnombre=[p for p in piezas if not p['nombre'] or re.match(r'^(mesh|object|cube|node)[_\.\d]*$',p['nombre'],re.I)]
print(f"nombres repetidos {len(rep)} | sin MOD_ {len(sinmod)} | sin nombre válido {len(sinnombre)}")
por_mod=collections.Counter(next((a for a in p['anc'] if a.upper().startswith('MOD_')),'—') for p in piezas)
print('por sistema:',dict(sorted(por_mod.items())))
# contra los JSON
base=lambda s: re.sub(r'\s*\(\d+ de \d+\)$','',s)
esper=collections.Counter()
for f in glob.glob('/Users/lucastravecedo/Documents/Control y seguimiento matenimieno UAV/Informacion /Informacion Drones/C188/4. Despiece para Claude Design/JSON para Claude Design/*.json'):
    for p in json.load(open(f))['piezas']: esper[p['malla']]+=p['cantidad']
tiene=collections.Counter(base(x) for x in nombres)
faltan={k:v-tiene.get(k,0) for k,v in esper.items() if tiene.get(k,0)<v}
sobran={k:tiene[k]-esper.get(k,0) for k in tiene if re.search(r'F(2[2-9]|[3-9]\d|1[0-5]\d)-',k) and tiene[k]>esper.get(k,0)}
print(f"JSON fig 22-151: esperadas {sum(esper.values())} mallas en {len(esper)} nombres | faltan {sum(faltan.values())} ({len(faltan)} nombres) | sobran {sum(sobran.values())}")
figs_faltan=collections.Counter(re.search(r'F(\d+)-',k).group(1) for k in faltan)
print('faltan por figura:',dict(sorted(figs_faltan.items(),key=lambda x:int(x[0]))))
json.dump({'faltan':faltan,'sobran':sobran,'repetidos':rep,'sin_mod':sinmod},open(os.path.join(os.path.dirname(__file__),'revision_glb.json'),'w'),ensure_ascii=False,indent=1)
# piezas bajo el suelo o muy fuera
suelo=lo[1]
lejos=[p['nombre'] for p in piezas if np.any(p['lo']<np.percentile(C,0.5,0)-1.0) or np.any(p['hi']>np.percentile(C,99.5,0)+1.0)]
print('piezas muy alejadas del resto:',len(lejos),lejos[:8])
json.dump({'lo':lo.tolist(),'hi':hi.tolist()},open(os.path.join(os.path.dirname(__file__),'caja.json'),'w'))

# ---------- Posiciones clave ----------
def busca(rx, mod=None):
    return [p for p in piezas if re.search(rx,p['nombre'],re.I) and (not mod or any(a.upper()==mod for a in p['anc']))]
def centro(ps): return np.mean([(p['lo']+p['hi'])/2 for p in ps],0) if ps else None
IN=0.0254
print('\nsobran:',list(sobran.items())[:10])
cf=[x for x in busca(r'cortafuego|mampara del motor') if any(a.upper()=='MOD_FUSELAJE' for a in x['anc']) and (x['hi'][1]-x['lo'][1])>0.3]
print('cortafuego:',len(cf),[p['nombre'][:50] for p in cf[:3]])
# El morro: ¿hacia +Z o -Z? (la hélice)
hel=busca(r'pala|spinner|cono de (la )?hélice','MOD_HELICE'); ch=centro(hel)
nariz=np.sign(ch[2]) if ch is not None else 1
print('hélice en z=%.2f → morro hacia %s' % (ch[2], '+Z' if nariz>0 else '-Z'))
if cf:
    zf=np.median([ (p['lo'][2]+p['hi'][2])/2 for p in cf ])
    sta=lambda z: (zf-z)*nariz/IN   # STA en pulgadas, positivo hacia atrás
    print(f'cortafuego z={zf:.3f}')
    def rep_(etq,rx,mod,esper):
        ps=busca(rx,mod); 
        if not ps: print(f'  {etq}: no encontrado'); return
        c=centro(ps); print(f'  {etq}: STA {sta(c[2]):7.1f}" (manual {esper}")  BL {abs(c[0])/IN:6.1f}"  altura {c[1]:.2f} m  [{len(ps)} mallas]')
    rep_('herrajes/pernos de unión ala delantera',r'unión del larguero delantero',None,'33.58, BL 52.75')
    rep_('herrajes/pernos de unión ala trasera',r'unión del larguero trasero',None,'64.57, BL 52.77')
    rep_('montante del ala',r'^(conjunto del )?montante',None,'23.9 (fuselaje) → ala')
    rep_('deriva',r'deriva','MOD_EMPENAJE','~200-233')
    rep_('estabilizador',r'estabilizador','MOD_EMPENAJE','~212-233')
    rep_('tolva',r'tolva','MOD_TOLVA','~0-60 (entre cortafuego y cabina)')
    rep_('asiento',r'asiento','MOD_CABINA','~75-110')
    rep_('cilindros/motor',r'cilindro|cárter','MOD_MOTOR','negativa (delante del cortafuego)')
# vía del tren y diedro
rue=busca(r'^neumático','MOD_TREN')
xs=sorted(set(round(((p['lo']+p['hi'])/2)[0],2) for p in rue))
if rue:
    izq=[p for p in rue if (p['lo'][0]+p['hi'][0])/2< -0.3]; der=[p for p in rue if (p['lo'][0]+p['hi'][0])/2>0.3]
    if izq and der: print(f"vía del tren: {abs(centro(der)[0]-centro(izq)[0]):.2f} m (POH 2.16, servicio 2.24)")
ala=[p for p in piezas if any(a.upper()=='MOD_ALA' for a in p['anc'])]
rev=[p for p in ala if re.search(r'revestimiento',p['nombre'],re.I)]
pun=[p for p in rev if abs((p['lo'][0]+p['hi'][0])/2)>4.5]; raiz=[p for p in rev if abs((p['lo'][0]+p['hi'][0])/2)<2.5]
if pun and raiz:
    dy=centro(pun)[1]-centro(raiz)[1]; dx=abs(centro(pun)[0])-abs(centro(raiz)[0])
    print(f"diedro aparente: {np.degrees(np.arctan2(dy,dx)):.1f}°")
print(f"altura del suelo al punto más alto: {hi[1]-lo[1]:.2f} m (POH 2.49) · envergadura {hi[0]-lo[0]:.2f} (POH 12.70/servicio 12.31) · longitud {hi[2]-lo[2]:.2f} (POH 7.90/servicio 7.78)")
print('\n--- detalle')
for rx,et in [(r'unión del larguero delantero','ala delantera (BL 52.75, WL -9.25)'),(r'unión del larguero trasero','ala trasera (BL 52.77, WL -10.27)')]:
    for p_ in busca(rx):
        c=(p_['lo']+p_['hi'])/2; print(f"  {et}: STA {sta(c[2]):.1f}  BL {abs(c[0])/IN:.1f}  WL rel. cortafuego {(c[1]-np.median([(x['lo'][1]+x['hi'][1])/2 for x in cf]))/IN:.1f}")
tw=busca(r'neumático|rueda de cola','MOD_TREN'); cola=[p for p in tw if (p['lo'][2]+p['hi'][2])/2<-2]; prin=[p for p in busca(r'^neumático','MOD_TREN') if (p['lo'][2]+p['hi'][2])/2>0]
if cola and prin:
    zc,zp=centro(cola)[2],centro(prin)[2]; print(f"  rueda de cola en STA {sta(zc):.0f}\", ruedas principales en STA {sta(zp):.0f}\"")
    # actitud: línea del fuselaje (estación 0 vs 143) a partir de piezas del fuselaje en esas estaciones
fus=[p for p in piezas if any(a.upper()=='MOD_FUSELAJE' for a in p['anc'])]
def alto_en(st):
    zs=zf-st*IN*nariz; ps=[p for p in fus if p['lo'][2]<=zs<=p['hi'][2]]
    return max(p['hi'][1] for p in ps) if ps else None, min(p['lo'][1] for p in ps) if ps else None
for st in (0,60,111,143,175,212):
    a=alto_en(st); print(f"  fuselaje en STA {st}: techo {a[0]:.2f} m · piso {a[1]:.2f} m" if a[0] else f"  STA {st}: sin piezas")
