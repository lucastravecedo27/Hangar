// Láminas oficiales de despiece, de cualquier modelo de la flota: números clickeables sobre la
// imagen, zoom/arrastre y modo de ajuste.
//
// Cada modelo trae sus propias láminas y su propio despiece, y no todos vienen igual de
// completos: las del T50 son los planos CAD numerados de DJI y las del T100 son sus fotos
// oficiales de materiales, que no llevan números impresos. Por eso el modo de ajuste (colocar
// a mano el número de cada pieza sobre la lámina) es parte del flujo normal, no un arreglo.
(function(){
  const $diag=document.getElementById('diagrama'), $lienzo=document.getElementById('lienzo'), $img=document.getElementById('imagen'), $puntos=document.getElementById('puntos');
  let EQUIPOS=[], MODELOS=[], MODELO=null, MODULOS=[], MOD=null, SEL=null, EDITAR=false, HOTS=[], SISTEMA=null;
  let zoom=1, px=0, py=0, imgW=1, imgH=1;

  // El nombre en castellano viene precalculado en diagramas.json (mismo traductor, hecho una
  // vez), para que la pieza se llame igual aquí, en el buscador de la orden y en la bitácora.
  const _traducir = window.traducirPieza;
  const traducir = (p)=> (p && typeof p === 'object')
    ? (p.nombre_es || _traducir(p) || p.nombre_en || '')
    : (_traducir(p) || p || '');

  // ---- Zoom / pan ----
  function aplicar(){ $lienzo.style.transform=`translate(${px}px,${py}px) scale(${zoom})`; document.getElementById('zoomTxt').textContent=Math.round(zoom*100)+' %'; $puntos.querySelectorAll('.punto').forEach(p=>p.style.transform=`translate(-50%,-50%) scale(${1/zoom})`); }
  function ajustar(){ const W=$diag.clientWidth, H=$diag.clientHeight; zoom=Math.min(W/imgW, H/imgH)*.96; px=(W-imgW*zoom)/2; py=(H-imgH*zoom)/2-14; aplicar(); }
  function zoomEn(f, cx, cy){ const nz=Math.max(.15, Math.min(6, zoom*f)); px=cx-(cx-px)*(nz/zoom); py=cy-(cy-py)*(nz/zoom); zoom=nz; aplicar(); }
  $diag.addEventListener('wheel', e=>{ e.preventDefault(); const r=$diag.getBoundingClientRect(); zoomEn(e.deltaY<0?1.15:1/1.15, e.clientX-r.left, e.clientY-r.top); }, {passive:false});
  document.getElementById('zMas').onclick=()=>zoomEn(1.25,$diag.clientWidth/2,$diag.clientHeight/2);
  document.getElementById('zMenos').onclick=()=>zoomEn(1/1.25,$diag.clientWidth/2,$diag.clientHeight/2);
  document.getElementById('zReset').onclick=ajustar;
  window.addEventListener('resize', ajustar);

  let arr=null, movido=0, arrastrandoPunto=null;
  function posImagen(e){ const r=$img.getBoundingClientRect(); return {x:(e.clientX-r.left)/r.width*100, y:(e.clientY-r.top)/r.height*100}; }
  $diag.addEventListener('pointerdown', e=>{
    if(e.target.closest('.controles')||e.target.closest('.ayuda-edicion')) return;
    const punto=e.target.closest('.punto');
    if(punto && EDITAR){ arrastrandoPunto=HOTS[Number(punto.dataset.i)]; movido=0; $diag.setPointerCapture(e.pointerId); return; }
    arr={x:e.clientX-px, y:e.clientY-py}; movido=0; $diag.classList.add('agarrando'); $diag.setPointerCapture(e.pointerId);
  });
  $diag.addEventListener('pointermove', e=>{
    if(arrastrandoPunto){ movido+=1; const p=posImagen(e); arrastrandoPunto.x=Math.max(0,Math.min(100,p.x)); arrastrandoPunto.y=Math.max(0,Math.min(100,p.y)); pintarPuntos(); return; }
    if(!arr) return; movido+=Math.abs(e.movementX)+Math.abs(e.movementY); px=e.clientX-arr.x; py=e.clientY-arr.y; aplicar();
  });
  $diag.addEventListener('pointerup', e=>{
    if(arrastrandoPunto){ arrastrandoPunto=null; return; }
    const fueClic = movido<5; arr=null; $diag.classList.remove('agarrando');
    if(!fueClic) return;
    const punto=e.target.closest('.punto');
    if(punto){ seleccionar(Number(punto.dataset.n)); return; }
    if(EDITAR && SEL!=null && e.target===$img || (EDITAR && SEL!=null && e.target.id==='puntos')){ const p=posImagen(e); HOTS.push({n:SEL,x:+p.x.toFixed(2),y:+p.y.toFixed(2)}); pintarPuntos(); pintarLista(); toast(`Número ${SEL} colocado`); }
  });
  $puntos.addEventListener('dblclick', e=>{ const punto=e.target.closest('.punto'); if(punto && EDITAR){ HOTS.splice(Number(punto.dataset.i),1); pintarPuntos(); pintarLista(); } });

  // ---- Edición ----
  document.getElementById('chkEditar').addEventListener('change', e=>{
    EDITAR=e.target.checked; $diag.classList.toggle('editando',EDITAR);
    document.getElementById('editAcciones').style.display=EDITAR?'inline-flex':'none';
    document.getElementById('ayudaEdicion').style.display=EDITAR?'block':'none';
  });
  document.getElementById('btnGuardar').onclick=async()=>{ await api(`/api/diagramas/${MODELO.clave}/${MOD.clave}/hotspots`,{method:'PUT',body:HOTS}); MOD.hotspots=HOTS.map(h=>({...h})); MOD.hotspots_personalizados=true; toast('Posiciones guardadas'); };
  document.getElementById('btnRestablecer').onclick=async()=>{
    if(!await confirmar({titulo:'Restablecer posiciones', mensaje:`Se descartan los números que hayas colocado a mano en «${escapar(MOD.nombre)}».`, aceptar:'Restablecer', peligro:true})) return;
    await api(`/api/diagramas/${MODELO.clave}/${MOD.clave}/hotspots`,{method:'DELETE'}); await cargarModulos(); toast('Posiciones restablecidas');
  };

  // ---- Datos ----
  async function arrancar(){
    const [datos, equipos] = await Promise.all([api('/api/modelos'), api('/api/equipos')]);
    EQUIPOS = equipos;
    MODELOS = datos.modelos.filter(m=>m.tiene_diagramas);
    const $mod=document.getElementById('selModelo');
    // El modelo lo manda la URL, si no el del dron que se venía mirando, si no el de casa.
    const eqURL = EQUIPOS.find(e=>String(e.id)===String(paramURL('equipo')));
    const eqModelo = eqURL && (MODELOS.find(m=>m.clave===eqURL.modelo) ? eqURL.modelo : null);
    const inicial = paramURL('modelo') || eqModelo || datos.predeterminado;
    // Drones y aviones en el mismo selector, cada uno en su grupo.
    const opcion=m=>`<option value="${m.clave}" ${m.clave===inicial?'selected':''}>${escapar(m.nombre)} · ${m.n_despiece} piezas</option>`;
    const grupo=(tipo,titulo)=>{ const ms=MODELOS.filter(m=>(m.tipo_activo||m.tipo||'dron')===tipo);
      return ms.length?`<optgroup label="${titulo}">${ms.map(opcion).join('')}</optgroup>`:''; };
    $mod.innerHTML = (grupo('dron','Drones')+grupo('avion','Aviones')) || '<option value="">Sin diagramas cargados</option>';
    $mod.addEventListener('change', ()=>{ MOD=null; pintarEquipos(); cargarModulos(); });
    document.getElementById('selEquipo').addEventListener('change', cargarModulos);
    pintarEquipos();
    await cargarModulos();
  }

  const esAvion=()=>{ const m=modeloElegido(); return !!m && (m.tipo_activo||m.tipo)==='avion'; };
  function modeloElegido(){
    const c=document.getElementById('selModelo').value;
    return MODELOS.find(m=>m.clave===c) || MODELOS[0] || null;
  }

  function pintarEquipos(){
    // Sólo tiene sentido cruzar una lámina con las horas de un equipo de ESE modelo (un avión
    // de la empresa usa la copia de la plantilla, así que también vale su plantilla).
    const m=modeloElegido(); const sel=document.getElementById('selEquipo');
    const suyos=EQUIPOS.filter(e=>!m || e.modelo===m.clave || (e.plantilla && e.plantilla===m.clave));
    sel.innerHTML = `<option value="">${esAvion()?'Sin avión':'Sin dron'} · sólo el catálogo</option>` +
      (suyos.length ? opcionesEquipos(suyos, paramURL('equipo')||suyos[0].id).replace('selected','selected') : '');
    if(!suyos.length) sel.value='';
  }

  async function cargarModulos(){
    const eq=document.getElementById('selEquipo').value;
    const clave=document.getElementById('selModelo').value;
    const datos=await api(`/api/diagramas?modelo=${encodeURIComponent(clave)}`+(eq?`&equipo_id=${eq}`:''));
    MODELO=datos.modelo; MODULOS=datos.laminas;
    if(!MODULOS.length){ document.getElementById('modulos').innerHTML=''; return; }
    pintarSelectorModulos();
    const inicial = (MOD && MODULOS.some(m=>m.clave===MOD.clave)) ? MOD.clave
                  : (paramURL('modulo') || moduloDePieza(paramURL('pieza')) || laminaDeEntrada());
    abrir(inicial);
  }

  function pintarSelectorModulos(){
    // El T100 trae 30 láminas de cuatro sistemas distintos (aeronave, esparcido, elevación,
    // control remoto): en una sola fila de botones no se encuentra nada, así que van agrupadas.
    const sistemas=[...new Set(MODULOS.map(m=>m.sistema))];
    if(MODULOS.length>40){
      // El catálogo de un avión trae cientos de figuras: primero el sistema y luego sus láminas.
      const actual=(MOD&&MOD.sistema)||SISTEMA||sistemas[0]; SISTEMA=actual;
      document.getElementById('modulos').innerHTML=`<div class="grupo-modulos">
          <select id="selSistema" style="min-width:190px">${sistemas.map(s=>`<option ${s===actual?'selected':''}>${escapar(s)}</option>`).join('')}</select>
          ${MODULOS.filter(m=>m.sistema===actual).map(m=>`<button class="pillbtn ${MOD&&MOD.clave===m.clave?'active':''}" data-m="${m.clave}"><i class="${m.nivel}"></i>${escapar(m.nombre)}</button>`).join('')}
        </div>`;
      document.getElementById('selSistema').onchange=e=>{ SISTEMA=e.target.value; const pri=MODULOS.find(m=>m.sistema===SISTEMA); abrir(pri.clave); };
      document.querySelectorAll('#modulos [data-m]').forEach(b=>b.onclick=()=>abrir(b.dataset.m));
      return;
    }
    document.getElementById('modulos').innerHTML = sistemas.map(s=>`<div class="grupo-modulos">
        ${sistemas.length>1?`<span class="etiqueta-sistema">${escapar(s)}</span>`:''}
        ${MODULOS.filter(m=>m.sistema===s).map(m=>`<button class="pillbtn ${MOD&&MOD.clave===m.clave?'active':''}" data-m="${m.clave}"><i class="${m.nivel}"></i>${escapar(m.nombre)}</button>`).join('')}
      </div>`).join('');
    document.querySelectorAll('#modulos [data-m]').forEach(b=>b.onclick=()=>abrir(b.dataset.m));
  }
  // Con qué lámina se abre la pantalla. La primera hoja del Excel no siempre es la más útil
  // (la del T100 es el tanque suelto, con una sola pieza), así que se entra por la lámina más
  // completa del primer sistema, que es la que da idea de todo el despiece.
  function laminaDeEntrada(){
    const primero = MODULOS[0].sistema;
    return MODULOS.filter(m=>m.sistema===primero)
                  .reduce((a,b)=>(b.partes||[]).length>(a.partes||[]).length?b:a).clave;
  }

  function moduloDePieza(clave){ if(!clave) return null; const m=MODULOS.find(m=>(m.piezas_catalogo||[]).includes(clave)); return m?m.clave:null; }

  function abrir(clave){
    const antes=MOD&&MOD.sistema;
    MOD=MODULOS.find(m=>m.clave===clave)||MODULOS[0]; SEL=null; HOTS=(MOD.hotspots||[]).map(h=>({...h}));
    if(MODULOS.length>40 && MOD.sistema!==antes){ SISTEMA=MOD.sistema; pintarSelectorModulos(); }
    document.querySelectorAll('#modulos [data-m]').forEach(b=>b.classList.toggle('active', b.dataset.m===MOD.clave));
    $img.onload=()=>{ imgW=$img.naturalWidth; imgH=$img.naturalHeight; $lienzo.style.width=imgW+'px'; $lienzo.style.height=imgH+'px'; ajustar(); pintarPuntos(); };
    $img.src=MOD.imagen_url;
    pintarPuntos(); pintarLista(); pintarDetalle(); pintarEstado();
  }

  function pintarPuntos(){
    $puntos.innerHTML=HOTS.map((h,i)=>`<div class="punto ${MOD.nivel} ${SEL===h.n?'sel':''}" data-n="${h.n}" data-i="${i}" style="left:${h.x}%;top:${h.y}%;transform:translate(-50%,-50%) scale(${1/zoom})" title="Pieza ${h.n}">${h.n}</div>`).join('');
  }
  function seleccionar(n){ SEL=n; pintarPuntos(); pintarLista(); pintarDetalle(); const el=document.querySelector(`#lista .item[data-n="${n}"]`); if(el) el.scrollIntoView({block:'nearest'}); }

  function pintarLista(){
    const q=document.getElementById('buscar').value.trim().toLowerCase();
    const con=new Set(HOTS.map(h=>h.n));
    const partes=(MOD.partes||[]).filter(p=>!q || [p.n,p.codigo,p.nombre_en,traducir(p),...(p.variantes||[]).map(v=>v.codigo+' '+v.nombre_es)].join(' ').toLowerCase().includes(q));
    document.getElementById('partesConteo').textContent=`· ${partes.length}`;
    document.getElementById('lista').innerHTML=partes.map(p=>`<div class="item clk ${SEL===p.n?'sel':''} ${con.has(p.n)?'':'sinpunto'}" data-n="${p.n}">
      <span class="num">${p.n}</span>
      <div class="cuerpo"><b>${escapar(traducir(p))}</b><div class="mut">${p.nombre_en?escapar(p.nombre_en)+' · ':''}<span class="codigo">${escapar(p.codigo)}</span>${p.auxiliar?' · aux.':''}${(p.variantes||[]).length?` · +${p.variantes.length} variante${p.variantes.length>1?'s':''}`:''}</div></div>
      ${con.has(p.n)?'':'<span class="tag gray" title="Sin número ubicado en el diagrama">sin punto</span>'}</div>`).join('') || '<div class="empty" style="padding:20px">Sin piezas.</div>';
    document.querySelectorAll('#lista .item').forEach(el=>el.onclick=()=>seleccionar(Number(el.dataset.n)));
  }
  document.getElementById('buscar').addEventListener('input', pintarLista);

  function pintarDetalle(){
    const el=document.getElementById('detalle');
    const p=(MOD.partes||[]).find(x=>x.n===SEL);
    if(!p){
      const n=(MOD.partes||[]).length;
      // Las láminas del T50 son planos CAD con los números impresos; las del T100 son las fotos
      // de materiales de DJI, que no los llevan. Sin números no hay nada que clicar sobre la
      // imagen, así que conviene decir dónde está la pieza y cómo colocarlos.
      const ayuda = HOTS.length
        ? 'Haz clic en un número del diagrama o en una pieza de la lista.'
        : esAvion() ? 'Aún no hay números ubicados en esta figura: busca la pieza en la lista de la derecha, '
          + 'o activa «Ajustar posiciones» y haz clic sobre su número en el dibujo.'
        : 'Esta lámina es la foto oficial de materiales y no trae números impresos: '
          + 'busca la pieza en la lista de la derecha, o activa «Ajustar posiciones» para ir '
          + 'colocando su número sobre la foto.';
      el.innerHTML=`<h4>${escapar(MOD.nombre)}</h4><div class="mut">${escapar(MODELO?MODELO.nombre:'')} · ${escapar(MOD.zona||'')} · ${n} pieza${n===1?'':'s'} · ${HOTS.length} número${HOTS.length===1?'':'s'} ubicado${HOTS.length===1?'':'s'}${MOD.hotspots_personalizados?' (ajustados)':''}</div><div class="empty" style="padding:18px 10px">${ayuda}</div>`; return; }
    const veces=HOTS.filter(h=>h.n===p.n).length;
    el.innerHTML=`<div class="mut">${escapar(MOD.zona||MOD.nombre)} · pieza n.º ${p.n}</div>
      <h4>${escapar(traducir(p))}</h4>
      <div class="mut">${[p.nombre_en,p.nombre_zh].filter(Boolean).map(escapar).join(' · ')}</div>
      <div class="cifras" style="grid-template-columns:1fr 1fr 1fr">
        <div class="cifra"><div class="l">${esAvion()?'Número de parte':'Código DJI'}</div><div class="v" style="font-size:13px;font-family:ui-monospace,Menlo,monospace">${escapar(p.codigo)}</div></div>
        <div class="cifra"><div class="l">Zona</div><div class="v" style="font-size:13px">${escapar(MOD.zona||MOD.nombre)}</div></div>
        <div class="cifra"><div class="l">${p.cantidad?'Cantidad':'Tipo'}</div><div class="v" style="font-size:13px">${p.cantidad?escapar(String(p.cantidad))+(p.auxiliar?' · fijación':''):(p.auxiliar?'Material auxiliar':'Pieza principal')}</div></div>
      </div>
      ${(p.variantes||[]).length?`<div class="mut" style="margin:10px 0 4px">Otras versiones de este número (lado, serie o equipo):</div>
        <table class="tabla" style="width:100%;font-size:12.5px"><tbody>${p.variantes.map(v=>`<tr><td class="codigo" style="font-family:ui-monospace,Menlo,monospace">${escapar(v.codigo)}</td><td>${escapar(v.nombre_es||v.nombre_en)}</td><td class="mut">${escapar(String(v.cantidad||''))}</td></tr>`).join('')}</tbody></table>`:''}
      <div class="mut">${veces?`Ubicada ${veces} vez${veces>1?'es':''} en el diagrama.`:'Sin número ubicado: activa "Ajustar posiciones" y haz clic sobre el número en el diagrama.'}</div>
      <div class="acciones" style="margin-top:12px"><a class="btn secundario peq" href="/actividades">Crear actividad de compra</a></div>`;
  }

  // Cómo se cuenta el desgaste de una pieza. No todos los modelos traen lo mismo: del T50 DJI
  // publica vida útil en horas de vuelo y del T100 sólo plazos de calendario, así que la ficha
  // dice con qué se está midiendo en vez de enseñar un «0 / 0 h» que no significa nada.
  function plazoTxt(c){
    if(c.sin_plazo) return 'Sin plazo publicado · revisión diaria';
    return `${usoPieza(c)} · ${c.pct}% · ${NIVEL_TXT[c.nivel]}`;
  }

  function pintarEstado(){
    const card=document.getElementById('cardEstado'); const lista=MOD.estado_piezas||[];
    card.style.display=lista.length?'block':'none';
    document.getElementById('estadoPiezas').innerHTML=lista.map(c=>`<div class="item"><span class="punto ${c.nivel}"></span>
      <div class="cuerpo"><b>${escapar(c.nombre)}</b><div class="mut">${plazoTxt(c)}</div>${c.sin_plazo?'':barra(c)}</div>
      <button class="btn peq ${c.nivel==='ok'?'secundario':'verde'}" data-cid="${c.id}" data-nombre="${escapar(c.nombre)}">Cambiar</button></div>`).join('');
    document.querySelectorAll('#estadoPiezas [data-cid]').forEach(b=>b.onclick=async()=>{
      const eq=document.getElementById('selEquipo').value;
      if(!eq){ toast(esAvion()?'Elige primero el avión al que se le cambia la pieza':'Elige primero el dron al que se le cambia la pieza'); return; }
      if(!await confirmar({titulo:'Registrar cambio de pieza',
        mensaje:`Se anota el cambio de «${escapar(b.dataset.nombre)}» y sus contadores (horas y meses en servicio) vuelven a cero.`,
        aceptar:'Registrar cambio'})) return;
      await api('/api/mantenimientos',{method:'POST',body:{equipo_id:eq, componente_id:b.dataset.cid, tipo:'preventivo', descripcion:`Cambio de ${b.dataset.nombre}`}});
      toast('Cambio registrado'); await cargarModulos();
    });
  }

  arrancar();
})();
