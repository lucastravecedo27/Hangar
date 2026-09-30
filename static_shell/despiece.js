// Modelo 3D del DJI Agras T50 (geometría procedimental detallada, Three.js r128) con animación de selección:
//
// La pantalla trabaja con UN modelo a la vez, el que diga MODELO_3D, y sólo con los modelos que
// tienen archivo 3D (hoy sólo el T50). No sigue al dron seleccionado a propósito: si lo hiciera,
// un T70P mostraría sus láminas junto a la carrocería de un T50. Los modelos sin archivo 3D se
// trabajan desde la pantalla de Diagramas.
// al hacer clic, la pieza sale hacia la cámara, el resto se atenúa y se muestra su desgaste.
(function(){
  const $cargando=document.getElementById('cargando'), visor=document.getElementById('visor'), canvas=document.getElementById('canvas3d'), etiqueta=document.getElementById('etiqueta');
  if(typeof THREE==='undefined'){ $cargando.textContent='No se pudo cargar Three.js (requiere conexión a internet la primera vez).'; return; }
  window.addEventListener('error', e=>{ if($cargando.isConnected) $cargando.textContent='Error en el visor 3D: '+(e.message||e); });

  const COLOR={ok:0x8f9d8a, proximo:0xe8a400, critico:0xe0473e, vencido:0xb3261e};
  let renderer;
  try{
    renderer=new THREE.WebGLRenderer({canvas, antialias:true, alpha:true, powerPreference:'high-performance'});
  }catch(err){
    $cargando.textContent='Este navegador no puede dibujar 3D (WebGL no disponible). Prueba con Chrome, Edge o Safari actualizados.';
    return;
  }
  // El navegador puede tirar el contexto WebGL (cambio de GPU, suspensión, pestaña en segundo
  // plano mucho rato). Sin esto la vista se queda en negro para siempre.
  canvas.addEventListener('webglcontextlost', e=>{ e.preventDefault(); dibujando=false;
    if(!document.getElementById('aviso3d')){ const d=document.createElement('div'); d.id='aviso3d';
      d.className='cargando'; d.textContent='Recuperando el visor 3D…'; visor.appendChild(d); } }, false);
  canvas.addEventListener('webglcontextrestored', ()=>{ const d=document.getElementById('aviso3d'); if(d) d.remove();
    anchoCanvas=0; ajustar(); dibujando=true; }, false);
  renderer.setPixelRatio(Math.min(devicePixelRatio,2)); renderer.outputEncoding=THREE.sRGBEncoding;
  renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  // Tono neutro: ACES es un mapeo cinematográfico que desplaza los claros hacia el naranja, y
  // sobre el gris del T50 se veía amarillento. Con mapeo lineal el material sale con el color
  // que trae el archivo, que es lo que interesa para identificar una pieza.
  renderer.toneMapping=THREE.LinearToneMapping; renderer.toneMappingExposure=1;
  const scene=new THREE.Scene(); const camera=new THREE.PerspectiveCamera(36,1,.1,100);
  // Fondo del visor: el composer del bloom escribe alpha opaco, así que el degradado del CSS
  // quedaba tapado por un gris. Se dibuja un telón propio pegado a la cámara. No puede ir en
  // scene.background porque ese camino sí pasa por el tone mapping ACES y aplasta el degradado.
  const fondo=(function(){
    const N=512, c=document.createElement('canvas'); c.width=c.height=N; const ctx=c.getContext('2d');
    const g=ctx.createRadialGradient(N*.5,N*.38,0, N*.5,N*.38,N*.80);
    g.addColorStop(0,'#f4f4f5'); g.addColorStop(.28,'#e6e7ea'); g.addColorStop(.58,'#c9ccd3'); g.addColorStop(.82,'#a7abb5'); g.addColorStop(1,'#8a8f9a');
    ctx.fillStyle=g; ctx.fillRect(0,0,N,N);
    const tex=new THREE.CanvasTexture(c); tex.encoding=THREE.sRGBEncoding; tex.minFilter=THREE.LinearFilter; tex.generateMipmaps=false;
    const m=new THREE.Mesh(new THREE.PlaneGeometry(1,1),
      new THREE.MeshBasicMaterial({map:tex, depthTest:false, depthWrite:false, toneMapped:false, fog:false}));
    m.renderOrder=-1; m.frustumCulled=false; m.position.z=-30;
    camera.add(m); scene.add(camera);   // la cámara debe estar en la escena para que se dibuje el telón
    return m;
  })();
  function ajustarFondo(){
    const h=2*30*Math.tan(THREE.MathUtils.degToRad(camera.fov)/2);
    fondo.scale.set(h*camera.aspect*1.05, h*1.05, 1);
  }
  // Luces neutras. Antes eran cálidas (cielo crema, rebote tierra, relleno ámbar) y teñían de
  // amarillo todo el dron; el gris del T50 salía beige. Ahora sólo el rebote del suelo conserva
  // un matiz frío, que es lo que hace un hangar real con suelo claro.
  scene.add(new THREE.HemisphereLight(0xffffff,0xe6e7ea,.42));
  const sol=new THREE.DirectionalLight(0xffffff,.78); sol.position.set(4,8,5); sol.castShadow=true; sol.shadow.mapSize.set(4096,4096); sol.shadow.radius=2;
  sol.shadow.camera.left=-5; sol.shadow.camera.right=5; sol.shadow.camera.top=5; sol.shadow.camera.bottom=-5; sol.shadow.bias=-.0005; scene.add(sol);
  const relleno=new THREE.DirectionalLight(0xffffff,.3); relleno.position.set(-5,3,-4); scene.add(relleno);
  // Fondo claro original (crema) con suelo de sombras suaves y rejilla discreta
  const Y_SUELO=-1.62;
  const suelo=new THREE.Mesh(new THREE.PlaneGeometry(16,16), new THREE.ShadowMaterial({opacity:.26})); suelo.rotation.x=-Math.PI/2; suelo.position.y=Y_SUELO; suelo.receiveShadow=true; scene.add(suelo);
  const rejilla=new THREE.GridHelper(12,24,0xb6bcc6,0xd3d6dc); rejilla.position.y=Y_SUELO+.002; scene.add(rejilla);
  rejilla.material.transparent=true; rejilla.material.opacity=.7;
  const halo=new THREE.Mesh(new THREE.CircleGeometry(3.4,96), new THREE.MeshBasicMaterial({color:0xfdb913, transparent:true, opacity:.05})); halo.rotation.x=-Math.PI/2; halo.position.y=Y_SUELO+.004; scene.add(halo);
  // Polvo del rotor: el chorro de las hélices arrastra el suelo hacia fuera en un anillo bajo.
  // Vive en la escena y no dentro del dron, porque se queda pegado al suelo mientras la máquina
  // sube. Cada partícula lleva su ángulo de salida, su velocidad radial y su propio ritmo de
  // vida, para que el anillo no lata todo a la vez.
  const POLVO=(function(){
    const n=560, pos=new Float32Array(n*3), vida=new Float32Array(n), sem=new Float32Array(n*3);
    for(let i=0;i<n;i++){
      vida[i]=Math.random();
      sem[i*3]=Math.random()*Math.PI*2;
      sem[i*3+1]=.35+Math.random()*.6;
      sem[i*3+2]=.55+Math.random()*.9;
    }
    const geo=new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos,3));
    const pts=new THREE.Points(geo, new THREE.PointsMaterial({
      color:0xc0ae8c, size:.075, transparent:true, opacity:0, depthWrite:false}));
    pts.position.y=Y_SUELO+.02; scene.add(pts);
    return {pts, vida, sem, n, geo};
  })();

  const foco=new THREE.SpotLight(0xffffff,.52,30,.6,.5,1); foco.position.set(0,9,2); foco.target.position.set(0,-.5,0); scene.add(foco); scene.add(foco.target);
  const borde=new THREE.DirectionalLight(0xdcE8f4,.38); borde.position.set(-6,2,-6); scene.add(borde);
  let composer=null, bloom=null;
  if(THREE.EffectComposer&&THREE.UnrealBloomPass){ composer=new THREE.EffectComposer(renderer); composer.setPixelRatio(renderer.getPixelRatio()); composer.addPass(new THREE.RenderPass(scene,camera)); bloom=new THREE.UnrealBloomPass(new THREE.Vector2(visor.clientWidth,visor.clientHeight), .18, .5, .99); composer.addPass(bloom); }

  // ---- Materiales (colores del T50 real: fuselaje gris claro, brazos/motores/tren negros) ----
  const M={
    gris:()=>new THREE.MeshStandardMaterial({color:0x9da2a7, metalness:.1, roughness:.55}),
    verde:()=>new THREE.MeshStandardMaterial({color:0x9da2a7, metalness:.1, roughness:.55}),
    grisOscuro:()=>new THREE.MeshStandardMaterial({color:0x666b70, metalness:.15, roughness:.55}),
    carbono:()=>new THREE.MeshStandardMaterial({color:0x141618, metalness:.4, roughness:.32}),
    negro:()=>new THREE.MeshStandardMaterial({color:0x1e2124, metalness:.3, roughness:.5}),
    aluminio:()=>new THREE.MeshStandardMaterial({color:0xa7adb3, metalness:.9, roughness:.28}),
    goma:()=>new THREE.MeshStandardMaterial({color:0x0f1012, metalness:0, roughness:.95}),
    tanque:()=>new THREE.MeshPhysicalMaterial({color:0xa9aeb3, metalness:0, roughness:.35, transparent:true, opacity:.9, clearcoat:.4}),
    pantalla:()=>new THREE.MeshStandardMaterial({color:0x0d1a26, metalness:.6, roughness:.15, emissive:0x0a2238, emissiveIntensity:.6}),
  };
  const dron=new THREE.Group(); scene.add(dron);
  const PARTES=[]; const PROPS=[]; const NIEBLAS=[];
  // Cada malla con nombre propio del archivo 3D es una pieza identificable por separado.
  const PIEZAS=[];
  const V=(x,y,z)=>new THREE.Vector3(x,y,z);
  function mesh(geo, mat){ const m=new THREE.Mesh(geo,mat); m.castShadow=true; m.receiveShadow=true; return m; }
  const caja=(w,h,d,mat,seg,rad)=>{ const r=rad!==undefined?rad:Math.min(w,h,d)*.22; const geo=(THREE.RoundedBoxGeometry&&r>0)?new THREE.RoundedBoxGeometry(w,h,d,6,r):new THREE.BoxGeometry(w,h,d,seg,seg,seg); return mesh(geo,mat); };
  function torneado(perfil, mat, seg=72){ return mesh(new THREE.LatheGeometry(perfil.map(([r,y])=>new THREE.Vector2(r,y)), seg), mat); }
  function tuboCurvo(puntos, r, mat){ const curva=new THREE.CatmullRomCurve3(puntos, false, 'catmullrom', .35); return mesh(new THREE.TubeGeometry(curva, 84, r, 22, false), mat); }
  function pala(largo, ancho, mat){
    const f=new THREE.Shape(); f.moveTo(0,-ancho*.35); f.quadraticCurveTo(largo*.25,-ancho*.55, largo*.6,-ancho*.42); f.quadraticCurveTo(largo*.95,-ancho*.25, largo,0);
    f.quadraticCurveTo(largo*.95,ancho*.25, largo*.6,ancho*.42); f.quadraticCurveTo(largo*.25,ancho*.55, 0,ancho*.35); f.closePath();
    const geo=new THREE.ExtrudeGeometry(f,{depth:.008, bevelEnabled:true, bevelThickness:.003, bevelSize:.004, bevelSegments:4, steps:2, curveSegments:24});
    const pos=geo.attributes.position; for(let i=0;i<pos.count;i++){ const x=pos.getX(i), y=pos.getY(i), z=pos.getZ(i); const tw=(x/largo)*.35; pos.setY(i, y*Math.cos(tw)-z*Math.sin(tw)); pos.setZ(i, y*Math.sin(tw)+z*Math.cos(tw)); } geo.computeVertexNormals();
    const m=mesh(geo,mat); m.rotation.x=-Math.PI/2; return m; }
  const cil=(rt,rb,h,mat,seg=48)=>mesh(new THREE.CylinderGeometry(rt,rb,h,seg), mat);
  const esf=(r,mat)=>mesh(new THREE.SphereGeometry(r,48,32), mat);
  function tubo(a,b,r,mat){ const d=b.clone().sub(a); const m=cil(r,r,d.length(),mat,24); m.position.copy(a).add(d.clone().multiplyScalar(.5)); m.quaternion.setFromUnitVectors(V(0,1,0), d.clone().normalize()); return m; }
  function parte(key, nombre, dir, dist, base, ...objs){
    const g=new THREE.Group(); g.position.copy(base); objs.forEach(o=>{ let idx=0; o.traverse(n=>{ if(n.isMesh){ n.userData.key=key; n.material.transparent=n.material.transparent||false; n.userData.op=n.material.opacity; n.userData.basePos=n.position.clone(); n.userData.idx=idx++; } }); g.add(o); });
    dron.add(g); const p={key, nombre, grupo:g, base:base.clone(), dir:dir.clone().normalize(), dist, objs, offset:new THREE.Vector3()}; PARTES.push(p); return p;
  }

  // ---- Fuselaje (gris claro, boxy, con paneles laterales) ----
  (function(){
    const g=new THREE.Group();
    const cuerpo=caja(.96,.38,1.0,M.gris(),2,.07); g.add(cuerpo);
    const bajo=caja(.9,.12,.9,M.grisOscuro()); bajo.position.y=-.24; g.add(bajo);
    for(const s of [-1,1]){ const panel=caja(.03,.26,.7,M.grisOscuro()); panel.position.set(s*.49,-.02,0); g.add(panel); const nervio=caja(.05,.05,.86,M.gris()); nervio.position.set(s*.47,.14,0); g.add(nervio); }
    const bandeja=caja(.7,.03,.6,M.negro()); bandeja.position.set(.1,.2,-.1); g.add(bandeja);
    parte('marco_c','Marco central',V(0,1,0),0,V(0,0,0),g);
  })();
  (function(){
    const g=new THREE.Group();
    const f=caja(.8,.3,.34,M.verde(),2); g.add(f);
    for(const s of [-1,1]){ const domo=esf(.06,M.gris()); domo.position.set(s*.3,.17,.02); g.add(domo); }
    const fpv=cil(.045,.045,.05,M.goma()); fpv.rotation.x=Math.PI/2; fpv.position.set(0,-.02,.18); g.add(fpv);
    const lente=cil(.025,.025,.02,M.pantalla()); lente.rotation.x=Math.PI/2; lente.position.set(0,-.02,.21); g.add(lente);
    parte('marco_d','Marco delantero',V(0,0,1),1,V(0,.0,.66),g);
  })();
  (function(){
    const g=new THREE.Group(); g.add(caja(.8,.3,.34,M.verde(),2));
    const ventila=caja(.55,.14,.02,M.goma()); ventila.position.set(0,-.02,-.17); g.add(ventila);
    parte('marco_t','Marco trasero',V(0,0,-1),1,V(0,0,-.66),g);
  })();
  // Batería superior gris con nervaduras
  (function(){
    const g=new THREE.Group();
    const b=caja(.62,.3,.6,M.verde(),2,.05); g.add(b);
    for(let i=-1;i<=1;i++){ const nerv=caja(.36,.025,.05,M.gris()); nerv.position.set(0,.16,i*.14); g.add(nerv); }
    const asa=caja(.34,.03,.06,M.negro()); asa.position.set(0,.13,-.28); g.add(asa);
    const conector=caja(.2,.06,.04,M.negro()); conector.position.set(.1,-.05,.31); g.add(conector);
    for(let i=0;i<4;i++){ const led=caja(.025,.01,.02,M.pantalla()); led.position.set(-.12+i*.08,.16,.27); g.add(led); }
    parte('bateria','Batería',V(0,1,0),1.4,V(.06,.34,-.05),g);
  })();
  // RTK (cilindro delante-izquierda y detrás-derecha) y antena SDR
  (function(){
    const g=new THREE.Group();
    const r1=torneado([[0,0],[.09,0],[.1,.02],[.1,.17],[.095,.2],[.06,.21],[0,.21]],M.gris()); r1.position.set(-.36,0,.3); g.add(r1); const t1=cil(.06,.06,.01,M.grisOscuro()); t1.position.set(-.36,.215,.3); g.add(t1);
    const r2=cil(.07,.07,.12,M.gris()); r2.position.set(.38,.06,-.38); g.add(r2);
    parte('rtk','Módulo RTK',V(-.6,1,.4),1.7,V(0,.2,0),g);
    const a=new THREE.Group(); const rod=cil(.007,.01,.3,M.goma()); rod.position.y=.15; a.add(rod); const punta=esf(.012,M.goma()); punta.position.y=.31; a.add(punta);
    parte('antena','Antena SDR',V(.6,1,-.4),2,V(.32,.2,-.2),a);
  })();
  // Radares fasados (cajas negras compactas delante y detrás)
  for(const [key,nombre,z,dir] of [['radar_d','Radar delantero',.9,V(0,.4,1)],['radar_t','Radar trasero',-.9,V(0,.4,-1)]]){
    const g=new THREE.Group(); const c=caja(.16,.14,.1,M.negro(),2); g.add(c);
    const cara=caja(.13,.11,.01,M.goma()); cara.position.z=Math.sign(z)*.055; g.add(cara);
    const sop=caja(.08,.04,.1,M.aluminio()); sop.position.set(0,-.08,-Math.sign(z)*.03); g.add(sop);
    parte(key,nombre,dir,1.6,V(0,.02,z),g);
  }
  // Brazos de carbono (negros) con bisagra, motores coaxiales negros y hélices de 54"
  const L=1.35;
  [[1,1],[-1,1],[-1,-1],[1,-1]].forEach(([sx,sz],i)=>{
    const dir=V(sx,0,sz).normalize(); const ang=Math.atan2(sx,sz);
    const raizPos=V(sx*.46, .02, sz*.48); const fin=raizPos.clone().addScaledVector(dir,L);
    const g=new THREE.Group();
    const tb=tubo(V(0,0,0).addScaledVector(dir,-L/2+.12), V(0,0,0).addScaledVector(dir,L/2), .032, M.carbono()); g.add(tb);
    const bis=caja(.16,.14,.1,M.aluminio()); bis.position.copy(dir.clone().multiplyScalar(-L/2+.06)); bis.rotation.y=ang; g.add(bis);
    const pasador=cil(.05,.05,.17,M.negro()); pasador.position.copy(dir.clone().multiplyScalar(-L/2+.06)); g.add(pasador);
    const cierre=caja(.09,.06,.14,M.negro()); cierre.position.copy(dir.clone().multiplyScalar(-L/2+.2)); cierre.rotation.y=ang; g.add(cierre);
    const soporte=caja(.12,.16,.12,M.negro()); soporte.position.copy(dir.clone().multiplyScalar(L/2)); soporte.rotation.y=ang; g.add(soporte);
    const esc=new THREE.Group(); const escCaja=caja(.16,.08,.11,M.negro()); esc.add(escCaja);
    for(let k=-3;k<=3;k++){ const al=caja(.14,.03,.006,M.aluminio()); al.position.set(0,.05,k*.014); esc.add(al); }
    esc.position.copy(dir.clone().multiplyScalar(L/2-.2)).add(V(0,.06,0)); esc.rotation.y=ang; g.add(esc);
    const palanca=caja(.05,.03,.12,M.negro()); palanca.position.copy(dir.clone().multiplyScalar(-L/2+.14)).add(V(0,-.07,0)); palanca.rotation.y=ang; g.add(palanca);
    parte('brazo','Conector de brazo M'+(i+1),dir,1,raizPos.clone().addScaledVector(dir,L/2),g);
    for(const [lado,ky] of [[1,.13],[-1,-.14]]){
      const mg=new THREE.Group();
      const carcasa=torneado([[0,-.055],[.07,-.055],[.09,-.045],[.095,.0],[.09,.045],[.075,.055],[.05,.06],[.02,.062],[0,.062]],M.negro()); if(lado<0) carcasa.rotation.z=Math.PI; mg.add(carcasa);
      const campana=torneado([[0,0],[.06,0],[.078,.01],[.082,.028],[.07,.036],[0,.036]],M.carbono()); campana.position.y=lado*.06; if(lado<0) campana.rotation.z=Math.PI; mg.add(campana);
      for(let k=0;k<14;k++){ const a=k/14*Math.PI*2; const aleta=caja(.014,.08,.005,M.aluminio()); aleta.position.set(Math.cos(a)*.092,0,Math.sin(a)*.092); aleta.rotation.y=-a; mg.add(aleta); }
      const eje=cil(.018,.018,.05,M.aluminio()); eje.position.y=lado*.1; mg.add(eje);
      parte('motor','Motor M'+(i+1)+(lado>0?' superior':' inferior'),dir.clone().add(V(0,lado*.4,0)),1.6,fin.clone().add(V(0,ky,0)),mg);
      const hg=new THREE.Group(); const cubo=cil(.045,.045,.028,M.carbono()); hg.add(cubo);
      for(const s of [-1,1]){ const p=pala(.68,.075,M.carbono()); p.rotation.z=s>0?0:Math.PI; p.position.x=s*.03; hg.add(p); }
      const disco=new THREE.Mesh(new THREE.CircleGeometry(.72,48), new THREE.MeshBasicMaterial({color:0x9aa4ad, transparent:true, opacity:0, side:THREE.DoubleSide, depthWrite:false})); disco.rotation.x=-Math.PI/2; disco.userData.esDisco=true; hg.add(disco);
      hg.rotation.y=i*.7+lado; PROPS.push({g:hg, sentido:(i%2?1:-1)*lado, disco});
      parte('helice','Hélice M'+(i+1)+(lado>0?' superior':' inferior'),dir.clone().add(V(0,lado*.9,0)),1.9,fin.clone().add(V(0,ky+lado*.12,0)),hg);
    }
  });
  // Tanque de 40 L gris claro bajo el fuselaje, filtro, bomba y caudalímetro
  (function(){
    const g=new THREE.Group(); const t=caja(.8,.46,.74,M.tanque(),3,.09); g.add(t);
    const banda=caja(.82,.04,.76,M.grisOscuro()); banda.position.y=.2; g.add(banda);
    const banda2=caja(.82,.04,.76,M.grisOscuro()); banda2.position.y=-.2; g.add(banda2);
    parte('tanque','Tanque de aspersión',V(0,-1,0),1.3,V(0,-.52,.02),g);
    const f=new THREE.Group(); const tapa=cil(.08,.08,.05,M.negro()); f.add(tapa); const rosca=cil(.06,.06,.04,M.grisOscuro()); rosca.position.y=-.04; f.add(rosca);
    parte('filtro','Filtro y medidor de nivel',V(.6,-1,.6),1.9,V(.25,-.26,.28),f);
    const b=new THREE.Group(); for(const s of [-1,1]){ const c=cil(.06,.06,.2,M.negro()); c.rotation.x=Math.PI/2; c.position.x=s*.12; b.add(c); const m=cil(.05,.05,.1,M.carbono()); m.rotation.x=Math.PI/2; m.position.set(s*.12,0,-.15); b.add(m); }
    parte('bomba','Bomba de suministro',V(0,-1,-1),1.7,V(0,-.7,-.42),b);
    const c=caja(.1,.1,.08,M.negro()); parte('caudalimetro','Caudalímetro',V(-1,-1,.3),1.9,V(-.36,-.62,.24),c);
  })();
  // Aspersores centrífugos (negros) colgando bajo los brazos traseros
  [[1,-1],[-1,-1]].forEach(([sx,sz])=>{
    const dir=V(sx,0,sz).normalize(); const pos=V(sx*.46+dir.x*L*.6, -.22, sz*.48+dir.z*L*.6);
    const g=new THREE.Group(); const brida=cil(.028,.028,.26,M.negro()); brida.position.y=.13; g.add(brida);
    const motor=cil(.055,.055,.14,M.negro()); g.add(motor); const disco=cil(.12,.14,.02,M.carbono()); disco.position.y=-.085; g.add(disco); const disco2=cil(.1,.12,.015,M.carbono()); disco2.position.y=-.105; g.add(disco2);
    parte('aspersor','Aspersor centrífugo',dir.clone().add(V(0,-1.2,0)),1.6,pos,g);
    // niebla de aspersión (partículas que caen en cono)
    (function(){ const n=420, p=new Float32Array(n*3), vida=new Float32Array(n); for(let i=0;i<n;i++){ vida[i]=Math.random(); }
      const geo=new THREE.BufferGeometry(); geo.setAttribute('position',new THREE.BufferAttribute(p,3));
      const pts=new THREE.Points(geo,new THREE.PointsMaterial({color:0xff9a7a,size:.045,transparent:true,opacity:.5,depthWrite:false}));
      pts.position.set(0,-.12,0); g.add(pts); NIEBLAS.push({pts,vida,n}); })();
  });
  // Tren de aterrizaje (según diagrama DJI): tubos en L con codo, patín, pies de goma y barras cruzadas
  [[1],[-1]].forEach(([s])=>{
    const g=new THREE.Group(); const yPat=-1.0, xP=s*.52;
    for(const z of [-.42,.42]){
      const arriba=V(s*.36,-.16,z);
      g.add(tuboCurvo([arriba, V(s*.44,-.55,z*1.02), V(xP,yPat+.12,z*1.05), V(xP,yPat,z*1.4), V(xP,yPat,z*2.05)], .024, M.carbono()));
      const sop=caja(.1,.06,.08,M.aluminio(),1,.012); sop.position.copy(arriba).add(V(0,.03,0)); g.add(sop);
    }
    g.add(tubo(V(xP,yPat,-.5), V(xP,yPat,.5), .024, M.carbono()));
    for(const z of [-.86,.86]){ const pie=cil(.04,.032,.07,M.goma()); pie.rotation.x=Math.PI/2; pie.position.set(xP,yPat,z); g.add(pie); }
    for(const z of [-.42,.42]){ const abraz=cil(.034,.034,.05,M.negro()); abraz.position.set(xP,yPat+.06,z*1.05); g.add(abraz); }
    parte('tren','Tren de aterrizaje '+(s>0?'derecho':'izquierdo'),V(s*.6,-1,0),1.4,V(0,0,0),g);
  });
  // Barras cruzadas del tren
  (function(){ const g=new THREE.Group(); g.add(tubo(V(-.52,-1.0,-.42),V(.52,-1.0,-.42),.02,M.carbono())); g.add(tubo(V(-.52,-.92,.42),V(.52,-.92,.42),.02,M.carbono())); parte('tren','Barras cruzadas del tren',V(0,-1,0),1.4,V(0,0,0),g); })();
  // Control remoto y cargador en el suelo
  (function(){
    const g=new THREE.Group(); const c=caja(.5,.09,.32,M.negro(),2); g.add(c); const p=caja(.42,.005,.22,M.pantalla()); p.position.y=.048; g.add(p);
    for(const s of [-1,1]){ const st=cil(.03,.03,.03,M.goma()); st.position.set(s*.19,.06,.08); g.add(st); const ant=cil(.006,.006,.2,M.goma()); ant.position.set(s*.2,.14,-.15); ant.rotation.x=-.4; g.add(ant); }
    parte('control','Control remoto',V(1,.2,0),.9,V(2.4,-1.5,1.0),g);
    const k=new THREE.Group(); const cj=caja(.55,.32,.4,M.verde(),2); k.add(cj); const rej=caja(.4,.2,.01,M.goma()); rej.position.z=.2; k.add(rej); const mango=caja(.3,.03,.05,M.negro()); mango.position.y=.18; k.add(mango);
    parte('cargador','Cargador',V(-1,.2,0),.9,V(-2.4,-1.39,1.0),k);
  })();

  // ---- Estado ----
  let EQUIPOS=[], EQUIPO=null, COMPS=[], porMesh={}, porClave={}, SEL=null, HOVER=null, FILTRO='todas';
  // PIEZA: malla concreta del archivo 3D seleccionada; SEL: componente de mantenimiento del conjunto.
  let PIEZA=null, PIEZA_HOVER=null, BUSCA='';
  let DIAGRAMAS=[];
  // ---- Modo avión ----
  // Un avión trae ~9.200 mallas: verlas todas sueltas es ilegible y dibujarlas una a una es
  // lento. Se trabaja en tres niveles: SISTEMA (MOD_*) → GRUPO (una figura del catálogo, FIG_*)
  // → PIEZA. Cada grupo se dibuja fusionado en unos pocos «lotes» (uno por material) y sólo el
  // grupo abierto enseña sus piezas sueltas, que son las únicas que se pueden pinchar una a una.
  let PILOTO=null;
  let ES_AVION=false, GRUPOS=[], GRUPO_ABIERTO=null, VER_INTERIOR=false;
  // Tercera fase del despiece: todas las piezas sueltas y separadas (el despiece completo).
  let MODO_PIEZAS=false;
  // «Quitar tapas»: oculta tapas, cubiertas, capó, carenados, paneles y guardabarros (avión y drones).
  let SIN_TAPAS=false;
  const RX_TAPA=/\btapa|tapón|cubierta|cobertor|capó|\bcapo\b|carenado|carena|panel|guardabarros|registro de inspecci|puerta de (acceso|inspecci|servicio)|cover|cap\b|lid\b|fairing|cowl/i;
  // «Tapa del larguero» (spar cap) y los dobladores son estructura, no tapas.
  const esTapa=t=>RX_TAPA.test(t)&&!/larguero|doblador|refuerzo|spar cap/i.test(t);
  // Sistema elegido en el panel (sin grupo abierto): se resalta en el 3D y el panel lista sus grupos.
  let SISTEMA_SEL=null;
  const nGrupos=n=>ES_AVION?`${n} ${n===1?'grupo':'grupos'}`:`${n} ${n===1?'conjunto':'conjuntos'}`;
  const nomEquipo=()=>ES_AVION?'avión':'dron';
  const SIS_ABIERTOS=new Set();
  const NOMBRE_SISTEMA={MOD_ALA:'Ala', MOD_EMPENAJE:'Empenaje', MOD_FUSELAJE:'Fuselaje', MOD_CABINA:'Cabina',
    MOD_TOLVA:'Tolva', MOD_TREN:'Tren de aterrizaje', MOD_HELICE:'Hélice', MOD_MOTOR:'Motor',
    MOD_MANDOS:'Mandos de vuelo', MOD_COMBUSTIBLE:'Combustible', MOD_APLICACION:'Sistema de aplicación',
    MOD_ELECTRICO:'Eléctrico'};
  // Drones: sus conjuntos se reparten en sistemas funcionales para el explorador de piezas.
  const SIS_DRON={helice:'Propulsión', motor:'Propulsión', brazo:'Propulsión',
    tanque:'Aspersión', bomba:'Aspersión', caudalimetro:'Aspersión', filtro:'Aspersión', aspersor:'Aspersión',
    marco_c:'Estructura', marco_d:'Estructura', marco_t:'Estructura', tren:'Estructura',
    radar_d:'Sensores y enlace', radar_t:'Sensores y enlace', rtk:'Sensores y enlace', antena:'Sensores y enlace',
    bateria:'Energía'};
  const ORDEN_SIS_DRON=['Propulsión','Aspersión','Estructura','Sensores y enlace','Energía','Otros'];
  const nombreSistema=k=>NOMBRE_SISTEMA[k]||String(k).replace(/^MOD_/,'').toLowerCase().replace(/^./,c=>c.toUpperCase());
  const MESH2MOD={motor:'brazo_m1', brazo:'brazo_m1', helice:'helices', tanque:'tanque_2', filtro:'tanque_1', bomba:'bomba', caudalimetro:'caudalimetro', radar_d:'radar_delantero', radar_t:'radar_trasero', marco_d:'marco_delantero', marco_c:'marco_central', marco_t:'marco_trasero', bateria:'marco_central', rtk:'marco_trasero', antena:'marco_delantero', aspersor:'aspersor', tren:'tren'};
  const CLAVE2MOD={hose:'tanque_2', hose_connector:'tanque_2', spray_tank:'tanque_2', propeller_adapter:'helices', propeller_gasket:'helices', esc:'brazo_m1', arm_bolt:'brazo_m1', arm_fixing_screw:'brazo_m1', battery_slider:'marco_central', landing_gear_screw:'tren', delivery_pump_motor:'bomba', centrifugal_motor:'lanza', radar_bracket:'radar_delantero', rf_module:'marco_central', aerial_electronics:'radiador', cable_board:'placa_distribucion', spraying_module:'tanque_1', power_module:'placa_distribucion', weight_sensor:'marco_central', aircraft_connector:'cableado', aircraft_cable:'cableado'};
  // Piezas internas (sin objeto 3D propio) -> conjunto visible que las contiene
  const CLAVE2MESH={propeller_gasket:'helice', propeller_adapter:'helice', esc:'motor', arm_bolt:'brazo', arm_fixing_screw:'brazo', battery_slider:'bateria', landing_gear_screw:'tren', delivery_pump_motor:'bomba', centrifugal_motor:'aspersor', radar_bracket:'radar_d', hose:'tanque', hose_connector:'tanque', spraying_module:'tanque', weight_sensor:'marco_c', rf_module:'marco_c', aerial_electronics:'marco_t', cable_board:'marco_c', power_module:'marco_c', aircraft_connector:'marco_c', aircraft_cable:'marco_c'};
  let nivelMesh={}, grupoMesh={};
  const ORDEN={vencido:0,critico:1,proximo:2,ok:3};
  function nivelDe(key){ return nivelMesh[key]||'ok'; }
  // Caché de mallas por parte: con el modelo de despiece (1,7 k mallas) recorrer el árbol en cada
  // fotograma costaba más que dibujarlo. Se calcula una vez por parte y se reutiliza.
  function mallas(p){ if(!p._mallas){ const a=[]; p.objs.forEach(o=>o.traverse(n=>{
    // Sólo mallas tintables: el disco de desenfoque de las hélices usa un material básico sin
    // `emissive` y hacía fallar el coloreado si los datos llegaban antes que el modelo.
    if(n.isMesh&&n.material&&n.material.emissive&&!n.userData.esDisco) a.push(n); })); p._mallas=a; } return p._mallas; }
  // Nombre de catálogo en castellano (con el original inglés como respaldo).
  function nombrePiezaCatalogo(p){ return p.nombre_es || (window.traducirPieza ? window.traducirPieza(p.nombre_en) : '') || p.nombre_en || ''; }
  function moduloDe(c){ const clave=(c.mesh&&MESH2MOD[c.mesh])||CLAVE2MOD[c.clave]; return DIAGRAMAS.find(m=>m.clave===clave)||null; }
  let explode=0, objetivoExplode=null, autoRotar=false, girarHelices=false, rotY=.6, rotX=.28, zoom=8.5, t=0;
  let arrastrando=false, ultimo=null, movido=0, focoProg=0, niebla=false, marcarCambio=false, intro=1; explode=0;
  // Valores que la secuencia de entrada impone mientras dura.
  let introVuelo=1, introExplode=0;
  // Despegue: `volando` es lo que se pide y `vuelo` (0..1) lo que se está viendo, para que la
  // subida y la bajada sean progresivas en vez de un salto.
  let volando=false, vuelo=0;
  // «Sólo la pieza»: deja el resto del dron casi invisible en vez de translúcido, para inspeccionar
  // una pieza interior sin nada alrededor.
  let aislar=false;
  // Control de la vista: la rotación lleva inercia y el zoom se persigue con suavizado, para que
  // el movimiento se sienta continuo en vez de a saltos.
  let velRotY=0, velRotX=0, zoomObjetivo=zoom;
  // Encuadre del avión: la cámara mira a lo elegido (sistema, grupo o pieza) y se acerca según su
  // tamaño; sin selección vuelve al avión completo. Se recalcula al cambiar la selección y cada
  // medio segundo (el despiece y el giro mueven las piezas).
  const FOCO=new THREE.Vector3(0,-.35,0), FOCO_DEST=new THREE.Vector3(0,-.35,0), _caja=new THREE.Box3();
  const focoBase=()=>ES_AVION?new THREE.Vector3(0,-1.05,0):new THREE.Vector3(0,-.35,0);
  let _focoClave=null, _focoCuadro=0;
  const zMin=()=>ES_AVION?1.1:1.8;
  function mallasFoco(){
    if(PIEZA) return [PIEZA];
    if(GRUPO_ABIERTO) return GRUPO_ABIERTO.mallas;
    if(SISTEMA_SEL) return GRUPOS.filter(g=>g.sis===SISTEMA_SEL).flatMap(g=>g.mallas);
    if(SEL&&SEL.mesh){ const p=PARTES.filter(x=>x.key===SEL.mesh); if(p.length) return p.flatMap(mallas); }
    return null;
  }
  // Cada nivel recuerda cómo se estaba mirando al entrar en uno más profundo (distancia y punto
  // de mira). Al deseleccionar se vuelve exactamente a esa vista —la alejada que tenía el
  // usuario, ampliada o no—, en vez de saltar a un encuadre fijo.
  const VISTAS=[];
  function seguirFoco(){
    const clave=PIEZA?'p'+PIEZA.id:GRUPO_ABIERTO?'g'+GRUPO_ABIERTO.key:(SEL&&SEL.mesh)?'c'+SEL.mesh:SISTEMA_SEL?'s'+SISTEMA_SEL:'';
    const cambio=clave!==_focoClave;
    if(cambio&&_focoClave!==null){
      const i=VISTAS.findIndex(v=>v.clave===clave);
      if(i>=0){
        // Se sube a un nivel ya visitado: se recupera su vista y se olvidan las de más abajo.
        const v=VISTAS[i]; VISTAS.length=i;
        zoomObjetivo=v.zoom; FOCO_DEST.copy(v.foco); _focoClave=clave; _focoCuadro=0;
        FOCO.lerp(FOCO_DEST,.08); return;
      }
      VISTAS.push({clave:_focoClave, zoom:zoomObjetivo, foco:FOCO_DEST.clone()});
    }
    if(cambio||++_focoCuadro>30){
      _focoCuadro=0;
      const ms=mallasFoco();
      if(ms){
        _caja.makeEmpty(); ms.forEach(m=>{ if(m.geometry) _caja.expandByObject(m); });
        if(!_caja.isEmpty()){
          _caja.getCenter(FOCO_DEST);
          if(cambio){ const d=_caja.getSize(new THREE.Vector3()).length(); zoomObjetivo=Math.max(PIEZA?2.4:zMin(), Math.min(10.5, d*1.35+(PIEZA?1.6:.9))); }
        }
      } else if(cambio&&_focoClave===null) FOCO_DEST.copy(focoBase());
      _focoClave=clave;
    }
    FOCO.lerp(FOCO_DEST,.08);
  }
  // Calidad adaptativa: si el equipo no da los fotogramas, se baja la resolución interna y se
  // apaga el bloom antes que dejar la vista a tirones.
  let calidad=2, dibujando=true, visible=true, anchoCanvas=0, altoCanvas=0, primerFotograma=true;
  let muestras=0, sumaMs=0, ultimoT=performance.now();

  function colorear(){
    PARTES.forEach(p=>{ const nivel=nivelDe(p.key);
      mallas(p).forEach(n=>{ if(nivel!=='ok'){ n.material.emissive.setHex(COLOR[nivel]); n.material.emissiveIntensity=.35; } else { n.material.emissive.setHex(0x000000); n.material.emissiveIntensity=0; } }); });
  }
  function resaltar(){
    PARTES.forEach(p=>{ const sel=SEL&&p.key===SEL.mesh, hov=HOVER===p.key;
      const nivel=nivelDe(p.key);
      mallas(p).forEach(n=>{
        // La pieza concreta manda sobre el resaltado del conjunto.
        // Un realce blanco muy leve: cualquier tinte de color (antes naranja) falseaba el aspecto
        // real de la pieza, que es justo lo que se quiere ver al inspeccionarla. Lo que la
        // destaca es que el resto del dron se vuelve transparente, no un tinte encima.
        if(PIEZA===n){ n.material.emissive.setHex(0xffffff); n.material.emissiveIntensity=.1; }
        else if(PIEZA_HOVER===n){ n.material.emissive.setHex(0xffffff); n.material.emissiveIntensity=.4; }
        else if(sel){ n.material.emissive.setHex(0xffb000); n.material.emissiveIntensity=PIEZA?.18:.55; }
        else if(hov&&!PIEZA_HOVER){ n.material.emissive.setHex(0xffffff); n.material.emissiveIntensity=.25; }
        else if(nivel!=='ok'){ n.material.emissive.setHex(COLOR[nivel]); n.material.emissiveIntensity=.35; }
        else { n.material.emissive.setHex(0); n.material.emissiveIntensity=0; } }); });
  }
  function atenuar(){
    const claveActiva=PIEZA?PIEZA.userData.key:((SEL&&SEL.mesh)||(GRUPO_ABIERTO&&GRUPO_ABIERTO.key));
    const hayFoco=!!claveActiva;
    const fondo=aislar?.015:.08, hermanas=aislar?.05:.16;
    const sisSel=!claveActiva&&SISTEMA_SEL;
    const parteAbierta=GRUPO_ABIERTO&&GRUPO_ABIERTO.parte;
    PARTES.forEach(p=>{ const activo=sisSel?(p.sisExp?p.sisExp===SISTEMA_SEL:p.key.startsWith(SISTEMA_SEL+'/'))
        :(!claveActiva||(parteAbierta&&!PIEZA?p===parteAbierta:p.key===claveActiva)); const objetivo=activo?1:(sisSel?.14:fondo);
      mallas(p).forEach(n=>{ const base=n.userData.op??1;
        // Con una pieza suelta seleccionada, el resto de su conjunto se atenúa para no taparla.
        const f=(PIEZA&&activo&&n!==PIEZA)?hermanas:objetivo;
        // En el avión, la chapa de lo que no está en foco casi desaparece: si no, el velo amarillo
        // del revestimiento tapa la pieza o el grupo que se está mirando.
        const dest=base*((ES_AVION&&hayFoco&&n.userData.piel&&n!==PIEZA&&!(activo&&!PIEZA))?Math.min(f,.02):f);
        n.material.opacity+=(dest-n.material.opacity)*.12;

        // La pieza en foco va DELANTE de todo. Antes se quedaba opaca pero el resto del dron,
        // aunque translúcido, se dibujaba encima y la velaba: parecía que la transparente era
        // ella. Se le apaga el test de profundidad y se le da el último turno de dibujado, así
        // que nada la puede tapar y se ve con su color y su forma reales.
        // En el avión un grupo abierto tiene cientos de piezas: dibujarlas sin prueba de
        // profundidad las mezclaría entre sí. Sólo la pieza elegida pasa por delante de todo.
        const enFoco=hayFoco&&(PIEZA?n===PIEZA:(activo&&!ES_AVION));
        if(enFoco){
          n.material.transparent=true;      // para que entre en la pasada que se dibuja al final
          n.material.depthTest=false;
          n.material.depthWrite=false;
          n.renderOrder=999;
        } else {
          n.material.transparent=dest<1;
          n.material.depthTest=true;
          n.material.depthWrite=dest>=.5;
          n.renderOrder=0;
        }
      }); });
  }
  function ubicar(){
    if(ES_AVION){ ubicarAvion(); return; }
    const camLocal=dron.worldToLocal(camera.position.clone());
    // Despiece en dos fases: primero se separan los 41 conjuntos (lectura general) y, a partir de
    // la mitad del recorrido, cada pieza del archivo se separa dentro de su conjunto.
    const eConj=Math.min(1, explode/.55), ePieza=Math.max(0, (explode-.45)/.55);
    PARTES.forEach(p=>{
      const pos=p.base.clone().addScaledVector(p.dir, p.dist*eConj);
      const enFoco=(PIEZA?PIEZA.userData.key:(SEL&&SEL.mesh))===p.key;
      if(enFoco&&focoProg>0){ const hacia=camLocal.clone().sub(pos).normalize(); pos.addScaledVector(hacia, 1.6*focoProg).add(V(0,.25*focoProg,0)); }
      p.grupo.position.copy(pos);
      // Sub-despiece de la pieza enfocada: sus componentes se separan entre sí
      // Despiece pieza a pieza: además de separarse el conjunto, cada malla del archivo se aleja
      // del centro de su conjunto. Sólo se recalcula cuando cambia el despiece o el foco.
      const sub=enFoco?focoProg:0;
      if(p._eAplicado!==ePieza||p._sAplicado!==sub){ p._eAplicado=ePieza; p._sAplicado=sub;
        mallas(p).forEach(n=>{ const u=n.userData; if(!u.basePos) return;
          n.position.copy(u.basePos);
          if(u.dirP) n.position.addScaledVector(u.dirP, u.distP*ePieza);
          if(sub>0.001) n.position.addScaledVector(u.dirP||V(0,1,0), .22*sub); }); }
    });
  }
  // El tamaño se mide sobre el propio lienzo, no sobre el visor: al ampliar, el visor pasa a
  // ocupar toda la ventana con una columna lateral y sus medidas dejan de ser las del dibujo.
  function pixelRatioObjetivo(w, h){
    const area=w*h;
    // El coste crece con el área: en pantallas grandes se rebaja la resolución interna.
    // Se apunta a la resolución nativa de la pantalla (2× en Retina). Sólo con lienzos enormes
    // se baja un escalón, porque el coste crece con el área.
    const techo = area>3600000 ? 1.5 : area>2400000 ? 1.75 : 2;
    return Math.max(1, Math.min(devicePixelRatio||1, techo, calidad));
  }
  function ajustar(){
    const w=Math.max(1, Math.round(canvas.clientWidth||visor.clientWidth||1));
    const h=Math.max(1, Math.round(canvas.clientHeight||visor.clientHeight||1));
    const pr=pixelRatioObjetivo(w,h);
    if(w===anchoCanvas && h===altoCanvas && Math.abs(renderer.getPixelRatio()-pr)<.01) return;
    anchoCanvas=w; altoCanvas=h;
    renderer.setPixelRatio(pr);
    renderer.setSize(w,h,false);
    if(composer){ composer.setPixelRatio(pr); composer.setSize(w,h); if(bloom&&bloom.setSize) bloom.setSize(w,h); }
    camera.aspect=w/h; camera.updateProjectionMatrix(); ajustarFondo();
  }
  // Con ResizeObserver la vista se remide sola al ampliar, al plegar la barra lateral y al girar
  // el teléfono; «resize» de la ventana no cubre ninguno de esos casos.
  if(window.ResizeObserver) new ResizeObserver(()=>ajustar()).observe(canvas);
  window.addEventListener('resize', ajustar);
  window.addEventListener('orientationchange', ()=>setTimeout(ajustar, 220));
  document.addEventListener('visibilitychange', ()=>{
    if(!document.hidden){ ultimoT=performance.now(); primerFotograma=true; ajustar(); } });
  if(window.IntersectionObserver)
    new IntersectionObserver(e=>{ visible=e[0].isIntersecting; if(visible) ultimoT=performance.now(); },
                             {threshold:0}).observe(visor);
  ajustar();

  function animar(){
    requestAnimationFrame(animar);
    const ahora=performance.now(), dt=ahora-ultimoT; ultimoT=ahora;
    // Ni pestaña oculta ni visor fuera de pantalla gastan GPU. La excepción es el primer
    // fotograma: algunos contextos (pestaña en segundo plano al cargar, vistas incrustadas)
    // dicen estar ocultos y la vista se quedaría en blanco hasta tocarla.
    if(!dibujando || ((document.hidden || !visible) && !primerFotograma)) return;
    primerFotograma=false;
    // Medida de rendimiento sobre una ventana de 90 fotogramas; si no llega, se baja la calidad.
    if(dt<400){ sumaMs+=dt; muestras++; }
    if(muestras>=90){
      const medio=sumaMs/muestras; muestras=0; sumaMs=0;
      if(medio>38 && calidad>1.25){ calidad=1.25; if(bloom) bloom.enabled=false; anchoCanvas=0; ajustar(); }
      else if(medio>27 && calidad>1.6){ calidad=1.6; anchoCanvas=0; ajustar(); }
    }
    t+=.016;
    // Inercia de la rotación: al soltar, el modelo sigue girando y frena solo.
    if(!arrastrando){
      if(Math.abs(velRotY)>.00005||Math.abs(velRotX)>.00005){
        rotY+=velRotY; rotX=Math.max(-1.25,Math.min(1.25,rotX+velRotX));
        velRotY*=.93; velRotX*=.93;
      } else { velRotY=0; velRotX=0; }
    }
    // El zoom persigue su objetivo en vez de saltar: da sensación de acercamiento continuo.
    zoom+=(zoomObjetivo-zoom)*.18;
    if(Math.abs(zoomObjetivo-zoom)<.002) zoom=zoomObjetivo;
    if(objetivoExplode!==null){ explode+=(objetivoExplode-explode)*.08; if(Math.abs(objetivoExplode-explode)<.004){explode=objetivoExplode; objetivoExplode=null;} document.getElementById('explode').value=Math.round(explode*100); }
    const quiereFoco=(PIEZA||(SEL&&SEL.mesh)||GRUPO_ABIERTO)?1:0; focoProg+=(quiereFoco-focoProg)*.09;
    if(autoRotar&&!arrastrando&&!quiereFoco) rotY+=.0035;
    // --- Secuencia de entrada ---
    // El T50 aparece en vuelo estacionario, desciende hasta posarse y, sólo cuando ya está en el
    // suelo, se abre el despiece. Antes la vista arrancaba con la máquina desarmada, que es el
    // final de la historia y no el principio.
    if(intro>0){
      intro=Math.max(0, intro-.0038);          // ~4,5 s de secuencia
      const p=1-intro, suave=q=>q*q*(3-2*q);
      if(ES_AVION){                             // un avión no vuela en el visor: sólo gira montado
        introVuelo=0; introExplode=0;
      } else if(p<.32){                         // 1) estacionario
        introVuelo=1; introExplode=0;
      } else if(p<.68){                         // 2) aterrizaje
        introVuelo=1-suave((p-.32)/.36); introExplode=0;
      } else {                                  // 3) posado: se abre el despiece
        introVuelo=0; introExplode=suave((p-.68)/.32);
      }
      if(objetivoExplode===null){ explode=introExplode; document.getElementById('explode').value=Math.round(explode*100); }
      rotY+=.0045;
      zoom=ES_AVION?(10.5-3.7*p):(12.2-3.7*p); zoomObjetivo=zoom;
    }
    // --- Despegue ---
    // Durante la entrada la altura la manda la secuencia; después, el botón de despegue.
    if(intro>0) vuelo=introVuelo;
    else { vuelo+=((volando?1:0)-vuelo)*.022; if(vuelo<.0006) vuelo=0; }
    if(vuelo>0){
      // Dos senos de periodo distinto: el vaivén no se repite igual y parece sustentación real.
      const bamboleo=(Math.sin(t*1.7)*.055+Math.sin(t*2.9)*.018)*vuelo;
      dron.position.y=vuelo*2.35+bamboleo;
      dron.rotation.z=Math.sin(t*1.05)*.022*vuelo;
      // Al subir, la sombra y el halo del suelo se alejan: se encogen y se difuminan.
      halo.scale.setScalar(1-vuelo*.34); halo.material.opacity=.05+vuelo*.05;
      suelo.material.opacity=.26*(1-vuelo*.6);
    } else { dron.position.y=0; dron.rotation.z=0; halo.scale.setScalar(1); halo.material.opacity=.05; suelo.material.opacity=.26; }

    // En vuelo las hélices giran siempre, esté o no pulsado su interruptor.
    const impulso=Math.max(girarHelices?1:0, Math.min(1, vuelo*2.4));
    const vel=impulso?.35*impulso*(1-focoProg*.9)*(1-explode*.8):0;
    PROPS.forEach(p=>{ if(p.eje3){ p.ang+=p.sentido*vel; p.g.quaternion.setFromAxisAngle(p.eje3,p.ang); } else p.g.rotation[p.eje||'y']+=p.sentido*vel; if(p.disco){ const op=Math.min(.16,vel*.5); p.disco.material.opacity+=(op-p.disco.material.opacity)*.1; } });
    NIEBLAS.forEach(nb=>{ const arr=nb.pts.geometry.attributes.position.array; const on=niebla&&vel>.05; for(let i=0;i<nb.n;i++){ nb.vida[i]+=.012+Math.random()*.008; if(nb.vida[i]>1) nb.vida[i]=0; const v=nb.vida[i], a=i*2.399, r=v*.9*(0.3+Math.random()*.1); arr[i*3]=Math.cos(a)*r; arr[i*3+1]=-v*1.6; arr[i*3+2]=Math.sin(a)*r; } nb.pts.geometry.attributes.position.needsUpdate=true; nb.pts.material.opacity+=((on?.5:0)-nb.pts.material.opacity)*.08; });
    // --- Polvo levantado por las hélices ---
    // Sólo lo hay con los rotores en marcha, y arrecia cerca del suelo: es el efecto suelo. Al
    // ganar altura baja pero no desaparece, porque un T50 en estacionario sigue moviendo tierra.
    (function(){
      const cerca=.25+.75*Math.max(0, 1-vuelo*1.6);
      const fuerza=Math.min(1, vel/.3)*cerca;
      const arr=POLVO.geo.attributes.position.array;
      for(let i=0;i<POLVO.n;i++){
        POLVO.vida[i]+=.011*POLVO.sem[i*3+2]*(.35+fuerza);
        if(POLVO.vida[i]>1) POLVO.vida[i]=0;
        const v=POLVO.vida[i], ang=POLVO.sem[i*3]+v*.5, r=.35+v*POLVO.sem[i*3+1]*3.4;
        arr[i*3]=Math.cos(ang)*r;
        // El polvo del rotor sale casi horizontal y va cayendo: no es una columna que suba.
        arr[i*3+1]=Math.sin(v*Math.PI)*.34*(1-v*.45);
        arr[i*3+2]=Math.sin(ang)*r;
      }
      POLVO.geo.attributes.position.needsUpdate=true;
      POLVO.pts.material.opacity+=(fuerza*.5-POLVO.pts.material.opacity)*.07;
    })();
    if(marcarCambio){ const pulso=.55+Math.sin(t*6)*.35; PARTES.forEach(p=>{ const nv=nivelDe(p.key); if(nv!=='ok'&&!(SEL&&SEL.mesh===p.key)) mallas(p).forEach(n=>{ if(!n.userData.esDisco){ n.material.emissive.setHex(COLOR[nv]); n.material.emissiveIntensity=pulso*(nv==='vencido'?1.3:1); } }); }); }
    if(ES_AVION&&PILOTO){ dron.rotation.set(0,0,dron.rotation.z); } else { dron.rotation.y=rotY; dron.rotation.x=rotX; }
    // El avión es largo y bajo: se mira a su altura, no al punto medio de un dron.
    if(ES_AVION&&PILOTO){
      // Modo piloto: los ojos en el asiento; arrastrar mueve la mirada (rotY gira la cabeza,
      // rotX la sube y la baja) en vez de girar el avión.
      dron.updateMatrixWorld(true);
      const ojo=dron.localToWorld(PILOTO.ojo.clone());
      const frente=PILOTO.frente.clone().transformDirection(dron.matrixWorld);
      const arriba=new THREE.Vector3(0,1,0), der=new THREE.Vector3().crossVectors(frente,arriba).normalize();
      frente.applyAxisAngle(arriba, -(rotY-PILOTO.rotY0)).applyAxisAngle(der, -(rotX-PILOTO.rotX0)*.8);
      camera.position.copy(ojo); camera.lookAt(ojo.add(frente));
    } else if(ES_AVION){ seguirFoco(); camera.position.set(FOCO.x, FOCO.y+.26*zoom+.5*Math.min(1,zoom/6), FOCO.z+zoom); camera.lookAt(FOCO); }
    else { seguirFoco(); camera.position.set(FOCO.x, FOCO.y+.365*zoom+.35*Math.min(1,zoom/8.5), FOCO.z+zoom); camera.lookAt(FOCO); }
    ubicar(); atenuar();
    const claveFoco=PIEZA?PIEZA.userData.key:((SEL&&SEL.mesh)||(GRUPO_ABIERTO&&GRUPO_ABIERTO.key));
    const sel=claveFoco?PARTES.find(x=>x.key===claveFoco):null;
    if(sel){ const s=1+Math.sin(t*4)*.03; PARTES.filter(x=>x.key===sel.key).forEach(x=>x.grupo.scale.setScalar(s)); const pos=new THREE.Vector3(); (PIEZA||sel.grupo).getWorldPosition(pos); pos.project(camera); etiqueta.style.left=((pos.x+1)/2*anchoCanvas)+'px'; etiqueta.style.top=((1-pos.y)/2*altoCanvas)+'px'; etiqueta.classList.add('ver'); }
    else { PARTES.forEach(x=>x.grupo.scale.setScalar(1)); etiqueta.classList.remove('ver'); }
    if(composer) composer.render(); else renderer.render(scene,camera);
  }
  animar();

  // ---- Etiqueta de inspección: al pasar el puntero por cualquier pieza muestra sus horas
  //      de uso frente a la vida útil recomendada del conjunto al que pertenece. ----
  const tip=document.createElement('div'); tip.className='tip3d'; visor.appendChild(tip);
  function datosDe(key){
    const directo=porMesh[key];
    if(directo) return directo;
    const grupo=grupoMesh[key]||[];
    if(!grupo.length) return null;
    // Si el conjunto agrupa varias piezas del catálogo, manda la más desgastada.
    return grupo.slice().sort((a,b)=>ORDEN[a.nivel]-ORDEN[b.nivel]||b.pct-a.pct)[0];
  }
  function pintarTip(m){
    if(ES_AVION){ pintarTipAvion(m); return; }
    const u=m.userData, conj=PARTES.find(p=>p.key===u.key), c=datosDe(u.key);
    let cuerpo;
    if(c){
      // El T50 se mide en horas de vuelo y el T70P en meses de servicio: la tarjeta dice con
      // qué se está midiendo en vez de enseñar unas horas que ese modelo no tiene.
      const calendario=midePorCalendario(c), excedida=calendario ? c.meses_restantes<0 : c.restante<0;
      cuerpo=`<div class="tip3d-barra">${barra(c)}</div>
        <div class="tip3d-cifras">
          <span><i>${calendario?'En servicio':'Horas de vuelo'}</i><b>${calendario?fmt(c.meses_en_servicio)+' meses':fmt(c.horas_uso)+' h'}</b></span>
          <span><i>Recomendado</i><b>${vidaPieza(c)}</b></span>
          <span><i>${excedida?'Excedido':'Restante'}</i><b class="${excedida?'mal':''}">${excesoPieza(c).replace(/^(quedan|excedidos?) /,'')}</b></span>
        </div>
        <div class="tip3d-pie">${c.pct}% de la vida útil · ${tagNivel(c.nivel)} · ${escapar(c.nombre)}</div>`;
    } else {
      cuerpo=`<div class="tip3d-pie">Pieza sin vida útil definida en el catálogo.</div>`;
    }
    tip.innerHTML=`<div class="tip3d-tit">${escapar(u.pieza)}</div>
      <div class="tip3d-sub">${escapar(conj?conj.nombre:u.key)} · <span class="codigo">${escapar(u.crudo)}</span></div>
      ${cuerpo}`;
  }
  function moverTip(px,py){
    const w=anchoCanvas||visor.clientWidth, h=altoCanvas||visor.clientHeight,
          tw=tip.offsetWidth||250, th=tip.offsetHeight||120;
    tip.style.left=Math.max(8, Math.min(w-tw-8, px+16))+'px';
    tip.style.top=Math.max(8, Math.min(h-th-8, py+16))+'px';
  }
  function ocultarTip(){ tip.classList.remove('ver'); }

  // ---- Interacción ----
  const ray=new THREE.Raycaster(), mouse=new THREE.Vector2();
  let _clic=null, _clicN=-1;
  const clicables=()=>{ if(ES_AVION) return clicablesAvion(); if(_clic&&_clicN===PARTES.length) return _clic; const a=[]; PARTES.forEach(p=>mallas(p).forEach(n=>a.push(n))); _clic=a; _clicN=PARTES.length; return a; };
  function xy(e){ const r=canvas.getBoundingClientRect(); const p=e.touches?e.touches[0]:e; return {x:p.clientX-r.left,y:p.clientY-r.top}; }
  function bajo(e){ const p=xy(e);
    if(!anchoCanvas||!altoCanvas) return null;
    mouse.x=(p.x/anchoCanvas)*2-1; mouse.y=-(p.y/altoCanvas)*2+1; ray.setFromCamera(mouse,camera);
    // Con una pieza en foco el resto queda casi invisible; si se exigiera la misma opacidad que
    // en la vista normal no se podría saltar de una pieza a otra sin pulsar antes «Volver».
    const minimo=(PIEZA||(SEL&&SEL.mesh))?.02:.5;
    const hits=ray.intersectObjects(clicables()).filter(h=>h.object.visible&&h.object.material.opacity>minimo&&!h.object.userData.esDisco); return hits.length?hits[0].object:null; }

  // ---- Puntero unificado: un solo camino para ratón, dedo y lápiz ----
  // Los eventos táctiles y de ratón por separado se pisaban entre sí en portátiles con pantalla
  // táctil y dejaban el arrastre pegado. Con Pointer Events hay un único flujo y captura real.
  const punteros=new Map();
  let pellizco=null;     // distancia entre dos dedos al empezar el gesto
  let zoomPellizco=zoom;

  const soportaPuntero = window.PointerEvent !== undefined;

  function nuevoPuntero(e){
    punteros.set(e.pointerId, xy(e));
    if(punteros.size===1){
      arrastrando=true; movido=0; ultimo=xy(e); velRotY=0; velRotX=0;
      canvas.classList.add('agarrando');
      try{ canvas.setPointerCapture(e.pointerId); }catch(err){}
    } else if(punteros.size===2){
      // Segundo dedo: el gesto pasa a ser pellizco para acercar y alejar.
      arrastrando=false; canvas.classList.remove('agarrando'); ocultarTip();
      const [a,b]=[...punteros.values()];
      pellizco=Math.hypot(a.x-b.x, a.y-b.y) || 1;
      zoomPellizco=zoomObjetivo;
    }
  }

  function moverPuntero(e){
    const p=xy(e);
    if(punteros.has(e.pointerId)) punteros.set(e.pointerId, p);

    if(punteros.size>=2 && pellizco){
      const [a,b]=[...punteros.values()];
      const d=Math.hypot(a.x-b.x, a.y-b.y) || 1;
      zoomObjetivo=Math.max(zMin(), Math.min(17, zoomPellizco * (pellizco/d)));
      return;
    }

    if(arrastrando && ultimo){
      ocultarTip();
      const dx=p.x-ultimo.x, dy=p.y-ultimo.y;
      movido+=Math.abs(dx)+Math.abs(dy);
      // La sensibilidad se normaliza por el ancho del lienzo: arrastrar media pantalla gira lo
      // mismo en el móvil que en la vista ampliada del escritorio.
      const k=1.9/Math.max(anchoCanvas,1);
      rotY+=dx*k*2.2; rotX=Math.max(-1.25, Math.min(1.25, rotX+dy*k*1.6));
      velRotY=dx*k*2.2*.55; velRotX=dy*k*1.6*.55;
      ultimo=p;
      return;
    }

    if(e.pointerType==='touch') return;   // sin puntero no hay señalado al pasar por encima
    const m=bajo(e), k=m?m.userData.key:null;
    if(k!==HOVER||m!==PIEZA_HOVER){ if(m) aislarMaterial(m); HOVER=k; PIEZA_HOVER=m; canvas.classList.toggle('sobre',!!m); resaltar(); if(m) pintarTip(m); }
    if(m){ tip.classList.add('ver'); moverTip(p.x,p.y); } else ocultarTip();
  }

  function soltarPuntero(e){
    const eraArrastre=arrastrando, quedaban=punteros.size;
    punteros.delete(e.pointerId);
    try{ canvas.releasePointerCapture(e.pointerId); }catch(err){}
    if(punteros.size<2) pellizco=null;
    if(punteros.size===0){
      arrastrando=false; ultimo=null; canvas.classList.remove('agarrando');
      // Un toque corto es una selección; un arrastre no debe seleccionar nada.
      if(eraArrastre && quedaban===1 && movido<7){
        velRotY=0; velRotX=0;
        const m=bajo(e);
        if(m) seleccionarPieza(m); else if(SEL||PIEZA) volver();
      }
    } else if(punteros.size===1){
      // Se levantó un dedo del pellizco: seguimos rotando con el que queda, sin salto.
      arrastrando=true; movido=99; ultimo=[...punteros.values()][0];
    }
  }

  if(soportaPuntero){
    canvas.addEventListener('pointerdown', e=>{ if(e.button>0) return; nuevoPuntero(e); });
    canvas.addEventListener('pointermove', moverPuntero);
    canvas.addEventListener('pointerup', soltarPuntero);
    canvas.addEventListener('pointercancel', soltarPuntero);
    canvas.addEventListener('pointerleave', e=>{
      if(arrastrando||punteros.size) return;
      ocultarTip();
      if(PIEZA_HOVER||HOVER){ HOVER=null; PIEZA_HOVER=null; canvas.classList.remove('sobre'); resaltar(); }
    });
  } else {
    // Respaldo para navegadores antiguos sin Pointer Events.
    canvas.addEventListener('mousedown', e=>{ arrastrando=true; movido=0; ultimo=xy(e); velRotY=0; velRotX=0; canvas.classList.add('agarrando'); });
    window.addEventListener('mouseup', e=>{ if(!arrastrando) return; arrastrando=false; canvas.classList.remove('agarrando');
      if(movido<7&&e.target===canvas){ const m=bajo(e); if(m) seleccionarPieza(m); else if(SEL||PIEZA) volver(); } });
    canvas.addEventListener('mousemove', e=>moverPuntero(Object.assign({}, e, {pointerId:1, pointerType:'mouse', clientX:e.clientX, clientY:e.clientY})));
    canvas.addEventListener('mouseleave', ()=>{ ocultarTip(); if(PIEZA_HOVER||HOVER){ HOVER=null; PIEZA_HOVER=null; canvas.classList.remove('sobre'); resaltar(); } });
    canvas.addEventListener('touchstart', e=>{ arrastrando=true; movido=0; ultimo=xy(e); },{passive:true});
    canvas.addEventListener('touchmove', e=>{ const p=xy(e); if(ultimo){ const dx=p.x-ultimo.x, dy=p.y-ultimo.y;
      movido+=Math.abs(dx)+Math.abs(dy); const k=1.9/Math.max(anchoCanvas,1);
      rotY+=dx*k*2.2; rotX=Math.max(-1.25,Math.min(1.25,rotX+dy*k*1.6)); } ultimo=p; },{passive:true});
    canvas.addEventListener('touchend', e=>{ arrastrando=false;
      if(movido<7&&e.changedTouches){ const tt=e.changedTouches[0]; const m=bajo({clientX:tt.clientX,clientY:tt.clientY}); if(m) seleccionarPieza(m); } });
  }

  // El gesto de dos dedos del trackpad llega como wheel+ctrlKey; se trata como pellizco.
  canvas.addEventListener('wheel', e=>{
    e.preventDefault();
    const paso = e.deltaMode===1 ? e.deltaY*16 : e.deltaY;   // algunas ruedas informan en líneas
    const factor = e.ctrlKey ? .015 : .0085;
    zoomObjetivo=Math.max(zMin(), Math.min(17, zoomObjetivo + paso*factor));
  }, {passive:false});

  // Doble clic: enfocar la pieza bajo el puntero, o volver si ya había una enfocada.
  canvas.addEventListener('dblclick', e=>{
    const m=bajo(e);
    if(m) seleccionarPieza(m); else if(SEL||PIEZA) volver();
  });

  // Teclado: rotar, acercar y salir sin tocar el ratón.
  canvas.setAttribute('tabindex','0');
  canvas.addEventListener('keydown', e=>{
    const paso=.12;
    if(e.key==='ArrowLeft'){ rotY-=paso; e.preventDefault(); }
    else if(e.key==='ArrowRight'){ rotY+=paso; e.preventDefault(); }
    else if(e.key==='ArrowUp'){ rotX=Math.max(-1.25, rotX-paso*.7); e.preventDefault(); }
    else if(e.key==='ArrowDown'){ rotX=Math.min(1.25, rotX+paso*.7); e.preventDefault(); }
    else if(e.key==='+'||e.key==='='){ zoomObjetivo=Math.max(zMin(), zoomObjetivo-.8); }
    else if(e.key==='-'||e.key==='_'){ zoomObjetivo=Math.min(17, zoomObjetivo+.8); }
  });

  document.getElementById('explode').addEventListener('input', e=>{ objetivoExplode=null; intro=0; explode=e.target.value/100; if(e.target.value>0) aterrizar(); });
  document.getElementById('btnAnimar').addEventListener('click', ()=>{ intro=0; objetivoExplode=explode>.5?0:1; if(objetivoExplode===1) aterrizar(); });

  // ---- Despegar ----
  // Un dron desarmado no vuela: al despegar se cierra primero el despiece, y al abrirlo se
  // aterriza. Las hélices arrancan solas mientras está en el aire.
  const btnVuelo=document.getElementById('btnVuelo');
  const IC_DESPEGAR='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M10 15.4V4.6"/><path d="M6.2 8.4 10 4.6l3.8 3.8"/><path d="M4.2 17.4h11.6"/></svg>';
  const IC_ATERRIZAR='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M10 4.6v10.8"/><path d="M13.8 11.6 10 15.4l-3.8-3.8"/><path d="M4.2 17.4h11.6"/></svg>';
  function pintarVuelo(){
    if(!btnVuelo) return;
    btnVuelo.innerHTML=(volando?IC_ATERRIZAR:IC_DESPEGAR)+' '+(volando?'Aterrizar':'Despegar');
    btnVuelo.classList.toggle('secundario',!volando);
    btnVuelo.setAttribute('aria-pressed', volando?'true':'false');
  }
  function aterrizar(){ if(!volando) return; volando=false; pintarVuelo(); }
  if(btnVuelo){
    btnVuelo.addEventListener('click', ()=>{
      volando=!volando;
      if(volando){ intro=0; objetivoExplode=0; }
      pintarVuelo();
      toast(volando?'En vuelo · las hélices giran mientras esté en el aire':'Aterrizando');
    });
    pintarVuelo();
  }
  // Interruptores de animación como botones (antes eran casillas de verificación).
  function interruptor(id, activo, alCambiar){
    const b=document.getElementById(id); if(!b) return;
    const pintar=()=>{ b.classList.toggle('secundario',!activo); b.setAttribute('aria-pressed', activo?'true':'false'); };
    b.addEventListener('click', ()=>{ activo=!activo; pintar(); alCambiar(activo); });
    pintar();
  }
  // Quitar tapas: en el avión se resuelve por lotes (aplicarInterior); en los drones, pieza a pieza
  // por el nombre de la malla del archivo 3D.
  function aplicarTapas(){
    if(ES_AVION){ aplicarInterior(); return; }
    PARTES.forEach(p=>mallas(p).forEach(n=>{ const nom=(n.userData.pieza||'')+' '+(n.userData.crudo||'');
      if(esTapa(nom)) n.visible=!SIN_TAPAS; }));
  }
  interruptor('btnTapas', false, v=>{ SIN_TAPAS=v; if(ES_AVION){ VER_INTERIOR=v; aplicarInterior();
      return toast(v?'Sin cubiertas: estructura, motor y sistemas a la vista':'Cubiertas puestas de nuevo'); }
    aplicarTapas();
    const n=ES_AVION?GRUPOS.reduce((a,g)=>a+g.mallas.filter(m=>m.userData.tapa).length,0)
                    :PIEZAS.filter(p=>esTapa(p.nombre+' '+p.crudo)).length;
    toast(v?`${n.toLocaleString('es')} tapas ocultas`:'Tapas visibles de nuevo'); });
  interruptor('btnAislar', false, v=>{ aislar=v; toast(v?'Sólo la pieza seleccionada: el resto del dron queda casi invisible':'El resto del dron vuelve a verse translúcido'); });
  interruptor('btnRotar', false, v=>autoRotar=v);
  interruptor('btnHelices', false, v=>girarHelices=v);
  interruptor('btnNiebla', false, v=>niebla=v);
  document.getElementById('btnCambio3d').addEventListener('click', ()=>{ marcarCambio=!marcarCambio; document.getElementById('btnCambio3d').classList.toggle('secundario',!marcarCambio); resaltar(); if(marcarCambio){ const n=Object.values(nivelMesh).filter(v=>v!=='ok').length; toast(n?`${n} pieza(s) para cambio resaltadas: amarillo próximo · naranja crítico · rojo vencido`:'No hay piezas para cambio en este equipo'); } });
  document.getElementById('btnReset').addEventListener('click', ()=>{
    rotY=.6; rotX=ES_AVION?.22:.28; zoomObjetivo=ES_AVION?6.8:8.5; velRotY=0; velRotX=0; intro=0; aterrizar();
    FOCO_DEST.copy(focoBase()); VISTAS.length=0; VISTAS.push({clave:'', zoom:zoomObjetivo, foco:focoBase()}); });
  document.getElementById('btnVolver').addEventListener('click', volver);
  const panelLateral=document.querySelector('.panel-pieza'), drawer=document.getElementById('drawer3d');
  let AMPLIO=false;
  const IC_AMPLIAR='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:15px;height:15px"><path d="M7.4 3.4H3.4v4M12.6 3.4h4v4M16.6 12.6v4h-4M7.4 16.6h-4v-4"/></svg> Ampliar';
  // Las tarjetas del panel lateral se mueven al cajón de la vista ampliada y vuelven a su sitio
  // al cerrar. Se guardan las referencias en vez de buscarlas por vecindad, que se rompía en
  // cuanto el orden del panel cambiaba.
  const TARJETAS_PANEL=Array.from(panelLateral.children);

  function ampliar(on){
    if(AMPLIO===on) return;
    AMPLIO=on;
    visor.classList.toggle('amplio', on);
    document.body.classList.toggle('sin-scroll', on);
    if(on) TARJETAS_PANEL.forEach(c=>drawer.appendChild(c));
    else TARJETAS_PANEL.forEach(c=>panelLateral.appendChild(c));
    document.getElementById('btnAmpliar').innerHTML = on ? '✕ Cerrar ampliación' : IC_AMPLIAR;
    // Pantalla completa real cuando el navegador la permite: quita la interfaz del navegador.
    if(on && visor.requestFullscreen && !document.fullscreenElement)
      visor.requestFullscreen().catch(()=>{});
    if(!on && document.fullscreenElement) document.exitFullscreen().catch(()=>{});
    // El lienzo se remide solo (ResizeObserver); esto cubre navegadores sin él.
    anchoCanvas=0; requestAnimationFrame(ajustar); setTimeout(ajustar, 120);
  }
  document.getElementById('btnAmpliar').addEventListener('click', ()=>ampliar(!AMPLIO));
  // Salir con la tecla de pantalla completa del navegador debe deshacer también nuestro estado.
  document.addEventListener('fullscreenchange', ()=>{ if(!document.fullscreenElement && AMPLIO) ampliar(false); });
  document.addEventListener('keydown', e=>{ if(e.key==='Escape'){ if(document.getElementById('lightbox').classList.contains('ver')) cerrarLightbox(); else if((PIEZA||SEL||GRUPO_ABIERTO||SISTEMA_SEL) && !e.target.closest('input,select,textarea')) volver(); else if(AMPLIO) ampliar(false); } });
  // Lightbox del diagrama oficial con zoom/arrastre y números clickeables
  const lb=document.getElementById('lightbox'), lbEsc=document.getElementById('lbEscenario'), lbInfo=document.getElementById('lbInfo');
  let lbZoom=1, lbX=0, lbY=0, lbArr=null, lbMov=0;
  function lbAplicar(){ lbEsc.style.transform=`translate(${lbX}px,${lbY}px) scale(${lbZoom})`; lbEsc.querySelectorAll('.punto').forEach(p=>p.style.transform=`translate(-50%,-50%) scale(${1/lbZoom})`); }
  function abrirLightbox(m){
    lbEsc.innerHTML=`<img src="${m.imagen_url}" alt="">`+(m.hotspots||[]).map(h=>`<div class="punto" data-n="${h.n}" style="left:${h.x}%;top:${h.y}%">${h.n}</div>`).join('');
    lbInfo.innerHTML=`<b>${escapar(m.nombre)}</b> · ${(m.partes||[]).length} piezas · rueda para acercar, arrastra para mover, clic en un número`;
    lb.classList.add('ver'); document.body.classList.add('sin-scroll');
    const img=lbEsc.querySelector('img'); img.onload=()=>{ const W=innerWidth, H=innerHeight; lbZoom=Math.min(W/img.naturalWidth, (H-90)/img.naturalHeight)*.96; lbEsc.style.width=img.naturalWidth+'px'; lbEsc.style.height=img.naturalHeight+'px'; lbX=(W-img.naturalWidth*lbZoom)/2; lbY=(H-90-img.naturalHeight*lbZoom)/2+10; lbAplicar(); };
    // Si la lámina ya estaba en caché, `load` pudo dispararse antes de asignar el manejador.
    if(img.complete&&img.naturalWidth) img.onload();
    lbEsc.querySelectorAll('.punto').forEach(p=>p.onclick=e=>{ e.stopPropagation(); const n=Number(p.dataset.n); const pz=(m.partes||[]).find(x=>x.n===n); lbEsc.querySelectorAll('.punto').forEach(x=>x.classList.toggle('sel',Number(x.dataset.n)===n));
      lbInfo.innerHTML=pz?`<b>${n}. ${escapar(nombrePiezaCatalogo(pz))}</b><div class="mut">${pz.nombre_zh?escapar(pz.nombre_zh)+' · ':''}<span class="codigo">${escapar(pz.codigo)}</span>${pz.auxiliar?' · material auxiliar':''}</div>`:`Pieza ${n} sin datos.`; });
  }
  function cerrarLightbox(){ lb.classList.remove('ver'); if(!AMPLIO) document.body.classList.remove('sin-scroll'); }
  document.getElementById('lbCerrar').onclick=cerrarLightbox;
  lb.addEventListener('wheel', e=>{ e.preventDefault(); const f=e.deltaY<0?1.15:1/1.15; const nz=Math.max(.1,Math.min(8,lbZoom*f)); lbX=e.clientX-(e.clientX-lbX)*(nz/lbZoom); lbY=e.clientY-(e.clientY-lbY)*(nz/lbZoom); lbZoom=nz; lbAplicar(); },{passive:false});
  lb.addEventListener('pointerdown', e=>{ if(e.target.closest('.cerrar')||e.target.closest('.info')) return; lbArr={x:e.clientX-lbX,y:e.clientY-lbY}; lbMov=0; lb.setPointerCapture(e.pointerId); });
  lb.addEventListener('pointermove', e=>{ if(!lbArr) return; lbMov+=Math.abs(e.movementX)+Math.abs(e.movementY); lbX=e.clientX-lbArr.x; lbY=e.clientY-lbArr.y; lbAplicar(); });
  lb.addEventListener('pointerup', e=>{ lbArr=null; });
  function volver(){
    // En el avión se sale por niveles: de la pieza al grupo, y del grupo al avión completo.
    if((PIEZA||SEL) && GRUPO_ABIERTO){ PIEZA=null; SEL=null; resaltar(); pintarDetalle(); pintarLista(); return; }
    if(GRUPO_ABIERTO){ cerrarGrupo(); SEL=null; PIEZA=null; document.getElementById('btnVolver').style.display=SISTEMA_SEL?'inline-block':'none'; resaltar(); pintarDetalle(); pintarLista(); return; }
    if(SISTEMA_SEL&&!SEL&&!PIEZA) SISTEMA_SEL=null;
    SEL=null; PIEZA=null; document.getElementById('btnVolver').style.display='none'; resaltar(); pintarDetalle(); pintarLista(); }

  // ---- Datos ----
  // De qué modelo es esta pantalla. Se resuelve al arrancar entre los modelos que tienen archivo
  // 3D; cambiar de modelo recarga la página, que es más barato y más seguro que desmontar la
  // escena de Three.js con el modelo a medio cargar.
  let MODELO_3D=null;

  async function elegirModelo3D(){
    const datos=await api('/api/modelos');
    const con3d=datos.modelos.filter(m=>m.tiene_3d);
    const $sel=document.getElementById('selModelo3d');
    if(!con3d.length){
      MODELO_3D=null;
      if($sel) $sel.style.display='none';
      return null;
    }
    // Manda la URL; si no, el modelo del dron que se venía mirando; si no, el primero que haya.
    const equipos=await api('/api/equipos');
    const eqURL=equipos.find(e=>String(e.id)===String(paramURL('equipo')));
    const pedido=paramURL('modelo') || (eqURL&&eqURL.modelo);
    const elegido=con3d.find(m=>m.clave===pedido) || con3d[0];
    MODELO_3D=elegido.clave; MODELOS=elegido.archivos_3d;
    ES_AVION=(elegido.tipo||elegido.tipo_activo)==='avion';
    prepararExplorador();
    if(ES_AVION) prepararInterfazAvion();
    if($sel){
      // El selector sólo aparece cuando de verdad hay entre qué elegir.
      $sel.style.display=con3d.length>1?'':'none';
      $sel.innerHTML=con3d.map(m=>`<option value="${m.clave}" ${m.clave===MODELO_3D?'selected':''}>${escapar(m.nombre)}</option>`).join('');
      // Sólo un cambio hecho por el usuario recarga: Chrome restaura el valor anterior del
      // selector al volver a la página y, sin esta guarda, saltaba solo a otro modelo.
      $sel.onchange=e=>{ if(!e.isTrusted||$sel.value===MODELO_3D) return; location.search='?modelo='+encodeURIComponent($sel.value); };
    }
    const $enc=document.getElementById('encabezado3d');
    if($enc) $enc.textContent='Modelo 3D del '+elegido.nombre.replace(/^DJI /,'');
    return elegido;
  }

  async function cargarEquipos(){
    const todos=await api('/api/equipos'); const sel=document.getElementById('selEquipo');
    // Sólo los drones de este modelo: cruzar las horas de un T100 con el despiece de otro daría
    // piezas que no existen en ese dron.
    EQUIPOS=todos.filter(e=>e.modelo===MODELO_3D);
    sel.innerHTML=EQUIPOS.length?opcionesEquipos(EQUIPOS, paramURL('equipo')||EQUIPOS[0].id)
      :`<option value="">Sin ${ES_AVION?'aviones':'drones'} ${MODELO_3D}</option>`;
    sel.addEventListener('change', ()=>cargarEquipo(sel.value));
    await cargarEquipo(EQUIPOS.length?sel.value:'');
    const piezaURL=paramURL('pieza'); if(piezaURL&&porClave[piezaURL]) seleccionar(porClave[piezaURL]);
  }
  async function cargarEquipo(id){
    EQUIPO=EQUIPOS.find(e=>String(e.id)===String(id))||null;
    const [comps, diag]=await Promise.all([
      id?api(`/api/componentes?equipo_id=${id}`):[],
      api(`/api/diagramas?modelo=${MODELO_3D}`+(id?`&equipo_id=${id}`:'')),
    ]);
    COMPS=comps; DIAGRAMAS=diag.laminas;
    porMesh={}; porClave={}; nivelMesh={}; grupoMesh={};
    COMPS.forEach(c=>{ porClave[c.clave]=c; const key=c.mesh||CLAVE2MESH[c.clave]; if(!key) return; if(c.mesh) porMesh[key]=c; (grupoMesh[key]=grupoMesh[key]||[]).push(c); if(!nivelMesh[key]||ORDEN[c.nivel]<ORDEN[nivelMesh[key]]) nivelMesh[key]=c.nivel; });
    colorear(); pintarLista(); if(PIEZA_HOVER&&tip.classList.contains('ver')) pintarTip(PIEZA_HOVER); if(SEL){ const c=COMPS.find(c=>c.clave===SEL.clave); SEL=c?Object.assign({},c,{mesh:c.mesh||CLAVE2MESH[c.clave]||null}):null; pintarDetalle(); resaltar(); }
  }
  // Al cargar el GLB se clona UN material por (conjunto, material original) para no duplicar
  // 1.765 materiales. El efecto colateral es que decenas de mallas comparten el mismo objeto:
  // al poner en foco una de ellas, la opacidad y el `depthTest` que se le daban afectaban a
  // todas sus hermanas, así que el resto del conjunto se negaba a volverse transparente.
  // Se le da a la pieza enfocada un material propio (una sola vez por malla).
  function aislarMaterial(n){
    if(!n || n.userData.aislado) return;
    n.material = n.material.clone();
    n.material.opacity = n.userData.op ?? 1;
    n.userData.aislado = true;
  }

  function seleccionarMesh(key){ PIEZA=null; const c=porMesh[key]; if(c) seleccionar(c); else { resaltar(); pintarDetalle(); } }
  // Selecciona una pieza concreta del archivo 3D (y, con ella, el conjunto al que pertenece).
  function seleccionarPieza(m){
    // En el avión, pinchar un grupo cerrado lo abre; sólo dentro de un grupo abierto se elige pieza.
    if(ES_AVION && m.userData.lote){ abrirGrupo(m.userData.key); return; }
    // Con el despiece completo se puede pinchar cualquier pieza: se abre su grupo y se enfoca.
    const gk=m.userData.grupoExp||m.userData.key;
    if(GRUPOS.length && (!GRUPO_ABIERTO||GRUPO_ABIERTO.key!==gk)) abrirGrupo(gk);
    aislarMaterial(m);
    PIEZA=m; const c=porMesh[m.userData.key];
    if(c) seleccionar(c); else { SEL=null; document.getElementById('btnVolver').style.display='inline-block'; resaltar(); pintarDetalle(); pintarLista(); }
    etiquetarPieza();
  }
  function zonaDeMesh(key){
    const m=DIAGRAMAS.find(x=>x.clave===MESH2MOD[key]);
    return m?(m.zona||m.nombre):'';
  }
  function etiquetarPieza(){
    if(!PIEZA) return;
    if(ES_AVION){ const u=PIEZA.userData, gr=GRUPOS.find(x=>x.key===u.key);
      etiqueta.innerHTML=`${escapar(u.pieza)}<small>${escapar(gr?gr.nombre:'')} · <span class="codigo">${escapar(u.pn||'')}</span></small>`; return; }
    const conj=PARTES.find(p=>p.key===PIEZA.userData.key);
    const zona=zonaDeMesh(PIEZA.userData.key);
    etiqueta.innerHTML=`${escapar(PIEZA.userData.pieza)}<small>${escapar(zona||(conj?conj.nombre:PIEZA.userData.key))} · <span class="codigo">${escapar(PIEZA.userData.crudo)}</span></small>`;
  }
  // `conservarModulo` lo usa el selector de módulos: al pulsar un chip, el conjunto 3D que se
  // enfoca puede pertenecer a otro módulo (la placa de distribución se dibuja sobre el marco
  // central), y sin esto el panel saltaba solo al módulo del conjunto en vez de quedarse en el
  // que acababa de pulsar el usuario. Ese era el motivo de que «no sirviera».
  function seleccionar(c, conservarModulo){
    // El chip activo sigue a la pieza elegida cuando la selección nace del 3D o de la lista.
    if(!conservarModulo){ const mod=moduloDe(c); if(mod) MOD_ACTUAL=mod.clave; }
    SEL=Object.assign({},c,{mesh:c.mesh||CLAVE2MESH[c.clave]||null}); document.getElementById('btnVolver').style.display=SEL.mesh?'inline-block':'none';
    if(PIEZA) etiquetarPieza(); else etiqueta.innerHTML=`${escapar(c.nombre)}<small>${usoPieza(c)} · ${NIVEL_TXT[c.nivel]}</small>`;
    resaltar(); pintarDetalle(); pintarLista();
  }

  // ---- Diagrama oficial del fabricante embebido (siempre visible) ----
  let MOD_ACTUAL='marco_central';
  function htmlDiagrama(m){
    if(!m) return '';
    return `<div class="mini-diag-titulo">Despiece oficial del fabricante · ${escapar(m.nombre)} <span class="mut">(${(m.partes||[]).length} piezas · clic en un número)</span></div>
      <div class="mini-diag" id="miniDiag"><img src="${m.imagen_url}" alt="">${(m.hotspots||[]).map(h=>`<div class="punto mini" data-n="${h.n}" style="left:${h.x}%;top:${h.y}%">${h.n}</div>`).join('')}</div>
      <div class="mini-diag-info" id="miniInfo">Selecciona un número para ver la pieza · clic en la imagen para ampliar el diagrama.</div>
      <details style="margin-top:8px" ${AMPLIO?'open':''}><summary style="font-size:12px;font-weight:640;cursor:pointer">Lista de piezas del diagrama (${(m.partes||[]).length})</summary>
      <div class="pieza-lista" style="max-height:${AMPLIO?'40vh':'260px'};margin-top:6px">${(m.partes||[]).map(p=>`<div class="item clk" data-pn="${p.n}" style="padding:6px 8px"><span class="num" style="width:22px;height:22px;border-radius:50%;background:var(--acc-soft);color:var(--acc-deep);font-size:10.5px;font-weight:700;display:grid;place-items:center;flex:none">${p.n}</span><div class="cuerpo"><b style="font-size:12px">${escapar(nombrePiezaCatalogo(p))}</b><div class="mut"><span class="codigo">${escapar(p.codigo)}</span>${p.auxiliar?' · aux.':''}</div></div></div>`).join('')}</div></details>`;
  }
  function enlazarDiagrama(el, m){
    if(!m) return; MOD_ACTUAL=m.clave;
    const im=el.querySelector('#miniDiag img'); if(im) im.onclick=()=>abrirLightbox(m);
    const marcar=n=>{ const pz=(m.partes||[]).find(x=>x.n===n);
      el.querySelectorAll('#miniDiag .punto').forEach(x=>x.classList.toggle('sel', Number(x.dataset.n)===n));
      el.querySelectorAll('[data-pn]').forEach(x=>x.classList.toggle('sel', Number(x.dataset.pn)===n));
      const info=el.querySelector('#miniInfo'); if(info) info.innerHTML=pz?`<b>${n}. ${escapar(nombrePiezaCatalogo(pz))}</b><div class="mut">${escapar(pz.nombre_zh)} · <span class="codigo">${escapar(pz.codigo)}</span>${pz.auxiliar?' · material auxiliar':''}</div>`:`Pieza ${n} sin datos en la lista.`; };
    el.querySelectorAll('#miniDiag .punto').forEach(p=>p.onclick=()=>marcar(Number(p.dataset.n)));
    el.querySelectorAll('[data-pn]').forEach(p=>p.onclick=()=>{ marcar(Number(p.dataset.pn)); const pt=el.querySelector(`#miniDiag .punto[data-n="${p.dataset.pn}"]`); if(pt) pt.scrollIntoView({block:'nearest'}); });
  }
  // Qué conjuntos del modelo 3D corresponden a un módulo del despiece oficial. Se cruzan las tres
  // tablas disponibles: la de mallas (MESH2MOD), la del catálogo (CLAVE2MOD/CLAVE2MESH) y las
  // piezas que el propio diagrama declara suyas.
  // Módulos que no tienen conjunto propio en el 3D: la cubierta frontal y su luz auxiliar van
  // montadas sobre el módulo delantero, así que es ahí donde hay que mirar.
  const MOD2MESH_EXTRA={cubierta_frontal:'marco_d'};
  function conjuntosDeModulo(claveMod){
    const claves=new Set();
    if(MOD2MESH_EXTRA[claveMod]) claves.add(MOD2MESH_EXTRA[claveMod]);
    Object.keys(MESH2MOD).forEach(k=>{ if(MESH2MOD[k]===claveMod) claves.add(k); });
    COMPS.forEach(c=>{ if(CLAVE2MOD[c.clave]===claveMod){ const k=c.mesh||CLAVE2MESH[c.clave]; if(k) claves.add(k); } });
    const m=DIAGRAMAS.find(x=>x.clave===claveMod);
    (m&&m.piezas_catalogo||[]).forEach(cl=>{ const c=porClave[cl]; const k=c&&(c.mesh||CLAVE2MESH[cl]); if(k) claves.add(k); });
    return [...claves].filter(k=>PARTES.some(p=>p.key===k));
  }

  // Al elegir un módulo en el panel del diagrama, el modelo 3D salta a ese conjunto: abre el
  // despiece, lo enfoca y atenúa el resto del dron, para ver en volumen lo mismo que la lámina.
  //
  // El orden importa: PRIMERO se pinta la lámina del módulo, que es lo que nunca puede fallar, y
  // sólo después se intenta mover el 3D, aislado en su propio try. Si el enfoque revienta, el
  // panel ya ha respondido; antes, un error aquí dejaba el botón sin hacer absolutamente nada
  // (ni siquiera cambiaba el dibujo) y no había forma de saber por qué.
  function abrirModulo3D(claveMod){
    MOD_ACTUAL=claveMod;
    try{ pintarDetalle(); }
    catch(err){ avisarFallo('pintando la lámina del módulo', err); }

    try{
      intro=0; aterrizar(); objetivoExplode=1;
      const keys=conjuntosDeModulo(claveMod);
      const conMalla=keys.map(k=>porMesh[k]).find(Boolean);
      if(conMalla){ PIEZA=null; seleccionar(conMalla, true); return; }
      // El módulo no tiene una pieza de catálogo con malla propia: se enfoca la primera de sus
      // piezas que sí tenga representación en el 3D.
      const m=DIAGRAMAS.find(x=>x.clave===claveMod);
      const alt=(m&&m.piezas_catalogo||[]).map(cl=>porClave[cl]).find(c=>c&&(c.mesh||CLAVE2MESH[c.clave]));
      if(alt){ PIEZA=null; seleccionar(alt, true); return; }
      toast('Este módulo no tiene piezas representadas en el modelo 3D; se muestra su lámina.');
    }catch(err){ avisarFallo('enfocando el módulo en el 3D', err); }
  }

  // Un fallo tiene que verse y quedar escrito, no morir en silencio dentro de un manejador.
  function avisarFallo(donde, err){
    const msg=`Fallo ${donde}: ${(err&&err.message)||err}`;
    try{ toast(msg); }catch(e){}
    try{
      fetch('/api/log-js', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({pagina: location.pathname, mensaje: msg, pila: err&&err.stack})});
    }catch(e){}
    if(window.console) console.error(msg, err);
  }

  function htmlSelectorModulos(){
    return `<div class="modulos" style="margin:6px 0 4px">${DIAGRAMAS.map(m=>`<button class="pillbtn ${m.clave===MOD_ACTUAL?'active':''}" data-mod="${m.clave}" style="padding:4px 9px;font-size:11px"><i class="${m.nivel}"></i>${escapar(m.nombre)}</button>`).join('')}</div>`;
  }
  // Ficha de la pieza concreta del archivo 3D (por encima de los datos del conjunto).
  function htmlPiezaSel(){
    if(!PIEZA) return '';
    const u=PIEZA.userData, conj=PARTES.find(p=>p.key===u.key);
    const hermanas=PIEZAS.filter(x=>x.key===u.key&&x.crudo===u.crudo).length;
    return `<div class="nota" style="margin:0 0 12px"><b>Pieza seleccionada:</b> ${escapar(u.pieza)}
      <div class="mut"><span class="codigo">${escapar(u.crudo)}</span> · conjunto ${escapar(conj?conj.nombre:u.key)}${hermanas>1?` · ${hermanas} ejemplares iguales`:''}</div></div>`;
  }
  function pintarDetalle(){
    const el=document.getElementById('detalle');
    if(GRUPOS.length||ES_AVION) return;           // la ficha vive dentro del explorador de piezas
    if(!SEL&&PIEZA){
      const conj=PARTES.find(p=>p.key===PIEZA.userData.key);
      el.innerHTML=`<h4>${escapar(PIEZA.userData.pieza)}</h4>${htmlPiezaSel()}
        <div class="mut">Este conjunto (${escapar(conj?conj.nombre:'')}) no tiene una pieza de mantenimiento asociada en el catálogo.</div>`;
      return; }
    if(!SEL){
      const m=DIAGRAMAS.find(x=>x.clave===MOD_ACTUAL)||DIAGRAMAS[0];
      el.innerHTML=`<h4>Diagrama de piezas del ${MODELO_3D}</h4><div class="mut">Elige un módulo o haz clic en una pieza del modelo 3D.</div>${htmlSelectorModulos()}${htmlDiagrama(m)}`;
      el.querySelectorAll('[data-mod]').forEach(b=>b.onclick=()=>{
        try{ abrirModulo3D(b.dataset.mod); }catch(err){ avisarFallo('abriendo el módulo', err); } });
      enlazarDiagrama(el, m); return; }
    const c=SEL;
    // Manda el módulo del panel: si el usuario pulsó «Placa de distribución principal» quiere ver
    // esa lámina, aunque el conjunto 3D enfocado sea el marco central.
    const modPanel=DIAGRAMAS.find(x=>x.clave===MOD_ACTUAL)||moduloDe(c);
    el.innerHTML=`<h4>${escapar(c.nombre)}</h4>${htmlPiezaSel()}
      <div class="mut">${escapar(c.modulo)} · ${escapar(EQUIPO?EQUIPO.nombre:'')}${porClave[c.clave]&&porClave[c.clave].mesh?'':(CLAVE2MESH[c.clave]?' · pieza interna, se muestra su conjunto':' · pieza interna (sin representación 3D)')}</div>
      <div style="margin:10px 0 4px">${barra(c)}</div>
      <div class="pct">${c.pct}% de la vida útil · ${tagNivel(c.nivel)}</div>
      <div class="cifras">
        <div class="cifra"><div class="l">${midePorCalendario(c)?'En servicio':'Horas uso'}</div><div class="v">${midePorCalendario(c)?fmt(c.meses_en_servicio):fmt(c.horas_uso)}</div></div>
        <div class="cifra"><div class="l">Vida útil</div><div class="v">${vidaPieza(c)}</div></div>
        <div class="cifra"><div class="l">Estado del plazo</div><div class="v" style="font-size:13px;color:${c.nivel==='vencido'?'var(--red)':c.nivel==='ok'?'var(--green)':'var(--acc-deep)'}">${excesoPieza(c)}</div></div>
      </div>
      ${c.nota?`<div class="nota">🔍 ${escapar(c.nota)}</div>`:''}
      ${(g=>g&&g.length>1?`<div class="mini-diag-titulo">Piezas de este conjunto</div><div class="lista" style="margin-bottom:12px">${g.filter(x=>x.id!==c.id).map(x=>`<div class="item clk" data-cid="${x.id}"><span class="punto ${x.nivel}"></span><div class="cuerpo"><b>${escapar(x.nombre)}</b><div class="mut">${usoPieza(x)} · ${x.pct}% · ${NIVEL_TXT[x.nivel]}</div>${barra(x)}</div></div>`).join('')}</div>`:'')(grupoMesh[c.mesh||CLAVE2MESH[c.clave]])}
      <div class="mut" style="margin-bottom:12px">Último cambio: <b>${c.fecha_ultimo_cambio?fmtFecha(c.fecha_ultimo_cambio):'ninguno (pieza original)'}</b> · Instalada: ${fmtFecha(c.fecha_instalado)}</div>
      <div class="acciones">
        <button class="btn ${c.nivel==='ok'?'secundario':'verde'}" id="btnCambio">🔧 Registrar cambio</button>
        <button class="btn secundario" id="btnAjuste">Ajustar horas</button>
        <a class="btn secundario" href="/despiece?modulo=${(modPanel||{}).clave||''}&equipo=${EQUIPO?EQUIPO.id:''}">Abrir diagrama completo</a>
      </div>
      ${htmlSelectorModulos()}${htmlDiagrama(modPanel)}`;
    el.querySelectorAll('[data-mod]').forEach(b=>b.onclick=()=>{
        try{ abrirModulo3D(b.dataset.mod); }catch(err){ avisarFallo('abriendo el módulo', err); } });
    enlazarDiagrama(el, modPanel);
    el.querySelectorAll('[data-cid]').forEach(it=>it.onclick=()=>{ const x=COMPS.find(y=>String(y.id)===it.dataset.cid); if(x) seleccionar(x); });
    document.getElementById('btnCambio').onclick=async()=>{ if(!confirm(`¿Registrar el cambio de "${c.nombre}" en ${EQUIPO.nombre}? Sus horas de uso vuelven a cero.`)) return;
      await api('/api/mantenimientos',{method:'POST',body:{equipo_id:EQUIPO.id, componente_id:c.id, tipo:'preventivo', descripcion:`Cambio de ${c.nombre}`}}); toast('Cambio registrado'); await cargarEquipo(EQUIPO.id); };
    document.getElementById('btnAjuste').onclick=async()=>{ const v=prompt(`Horas de uso actuales de "${c.nombre}":`, c.horas_uso); if(v===null||isNaN(Number(v))) return;
      await api(`/api/componentes/${c.id}`,{method:'PUT',body:{horas_uso:Number(v)}}); toast('Horas ajustadas'); await cargarEquipo(EQUIPO.id); };
  }
  // Piezas del archivo 3D agrupadas por conjunto y por nombre (las repetidas se cuentan: ×4 tornillos).
  let _agrup=null, _agrupN=-1;
  function piezasAgrupadas(){
    if(_agrup&&_agrupN===PIEZAS.length) return _agrup;
    const porKey=new Map();
    PIEZAS.forEach(pz=>{
      if(!porKey.has(pz.key)) porKey.set(pz.key, new Map());
      const m=porKey.get(pz.key);
      if(!m.has(pz.crudo)) m.set(pz.crudo, {nombre:pz.nombre, crudo:pz.crudo, mallas:[]});
      m.get(pz.crudo).mallas.push(pz.malla);
    });
    _agrup=porKey; _agrupN=PIEZAS.length; return _agrup;
  }
  let _ciclo={};
  function pintarPiezasModelo(){
    if(ES_AVION){ pintarArbolAvion(); return; }
    const cont=document.getElementById('lista'), agr=piezasAgrupadas();
    const q=BUSCA.trim().toLowerCase();
    let total=0, mostradas=0, html='';
    PARTES.slice().sort((a,b)=>a.nombre.localeCompare(b.nombre,'es')).forEach(parte=>{
      const m=agr.get(parte.key); if(!m) return;
      const filas=[...m.values()].filter(x=>{ total+=0; return !q||x.nombre.toLowerCase().includes(q)||x.crudo.toLowerCase().includes(q); })
        .sort((a,b)=>a.nombre.localeCompare(b.nombre,'es'));
      if(!filas.length) return;
      mostradas+=filas.reduce((a,x)=>a+x.mallas.length,0);
      html+=`<div class="modulo">${escapar(parte.nombre)} <span class="mut">· ${[...m.values()].reduce((a,x)=>a+x.mallas.length,0)} piezas</span></div>`;
      html+=filas.map(x=>`<div class="item clk ${PIEZA&&x.mallas.includes(PIEZA)?'sel':''}" data-crudo="${escapar(x.crudo)}" data-key="${escapar(parte.key)}">
        <span class="punto ${nivelDe(parte.key)}"></span>
        <div class="cuerpo"><b>${escapar(x.nombre)}</b><div class="mut"><span class="codigo">${escapar(x.crudo)}</span>${x.mallas.length>1?` · ×${x.mallas.length}`:''}</div></div></div>`).join('');
    });
    PIEZAS.forEach(()=>{}); total=PIEZAS.length;
    document.getElementById('piezasConteo').textContent=`· ${mostradas} de ${total} piezas del modelo 3D`;
    cont.innerHTML=html||`<div class="empty" style="padding:20px">Ninguna pieza coincide con «${escapar(BUSCA)}».</div>`;
    cont.querySelectorAll('[data-crudo]').forEach(el=>el.addEventListener('click',()=>{
      const grupo=agr.get(el.dataset.key); if(!grupo) return;
      const x=grupo.get(el.dataset.crudo); if(!x||!x.mallas.length) return;
      const id=el.dataset.key+'|'+el.dataset.crudo; _ciclo[id]=((_ciclo[id]||0)+(PIEZA&&x.mallas.includes(PIEZA)?1:0))%x.mallas.length;
      seleccionarPieza(x.mallas[_ciclo[id]]);
      if(x.mallas.length>1) toast(`${x.nombre} · ejemplar ${_ciclo[id]+1} de ${x.mallas.length}`);
    }));
  }
  function pintarLista(){
    if(GRUPOS.length||ES_AVION){ pintarArbolAvion(); return; }
    if(FILTRO==='modelo'){ pintarPiezasModelo(); return; }
    const lista=COMPS.filter(c=>FILTRO==='todas'||(FILTRO==='alerta'?c.nivel!=='ok':!!c.mesh));
    document.getElementById('piezasConteo').textContent=`· ${lista.length} de ${COMPS.length}`;
    const grupos={}; lista.forEach(c=>{(grupos[c.modulo]=grupos[c.modulo]||[]).push(c);});
    document.getElementById('lista').innerHTML=Object.keys(grupos).sort().map(m=>`<div class="modulo">${escapar(m)}</div>`+grupos[m].map(c=>`
      <div class="item clk ${SEL&&SEL.id===c.id?'sel':''} ${c.mesh?'':'interno'}" data-id="${c.id}">
        <span class="punto ${c.nivel}"></span>
        <div class="cuerpo"><b>${escapar(c.nombre)}</b><div class="mut">${usoPieza(c)} · ${c.pct}%</div></div>
        <div style="width:64px">${barra(c)}</div></div>`).join('')).join('')||`<div class="empty" style="padding:20px">Sin piezas.</div>`;
    document.querySelectorAll('#lista .item').forEach(el=>el.addEventListener('click',()=>{ const c=COMPS.find(x=>String(x.id)===el.dataset.id); if(c) seleccionar(c); }));
  }
  document.querySelectorAll('[data-f]').forEach(b=>b.addEventListener('click',()=>{ document.querySelectorAll('[data-f]').forEach(x=>x.classList.remove('active')); b.classList.add('active'); FILTRO=b.dataset.f;
    const bp=document.getElementById('buscaPieza'); if(bp) bp.style.display=FILTRO==='modelo'?'block':'none';
    pintarLista(); }));
  (function(){ const bp=document.getElementById('buscaPieza'); if(!bp) return;
    let tm=null; bp.addEventListener('input', ()=>{ BUSCA=bp.value; clearTimeout(tm); tm=setTimeout(()=>{ if(FILTRO==='modelo') pintarPiezasModelo(); }, 120); }); })();

  // ---- Modelo real (GLB de despiece con nodos nombrados) ----
  // El despiece del T50 trae ~1.765 mallas nombradas en español y una jerarquía
  // brazo_Mx / pod_motor_Mx / helice_(superior|inferior)_Mx que se usa para agrupar las piezas
  // clickeables. Las claves resultantes son las mismas que usa el catálogo (columna `mesh`).
  //
  // Los archivos ya no están escritos aquí: los da `/api/modelos`, así que en cuanto se deje el
  // GLB de otro modelo en static_shell/modelos/ y se registre en core/modelos.py, esta pantalla
  // lo carga sin tocar este archivo. `clasificar()` de más abajo agrupa por el nombre del nodo,
  // de modo que un modelo nuevo que respete esos nombres funciona tal cual.
  let MODELOS=[];
  // Los nodos del archivo vienen como `bomba_impulsor_rodete`; se muestran tal cual pero legibles.
  const SIGLAS={rtk:'RTK', esc:'ESC', fpv:'FPV', sdr:'SDR', led:'LED', pcb:'PCB', fpc:'FPC', tx:'TX', rx:'RX', rf:'RF', y:'Y', m1:'M1', m2:'M2', m3:'M3', m4:'M4', hdpe:'HDPE'};
  function nombrePieza(crudo){
    const t=(crudo||'').replace(/_/g,' ').trim().split(/\s+/).map(w=>{
      const k=w.toLowerCase(); if(SIGLAS[k]) return SIGLAS[k];
      if(/^m\d+$/i.test(w)||/^[A-Z0-9]+$/.test(w)) return w;
      return k;
    });
    if(!t.length) return 'Pieza';
    t[0]=t[0].charAt(0).toUpperCase()+t[0].slice(1);
    return t.join(' ');
  }
  // Cada archivo 3D nombra sus nodos a su manera y hay que agrupar sus mallas en los mismos
  // conjuntos que usa el catálogo (columna `mesh`). El T50 lo dice en el nombre de la pieza
  // (`tanque_`, `bomba_`, `brazo_M1/…`); el T70P lo dice en la jerarquía, con un grupo `MOD_*`
  // por sistema. Por eso hay una función de clasificación por modelo en vez de una sola.
  const SIN_TILDES = t => (t||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');

  function clasificarT50(nombre, ancestros){
    const n=(nombre||'').toLowerCase(), anc=ancestros.join('/').toLowerCase();
    // --- piezas colgadas de un brazo ---
    if(/brazo_m[1-4]/.test(anc)||/^tubo_carbono|^casquillo_tubo|^bisagra_|^palanca_bloqueo|^etiqueta_brazo|^marca_amarilla|^flecha_roja|^manguera_brazo|^conector_brazo/.test(n)){
      if(/helice_(superior|inferior)/.test(anc)||/^helice_/.test(n)) return 'helice';
      if(/^lanza_|^disco_|^motor_centrifugo|^manguera_lanza|^manguera_brazo|^clip_manguera_brazo|^electrovalvula|^valvula_antirretorno|^fuelle_lanza|aspersor/.test(n)) return 'aspersor';
      if(/^esc_|^modulo_esc|^tornillo_esc|^cable_esc|^conector_esc|^junta_barra_bus|^junta_silicona_tres_fases/.test(n)) return 'motor';
      if(/pod_motor/.test(anc)||/^motor_|^cubierta_motor|^cubierta_inferior|^cuello_inferior|^asiento_motor|^tapa_superior_motor|^protector_motor|^pinza_helice|^soporte_helice|^luz_navegacion/.test(n)) return 'motor';
      return 'brazo';
    }
    // --- depósito y tapa/filtro ---
    if(/^tanque_tapa|^tapa_tanque|^filtro_|^tanque_cordon_tapa/.test(n)) return 'filtro';
    if(/^tanque_|^correa_|^nivel_|^purga_|^respiradero|^racor_salida_tanque|^sensor_nivel|^pieza_y_|^manguera_tanque_bomba|^abrazadera_manguera_tanque|^tapa_giratoria_salida_agua/.test(n)) return 'tanque';
    // --- antenas y RTK ---
    if(/^antena_rtk|^anillo_goma_rtk|^cable_coaxial_rtk|^cable_señal_rtk|^cable_senal_rtk/.test(n)) return 'rtk';
    if(/^antena_|^clip_cable_rf/.test(n)) return 'antena';
    // --- batería ---
    if(/^bateria|^hebilla_bateria|^clip_fijacion_bateria|^muelle_clip_fijacion|^rodillo_fijacion|^soporte_bateria|^tornillo_soporte_bateria|^conector_potencia_bateria|^eje_rodillo_fijacion/.test(n)) return 'bateria';
    // --- radares ---
    if(/^radar_trasero|^radar_inferior|^tornillo_radar_trasero|^cable_señal_radar_trasero|^cable_senal_radar_trasero/.test(n)) return 'radar_t';
    if(/^radar_|^soporte_radar_frontal/.test(n)) return 'radar_d';
    // --- módulo frontal / cubierta delantera ---
    if(/^modulo_frontal|^camara_fpv|^sensor_binocular|^modulo_vision_frontal|^soporte_fpv|^tapa_lente|^faro_|^tornillo_faro|^luz_auxiliar|^junta_luz_auxiliar|^cubierta_frontal|^tapon_estanco_frontal|^goma_amortiguacion_frontal|^soporte_auxiliar_frontal|^cable_señal_frontal|^cable_senal_frontal|^baliza_|^franja_led|^almohadilla_anticolision|^tornillo_modulo|^luz_led/.test(n)) return 'marco_d';
    // --- carcasa trasera, radiador y placa de distribución ---
    if(/^carcasa_|^tornillo_carcasa|^tapon_sellado_trasero|^rejilla_ventilador|^modulo_rejilla|^tornillo_rejilla|^disipador_|^modulo_potencia|^placa_distribuidora|^borne_distribuidor/.test(n)) return 'marco_t';
    // --- circuito de pulverización ---
    if(/^bomba_|^manguera_bomba|^valvula_tres_vias|^soporte_bomba_tanque|^abrazadera_manguera_bomba/.test(n)) return 'bomba';
    if(/^caudalimetro|^soporte_caudalimetro|^manguera_caudalimetro/.test(n)) return 'caudalimetro';
    // --- tren de aterrizaje ---
    if(/^tren_/.test(n)) return 'tren';
    return 'marco_c';
  }

  // Convención de los modelos nuevos: los nombres van en castellano corriente («Bastidor
  // central», «Bomba de impulsor…») y lo que manda es el grupo `MOD_*` del que cuelga la pieza;
  // sólo se afina por nombre dentro de él. Es la que se pide a quien construya un modelo nuevo,
  // y por eso es también la regla por defecto.
  function clasificarPorModulos(nombre, ancestros){
    const n=SIN_TILDES(nombre), anc=SIN_TILDES(ancestros.join('/'));
    if(anc.includes('mod_brazos')) return 'brazo';
    if(anc.includes('mod_propulsion')){
      // ROT_Mx es el pivote del rotor: dentro va todo lo que gira con la hélice.
      if(anc.includes('rot_')||/helice|pinza de helice|eje de helice|punta de helice/.test(n)) return 'helice';
      return 'motor';
    }
    if(anc.includes('mod_barra')) return 'aspersor';
    if(anc.includes('mod_tren')) return 'tren';
    if(anc.includes('mod_energia')) return 'bateria';
    if(anc.includes('mod_deposito')){
      if(/bomba|impulsor/.test(n)) return 'bomba';
      if(/caudalimetro/.test(n)) return 'caudalimetro';
      if(/filtro|manometro|nivel/.test(n)) return 'filtro';
      return 'tanque';
    }
    if(anc.includes('mod_avionica')){
      if(/antena rtk|antena rtk|base de antena rtk/.test(n)) return 'rtk';
      if(/antena sdr|coaxial/.test(n)) return 'antena';
      if(/radar/.test(n)) return 'radar_d';
      if(/fpv|vision|lente|luz auxiliar|baliza/.test(n)) return 'marco_d';
      return 'marco_t';
    }
    return 'marco_c';
  }

  // Sólo el T50 necesita reglas propias: su archivo es anterior a la convención `MOD_*` y dice
  // el conjunto en el nombre de cada pieza. Cualquier modelo nuevo que respete la convención
  // funciona sin tocar nada aquí.
  const CLASIFICADORES={T50:clasificarT50};
  function clasificar(nombre, ancestros){
    return (CLASIFICADORES[MODELO_3D]||clasificarPorModulos)(nombre, ancestros);
  }
  // El sufijo Mx sólo identifica el brazo cuando viene de la jerarquía o del nombre de la pieza;
  // en tornillería (M30, M40…) es la métrica, por eso se descarta si va seguido de otro dígito.
  const CON_INSTANCIA={helice:1, motor:1, brazo:1, aspersor:1};
  function instanciaDe(key, nombre, ancestros){
    if(!CON_INSTANCIA[key]) return '';
    const a=ancestros.join('/').match(/_M([1-4])(?![0-9])/i);
    if(a) return 'M'+a[1];
    const b=(nombre||'').match(/_M([1-4])(?![0-9])/i);
    return b?'M'+b[1]:'';
  }
  const NOMBRES={helice:'Hélice',motor:'Motor',brazo:'Brazo',tanque:'Tanque',filtro:'Tapa y filtro',rtk:'RTK',antena:'Antena',bateria:'Batería',radar_d:'Radar',radar_t:'Radar inferior',marco_d:'Módulo frontal',marco_t:'Carcasa trasera',bomba:'Bomba',caudalimetro:'Caudalímetro',aspersor:'Aspersor',tren:'Tren',marco_c:'Marco'};

  // Los conjuntos del dron, en el mismo formato que los grupos del avión, para que el explorador
  // de piezas sea uno solo: sistema (SIS_DRON) › conjunto (cada PARTE) › pieza.
  function construirGruposDron(){
    GRUPOS=[]; _indice=null;
    PARTES.forEach((p,i)=>{
      const sis=SIS_DRON[p.key]||'Otros'; p.sisExp=sis;
      const ms=mallas(p), key='D'+i;
      ms.forEach(n=>{ const u=n.userData; u.grupoExp=key; u.nombreBase=u.pieza||u.crudo||'Pieza'; u.pn=u.pn||''; u.ref=u.ref||'';
        u.tapa=esTapa((u.pieza||'')+' '+(u.crudo||'')); });
      GRUPOS.push({key, clave:p.key, parte:p, sis, fig:null, nombre:p.nombre, mallas:ms, lotes:[], sinLotes:true, base:p.base});
    });
  }
  function cargarModeloReal(i){
    i=i||0;
    if(!THREE.GLTFLoader||i>=MODELOS.length){ if($cargando.isConnected) $cargando.remove(); return; }
    new THREE.GLTFLoader().load(MODELOS[i], gltf=>{
      const raiz=gltf.scene;
      if(ES_AVION){ cargarAvion(raiz, gltf.parser); return; }
      // normalizar tamaño y posición
      const caja0=new THREE.Box3().setFromObject(raiz); const tam=caja0.getSize(new THREE.Vector3()); const esc=4.6/Math.max(tam.x,tam.y,tam.z); raiz.scale.setScalar(esc);
      raiz.updateMatrixWorld(true); const caja1=new THREE.Box3().setFromObject(raiz); const centro=caja1.getCenter(new THREE.Vector3());
      raiz.position.sub(centro); raiz.position.y+= (centro.y-caja1.min.y) - (0 - Y_SUELO) + .02;
      // quitar modelo programado
      PARTES.forEach(p=>dron.remove(p.grupo)); PARTES.length=0; PROPS.length=0; NIEBLAS.length=0; PIEZAS.length=0; _clic=null; _clicN=-1;
      dron.add(raiz); dron.updateMatrixWorld(true);
      // agrupar mallas por pieza
      const grupos={};
      raiz.traverse(n=>{
        if(!n.isMesh) return;
        // Sólo proyectan sombra las piezas con tamaño relevante: con 1,7 k mallas, hacer que la
        // tornillería proyecte sombra multiplica el coste del pase de sombras sin que se note.
        if(n.geometry&&!n.geometry.boundingSphere) n.geometry.computeBoundingSphere();
        const r=n.geometry&&n.geometry.boundingSphere?n.geometry.boundingSphere.radius*esc:1;
        n.castShadow=r>.035; n.receiveShadow=true;
        const anc=[]; let a=n.parent; while(a&&a!==raiz){ anc.push(a.name||''); a=a.parent; }
        const key=clasificar(n.name||'', anc);
        const inst=instanciaDe(key, n.name||'', anc);
        const wp=new THREE.Vector3(); n.getWorldPosition(wp); const lp=dron.worldToLocal(wp.clone());
        let sub='';
        if(key==='helice'){ const h=anc.find(x=>/^helice_/.test(x))||n.name||''; sub=/inferior/.test(h)?'inf':'sup'; }
        if(key==='motor'){ const pod=n.parent; const pc=new THREE.Vector3(); (pod.isGroup||pod.isObject3D)&&pod.getWorldPosition(pc); sub=(/inferior/.test(n.name)||(!/superior/.test(n.name)&&wp.y<pc.y-.02))?'inf':'sup'; if(/esc|disipador/.test((n.name||'').toLowerCase())) sub='esc'; }
        if(key==='aspersor'||key==='tren'){ sub=lp.x>=0?'der':'izq'; if(/travesano/.test(n.name||'')) sub='trav'; }
        const id=key+'|'+inst+'|'+sub; (grupos[id]=grupos[id]||{key,inst,sub,mallas:[],suma:new THREE.Vector3()}).mallas.push(n); grupos[id].suma.add(lp);
      });
      Object.values(grupos).forEach(gr=>{
        const centroide=gr.suma.multiplyScalar(1/gr.mallas.length);
        const g=new THREE.Group(); g.position.copy(centroide); dron.add(g); g.updateMatrixWorld(true);
        // Un clon de material por (grupo, material original): conserva el aspecto PBR del GLB y
        // permite teñir/atenuar la pieza sin duplicar 1.765 materiales.
        const cacheMat=new Map(); let radio=1e-4;
        gr.mallas.forEach((m,i)=>{
          let cl=cacheMat.get(m.material); if(!cl){ cl=m.material.clone(); cacheMat.set(m.material,cl); }
          m.material=cl;
          g.attach(m); m.userData.key=gr.key; m.userData.op=cl.opacity; m.userData.basePos=m.position.clone(); m.userData.idx=i;
          m.userData.crudo=m.name||'pieza'; m.userData.pieza=nombrePieza(m.name);
          // Centro real de la pieza dentro del conjunto (la geometría puede no estar centrada en su origen).
          if(m.geometry&&!m.geometry.boundingBox) m.geometry.computeBoundingBox();
          const c=new THREE.Vector3(); if(m.geometry&&m.geometry.boundingBox) m.geometry.boundingBox.getCenter(c);
          m.updateMatrix(); c.applyMatrix4(m.matrix);
          m.userData.centro=c; radio=Math.max(radio,c.length());
        });
        // Despiece individual: cada pieza se aleja radialmente del centro de su conjunto, tanto más
        // cuanto más exterior es. El desvío por índice evita que piezas idénticas queden superpuestas.
        gr.mallas.forEach((m,i)=>{
          const c=m.userData.centro, d=c.clone();
          if(d.lengthSq()<1e-8){ const a=i*2.399; d.set(Math.cos(a)*.6, .5, Math.sin(a)*.6); }
          else { const a=i*2.399; d.normalize().addScaledVector(V(Math.cos(a),Math.sin(a*1.7),Math.sin(a)), .18); }
          m.userData.dirP=d.normalize();
          // Proporcional al tamaño del conjunto: un radar pequeño florece poco, el tanque mucho.
          m.userData.distP=(gr.mallas.length>1?1:0)*(radio*.55+c.length()*1.75);
          PIEZAS.push({malla:m, nombre:m.userData.pieza, crudo:m.userData.crudo, key:gr.key});
        });
        const dir=centroide.clone(); if(gr.key==='helice') dir.y+=gr.sub==='inf'?-1.2:1.4; if(gr.key==='motor') dir.y+=gr.sub==='inf'?-.6:.6; if(gr.key==='tanque'||gr.key==='bomba'||gr.key==='tren') dir.y-=1; if(gr.key==='bateria'||gr.key==='rtk'||gr.key==='filtro'||gr.key==='antena') dir.y+=1.4; if(dir.lengthSq()<1e-4) dir.set(0,1,0);
        const nombre=`${NOMBRES[gr.key]||gr.key}${gr.inst?' '+gr.inst:''}${gr.sub==='sup'?' superior':gr.sub==='inf'?' inferior':gr.sub==='esc'?' (ESC)':gr.sub==='der'?' derecho':gr.sub==='izq'?' izquierdo':''}`;
        PARTES.push({key:gr.key, nombre, grupo:g, base:centroide.clone(), dir:dir.normalize(), dist:1.15, objs:[g], offset:new THREE.Vector3()});
        if(gr.key==='helice') PROPS.push({g, sentido:(gr.inst==='M1'||gr.inst==='M3')?1:-1, disco:null});
        if(gr.key==='aspersor'&&gr.sub!=='trav'){ const n=420, p=new Float32Array(n*3), vida=new Float32Array(n); for(let i=0;i<n;i++) vida[i]=Math.random();
          const geo=new THREE.BufferGeometry(); geo.setAttribute('position',new THREE.BufferAttribute(p,3));
          const pts=new THREE.Points(geo,new THREE.PointsMaterial({color:0xff9a7a,size:.045,transparent:true,opacity:0,depthWrite:false})); pts.position.set(0,-.1,0); g.add(pts); NIEBLAS.push({pts,vida,n}); }
      });
      raiz.parent&&dron.remove(raiz);
      construirGruposDron();
      _clic=null; _clicN=-1;
      // El GLB real llega después del modelo procedimental: se reinicia la secuencia de entrada
      // para verla con las piezas de verdad, y en su punto de partida (montado y en el aire).
      intro=1; explode=0; introVuelo=1; introExplode=0; volando=false; objetivoExplode=null;
      colorear(); resaltar(); pintarLista(); if($cargando.isConnected) $cargando.remove();
      toast(`Despiece del ${MODELO_3D} cargado · ${PIEZAS.length} piezas clickeables en ${PARTES.length} conjuntos`);
    }, ev=>{ if($cargando.isConnected&&ev&&ev.lengthComputable) $cargando.textContent=`Cargando despiece 3D del ${MODELO_3D}… `+Math.round(ev.loaded/ev.total*100)+'%'; }, err=>{ console.error(err); if(i+1<MODELOS.length){ $cargando.textContent=`Cargando modelo alternativo del ${MODELO_3D}…`; cargarModeloReal(i+1); }
      else { $cargando.textContent='No se pudo cargar el modelo real (se muestra el esquemático).'; setTimeout(()=>{ if($cargando.isConnected) $cargando.remove(); },2500); } });
  }

  // =====================================================================================
  // ---- Modo avión: sistema → grupo → pieza ----
  // =====================================================================================
  // Nombre de malla que escribe el despiece: «Perno — AN3-5A — F16-2 (1 de 4)».
  function partirNombre(raw){
    const s=(raw||'').trim(), m=s.match(/\s*\((\d+) de (\d+)\)\s*$/);
    const base=m?s.slice(0,m.index):s, partes=base.split(/\s+—\s+/);
    return {nombre:partes[0]||'Pieza', pn:partes[1]||'', ref:partes[2]||'', inst:m?`${m[1]} de ${m[2]}`:'', base};
  }
  // Revestimientos y tapas: lo que se oculta con «Ver interior».
  const RX_PIEL=/revestimiento|capó|capo |carenado|chapa|panel|tapa de inspecci|puerta|parabrisas|ventana|capota|guardabarros|cono de cola|punta de ala|carena|forro|tapicer|^borde de ataque|pasarela|antideslizante|tapa de registro|protector de la luz|placa de cierre|^punta d|^cubierta\b|placa de inspecci/i;
  // Todo lo pintado por fuera (amarillo agrícola y blanco) y los metacrilatos también es cubierta,
  // se llame como se llame la pieza: «Ver interior» deja sólo la estructura, el motor y los sistemas.
  const RX_PIEL_MAT=/amarillo|pintura blanca|metacrilato/i;
  // …pero sólo si es chapa (fina y ancha): los montantes, refuerzos, placas de empalme o la
  // tolva también van pintados y son estructura o sistema, no cubierta.
  const RX_ESTRUCTURA=/larguer|montante|refuerzo|empalme|soporte|ret[eé]n|herraje|costilla|tolva|bisagra|palanca|varilla|tubo|brazo|perfil|[aá]ngulo|cuaderna|mamparo/i;
  function esLamina(m){
    const g=m.geometry; if(!g) return false; if(!g.boundingBox) g.computeBoundingBox();
    const t=g.boundingBox.getSize(new THREE.Vector3()).multiply(m.scale); const d=[Math.abs(t.x),Math.abs(t.y),Math.abs(t.z)].sort((a,b)=>a-b);
    return d[0]<d[1]*.12 && d[1]>.12;
  }
  const ordenSis=(a,b)=>{ const o=ES_AVION?ORDEN_SIS:ORDEN_SIS_DRON; const ia=o.indexOf(a), ib=o.indexOf(b); return (ia<0?99:ia)-(ib<0?99:ib); };
  const ORDEN_SIS=['MOD_ALA','MOD_FUSELAJE','MOD_CABINA','MOD_EMPENAJE','MOD_MOTOR','MOD_HELICE','MOD_TREN','MOD_TOLVA','MOD_APLICACION','MOD_COMBUSTIBLE','MOD_MANDOS','MOD_ELECTRICO'];
  let _verClic=0, _clicAv=null, _clicAvVer=-1;

  // Un solo explorador de piezas a la altura del visor, igual para drones y aviones (y para
  // cualquier modelo que se añada): la ficha de detalle y los filtros repetían la navegación.
  function prepararExplorador(){
    const panel=document.querySelector('.panel-pieza'); if(panel) panel.classList.add('modo-explorador');
    const cajon=document.getElementById('drawer3d'); if(cajon) cajon.classList.add('modo-explorador');
    FILTRO='modelo';
    const fil=document.querySelector('[data-f]'); if(fil&&fil.parentElement) fil.parentElement.style.display='none';
    const h3=document.getElementById('piezasConteo'); if(h3&&h3.parentElement) h3.parentElement.firstChild.textContent='Explorador de piezas ';
    const bp=document.getElementById('buscaPieza');
    if(bp){ bp.style.display='block'; bp.placeholder=ES_AVION?'Buscar pieza o número de parte (p. ej. bisagra, AN3-5A)…':'Buscar pieza (p. ej. rodete, radar, muelle)…'; }
  }
  function prepararInterfazAvion(){
    dron.visible=false;                 // el dron esquemático no debe asomar mientras carga el avión
    ['btnVuelo','btnNiebla'].forEach(id=>{ const b=document.getElementById(id); if(b) b.style.display='none'; });
    const bh=document.getElementById('btnHelices'); if(bh) bh.title='Hace girar la hélice';
    const bi=document.getElementById('btnInterior');
    if(bi){ bi.style.display=''; bi.title='Modo piloto: te sienta en la cabina, mirando al frente; arrastra para mirar alrededor';
      interruptor('btnInterior', false, v=>modoPiloto(v)); }
    // En el avión «Quitar tapas» quita TODAS las cubiertas: revestimiento pintado, capó, paneles,
    // ventanas y tapas; queda el funcionamiento interno despejado.
    const bt=document.getElementById('btnTapas');
    if(bt){ bt.title='Desprende todo el revestimiento (chapa pintada, capó del motor, paneles, ventanas y tapas) y deja la estructura, el motor y los sistemas';
      [...bt.childNodes].forEach(n=>{ if(n.nodeType===3&&n.textContent.trim()) n.textContent=' Quitar cubiertas'; }); }
    FILTRO='modelo';
    document.querySelectorAll('[data-f]').forEach(b=>{ b.classList.toggle('active', b.dataset.f==='modelo');
      if(b.dataset.f!=='modelo') b.style.display='none'; else b.textContent='Sistemas y grupos'; });
    const bp=document.getElementById('buscaPieza');
    if(bp){ bp.style.display='block'; bp.placeholder='Buscar pieza o número de parte (p. ej. bisagra, AN3-5A)…'; }

    if($cargando) $cargando.textContent='Cargando el avión… (9.000+ piezas, puede tardar unos segundos)';
    const sub=document.querySelector('.encabezado p, header p, main > div p');
    const ayuda=[...document.querySelectorAll('p')].find(x=>/Pasa el puntero por cualquier pieza/.test(x.textContent));
    if(ayuda) ayuda.textContent='Haz clic en una parte del avión para abrir su grupo de piezas y otra vez sobre una pieza para inspeccionarla. «Despiece» separa sistemas, grupos y piezas; «Quitar cubiertas» deja la estructura y los sistemas a la vista; «Ver interior» te sienta en la cabina como piloto.';
  }

  // La hélice gira sobre su eje real, no sobre un eje fijo del archivo: las palas ocupan un
  // plano, y el eje es la perpendicular a sus dos direcciones principales (análisis de
  // componentes principales de los vértices), orientado hacia el morro. Se monta en un pivote
  // centrado en el cubo; gira a derechas vista desde la cabina, como la Continental del 188.
  function modoPiloto(activar){
    if(!activar){ if(PILOTO){ rotY=PILOTO.rotY0; rotX=PILOTO.rotX0; camera.near=.1; camera.fov=36; camera.updateProjectionMatrix(); ajustarFondo(); }
      PILOTO=null; toast('Vista exterior'); return; }
    // Asiento: el grupo de la figura 52 (asiento de regulación vertical) o, si no, cualquier asiento.
    const asiento=GRUPOS.find(g=>g.fig==='52'||g.fig===52) || GRUPOS.find(g=>/asiento/i.test(g.nombre));
    const helice=PROPS.find(p=>p.eje3);
    if(!asiento||!helice){ toast('Este modelo no trae asiento o hélice para situar al piloto'); return; }
    dron.rotation.set(0,0,0); dron.updateMatrixWorld(true);
    const caja=new THREE.Box3(); asiento.mallas.forEach(m=>caja.expandByObject(m));
    const c=caja.getCenter(new THREE.Vector3()), tam=caja.getSize(new THREE.Vector3());
    // Los ojos, a media altura entre el respaldo del asiento y el techo de la capota (el modelo
    // está a escala de la escena, así que no vale sumar metros reales).
    const capota=GRUPOS.find(g=>/capota/i.test(g.nombre))||GRUPOS.find(g=>/parabrisas/i.test(g.nombre));
    let techo=caja.max.y+tam.y;
    if(capota){ const cc=new THREE.Box3(); capota.mallas.forEach(m=>cc.expandByObject(m)); if(!cc.isEmpty()) techo=cc.max.y; }
    const ojo=dron.worldToLocal(new THREE.Vector3(c.x, caja.max.y+(techo-caja.max.y)*.55, c.z));
    const cubo=dron.worldToLocal(helice.g.getWorldPosition(new THREE.Vector3()));
    const frente=cubo.clone().sub(ojo); frente.y=0; frente.normalize();
    PILOTO={ojo, frente, rotY0:rotY, rotX0:rotX};
    velRotY=0; velRotX=0; intro=0; autoRotar=false;
    camera.near=.02; camera.fov=70; camera.updateProjectionMatrix(); ajustarFondo();
    toast('Modo piloto · arrastra para mirar alrededor');
  }

  function montarHelice(g, entrada, ejeDado){
    const pts=[], v=new THREE.Vector3();
    entrada.mallas.forEach(m=>{ const pos=m.geometry&&m.geometry.attributes.position; if(!pos) return;
      m.updateMatrix(); const paso=Math.max(1,Math.floor(pos.count/400));
      for(let i=0;i<pos.count;i+=paso) pts.push(v.fromBufferAttribute(pos,i).applyMatrix4(m.matrix).clone()); });
    if(pts.length<20) return null;
    const c=pts.reduce((a,p)=>a.add(p),new THREE.Vector3()).multiplyScalar(1/pts.length);
    // Pivote en el cubo: el centro de la caja de la hélice (simétrica respecto a su eje). La media
    // de los vértices se desplaza con la torsión de las palas y la hacía cabecear al girar.
    let pivoteEn=ejeDado?new THREE.Box3().setFromPoints(pts).getCenter(new THREE.Vector3()):c;
    // Mejor aún: el cono (spinner) es de revolución, así que el centro de su caja en su propia
    // geometría está sobre el eje. Se usa el cono más grande del grupo.
    if(ejeDado){ const conos=entrada.mallas.filter(m=>/cono|spinner/i.test(m.userData.pieza||'')&&m.geometry&&m.geometry.attributes.position);
      conos.sort((a,b)=>b.geometry.attributes.position.count-a.geometry.attributes.position.count);
      const k=conos.find(m=>!/mamparo|separador/i.test(m.userData.pieza))||conos[0];
      if(k){ if(!k.geometry.boundingBox) k.geometry.computeBoundingBox(); pivoteEn=k.geometry.boundingBox.getCenter(new THREE.Vector3()).applyMatrix4(k.matrix); } }
    const C=[[0,0,0],[0,0,0],[0,0,0]];
    pts.forEach(p=>{ const d=[p.x-c.x,p.y-c.y,p.z-c.z]; for(let i=0;i<3;i++) for(let j=0;j<3;j++) C[i][j]+=d[i]*d[j]; });
    const mul=(M,x)=>new THREE.Vector3(M[0][0]*x.x+M[0][1]*x.y+M[0][2]*x.z, M[1][0]*x.x+M[1][1]*x.y+M[1][2]*x.z, M[2][0]*x.x+M[2][1]*x.y+M[2][2]*x.z);
    const potencia=(M,x)=>{ for(let k=0;k<60;k++){ x=mul(M,x); const l=x.length(); if(l<1e-12) break; x.multiplyScalar(1/l); } return x; };
    const e1=potencia(C,new THREE.Vector3(1,.3,.2));
    const l1=mul(C,e1).dot(e1), D=C.map((f,i)=>f.map((x,j)=>x-l1*[e1.x,e1.y,e1.z][i]*[e1.x,e1.y,e1.z][j]));
    const e2=potencia(D,new THREE.Vector3(.2,1,.3));
    const eje=ejeDado?ejeDado.clone():new THREE.Vector3().crossVectors(e1,e2).normalize();
    // Hacia delante: del centro del avión (origen de `dron`, que en el grupo está en -g.position) al cubo.
    const alMorro=c.clone().add(g.position);
    if(eje.dot(alMorro)<0) eje.negate();
    g.updateMatrixWorld(true);
    const pivote=new THREE.Group(); pivote.position.copy(pivoteEn); g.add(pivote); pivote.updateMatrixWorld(true);
    [...g.children].forEach(ch=>{ if(ch!==pivote) pivote.attach(ch); });
    entrada.mallas.forEach(m=>{ if(m.userData.basePos) m.userData.basePos.sub(pivoteEn); });
    return {g:pivote, eje3:eje, ang:0, sentido:1, disco:null};
  }

  function cargarAvion(raiz, parser){
    const orig=o=>{ const a=parser&&parser.associations&&parser.associations.get(o);
      // Three r128 guarda {type:'nodes', index}; versiones posteriores guardan {nodes: índice}.
      const i=a?(a.type==='nodes'?a.index:a.nodes):undefined;
      if(i!==undefined&&parser.json.nodes[i]) return parser.json.nodes[i].name||'';
      return (o.name||'').replace(/_/g,' '); };
    // Las alternativas del catálogo que no van montadas a la vez (12 V / 24 V, hélice de 86" / 82",
    // tolva normal / de abertura grande…) viven en el archivo bajo MOD_VARIANTES: se conservan para
    // la trazabilidad, pero no se dibujan ni se cuentan (estaban superpuestas a la pieza de serie).
    (function(){ const fuera=[]; raiz.traverse(o=>{ if(/^MOD[_ ]VARIANTES/i.test(orig(o)||o.name||'')) fuera.push(o); });
      fuera.forEach(o=>o.parent&&o.parent.remove(o));
      if(fuera.length) console.info(`[Hangar 3D] ${fuera.length} grupo(s) de variantes del catálogo sin dibujar.`); })();
    // Actitud en tierra: el Cessna 188 apoya en las dos ruedas principales y la rueda de cola, con
    // el eje del fuselaje a 12°41' del suelo (manual del propietario). El archivo viene nivelado,
    // así que se gira aquí alrededor del eje de las ruedas principales, con el morro hacia arriba.
    (function(){
      const ACTITUD=-(12+41/60)*Math.PI/180;          // morro hacia +Z: girar en −X lo levanta
      raiz.updateMatrixWorld(true);
      const ruedas=[];
      raiz.traverse(o=>{ if(o.isMesh&&/^neum[aá]tico/i.test(partirNombre(orig(o)||orig(o.parent)).nombre)){
        const bx=new THREE.Box3().setFromObject(o); ruedas.push({c:bx.getCenter(new THREE.Vector3()), piso:bx.min.y}); } });
      if(ruedas.length<2) return;
      const zs=ruedas.map(r=>r.c.z).sort((a,b)=>a-b), mitad=(zs[0]+zs[zs.length-1])/2;
      const prin=ruedas.filter(r=>r.c.z>=mitad), cola=ruedas.filter(r=>r.c.z<mitad);   // la de cola queda atrás
      if(!prin.length||!cola.length) return;
      const eje=prin.reduce((v,r)=>v.add(r.c),new THREE.Vector3()).multiplyScalar(1/prin.length);
      // Sólo se inclina si el archivo está modelado como el avión real nivelado: ruedas principales
      // en el suelo y la de cola en el aire, a la altura que da la actitud. Si las tres ruedas
      // apoyan con el avión nivelado (tren de cola demasiado largo), inclinarlo dejaría las
      // principales flotando: se deja nivelado y se avisa en la consola.
      const pisoPrin=Math.min(...prin.map(r=>r.piso)), pisoCola=Math.min(...cola.map(r=>r.piso));
      const esperado=Math.abs(eje.z-cola[0].c.z)*Math.tan(-ACTITUD);
      if(pisoCola-pisoPrin<esperado*.5){
        console.info(`[Hangar 3D] Actitud en tierra no aplicada: la rueda de cola está a ${(pisoCola-pisoPrin).toFixed(2)} sobre las principales y debería estar a ~${esperado.toFixed(2)}.`);
        return;
      }
      const q=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),ACTITUD);
      raiz.position.sub(eje).applyQuaternion(q).add(eje); raiz.quaternion.premultiply(q);
      raiz.updateMatrixWorld(true);
    })();
    // Normalizar tamaño y apoyarlo en el suelo, igual que los drones.
    const caja0=new THREE.Box3().setFromObject(raiz); const tam=caja0.getSize(new THREE.Vector3());
    const esc=4.6/Math.max(tam.x,tam.y,tam.z); raiz.scale.multiplyScalar(esc);
    raiz.updateMatrixWorld(true); const caja1=new THREE.Box3().setFromObject(raiz); const centro=caja1.getCenter(new THREE.Vector3());
    raiz.position.sub(centro); raiz.position.y+=(centro.y-caja1.min.y)-(0-Y_SUELO)+.02;
    PARTES.forEach(p=>dron.remove(p.grupo)); PARTES.length=0; PROPS.length=0; NIEBLAS.length=0; PIEZAS.length=0; GRUPOS=[];
    dron.add(raiz); dron.updateMatrixWorld(true);

    // 1) Clasificar cada malla por su grupo FIG_ y su sistema MOD_.
    const porGrupo=new Map();
    raiz.traverse(n=>{
      if(!n.isMesh) return;
      let nombre=orig(n); if(!/—/.test(nombre)&&n.parent){ const np=orig(n.parent); if(/—/.test(np)) nombre=np; }
      let sis='MOD_OTROS', fig='', a=n.parent;
      while(a&&a!==raiz){ const nm=orig(a); if(!fig&&/^FIG_/i.test(nm)) fig=nm; if(/^MOD_/i.test(nm)){ sis=nm.toUpperCase(); break; } a=a.parent; }
      const num=(fig.match(/^FIG_(\d+)/i)||[])[1]||'';
      const key=sis+'/'+(num?'F'+num:'varios');
      if(!porGrupo.has(key)) porGrupo.set(key,{key, sis, fig:num, nombre:num?fig.replace(/^FIG_\d+\s*/i,'').trim()||('Figura '+num):'Otras piezas de '+nombreSistema(sis), items:[]});
      const wp=new THREE.Vector3(); n.getWorldPosition(wp);
      porGrupo.get(key).items.push({n, nombre, lp:dron.worldToLocal(wp.clone())});
    });

    // 2) Un THREE.Group por grupo, con sus piezas sueltas (ocultas) y sus lotes fusionados.
    const utils=THREE.BufferGeometryUtils;
    porGrupo.forEach(gr=>{
      const c=gr.items.reduce((v,it)=>v.add(it.lp),new THREE.Vector3()).multiplyScalar(1/gr.items.length);
      const g=new THREE.Group(); g.position.copy(c); dron.add(g); g.updateMatrixWorld(true);
      const cache=new Map(), cubos=new Map(); let radio=1e-4;
      gr.items.forEach((it,i)=>{
        const m=it.n; let cl=cache.get(m.material); if(!cl){ cl=m.material.clone(); cache.set(m.material,cl); } m.material=cl;
        g.attach(m); m.updateMatrix();
        const pz=partirNombre(it.nombre), piel=RX_PIEL.test(pz.nombre)||(RX_PIEL_MAT.test(cl.name||'')&&!RX_ESTRUCTURA.test(pz.nombre)&&esLamina(m)), tapa=esTapa(pz.nombre);
        Object.assign(m.userData,{key:gr.key, op:cl.opacity, basePos:m.position.clone(), idx:i, crudo:pz.pn?`${pz.pn} · ${pz.ref}`:pz.base,
          pieza:pz.nombre+(pz.inst?` (${pz.inst})`:''), nombreBase:pz.nombre, pn:pz.pn, ref:pz.ref, inst:pz.inst, piel, tapa});
        if(m.geometry&&!m.geometry.boundingBox) m.geometry.computeBoundingBox();
        const cc=new THREE.Vector3(); if(m.geometry&&m.geometry.boundingBox) m.geometry.boundingBox.getCenter(cc); cc.applyMatrix4(m.matrix);
        m.userData.centro=cc; radio=Math.max(radio,cc.length());
        m.castShadow=false; m.receiveShadow=true; m.visible=false;
        PIEZAS.push({malla:m, nombre:pz.nombre, crudo:m.userData.crudo, key:gr.key});
        // Geometría para el lote: sólo posición y normal, sin índice, ya en coordenadas del grupo.
        if(utils&&m.geometry&&m.geometry.attributes.position){
          let geo=m.geometry.index?m.geometry.toNonIndexed():m.geometry.clone();
          Object.keys(geo.attributes).forEach(k=>{ if(k!=='position'&&k!=='normal') geo.deleteAttribute(k); });
          if(!geo.attributes.normal) geo.computeVertexNormals();
          geo.morphAttributes={}; geo.applyMatrix4(m.matrix);
          const k=cl.uuid+(piel?'|p':'')+(tapa?'|t':''); if(!cubos.has(k)) cubos.set(k,{mat:cl, piel, tapa, geos:[]}); cubos.get(k).geos.push(geo);
        }
      });
      // Despiece interno del grupo: cada pieza se aparta de su centro al abrir el grupo.
      gr.items.forEach(({n:m},i)=>{
        const d=m.userData.centro.clone(), a=i*2.399;
        if(d.lengthSq()<1e-8) d.set(Math.cos(a)*.6,.5,Math.sin(a)*.6); else d.normalize().addScaledVector(V(Math.cos(a),Math.sin(a*1.7),Math.sin(a)),.18);
        m.userData.dirP=d.normalize(); m.userData.distP=gr.items.length>1?(.12+m.userData.centro.length()*.55):0;
      });
      const lotes=[];
      cubos.forEach(cu=>{
        let geo=null; try{ geo=utils.mergeBufferGeometries(cu.geos,false); }catch(e){ geo=null; }
        if(!geo) return;
        const lote=new THREE.Mesh(geo, cu.mat); lote.castShadow=true; lote.receiveShadow=true;
        lote.userData={key:gr.key, lote:true, piel:cu.piel, tapa:cu.tapa, op:cu.mat.opacity};
        g.add(lote); lotes.push(lote);
      });
      // Si la fusión falló (geometrías incompatibles), el grupo se dibuja con sus piezas sueltas.
      if(!lotes.length) gr.items.forEach(({n})=>n.visible=true);
      const entrada={key:gr.key, sis:gr.sis, fig:gr.fig, nombre:gr.nombre, g, base:c.clone(), mallas:gr.items.map(x=>x.n), lotes, sinLotes:!lotes.length};
      GRUPOS.push(entrada);
      PARTES.push({key:gr.key, nombre:gr.nombre, grupo:g, base:c.clone(), dir:V(0,1,0), dist:0, objs:[g], offset:new THREE.Vector3()});
      // El eje de la hélice es el del cigüeñal: el eje longitudinal del avión (+Z del archivo),
      // con la actitud en tierra aplicada. La forma de una bipala retorcida no lo define bien.
      if(gr.sis==='MOD_HELICE'){ const h=montarHelice(g, entrada, new THREE.Vector3(0,0,1).applyQuaternion(raiz.quaternion).normalize()); if(h) PROPS.push(h); }
    });

    // 3) Direcciones del despiece: los sistemas se apartan del centro del avión y, dentro de cada
    //    sistema, los grupos se apartan del centro del sistema.
    const centroSis={};
    GRUPOS.forEach(gr=>{ (centroSis[gr.sis]=centroSis[gr.sis]||{v:new THREE.Vector3(),n:0}); centroSis[gr.sis].v.add(gr.base); centroSis[gr.sis].n++; });
    Object.values(centroSis).forEach(o=>o.v.multiplyScalar(1/o.n));
    GRUPOS.forEach(gr=>{
      const cs=centroSis[gr.sis].v;
      const ds=cs.clone(); ds.y+=.35; if(ds.lengthSq()<.02) ds.set(0,1,0); gr.dirSis=ds.normalize(); gr.distSis=.9;
      const df=gr.base.clone().sub(cs); df.y+=.05; if(df.lengthSq()<.004) df.set(0,1,0); gr.dirFig=df.normalize(); gr.distFig=.5;
    });
    _verClic++; aplicarInterior();
    dron.visible=true; raiz.parent&&dron.remove(raiz);
    _clic=null; _clicN=-1;
    intro=1; explode=0; introVuelo=0; introExplode=0; volando=false; objetivoExplode=null;
    colorear(); resaltar(); pintarDetalle(); pintarLista(); if($cargando.isConnected) $cargando.remove();
    const nSis=new Set(GRUPOS.map(g=>g.sis)).size;
    primerFotograma=true;
    toast(`${MODELO_3D} cargado · ${nSis} sistemas · ${GRUPOS.length} grupos · ${PIEZAS.length.toLocaleString('es')} piezas`);
  }

  function ubicarAvion(){
    // Tres fases: sistemas (0-40 %), grupos (40-70 %) y cada pieza (70-100 %).
    const e1=Math.min(1,explode/.4), e2=Math.min(1,Math.max(0,(explode-.4)/.3)), e3=Math.min(1,Math.max(0,(explode-.7)/.3));
    const piezas=e3>.001;
    if(piezas!==MODO_PIEZAS){ MODO_PIEZAS=piezas; aplicarInterior(); }
    const camLocal=dron.worldToLocal(camera.position.clone());
    GRUPOS.forEach(gr=>{
      const pos=gr.base.clone().addScaledVector(gr.dirSis,gr.distSis*e1).addScaledVector(gr.dirFig,gr.distFig*e2);
      const abierto=GRUPO_ABIERTO===gr;
      if(abierto&&focoProg>0){ const hacia=camLocal.clone().sub(pos).normalize(); pos.addScaledVector(hacia,.5*focoProg); }
      gr.g.position.copy(pos);
      const ep=Math.round(Math.max(e3, abierto?focoProg:0)*200)/200;
      if(gr._ep!==ep){ gr._ep=ep; gr.mallas.forEach(n=>{ const u=n.userData; if(u.basePos) n.position.copy(u.basePos).addScaledVector(u.dirP,u.distP*ep); }); }
    });
  }

  function clicablesAvion(){
    if(_clicAv&&_clicAvVer===_verClic) return _clicAv;
    const a=[];
    GRUPOS.forEach(gr=>{
      if(gr===GRUPO_ABIERTO||gr.sinLotes||MODO_PIEZAS) gr.mallas.forEach(n=>{ if(n.visible) a.push(n); });
      else gr.lotes.forEach(l=>{ if(l.visible) a.push(l); });
    });
    _clicAv=a; _clicAvVer=_verClic; return a;
  }

  function aplicarInterior(){
    GRUPOS.forEach(gr=>{
      const abierto=gr===GRUPO_ABIERTO;
      const oculta=u=>(VER_INTERIOR&&u.piel)||(SIN_TAPAS&&u.tapa);
      gr.lotes.forEach(l=>l.visible=!abierto&&!MODO_PIEZAS&&!oculta(l.userData));
      gr.mallas.forEach(n=>n.visible=(abierto||gr.sinLotes||MODO_PIEZAS)&&!oculta(n.userData));
    });
    _verClic++;
  }

  function abrirGrupo(key){
    const gr=GRUPOS.find(x=>x.key===key); if(!gr) return;
    if(GRUPO_ABIERTO&&GRUPO_ABIERTO!==gr) cerrarGrupo(true);
    GRUPO_ABIERTO=gr; PIEZA=null; SEL=null; SIS_ABIERTOS.add(gr.sis); SISTEMA_SEL=gr.sis;
    aplicarInterior(); intro=0;
    document.getElementById('btnVolver').style.display='inline-block';
    etiqueta.innerHTML=`${escapar(gr.nombre)}<small>${escapar(nombreSistema(gr.sis))}${gr.fig?' · Fig. '+gr.fig:''} · ${gr.mallas.length} piezas</small>`;
    resaltar(); pintarDetalle(); pintarLista();
  }
  function cerrarGrupo(silencioso){
    if(!GRUPO_ABIERTO) return;
    const gr=GRUPO_ABIERTO; GRUPO_ABIERTO=null; PIEZA=null; gr._ep=-1;
    aplicarInterior();
    if(!silencioso){ resaltar(); pintarDetalle(); pintarLista(); }
  }

  function pintarTipAvion(m){
    const u=m.userData, gr=GRUPOS.find(x=>x.key===u.key);
    if(u.lote){
      tip.innerHTML=`<div class="tip3d-tit">${escapar(gr?gr.nombre:'')}</div>
        <div class="tip3d-sub">${escapar(nombreSistema(gr&&gr.sis))}${gr&&gr.fig?' · Fig. '+gr.fig:''} · ${gr?gr.mallas.length:0} piezas</div>
        <div class="tip3d-pie">Clic para abrir el grupo y ver sus piezas.</div>`;
      return;
    }
    tip.innerHTML=`<div class="tip3d-tit">${escapar(u.pieza)}</div>
      <div class="tip3d-sub">${escapar(gr?gr.nombre:'')} · <span class="codigo">${escapar(u.pn||'')}</span>${u.ref?' · '+escapar(u.ref):''}</div>
      <div class="tip3d-pie">Clic para inspeccionar la pieza.</div>`;
  }

  // Piezas de un grupo, juntando las repetidas (×4 pernos).
  function repetidasDe(gr){
    const m=new Map();
    gr.mallas.forEach(n=>{ const u=n.userData, k=u.crudo; if(!m.has(k)) m.set(k,{nombre:u.nombreBase, pn:u.pn, ref:u.ref, mallas:[]}); m.get(k).mallas.push(n); });
    return [...m.values()].sort((a,b)=>{ const ia=parseInt((a.ref.split('-')[1]||'0'),10), ib=parseInt((b.ref.split('-')[1]||'0'),10); return (ia-ib)||a.nombre.localeCompare(b.nombre,'es'); });
  }
  let _cicloAv={};
  function elegirRepetida(x){
    const id=x.pn+'|'+x.ref; _cicloAv[id]=((_cicloAv[id]||0)+(PIEZA&&x.mallas.includes(PIEZA)?1:0))%x.mallas.length;
    const m=x.mallas[_cicloAv[id]]; if(!m.visible) return toast('Esa pieza es un revestimiento: desactiva «Quitar cubiertas» para verla.');
    aislarMaterial(m); PIEZA=m; SEL=null; etiquetarPieza(); resaltar(); pintarDetalle(); pintarLista();
    if(x.mallas.length>1) toast(`${x.nombre} · ejemplar ${_cicloAv[id]+1} de ${x.mallas.length}`);
  }

  // La lámina del catálogo del fabricante de ese grupo (la misma que en Diagramas).
  function htmlLaminaAvion(gr){
    const fig=parseInt(gr.fig,10); if(!fig) return '';
    const ls=(DIAGRAMAS||[]).filter(m=>m.figura===fig); if(!ls.length) return '';
    return `<div class="mini-diag-titulo" style="margin-top:12px">Lámina del fabricante · Figura ${fig}</div>
      ${ls.map(m=>`<a href="/diagramas?modelo=${encodeURIComponent(MODELO_3D)}&modulo=${encodeURIComponent(m.clave)}" title="Abrir en Diagramas">
        <div class="mini-diag"><img src="${m.imagen_url}" alt="${escapar(m.nombre)}" loading="lazy"></div></a>`).join('')}
      <div class="mut" style="font-size:12px">Clic en la lámina para abrirla en Diagramas con sus números y la lista de piezas.</div>`;
  }
  function pintarDetalleAvion(el){
    if(PIEZA&&GRUPO_ABIERTO){
      const u=PIEZA.userData, gr=GRUPO_ABIERTO, iguales=gr.mallas.filter(n=>n.userData.crudo===u.crudo).length;
      el.innerHTML=`<h4>${escapar(u.pieza)}</h4>
        <div class="cifras">
          <div class="cifra"><div class="l">Número de parte</div><div class="v codigo" style="font-size:14px">${escapar(u.pn||'—')}</div></div>
          <div class="cifra"><div class="l">Figura · índice</div><div class="v" style="font-size:14px">${escapar(u.ref||'—')}</div></div>
          <div class="cifra"><div class="l">Iguales en el grupo</div><div class="v" style="font-size:14px">${iguales}</div></div>
        </div>
        <div class="mut" style="margin:8px 0 12px">${escapar(nombreSistema(gr.sis))} · ${escapar(gr.nombre)}${u.piel?' · revestimiento':''}</div>
        <div class="nota">Esta pieza aún no tiene vida útil cargada en el catálogo de mantenimiento del avión.</div>
        <div class="acciones"><button class="btn secundario" id="avVolverGrupo">Volver al grupo</button></div>`;
      el.querySelector('#avVolverGrupo').onclick=()=>volver();
      return;
    }
    if(GRUPO_ABIERTO){
      const gr=GRUPO_ABIERTO, rep=repetidasDe(gr);
      el.innerHTML=`<h4>${escapar(gr.nombre)}</h4>
        <div class="mut" style="margin-bottom:10px">${escapar(nombreSistema(gr.sis))}${gr.fig?' · Figura '+gr.fig+' del catálogo Cessna P694-12':''} · ${gr.mallas.length} piezas (${rep.length} distintas)</div>
        <div class="pieza-lista" style="max-height:${AMPLIO?'52vh':'320px'}">${rep.map((x,i)=>`<div class="item clk" data-ri="${i}" style="padding:6px 8px">
          <div class="cuerpo"><b style="font-size:12px">${escapar(x.nombre)}</b><div class="mut"><span class="codigo">${escapar(x.pn)}</span>${x.ref?' · '+escapar(x.ref):''}${x.mallas.length>1?' · ×'+x.mallas.length:''}</div></div></div>`).join('')}</div>
        ${htmlLaminaAvion(gr)}
        <div class="acciones" style="margin-top:10px"><button class="btn secundario" id="avCerrarGrupo">Cerrar grupo</button></div>`;
      el.querySelectorAll('[data-ri]').forEach(it=>it.onclick=()=>elegirRepetida(rep[Number(it.dataset.ri)]));
      el.querySelector('#avCerrarGrupo').onclick=()=>volver();
      return;
    }
    if(SISTEMA_SEL){
      const gs=GRUPOS.filter(g=>g.sis===SISTEMA_SEL).sort((a,b)=>(parseInt(a.fig,10)||999)-(parseInt(b.fig,10)||999));
      const n=gs.reduce((a,g)=>a+g.mallas.length,0);
      el.innerHTML=`<h4>${escapar(nombreSistema(SISTEMA_SEL))}</h4>
        <div class="mut" style="margin-bottom:10px">${nGrupos(gs.length)} · ${n.toLocaleString('es')} piezas. Elige un grupo para ver sus piezas.</div>
        <div class="lista">${gs.map(g=>`<div class="item clk" data-gk="${escapar(g.key)}" style="cursor:pointer"><div class="cuerpo"><b>${g.fig?'Fig. '+g.fig+' · ':''}${escapar(g.nombre)}</b><div class="mut">${g.mallas.length} piezas</div></div><span class="mut" aria-hidden="true">›</span></div>`).join('')}</div>
        <div class="acciones" style="margin-top:10px"><button class="btn secundario" id="avTodos">Todos los sistemas</button></div>`;
      el.querySelectorAll('[data-gk]').forEach(it=>it.onclick=()=>abrirGrupo(it.dataset.gk));
      el.querySelector('#avTodos').onclick=()=>volver();
      return;
    }
    const sis=[...new Set(GRUPOS.map(g=>g.sis))].sort(ordenSis);
    el.innerHTML=`<h4>${escapar(MODELO_3D)} · despiece por sistemas</h4>
      <div class="mut" style="margin-bottom:10px">${nGrupos(GRUPOS.length)} y ${PIEZAS.length.toLocaleString('es')} piezas. Elige un sistema o haz clic en una parte del avión.</div>
      <div class="lista">${sis.map(s=>{ const gs=GRUPOS.filter(g=>g.sis===s), n=gs.reduce((a,g)=>a+g.mallas.length,0);
        return `<div class="item clk" data-sis="${s}" style="cursor:pointer"><div class="cuerpo"><b>${escapar(nombreSistema(s))}</b><div class="mut">${nGrupos(gs.length)} · ${n.toLocaleString('es')} piezas</div></div><span class="mut" aria-hidden="true">›</span></div>`; }).join('')}</div>`;
    el.querySelectorAll('[data-sis]').forEach(it=>it.onclick=()=>elegirSistema(it.dataset.sis));
  }

  // Elegir un sistema desde el panel o el árbol: se resalta en el 3D y el panel pasa a sus grupos.
  function elegirSistema(s){
    if(GRUPO_ABIERTO) cerrarGrupo(true);
    PIEZA=null; SEL=null; SISTEMA_SEL=s; SIS_ABIERTOS.add(s); intro=0;
    document.getElementById('btnVolver').style.display='inline-block';
    const gs=GRUPOS.filter(g=>g.sis===s), n=gs.reduce((a,g)=>a+g.mallas.length,0);
    etiqueta.classList.remove('ver');
    toast(`${nombreSistema(s)} · ${nGrupos(gs.length)} · ${n.toLocaleString('es')} piezas`);
    resaltar(); pintarDetalle(); pintarLista();
  }

  let MODO_EXP='sistema', FILTRO_SIS=null, LIM_PIEZAS=150, _indice=null;
  // Todas las piezas distintas del avión (mismo nombre y número de parte dentro de un grupo),
  // ordenadas por nombre. Se arma una vez: son ~9.000 mallas.
  function indicePiezas(){
    if(_indice) return _indice;
    const m=new Map();
    GRUPOS.forEach(gr=>gr.mallas.forEach(n=>{ const u=n.userData, k=gr.key+'|'+u.crudo;
      if(!m.has(k)) m.set(k,{nombre:u.nombreBase||u.pieza, pn:u.pn, ref:u.ref, gr, mallas:[],
        busca:((u.nombreBase||'')+' '+(u.pn||'')+' '+(u.ref||'')+' '+gr.nombre).toLowerCase()});
      m.get(k).mallas.push(n); }));
    _indice=[...m.values()].sort((a,b)=>a.nombre.localeCompare(b.nombre,'es'));
    return _indice;
  }
  // Lámina del fabricante dentro del propio explorador: se abre y se cierra aquí mismo, marca el
  // número de la pieza elegida y, al pulsar un número, elige esa pieza en el avión. «Ampliar» la
  // abre a pantalla completa encima del visor, sin salir de la página.
  let LAM_VER=false, LAM_HOJA=0;
  const indiceDeRef=ref=>{ const m=/-(\d+)/.exec(ref||''); return m?Number(m[1]):null; };
  function laminasDe(gr){
    const f=parseInt(gr.fig,10); if(f) return (DIAGRAMAS||[]).filter(m=>m.figura===f);
    if(!gr.clave) return [];
    try{ return (DIAGRAMAS||[]).filter(m=>MESH2MOD[gr.clave]===m.clave||conjuntosDeModulo(m.clave).includes(gr.clave)); }catch(e){ return []; }
  }
  function htmlLaminaIntegrada(gr, x){
    const ls=laminasDe(gr); if(!ls.length) return '';
    const icLam='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="2.8" width="13" height="14.4" rx="1.8"/><circle cx="8" cy="8" r="1.6"/><path d="M9.2 9.2 12.6 12.6M6.5 13.8h3"/></svg>';
    if(!LAM_VER) return `<button type="button" class="exp-lam-btn" id="expLamVer">${icLam}<span><b>Lámina del fabricante</b><small>${gr.fig?'Fig. '+escapar(String(gr.fig))+' · ':''}${ls.length>1?ls.length+(gr.fig?' hojas':' láminas')+' · ':''}números clicables</small></span><span class="exp-ir">›</span></button>`;
    const m=ls[Math.min(LAM_HOJA,ls.length-1)], nSel=x?indiceDeRef(x.ref):null;
    return `<div class="exp-lamina">
      <div class="exp-lam-cab"><b>${gr.fig?'Lámina · Fig. '+escapar(String(gr.fig)):escapar(m.nombre)}</b>
        ${ls.length>1?ls.map((h,i)=>`<button type="button" class="exp-hoja ${i===Math.min(LAM_HOJA,ls.length-1)?'activo':''}" data-hoja="${i}">${gr.fig?'Hoja '+(i+1):escapar(h.nombre)}</button>`).join(''):''}
        <button type="button" class="exp-lam-acc" id="expLamAmpliar" title="Ver la lámina a pantalla completa">Ampliar</button>
        <button type="button" class="exp-lam-acc x" id="expLamCerrar" title="Ocultar la lámina" aria-label="Ocultar la lámina">✕</button></div>
      <div class="mini-diag" id="expLam"><img src="${m.imagen_url}" alt="${escapar(m.nombre)}">${(m.hotspots||[]).map(h=>`<div class="punto mini ${h.n===nSel?'sel':''}" data-n="${h.n}" style="left:${h.x}%;top:${h.y}%">${h.n}</div>`).join('')}</div>
      <div class="exp-lam-pie">${nSel!=null?`La pieza elegida es el número <b>${nSel}</b>. `:''}Pulsa un número para ${gr.fig?'verlo en el '+nomEquipo():'ver la pieza y su código'}.</div></div>`;
  }
  function enlazarLamina(cont, gr, rep){
    const ver=cont.querySelector('#expLamVer'); if(ver) ver.onclick=()=>{ LAM_VER=true; LAM_HOJA=0; pintarLista(); };
    const cer=cont.querySelector('#expLamCerrar'); if(cer) cer.onclick=()=>{ LAM_VER=false; pintarLista(); };
    cont.querySelectorAll('[data-hoja]').forEach(b=>b.onclick=()=>{ LAM_HOJA=Number(b.dataset.hoja); pintarLista(); });
    const ls=laminasDe(gr), m=ls[Math.min(LAM_HOJA,ls.length-1)];
    const amp=cont.querySelector('#expLamAmpliar'); if(amp&&m) amp.onclick=()=>abrirLightbox(m);
    cont.querySelectorAll('#expLam .punto').forEach(p=>p.onclick=e=>{ e.stopPropagation();
      const n=Number(p.dataset.n), r=rep.find(r=>indiceDeRef(r.ref)===n);
      if(r){ if(PIEZA&&r.mallas.includes(PIEZA)) volver(); else elegirRepetida(r); return; }
      const pz=m&&(m.partes||[]).find(q=>q.n===n);
      toast(pz?`${n}. ${pz.nombre_es||nombrePiezaCatalogo(pz)} · ${pz.codigo}${gr.fig?' · no está modelada en 3D':''}`:`Número ${n} sin datos`);
      cont.querySelectorAll('#expLam .punto').forEach(q=>q.classList.toggle('sel', q===p)); });
  }
  // Datos de una pieza del 3D: el número de parte y la referencia sólo los traen los aviones.
  function htmlDatosPieza(x, k){
    const d=[];
    if(x.pn) d.push(`<div><span>Número de parte</span><b class="codigo">${escapar(x.pn)}</b></div>`);
    if(x.ref) d.push(`<div><span>Figura · índice</span><b>${escapar(x.ref)}</b></div>`);
    d.push(`<div><span>Ejemplar</span><b>${k} de ${x.mallas.length}</b></div>`);
    return `<div class="exp-datos">${d.join('')}</div>`;
  }
  const inicialGrupo=g=>{ const m=/\bM([1-4])\b/.exec(g.nombre); return m?'M'+m[1]:(g.nombre||'?').slice(0,2); };
  // Piezas con vida útil (catálogo de mantenimiento del equipo elegido) de un conjunto del 3D.
  function compsDe(g){ if(!g||!g.clave) return []; return COMPS.filter(c=>(c.mesh||CLAVE2MESH[c.clave])===g.clave); }
  function peorNivel(gs){ let nv='ok'; gs.forEach(g=>compsDe(g).forEach(c=>{ if(ORDEN[c.nivel]<ORDEN[nv]) nv=c.nivel; })); return nv; }
  let MANT_TODAS=false;
  function htmlMantenimiento(gr){
    if(!EQUIPO) return gr?'':`<div class="exp-sec">Mantenimiento</div><div class="exp-ayuda">Elige un ${nomEquipo()} arriba para ver el desgaste de sus piezas.</div>`;
    let lista=gr?compsDe(gr):COMPS.slice();
    if(!lista.length) return '';
    lista.sort((a,b)=>(ORDEN[a.nivel]-ORDEN[b.nivel])||(b.pct-a.pct));
    const conAlerta=lista.filter(c=>c.nivel!=='ok');
    const ver=gr||MANT_TODAS?lista:conAlerta;
    const titulo=gr?`Mantenimiento de este conjunto · ${lista.length}`:`Mantenimiento de ${escapar(EQUIPO.nombre)} · ${conAlerta.length} con alerta`;
    return `<div class="exp-sec">${titulo}</div>`+(ver.length?ver.map(c=>`<button type="button" class="exp-fila exp-comp ${SEL&&SEL.id===c.id?'sel':''}" data-cid="${c.id}">
        <span class="punto ${c.nivel}"></span><span class="exp-cuerpo"><b>${escapar(c.nombre)}</b><span>${usoPieza(c)} · ${c.pct}%</span></span>
        <span style="width:56px;flex:none">${barra(c)}</span></button>`).join(''):`<div class="exp-ayuda">Ninguna pieza con alerta.</div>`)
      +(!gr&&lista.length>conAlerta.length?`<button type="button" class="btn secundario peq" id="expMantTodas" style="width:100%;margin-top:4px">${MANT_TODAS?'Ver sólo las que tienen alerta':'Ver las '+lista.length+' piezas con vida útil'}</button>`:'');
  }
  function enlazarMantenimiento(cont){
    cont.querySelectorAll('[data-cid]').forEach(el=>el.onclick=()=>{ const c=COMPS.find(x=>String(x.id)===el.dataset.cid); if(!c) return;
      if(SEL&&SEL.id===c.id){ SEL=null; resaltar(); pintarLista(); return; }
      const gr=GRUPOS.find(g=>g.clave&&g.clave===(c.mesh||CLAVE2MESH[c.clave]));
      if(gr&&GRUPO_ABIERTO!==gr) abrirGrupo(gr.key);
      PIEZA=null; seleccionar(c); });
    const t=cont.querySelector('#expMantTodas'); if(t) t.onclick=()=>{ MANT_TODAS=!MANT_TODAS; pintarLista(); };
    const x=cont.querySelector('#expCompX'); if(x) x.onclick=()=>{ SEL=null; resaltar(); pintarLista(); };
    const cam=cont.querySelector('#expCambio'); if(cam) cam.onclick=async()=>{ const c=SEL; if(!c||!EQUIPO) return;
      if(!confirm(`¿Registrar el cambio de "${c.nombre}" en ${EQUIPO.nombre}? Sus horas de uso vuelven a cero.`)) return;
      await api('/api/mantenimientos',{method:'POST',body:{equipo_id:EQUIPO.id, componente_id:c.id, tipo:'preventivo', descripcion:`Cambio de ${c.nombre}`}}); toast('Cambio registrado'); await cargarEquipo(EQUIPO.id); };
    const aj=cont.querySelector('#expAjuste'); if(aj) aj.onclick=async()=>{ const c=SEL; if(!c||!EQUIPO) return;
      const v=prompt(`Horas de uso actuales de "${c.nombre}":`, c.horas_uso); if(v===null||isNaN(Number(v))) return;
      await api(`/api/componentes/${c.id}`,{method:'PUT',body:{horas_uso:Number(v)}}); toast('Horas ajustadas'); await cargarEquipo(EQUIPO.id); };
  }
  // Ficha de una pieza con vida útil: desgaste, plazo y acciones (cambio y ajuste de horas).
  function htmlFichaComponente(){
    const c=SEL&&SEL.id?COMPS.find(x=>x.id===SEL.id)||SEL:null; if(!c) return '';
    return `<div class="exp-ficha"><button type="button" class="exp-ficha-x" id="expCompX" title="Cerrar (Esc)" aria-label="Cerrar">✕</button>
      <div class="exp-sup">Pieza con vida útil · ${escapar(c.modulo||'')}</div><b class="exp-nombre">${escapar(c.nombre)}</b>
      <div style="margin:2px 0 4px">${barra(c)}</div><div class="exp-nota" style="margin-top:0">${c.pct}% de la vida útil · ${tagNivel(c.nivel)}</div>
      <div class="exp-datos" style="margin-top:8px"><div><span>${midePorCalendario(c)?'En servicio':'Horas de uso'}</span><b>${midePorCalendario(c)?fmt(c.meses_en_servicio):fmt(c.horas_uso)}</b></div>
        <div><span>Vida útil</span><b>${vidaPieza(c)}</b></div><div><span>Plazo</span><b>${excesoPieza(c)}</b></div></div>
      ${c.nota?`<div class="exp-nota">${escapar(c.nota)}</div>`:''}
      <div class="exp-nota">Último cambio: <b>${c.fecha_ultimo_cambio?fmtFecha(c.fecha_ultimo_cambio):'ninguno (pieza original)'}</b></div>
      <div class="exp-botones"><button type="button" class="btn peq ${c.nivel==='ok'?'secundario':'verde'}" id="expCambio">Registrar cambio</button>
        <button type="button" class="btn peq secundario" id="expAjuste">Ajustar horas</button></div></div>`;
  }
  function fichaPiezaSel(){
    if(!PIEZA||!GRUPO_ABIERTO) return '';
    const x=repetidasDe(GRUPO_ABIERTO).find(r=>r.mallas.includes(PIEZA)); if(!x) return '';
    const gr=GRUPO_ABIERTO;
    return `<div class="exp-ficha"><button type="button" class="exp-ficha-x" id="expSoltar" title="Cerrar la pieza (Esc)" aria-label="Cerrar">✕</button><div class="exp-sup">${escapar(nombreSistema(gr.sis))} › ${gr.fig?'Fig. '+gr.fig+' · ':''}${escapar(gr.nombre)}</div>
      <b class="exp-nombre">${escapar(x.nombre)}</b>
      ${htmlDatosPieza(x, x.mallas.indexOf(PIEZA)+1)}
      <div class="exp-botones"><button type="button" class="btn peq secundario" id="expVerGrupo">Ver su grupo</button></div></div>`;
  }
  function irA(nivel, sis){
    if(nivel==='pieza') return;
    if(nivel==='grupo'){ if(PIEZA) volver(); return; }
    if(nivel==='sistema'){ if(GRUPO_ABIERTO||PIEZA) elegirSistema(sis); return; }
    if(GRUPO_ABIERTO) cerrarGrupo(true);
    SISTEMA_SEL=null; SIS_ABIERTOS.clear(); volver();
  }
  function pintarArbolAvion(){
    const cont=document.getElementById('lista'), q=BUSCA.trim().toLowerCase();
    document.getElementById('piezasConteo').textContent=`· ${nGrupos(GRUPOS.length)} · ${PIEZAS.length.toLocaleString('es')} piezas`;
    // Dos formas de recorrer el despiece: «Por sistema» (avión › sistema › grupo › pieza) y «Por
    // pieza» (todas las piezas distintas de la A a la Z, filtrables por sistema). Escribir en el
    // buscador pasa solo a «Por pieza».
    const icSis='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="5.6" height="5.6" rx="1.4"/><rect x="11.4" y="3" width="5.6" height="5.6" rx="1.4"/><rect x="3" y="11.4" width="5.6" height="5.6" rx="1.4"/><rect x="11.4" y="11.4" width="5.6" height="5.6" rx="1.4"/></svg>';
    const icPie='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M7.5 5h9.5M7.5 10h9.5M7.5 15h9.5"/><circle cx="4" cy="5" r=".9"/><circle cx="4" cy="10" r=".9"/><circle cx="4" cy="15" r=".9"/></svg>';
    const enPieza=MODO_EXP==='pieza'||!!q;
    const pestanas=`<div class="exp-tabs" role="tablist" aria-label="Cómo recorrer el despiece">
        <button type="button" role="tab" aria-selected="${!enPieza}" data-modo="sistema" class="${!enPieza?'activo':''}">
          <span class="exp-tab-ic">${icSis}</span><span class="exp-tab-tx"><b>Por sistema</b><small>${ES_AVION?'Ala, motor, tren…':'Propulsión, aspersión…'}</small></span></button>
        <button type="button" role="tab" aria-selected="${enPieza}" data-modo="pieza" class="${enPieza?'activo':''}">
          <span class="exp-tab-ic">${icPie}</span><span class="exp-tab-tx"><b>Por pieza</b><small>Lista de la A a la Z</small></span></button></div>`;
    const enlazarPestanas=()=>cont.querySelectorAll('[data-modo]').forEach(b=>b.onclick=()=>{
      MODO_EXP=b.dataset.modo; LIM_PIEZAS=150;
      if(MODO_EXP==='sistema'&&BUSCA){ BUSCA=''; const bp=document.getElementById('buscaPieza'); if(bp) bp.value=''; }
      pintarLista(); });
    if(q||MODO_EXP==='pieza'){
      const flechaP='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.5 6.5 10l5.5 5.5"/></svg>';
      const todas=indicePiezas();
      const filtradas=todas.filter(x=>(!FILTRO_SIS||x.gr.sis===FILTRO_SIS)&&(!q||x.busca.includes(q)));
      const sis=[...new Set(GRUPOS.map(g=>g.sis))].sort(ordenSis);
      let html=pestanas+`<div class="exp-chips"><button type="button" data-fs="" class="${!FILTRO_SIS?'activo':''}">Todos</button>${sis.map(x=>
        `<button type="button" data-fs="${x}" class="${FILTRO_SIS===x?'activo':''}">${escapar(nombreSistema(x))}</button>`).join('')}</div>
        ${PIEZA?`<div class="exp-cab"><button type="button" class="exp-atras-grande" id="expAtrasP" title="Volver a la lista (Esc)">${flechaP}<span>Atrás</span><small>la lista</small></button><div class="exp-tit"></div></div>`:''}
        ${fichaPiezaSel()}
        <div class="exp-ayuda">${filtradas.length.toLocaleString('es')} piezas distintas${q?` con «${escapar(BUSCA)}»`:''}${FILTRO_SIS?' en '+escapar(nombreSistema(FILTRO_SIS)):''} · clic para verla en el ${nomEquipo()}</div>`;
      let letra='';
      filtradas.slice(0,LIM_PIEZAS).forEach((x,i)=>{
        const l=(x.nombre[0]||'#').toUpperCase();
        if(!q&&l!==letra){ letra=l; html+=`<div class="exp-letra">${escapar(l)}</div>`; }
        const es=PIEZA&&x.mallas.includes(PIEZA);
        html+=`<button type="button" class="exp-fila pieza ${es?'sel':''}" data-pi="${i}"><span class="exp-cuerpo"><b>${escapar(x.nombre)}</b>
          <span>${x.pn?`<span class="codigo">${escapar(x.pn)}</span> · `:''}${escapar(nombreSistema(x.gr.sis))} › ${x.gr.fig?'Fig. '+x.gr.fig:escapar(x.gr.nombre)}${x.mallas.length>1?' · ×'+x.mallas.length:''}</span></span>
          <span class="exp-ir">${es?'✓':'›'}</span></button>`;
      });
      if(!filtradas.length) html+=`<div class="empty" style="padding:20px">Ninguna pieza coincide.</div>`;
      if(filtradas.length>LIM_PIEZAS) html+=`<button type="button" class="btn secundario peq" id="expMas" style="width:100%;margin-top:6px">Mostrar ${Math.min(300,filtradas.length-LIM_PIEZAS)} más (de ${(filtradas.length-LIM_PIEZAS).toLocaleString('es')} restantes)</button>`;
      const arriba=cont.scrollTop; cont.innerHTML=html; enlazarPestanas(); cont.scrollTop=arriba;
      const vg=cont.querySelector('#expVerGrupo'); if(vg) vg.onclick=()=>{ MODO_EXP='sistema'; BUSCA=''; const bp=document.getElementById('buscaPieza'); if(bp) bp.value=''; pintarLista(); };
      const so=cont.querySelector('#expSoltar'); if(so) so.onclick=()=>volver();
      const ap=cont.querySelector('#expAtrasP'); if(ap) ap.onclick=()=>volver();
      cont.querySelectorAll('[data-fs]').forEach(b=>b.onclick=()=>{ FILTRO_SIS=b.dataset.fs||null; LIM_PIEZAS=150; pintarLista(); cont.scrollTop=0; });
      const mas=cont.querySelector('#expMas'); if(mas) mas.onclick=()=>{ LIM_PIEZAS+=300; pintarLista(); };
      cont.querySelectorAll('[data-pi]').forEach(el=>el.onclick=()=>{ const x=filtradas[Number(el.dataset.pi)];
        if(PIEZA&&x.mallas.includes(PIEZA)){ volver(); return; }
        abrirGrupo(x.gr.key); const r=repetidasDe(GRUPO_ABIERTO).find(r=>r.mallas.includes(x.mallas[0])); if(r) elegirRepetida(r); });
      return;
    }
    // Explorador por niveles, uno por pantalla: avión › sistema › grupo › pieza. Arriba, un botón
    // para volver y el título del nivel; lo elegido se deselecciona pulsándolo otra vez, con
    // «Quitar selección» o con Esc. La ficha de la pieza aparece aquí mismo, encima de su grupo.
    const gr=GRUPO_ABIERTO, sisSel=gr?gr.sis:SISTEMA_SEL;
    const flecha='<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4.5 6.5 10l5.5 5.5"/></svg>';
    const completo = ES_AVION?'Avión completo':'Dron completo';
    const titulo = gr ? `${gr.fig?'Fig. '+gr.fig+' · ':''}${gr.nombre}` : sisSel ? nombreSistema(sisSel) : completo;
    const nivelSup = gr ? nombreSistema(gr.sis) : sisSel ? completo : '';
    const destino = PIEZA ? 'la lista del grupo' : nivelSup;
    let html=pestanas+`<div class="exp-cab">
        ${sisSel?`<button type="button" class="exp-atras-grande" id="expAtras" title="Volver (Esc)">${flecha}<span>Atrás</span><small>${escapar(destino)}</small></button>`:''}
        <div class="exp-tit"><div class="exp-sup">${sisSel?escapar(nivelSup):escapar(MODELO_3D||'')+' · despiece'}</div><b>${escapar(titulo)}</b></div>
        ${sisSel?'<button type="button" class="exp-limpiar" id="expLimpiar" title="Quitar la selección y ver el avión completo">✕</button>':''}
      </div>`;
    if(!sisSel){
      const sis=[...new Set(GRUPOS.map(g=>g.sis))].sort(ordenSis);
      html+=`<div class="exp-ayuda">Elige un sistema o haz clic en una parte del ${nomEquipo()}.</div><div class="exp-mosaico">`+sis.map(x=>{
        const gs=GRUPOS.filter(g=>g.sis===x), n=gs.reduce((a,g)=>a+g.mallas.length,0), nv=peorNivel(gs);
        return `<button type="button" class="exp-tesela" data-sisc="${x}"><b>${nv!=='ok'?`<i class="exp-nivel ${nv}" title="${NIVEL_TXT[nv]}"></i>`:''}${escapar(nombreSistema(x))}</b><span>${nGrupos(gs.length)}</span><span>${n.toLocaleString('es')} piezas</span></button>`; }).join('')+`</div>`;
    } else if(!gr){
      const gs=GRUPOS.filter(g=>g.sis===sisSel).sort((a,b)=>(parseInt(a.fig,10)||999)-(parseInt(b.fig,10)||999));
      html+=`<div class="exp-ayuda">${nGrupos(gs.length)}. Elige uno para ver sus piezas.</div>`+gs.map(g=>{ const nv=peorNivel([g]);
        return `<button type="button" class="exp-fila" data-gk="${escapar(g.key)}"><span class="exp-fig ${nv}">${g.fig||escapar(inicialGrupo(g))}</span>
          <span class="exp-cuerpo"><b>${escapar(g.nombre)}</b><span>${g.mallas.length} piezas${compsDe(g).length?' · '+compsDe(g).length+' con vida útil':''}</span></span><span class="exp-ir">›</span></button>`; }).join('');
    } else {
      const rep=repetidasDe(gr);
      const x=PIEZA&&rep.find(r=>r.mallas.includes(PIEZA));
      if(x){
        const u=PIEZA.userData, k=x.mallas.indexOf(PIEZA)+1;
        html+=`<div class="exp-ficha"><button type="button" class="exp-ficha-x" id="expSoltar" title="Cerrar la pieza (Esc)" aria-label="Cerrar">✕</button>
          <div class="exp-sup">Pieza seleccionada</div><b class="exp-nombre">${escapar(x.nombre)}</b>
          ${htmlDatosPieza(x, k)}
          ${u.piel?'<div class="exp-nota">Cubierta: con «Quitar cubiertas» se oculta.</div>':''}
          ${x.mallas.length>1?'<div class="exp-botones"><button type="button" class="btn peq secundario" id="expSiguiente">Siguiente ejemplar</button></div>':''}</div>`;
      }
      html+=htmlFichaComponente();
      html+=htmlLaminaIntegrada(gr, x);
      html+=htmlMantenimiento(gr);
      html+=`<div class="exp-ayuda">${rep.length} piezas distintas · ${gr.mallas.length} en total</div>`+rep.map((r,i)=>{
        const es=x===r;
        return `<button type="button" class="exp-fila pieza ${es?'sel':''}" data-gi="${i}"><span class="exp-cuerpo"><b>${escapar(r.nombre)}</b>
          <span>${r.pn?`<span class="codigo">${escapar(r.pn)}</span>`:''}${r.ref?' · '+escapar(r.ref):''}${r.mallas.length>1?(r.pn?' · ':'')+'×'+r.mallas.length:''}${!r.pn&&r.mallas.length<2?'1 unidad':''}</span></span>
          <span class="exp-ir">${es?'✓':''}</span></button>`; }).join('');
    }
    if(!sisSel) html+=htmlMantenimiento(null);
    cont.innerHTML=html; enlazarPestanas(); enlazarMantenimiento(cont);
    const atras=cont.querySelector('#expAtras'); if(atras) atras.onclick=()=>volver();
    const limpiar=cont.querySelector('#expLimpiar'); if(limpiar) limpiar.onclick=()=>irA('avion');
    cont.querySelectorAll('[data-sisc]').forEach(el=>el.onclick=()=>elegirSistema(el.dataset.sisc));
    cont.querySelectorAll('[data-gk]').forEach(el=>el.onclick=()=>abrirGrupo(el.dataset.gk));
    if(gr){ const rep=repetidasDe(gr);
      cont.querySelectorAll('[data-gi]').forEach(el=>el.onclick=()=>{ const r=rep[Number(el.dataset.gi)];
        if(PIEZA&&r.mallas.includes(PIEZA)) volver(); else elegirRepetida(r); });
      const sig=cont.querySelector('#expSiguiente'); if(sig) sig.onclick=()=>{ const r=rep.find(r=>r.mallas.includes(PIEZA)); if(r) elegirRepetida(r); };
      const sol=cont.querySelector('#expSoltar'); if(sol) sol.onclick=()=>volver();
      enlazarLamina(cont, gr, rep); }
    if(!PIEZA) cont.scrollTop=0;
    // Se desplaza sólo la lista, nunca la página: scrollIntoView movía toda la pantalla.
    const selEl=cont.querySelector('.item.sel, .exp-fila.sel');
    // Con la lámina abierta, lo que importa está arriba (ficha y lámina): no se salta a la fila.
    // Al elegir una pieza o una pieza con vida útil, su ficha (arriba) es lo que hay que ver.
    if(GRUPO_ABIERTO&&(PIEZA||SEL)) cont.scrollTop=0;
    else if(selEl){ const top=selEl.offsetTop-cont.offsetTop; if(top<cont.scrollTop||top>cont.scrollTop+cont.clientHeight-40) cont.scrollTop=Math.max(0,top-60); }
  }

  // Acceso de diagnóstico desde la consola del navegador (sólo lectura).
  window.__visor3d={get grupos(){return GRUPOS;}, get helices(){return PROPS;}, partes:PARTES, dron, scene, camera,
    // Dibuja n fotogramas aunque la pestaña esté oculta (pruebas automáticas).
    fotogramas(n){ for(let i=0;i<(n||1);i++){ primerFotograma=true; animar(); } }};
  (async function arrancar(){
    const elegido=await elegirModelo3D();
    await cargarEquipos();
    if(elegido) cargarModeloReal();
    else $cargando.textContent='Todavía no hay ningún archivo 3D cargado. Los despieces de cada modelo están en Diagramas.';
  })();
})();
