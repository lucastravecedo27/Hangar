// Sistema de interfaz compartido: ventanas flotantes, paneles laterales, confirmaciones
// y edición en línea con guardado automático. Depende de app.js (toast, escapar, api).

(function(){
  const abiertos = [];

  function bloquearFondo(){ document.body.classList.add('sin-scroll'); }
  function liberarFondo(){ if(!abiertos.length) document.body.classList.remove('sin-scroll'); }

  // ---- Ventana flotante ----
  // ventana({titulo, subtitulo, cuerpo, pie, ancho:'ancha'|'angosta', alAbrir, alCerrar})
  window.ventana = function(opciones){
    const velo = document.createElement('div');
    velo.className = 'velo';
    velo.innerHTML = `
      <div class="ventana ${opciones.ancho||''}" role="dialog" aria-modal="true">
        <div class="ventana-cab">
          <div>
            <h2>${opciones.titulo||''}</h2>
            ${opciones.subtitulo?`<p>${opciones.subtitulo}</p>`:''}
          </div>
          <button class="cerrar" type="button" aria-label="Cerrar">✕</button>
        </div>
        <div class="ventana-cuerpo">${opciones.cuerpo||''}</div>
        ${opciones.pie?`<div class="ventana-pie">${opciones.pie}</div>`:''}
      </div>`;
    document.body.appendChild(velo);
    abiertos.push(velo);
    bloquearFondo();
    requestAnimationFrame(()=>velo.classList.add('ver'));

    const ctrl = {
      raiz: velo,
      $: (sel)=>velo.querySelector(sel),
      $$: (sel)=>Array.from(velo.querySelectorAll(sel)),
      // Devuelve una promesa que se resuelve cuando el velo ya salió del DOM. Encadenar
      // `await v.cerrar()` antes de abrir otra cosa evita dos velos superpuestos, que se ven
      // como una pantalla doblemente oscurecida y difuminada.
      cerrar(){
        if(velo._cerrando) return velo._cerrando;
        velo.classList.remove('ver');
        const i = abiertos.indexOf(velo); if(i>=0) abiertos.splice(i,1);
        velo._cerrando = new Promise(listo=>setTimeout(()=>{
          velo.remove(); liberarFondo();
          if(opciones.alCerrar) opciones.alCerrar();
          listo();
        }, 200));
        return velo._cerrando;
      },
    };
    velo.querySelector('.cerrar').addEventListener('click', ctrl.cerrar);
    velo.addEventListener('mousedown', e=>{ if(e.target===velo && opciones.cerrarAlTocarFuera!==false) ctrl.cerrar(); });
    velo.addEventListener('keydown', e=>{ if(e.key==='Escape'){ e.stopPropagation(); ctrl.cerrar(); } });
    velo.setAttribute('tabindex','-1');
    velo.focus();
    const primero = velo.querySelector('input:not([type=hidden]),select,textarea');
    if(primero) setTimeout(()=>primero.focus(), 60);
    if(opciones.alAbrir) opciones.alAbrir(ctrl);
    return ctrl;
  };

  // ---- Confirmación (sustituye a confirm() del navegador) ----
  window.confirmar = function({titulo, mensaje, aceptar='Aceptar', peligro=false}){
    return new Promise(resolve=>{
      const v = ventana({
        titulo, ancho:'angosta',
        cuerpo:`<p style="font-size:13.5px;line-height:1.55;color:var(--ink2)">${mensaje||''}</p>`,
        pie:`<div class="der"><button class="btn secundario" data-no>Cancelar</button>
             <button class="btn ${peligro?'rojo':''}" data-si>${escapar(aceptar)}</button></div>`,
        alCerrar:()=>resolve(false),
      });
      v.$('[data-no]').onclick = ()=>v.cerrar();
      // La promesa se resuelve con el primer valor: pulsar «aceptar» gana al cierre.
      v.$('[data-si]').onclick = ()=>{ resolve(true); v.cerrar(); };
    });
  };

  // ---- Panel lateral deslizante ----
  window.panelLateral = function({titulo, subtitulo, cuerpo, pie, alCerrar}){
    const velo = document.createElement('div');
    velo.className = 'velo';
    velo.style.padding = '0';
    velo.style.justifyContent = 'flex-end';
    const panel = document.createElement('aside');
    panel.className = 'panel-flotante';
    panel.innerHTML = `
      <div class="cab">
        <div><h2>${titulo||''}</h2>${subtitulo?`<p>${subtitulo}</p>`:''}</div>
        <button class="cerrar" type="button" aria-label="Cerrar"
          style="margin-left:auto;flex:none;width:32px;height:32px;border-radius:10px;border:none;
                 background:rgba(115,122,134,.12);color:var(--ink2);cursor:pointer">✕</button>
      </div>
      <div class="cuerpo">${cuerpo||''}</div>
      ${pie?`<div class="pie">${pie}</div>`:''}`;
    document.body.appendChild(velo);
    document.body.appendChild(panel);
    abiertos.push(velo);
    bloquearFondo();
    requestAnimationFrame(()=>{ velo.classList.add('ver'); panel.classList.add('ver'); });

    const ctrl = {
      raiz: panel,
      $: (s)=>panel.querySelector(s),
      $$: (s)=>Array.from(panel.querySelectorAll(s)),
      cerrar(){
        if(velo._cerrando) return velo._cerrando;
        panel.classList.remove('ver'); velo.classList.remove('ver');
        const i = abiertos.indexOf(velo); if(i>=0) abiertos.splice(i,1);
        velo._cerrando = new Promise(listo=>setTimeout(()=>{
          panel.remove(); velo.remove(); liberarFondo();
          if(alCerrar) alCerrar();
          listo();
        }, 260));
        return velo._cerrando;
      },
    };
    panel.querySelector('.cerrar').onclick = ctrl.cerrar;
    velo.onmousedown = ctrl.cerrar;
    // El botón de cerrar vive en el panel, no en el velo; sin esto la tecla Escape no lo
    // encontraba y el panel lateral sólo se podía cerrar con el ratón.
    velo._cerrar = ctrl.cerrar;
    return ctrl;
  };

  document.addEventListener('keydown', e=>{
    if(e.key === 'Escape' && abiertos.length){
      const ultimo = abiertos[abiertos.length-1];
      if(ultimo._cerrar){ ultimo._cerrar(); return; }
      const boton = ultimo.querySelector('.cerrar');
      if(boton) boton.click();
    }
  });
})();


// ===== Edición en línea con guardado automático =====
// Cada celda editable lleva data-campo y data-id; al salir del campo (o tras 700 ms de pausa)
// se manda un PUT con ese único campo. El color del borde dice en qué punto va el guardado.
(function(){
  function marcar(celda, clase){
    celda.classList.remove('guardando','guardado','error');
    if(clase) celda.classList.add(clase);
    if(clase === 'guardado') setTimeout(()=>celda.classList.remove('guardado'), 1400);
  }

  window.edicionEnLinea = function(contenedor, {url, alGuardar, alError, validar}={}){
    let pendiente = null;

    async function guardar(celda){
      const id = celda.dataset.id, campo = celda.dataset.campo;
      const valor = celda.tagName === 'SELECT' ? celda.value : (celda.value ?? celda.textContent).trim();
      if(celda.dataset.original === valor) return;
      if(validar){
        const problema = validar(campo, valor);
        if(problema){ marcar(celda,'error'); toast(problema); celda.value = celda.dataset.original; return; }
      }
      marcar(celda, 'guardando');
      try{
        const r = await api(url(id), {method:'PUT', body:{[campo]: valor}});
        celda.dataset.original = valor;
        marcar(celda, 'guardado');
        if(alGuardar) alGuardar(r, celda);
      }catch(err){
        marcar(celda, 'error');
        celda.value = celda.dataset.original ?? '';
        toast(err.message);
        if(alError) alError(err, celda);
      }
    }

    contenedor.addEventListener('focusin', e=>{
      const celda = e.target.closest('.celda'); if(!celda) return;
      celda.dataset.original = celda.value ?? celda.textContent;
    });
    contenedor.addEventListener('input', e=>{
      const celda = e.target.closest('.celda'); if(!celda) return;
      clearTimeout(pendiente);
      pendiente = setTimeout(()=>guardar(celda), 900);
    });
    contenedor.addEventListener('change', e=>{
      const celda = e.target.closest('.celda'); if(!celda) return;
      clearTimeout(pendiente); guardar(celda);
    });
    contenedor.addEventListener('focusout', e=>{
      const celda = e.target.closest('.celda'); if(!celda) return;
      clearTimeout(pendiente); guardar(celda);
    });
    contenedor.addEventListener('keydown', e=>{
      const celda = e.target.closest('.celda'); if(!celda) return;
      if(e.key === 'Escape'){ celda.value = celda.dataset.original ?? ''; celda.blur(); }
      if(e.key === 'Enter' && celda.tagName !== 'TEXTAREA'){ e.preventDefault(); celda.blur(); }
    });
  };
})();


// ===== Utilidades de formato compartidas por los módulos nuevos =====
function fmtDias(d){
  if(d === null || d === undefined) return 'sin ritmo';
  if(d <= 0) return 'ya';
  if(d === 1) return '1 día';
  if(d < 60) return `${d} días`;
  if(d < 730) return `${Math.round(d/30)} meses`;
  return `${(d/365).toFixed(1)} años`;
}

function fmtFechaHora(t){
  if(!t) return '—';
  const f = new Date(t.replace(' ','T') + (t.includes('T')||t.length<=10 ? '' : 'Z'));
  if(isNaN(f)) return t;
  return f.toLocaleString('es-CO', {day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit'});
}

function descargar(url){
  const a = document.createElement('a');
  a.href = url; a.rel = 'noopener';
  document.body.appendChild(a); a.click(); a.remove();
}

// Genera un <select> con las opciones dadas ([{v,t}] o [t,...]).
function opciones(lista, sel){
  return lista.map(o=>{
    const v = (typeof o === 'object') ? o.v : o;
    const t = (typeof o === 'object') ? o.t : o;
    return `<option value="${escapar(v)}" ${String(sel)===String(v)?'selected':''}>${escapar(t)}</option>`;
  }).join('');
}


// ===== Pantalla completa =====
// La app se abre desde el icono del escritorio en modo aplicación (sin barra de direcciones ni
// pestañas). Este botón cubre el resto de casos y permite salir sin tocar el navegador.
(function(){
  const boton = document.getElementById('btnPantallaCompleta');
  if(!boton) return;

  function enPantallaCompleta(){
    return !!(document.fullscreenElement || document.webkitFullscreenElement);
  }
  function pintar(){
    const on = enPantallaCompleta();
    const txt = boton.querySelector('.txt');
    if(txt) txt.textContent = on ? 'Salir de pantalla completa' : 'Pantalla completa';
    boton.title = on ? 'Salir de pantalla completa (F o Esc)' : 'Pantalla completa (F)';
  }
  function alternar(){
    const raiz = document.documentElement;
    if(enPantallaCompleta()){
      (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    } else {
      const pedir = raiz.requestFullscreen || raiz.webkitRequestFullscreen;
      if(pedir) pedir.call(raiz).catch(()=>toast('El navegador no permitió la pantalla completa.'));
      else toast('Este navegador no admite pantalla completa.');
    }
  }

  boton.addEventListener('click', alternar);
  document.addEventListener('fullscreenchange', pintar);
  document.addEventListener('webkitfullscreenchange', pintar);
  // Atajo con «F», salvo mientras se escribe en un campo.
  document.addEventListener('keydown', e=>{
    if(e.key !== 'f' && e.key !== 'F') return;
    if(e.metaKey || e.ctrlKey || e.altKey) return;
    const foco = document.activeElement;
    if(foco && (foco.matches('input,textarea,select') || foco.isContentEditable)) return;
    e.preventDefault(); alternar();
  });
  pintar();
})();


// ===== Buscador de piezas del catálogo =====
// Autocompletado sobre las piezas instaladas en un dron. Se usa siempre que hay que apuntar un
// trabajo contra una pieza concreta: escribir el nombre a mano dejaba la tarea suelta, y al
// cerrar la orden no había a qué reiniciarle las horas.
//
//   buscadorPiezas(campo, {equipoId: ()=>id, alElegir: pieza=>{...}})
//
// Busca desde la tercera letra, sin tildes y por trozos («emp hel» → «Empaque de hélice»).
window.buscadorPiezas = function(campo, {equipoId, alElegir, minimo = 3} = {}){
  const caja = document.createElement('div');
  caja.className = 'bp-sugerencias';
  caja.hidden = true;
  const envoltura = document.createElement('div');
  envoltura.className = 'bp-envoltura';
  campo.parentNode.insertBefore(envoltura, campo);
  envoltura.appendChild(campo);
  envoltura.appendChild(caja);

  let resultados = [], activo = -1, pendiente = null, peticion = 0;

  const idEquipo = ()=> (typeof equipoId === 'function' ? equipoId() : equipoId);

  function cerrar(){ caja.hidden = true; activo = -1; }

  function pintar(){
    if(!resultados.length){
      caja.innerHTML = `<div class="bp-vacio">Ninguna pieza del catálogo coincide con «${escapar(campo.value.trim())}».</div>`;
      caja.hidden = false;
      return;
    }
    caja.innerHTML = resultados.map((p, i)=>`
      <button type="button" class="bp-item ${i===activo?'activo':''}" data-i="${i}">
        <span class="bp-nombre">${escapar(p.nombre)}</span>
        <span class="bp-modulo">${escapar(p.modulo)}${p.codigo?` · <span class="bp-codigo">${escapar(p.codigo)}</span>`:''}${p.auxiliar?' · aux.':''}</span>
        <span class="bp-uso">${p.tipo==='seguimiento' ? usoPieza(p) : 'sin vida útil'}</span>
        ${p.tipo==='seguimiento' ? tagNivel(p.nivel) : '<span class="tag gray">Despiece</span>'}
      </button>`).join('');
    caja.hidden = false;
    caja.querySelectorAll('.bp-item').forEach(b=>{
      // mousedown y no click: el blur del campo cerraría la lista antes de que llegue el click.
      b.addEventListener('mousedown', e=>{ e.preventDefault(); elegir(Number(b.dataset.i)); });
    });
  }

  function elegir(i){
    const pieza = resultados[i];
    if(!pieza) return;
    cerrar();
    if(alElegir) alElegir(pieza);
  }

  async function buscar(){
    const texto = campo.value.trim();
    const equipo = idEquipo();
    if(!equipo || texto.length < minimo){ cerrar(); return; }
    const mio = ++peticion;
    try{
      const datos = await api(`/api/piezas/buscar?equipo_id=${equipo}&q=${encodeURIComponent(texto)}`);
      if(mio !== peticion) return;   // llegó tarde: ya hay una búsqueda más nueva
      resultados = datos; activo = datos.length ? 0 : -1;
      pintar();
    }catch(err){ cerrar(); }
  }

  campo.setAttribute('autocomplete', 'off');
  campo.addEventListener('input', ()=>{ clearTimeout(pendiente); pendiente = setTimeout(buscar, 180); });
  campo.addEventListener('focus', ()=>{ if(resultados.length && campo.value.trim().length >= minimo) pintar(); });
  campo.addEventListener('blur', ()=>setTimeout(cerrar, 120));
  campo.addEventListener('keydown', e=>{
    if(caja.hidden) return;
    if(e.key === 'ArrowDown' || e.key === 'ArrowUp'){
      e.preventDefault();
      activo = Math.max(0, Math.min(resultados.length - 1, activo + (e.key === 'ArrowDown' ? 1 : -1)));
      pintar();
      caja.querySelector('.bp-item.activo')?.scrollIntoView({block:'nearest'});
    } else if(e.key === 'Enter' && activo >= 0){
      e.preventDefault(); elegir(activo);
    } else if(e.key === 'Escape'){
      e.stopPropagation(); cerrar();
    }
  });

  return { cerrar, limpiar(){ campo.value = ''; resultados = []; cerrar(); } };
};

// Motivos de una reparación (mismos valores que core/db.py MOTIVOS).
const MOTIVOS_TXT = {desgaste:'Desgaste / vida útil', 'daño':'Daño o rotura',
                     preventivo:'Preventivo', inspeccion:'Inspección', otro:'Otro'};

// Ficha de la pieza elegida en el buscador.
// Una pieza «de seguimiento» lleva horas y su cambio las reinicia solo. Una pieza del despiece
// no tiene vida útil en el catálogo DJI, así que se ofrece elegir a mano qué pieza con horas
// del mismo módulo se reinicia (o ninguna).
function tarjetaPieza(p){
  if(p.tipo === 'despiece'){
    const opciones = (p.piezas_modulo || []).map(c=>
      `<option value="${c.componente_id}">${escapar(c.nombre)} · ${usoPieza(c)}</option>`).join('');
    return `<div class="pieza-elegida">
      <b>${escapar(p.nombre)}</b>
      <span class="mut">${escapar(p.modulo)}</span>
      <span class="bp-codigo">${escapar(p.codigo || '')}</span>
      <span class="tag gray">Despiece</span>
      <button type="button" class="btn-icono" data-quitar title="Quitar la pieza elegida">✕</button>
      ${opciones ? `<div class="aviso-adelanto">El fabricante no le asigna vida útil, así que no tiene horas propias.
          Si el cambio deja como nueva una pieza que sí se cronometra, elígela y su contador vuelve a cero:
          <select data-reinicio style="margin-top:6px;width:100%">
            <option value="">— No reiniciar horas —</option>${opciones}</select></div>`
        : `<div class="aviso-adelanto">Este módulo no tiene piezas con vida útil, así que no hay horas que reiniciar.
            El cambio queda igualmente en la bitácora con su código.</div>`}
    </div>`;
  }
  const pct = Math.round(p.pct ?? (p.vida_util_horas ? p.horas_uso / p.vida_util_horas * 100 : 0));
  const adelantado = pct < 75;
  return `<div class="pieza-elegida">
    <b>${escapar(p.nombre)}</b>
    <span class="mut">${escapar(p.modulo)}</span>
    <span>${usoPieza(p)} · ${pct} %</span>
    ${tagNivel(p.nivel)}
    <button type="button" class="btn-icono" data-quitar title="Quitar la pieza elegida">✕</button>
    ${adelantado ? `<div class="aviso-adelanto">Le queda vida útil (${restaPieza(p)}).
      Si se cambia igualmente, el contador de esta pieza arranca de cero como repuesto nuevo.</div>` : ''}
  </div>`;
}

// Tarea de «cambiar pieza»: enganchada al componente real del dron cuando lo hay, y siempre con
// el nombre y el código exactos del catálogo.
// `componenteReinicio` es el id que eligió el usuario en la ficha de una pieza del despiece.
function tareaDeCambio(p, motivo, componenteReinicio){
  const razon = motivo === 'daño' ? 'por daño o rotura' : 'por desgaste';
  const esSeguimiento = p.tipo !== 'despiece';
  const horas = esSeguimiento ? ` — ${usoPieza(p)}` : '';
  const codigo = p.codigo ? ` [${p.codigo}]` : '';
  return {
    descripcion: `Cambiar ${p.nombre} (${p.modulo})${codigo} ${razon}${horas}`,
    origen: 'manual', motivo,
    componente_id: esSeguimiento ? p.componente_id : (componenteReinicio || null),
    pieza_clave: p.clave || null,
    codigo_pieza: p.codigo || null,
    nombre_pieza: p.nombre,
    nivel: esSeguimiento ? p.nivel : null,
    nota: p.nota || null,
  };
}
