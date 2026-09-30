"""Versión combinada del despiece del Cessna: parte del GLB nuevo de Claude Design y devuelve a
la posición del GLB anterior las mallas que Design movió sin motivo (ver revertir.json) y las
cubiertas exteriores que movió. Sólo toca las transformaciones de los nodos (chunk JSON)."""
import json,struct,re,sys,numpy as np
D="/Users/lucastravecedo/Documents/Control y seguimiento matenimieno UAV/Informacion /Informacion Drones/C188/3D/"
VIEJO=D+"anteriores/cessna-188-despiece 2026-09-27 13.28.glb"; NUEVO=sys.argv[1]; SALIDA=sys.argv[2]
def leer(r):
    b=open(r,'rb').read(); n=struct.unpack('<I',b[12:16])[0]; j=json.loads(b[20:20+n]); resto=b[20+n:]; return j,resto
jv,restov=leer(VIEJO); jn,resto=leer(NUEVO)
def binario(r): L=struct.unpack('<I',r[:4])[0]; return r[8:8+L]
BV,BN=binario(restov),binario(resto)
def vertices(j,B,i):
    pr=j['meshes'][j['nodes'][i]['mesh']]['primitives'][0]; a=j['accessors'][pr['attributes']['POSITION']]; bv=j['bufferViews'][a['bufferView']]
    st=bv.get('byteStride',12)//4; off=bv.get('byteOffset',0)+a.get('byteOffset',0)
    return np.frombuffer(B,dtype=np.float32,count=a['count']*st,offset=off).reshape(-1,st)[:,:3].astype(float)
def rigido(P,Q):
    """T 4x4 tal que Q ≈ T·P (mejor ajuste por mínimos cuadrados, con escala uniforme)."""
    cp,cq=P.mean(0),Q.mean(0); X,Y=P-cp,Q-cq
    U,S,Vt=np.linalg.svd(X.T@Y); d=np.sign(np.linalg.det(Vt.T@U.T)); Dm=np.diag([1,1,d])
    R=Vt.T@Dm@U.T; esc=(S*np.diag(Dm)).sum()/max((X**2).sum(),1e-12)
    T=np.eye(4); T[:3,:3]=R*esc; T[:3,3]=cq-esc*R@cp; err=np.abs((T[:3,:3]@P.T).T+T[:3,3]-Q).max(); return T,err
def ml(x):
    if 'matrix' in x: return np.array(x['matrix'],float).reshape(4,4).T
    T=np.eye(4); t=x.get('translation',[0,0,0]); r=x.get('rotation',[0,0,0,1]); s=x.get('scale',[1,1,1]); qx,qy,qz,qw=r
    R=np.array([[1-2*(qy*qy+qz*qz),2*(qx*qy-qz*qw),2*(qx*qz+qy*qw)],[2*(qx*qy+qz*qw),1-2*(qx*qx+qz*qz),2*(qy*qz-qx*qw)],[2*(qx*qz-qy*qw),2*(qy*qz+qx*qw),1-2*(qx*qx+qy*qy)]])
    T[:3,:3]=R*np.array(s); T[:3,3]=t; return T
def mundos(j):
    par={}; N=j['nodes']
    for i,x in enumerate(N):
        for c in x.get('children',[]): par[c]=i
    W={}
    def w(i):
        if i in W: return W[i]
        M=ml(N[i]); 
        if i in par: M=w(par[i])@M
        W[i]=M; return M
    return par,w
pv,wv=mundos(jv); pn,wn=mundos(jn)
iv={x.get('name',''):i for i,x in enumerate(jv['nodes']) if 'mesh' in x}
inn={x.get('name',''):i for i,x in enumerate(jn['nodes']) if 'mesh' in x}
def firma(j,i):
    pr=j['meshes'][j['nodes'][i]['mesh']]['primitives']; a=j['accessors'][pr[0]['attributes']['POSITION']]
    return (sum(j['accessors'][p['attributes']['POSITION']]['count'] for p in pr), tuple(np.round(a['min'],4)), tuple(np.round(a['max'],4)))
def centro(j,i,W):
    pr=j['meshes'][j['nodes'][i]['mesh']]['primitives']; a=j['accessors'][pr[0]['attributes']['POSITION']]
    return (W(i)@np.array([*(np.array(a['min'])+np.array(a['max']))/2,1]))[:3]
revertir=set(json.load(open('revertir.json')))
PIEL=re.compile(r'^(revestimiento|carenado|conjunto de puerta|puerta|capota|parabrisas|ventan|cubierta|tapa de nariz|conjunto de capó|capó|cono de cola|conjunto de cono de cola)',re.I)
cambiadas=0; pos=0
for nm,i in inn.items():
    if nm not in iv: continue
    v=iv[nm]
    cn=centro(jn,i,wn); cv=centro(jv,v,wv)
    if np.linalg.norm(cn-cv)<0.01 and firma(jn,i)==firma(jv,v): continue
    exterior=bool(PIEL.search(nm.split(' — ')[0])) and not re.search(r'F(37|12|69)-',nm)
    if nm not in revertir and not exterior: continue
    x=jn['nodes'][i]; P=wn(pn[i]) if i in pn else np.eye(4)
    if firma(jn,i)==firma(jv,v): nuevaW=wv(v); cambiadas+=1       # misma geometría: transformación del anterior
    else:
        fv,fn=firma(jv,v),firma(jn,i); T=None
        if fv[0]==fn[0]:                                # mismos vértices re-exportados: se busca el giro
            T,err=rigido(vertices(jv,BV,v),vertices(jn,BN,i))
            if err>1e-3: T=None
        if T is not None: nuevaW=wv(v)@np.linalg.inv(T); cambiadas+=1
        else: T=np.eye(4); T[:3,3]=cv-cn; nuevaW=T@wn(i); pos+=1       # geometría rehecha: sólo se recoloca
    L=np.linalg.inv(P)@nuevaW
    for k in ('translation','rotation','scale'): x.pop(k,None)
    x['matrix']=[float(v_) for v_ in L.T.reshape(-1)]
print('restauradas',cambiadas,'recolocadas',pos)
# Alternativas que Design dejó montadas (tolva de abertura grande): a MOD_VARIANTES, sin moverlas.
VARIANTE=re.compile(r'abertura grande',re.I)
N=jn['nodes']; par2={}
for i,x in enumerate(N):
    for c in x.get('children',[]): par2[c]=i
iv_=next(i for i,x in enumerate(N) if x.get('name','')=='MOD_VARIANTES')
Wv=wn(iv_); movidas=0
for i,x in enumerate(N):
    if 'mesh' in x and VARIANTE.search(x.get('name','')) and i in par2:
        a_=i
        while a_ in par2 and N[par2[a_]].get('name','')!='MOD_VARIANTES': a_=par2[a_]
        if a_ in par2: continue                     # ya estaba bajo MOD_VARIANTES
        W=wn(i); p_=par2[i]; N[p_]['children'].remove(i); N[iv_].setdefault('children',[]).append(i)
        for k in ('translation','rotation','scale'): x.pop(k,None)
        x['matrix']=[float(v_) for v_ in (np.linalg.inv(Wv)@W).T.reshape(-1)]; movidas+=1
print('a MOD_VARIANTES',movidas)
# Piezas que Design rehízo con otra forma y quedaron mal (panel de techo de pie, etc.): se
# trasplanta la malla completa de la versión anterior, con su posición.
TRASPLANTE=['Conjunto de puerta de acceso del fuselaje derecha — 1613292-20 — F22-18','Revestimiento izquierdo — 1613137-1 — F24-4',
  'Revestimiento derecho — 1613181-6 — F24-17','Cubierta derecha — 0712057-6 — F31-82','Ángulo de refuerzo del cono de cola derecho — 0712207-2AGW — F32-43',
  'Placa de refuerzo del flap de capó derecho — 1652016-2 — F66-28','Placa de empalme derecha — 1612001-4 — F31-7']
TIPO={5120:np.int8,5121:np.uint8,5122:np.int16,5123:np.uint16,5125:np.uint32,5126:np.float32}
NC={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}
nuevo_bin=bytearray(BN)
def copiar_accesor(ia):
    a=jv['accessors'][ia]; bv=jv['bufferViews'][a['bufferView']]; dt=np.dtype(TIPO[a['componentType']]); nc=NC[a['type']]
    st=bv.get('byteStride',dt.itemsize*nc); off=bv.get('byteOffset',0)+a.get('byteOffset',0)
    filas=[np.frombuffer(BV,dtype=dt,count=nc,offset=off+k*st) for k in range(a['count'])]
    datos=np.array(filas,dtype=dt).tobytes()
    while len(nuevo_bin)%4: nuevo_bin.append(0)
    jn['bufferViews'].append({'buffer':0,'byteOffset':len(nuevo_bin),'byteLength':len(datos)}); nuevo_bin.extend(datos)
    a2={k:v for k,v in a.items() if k not in ('bufferView','byteOffset')}; a2['bufferView']=len(jn['bufferViews'])-1
    jn['accessors'].append(a2); return len(jn['accessors'])-1
mat_por_nombre={m.get('name'):k for k,m in enumerate(jn['materials'])}
tras=0
for nm in TRASPLANTE:
    if nm not in iv or nm not in inn: continue
    v,i=iv[nm],inn[nm]; prims=[]
    for pr in jv['meshes'][jv['nodes'][v]['mesh']]['primitives']:
        p2={'attributes':{k:copiar_accesor(x) for k,x in pr['attributes'].items()}}
        if 'indices' in pr: p2['indices']=copiar_accesor(pr['indices'])
        if 'material' in pr: p2['material']=mat_por_nombre.get(jv['materials'][pr['material']].get('name'),pr['material'])
        if 'mode' in pr: p2['mode']=pr['mode']
        prims.append(p2)
    jn['meshes'].append({'name':jv['meshes'][jv['nodes'][v]['mesh']].get('name',nm),'primitives':prims})
    x=jn['nodes'][i]; x['mesh']=len(jn['meshes'])-1; P=wn(pn[i]) if i in pn else np.eye(4)
    for k in ('translation','rotation','scale'): x.pop(k,None)
    x['matrix']=[float(q) for q in (np.linalg.inv(P)@wv(v)).T.reshape(-1)]; tras+=1
while len(nuevo_bin)%4: nuevo_bin.append(0)
jn['buffers'][0]['byteLength']=len(nuevo_bin)
resto=struct.pack('<II',len(nuevo_bin),0x004E4942)+bytes(nuevo_bin)
print('trasplantadas',tras)
js=json.dumps(jn,ensure_ascii=False,separators=(',',':')).encode('utf-8'); js+=b' '*((4-len(js)%4)%4)
total=12+8+len(js)+len(resto)
open(SALIDA,'wb').write(struct.pack('<III',0x46546C67,2,total)+struct.pack('<II',len(js),0x4E4F534A)+js+resto)
