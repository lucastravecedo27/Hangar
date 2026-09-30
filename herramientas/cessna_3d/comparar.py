import re,collections,numpy as np,json,os
def cargar(ruta):
    os.environ['GLB']=ruta; g={}
    exec(open('auditar_glb.py').read().split("allo=np.min")[0], g)
    return {p['nombre']:p for p in g['piezas']}
D="/Users/lucastravecedo/Documents/Control y seguimiento matenimieno UAV/Informacion /Informacion Drones/C188/3D/"
A=cargar(D+"anteriores/cessna-188-despiece 2026-09-27 13.28.glb"); B=cargar(D+"cessna-188-despiece.glb")
PIEL=re.compile(r'revestimiento|capó|capo |carenado|chapa|panel|puerta|parabrisas|ventan|capota|cono de cola|punta|carena|tapa de nariz|borde de ataque|cubierta|flap del cap',re.I)
cambios=[]
for nm,b in B.items():
    a=A.get(nm)
    if not a: continue
    dc=np.linalg.norm(a['c']-b['c']); dt=np.abs(a['t']-b['t']).max()
    if (dc>0.03 or dt>0.03 or a['v']!=b['v'] or a['mats']!=b['mats']) and PIEL.search(nm.split(' — ')[0]):
        cambios.append((round(dc,2),round(dt,2),a['v'],b['v'],sorted(a['mats']),sorted(b['mats']),nm))
print('piezas de piel que cambiaron:',len(cambios))
for c in sorted(cambios,key=lambda x:-(x[0]+x[1]))[:60]: print(c[:4], c[4] if c[4]!=c[5] else '', '→',c[5] if c[4]!=c[5] else '', c[6][:80])
nuevas=[n for n in B if n not in A]; quitadas=[n for n in A if n not in B]
print('nuevas',len(nuevas),'quitadas',len(quitadas))
print('quitadas piel:',[n[:70] for n in quitadas if PIEL.search(n.split(' — ')[0])][:30])
print('nuevas piel:',[n[:70] for n in nuevas if PIEL.search(n.split(' — ')[0])][:30])
