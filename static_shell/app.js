// Utilidades compartidas por todas las pantallas.
function hora(){ const h=document.getElementById('hora'); if(h) h.textContent=new Date().toLocaleTimeString('es-CO',{hour:'2-digit',minute:'2-digit'}); }
hora(); setInterval(hora, 30000);

function toast(msg){
  const t=document.getElementById('toast'); if(!t) return;
  t.textContent=msg; t.classList.add('show');
  clearTimeout(t._tm); t._tm=setTimeout(()=>t.classList.remove('show'), 2400);
}

// Escapa también las comillas: el resultado se usa dentro de atributos (onclick="f('...')").
function escapar(s){ return String(s??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

// Anti-CSRF: toda petición que modifica datos lleva el token de la sesión (lo pone el servidor
// en <meta name="csrf-token">). Se envuelve fetch() para que valga también para las subidas de
// archivos y cualquier llamada que no pase por api().
(function(){
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.content : '';
  const original = window.fetch.bind(window);
  window.fetch = function(url, opts){
    opts = opts || {};
    const metodo = (opts.method || 'GET').toUpperCase();
    if(token && metodo !== 'GET' && metodo !== 'HEAD' && typeof url === 'string' && !/^https?:/i.test(url)){
      const h = new Headers(opts.headers || {});
      h.set('X-CSRF-Token', token);
      opts = {...opts, headers: h, credentials: 'same-origin'};
    }
    return original(url, opts);
  };
})();

async function api(url, opts={}){
  const r=await fetch(url, opts.body ? {...opts, headers:{'Content-Type':'application/json',...(opts.headers||{})}, body:JSON.stringify(opts.body)} : opts);
  let datos=null; try{ datos=await r.json(); }catch(e){}
  if(r.status===401){ location.href='/login'; throw new Error('Sesión caducada'); }
  if(!r.ok) throw new Error((datos&&datos.error)||`Error ${r.status}`);
  return datos;
}

function fmt(n, dec=1){ if(n===null||n===undefined||isNaN(n)) return '—'; return Number(n).toLocaleString('es-CO',{minimumFractionDigits:0,maximumFractionDigits:dec}); }
function fmtFecha(f){ if(!f) return '—'; const [y,m,d]=f.split('-'); return d&&m ? `${d}/${m}/${y}` : f; }
// Fecha LOCAL: toISOString() es UTC y en Colombia (UTC−5) a partir de las 7 p. m. ya daba el día siguiente.
function hoyISO(){ const d = new Date(); return new Date(d - d.getTimezoneOffset()*6e4).toISOString().slice(0,10); }

const NIVEL_TXT={ok:'OK', proximo:'Próximo', critico:'Crítico', vencido:'Vencido'};
function tagNivel(n){ return `<span class="tag ${n}">${NIVEL_TXT[n]||n}</span>`; }
function barra(c){ return `<div class="barra ${c.nivel}"><i style="width:${Math.min(c.pct,100)}%"></i></div>`; }

// ---- Cómo se mide el desgaste de una pieza ----
// No todos los modelos se miden igual: del T50 el fabricante publica vida útil en horas de vuelo
// y del T100 sólo plazos de calendario en meses, y hay consumibles sin ningún plazo (se revisan
// a diario). Estas tres funciones son el único sitio donde se decide cómo se escribe eso, para
// que una misma pieza se lea igual en el resumen, en mantenimiento, en reportes y en el buscador.
function midePorCalendario(c){
  return !c.vida_util_horas && !!c.vida_util_meses;
}
// «257 / 700 h» · «3,2 / 12 meses» · «sin plazo»
function usoPieza(c){
  if(midePorCalendario(c)) return `${fmt(c.meses_en_servicio)} / ${fmt(c.vida_util_meses,0)} meses`;
  if(c.vida_util_horas) return `${fmt(c.horas_uso)} / ${fmt(c.vida_util_horas,0)} h`;
  return 'sin plazo';
}
// «700 h» · «12 meses» · «—»
function vidaPieza(c){
  if(midePorCalendario(c)) return `${fmt(c.vida_util_meses,0)} meses`;
  return c.vida_util_horas ? `${fmt(c.vida_util_horas,0)} h` : '—';
}
// «quedan 443 h» · «quedan 8,8 meses» · «revisión diaria»
function restaPieza(c){
  if(midePorCalendario(c)) return c.meses_restantes!=null ? `quedan ${fmt(c.meses_restantes)} meses` : '—';
  return c.restante!=null ? `quedan ${fmt(c.restante)} h` : 'revisión diaria';
}

// «quedan 443 h» · «excedida 12 h» · «excedidos 3,1 meses»
function excesoPieza(c){
  if(midePorCalendario(c)){
    if(c.meses_restantes==null) return '—';
    return c.meses_restantes<0 ? `excedidos ${fmt(-c.meses_restantes)} meses` : `quedan ${fmt(c.meses_restantes)} meses`;
  }
  if(c.restante==null) return 'revisión diaria';
  return c.restante<0 ? `excedida ${fmt(-c.restante)} h` : `quedan ${fmt(c.restante)} h`;
}

function opcionesEquipos(equipos, sel, conTodos=false){
  const base = conTodos ? `<option value="">Todos los equipos</option>` : '';
  return base + equipos.map(e=>`<option value="${e.id}" ${String(sel)===String(e.id)?'selected':''}>${escapar(e.nombre)} · ${escapar(e.modelo)}</option>`).join('');
}

function paramURL(k){ return new URLSearchParams(location.search).get(k); }

// ===== Registro de errores =====
// La app se abre en una ventana sin menús, así que la consola del navegador no está a mano.
// Todo error no capturado se manda al servidor y queda en datos/errores_js.log, con su fichero
// y su línea. Se limita a 20 por carga y no se repite el mismo mensaje, para que un fallo dentro
// del bucle de animación (60 veces por segundo) no llene el disco.
(function(){
  let enviados = 0;
  const vistos = new Set();
  function registrar(mensaje, origen, pila){
    if(enviados >= 20 || vistos.has(mensaje)) return;
    vistos.add(mensaje); enviados++;
    try{
      fetch('/api/log-js', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({pagina: location.pathname + location.search, mensaje, origen, pila})});
    }catch(e){ /* si ni siquiera se puede avisar, no hay nada más que hacer */ }
  }
  window.addEventListener('error', e=>{
    registrar(e.message || String(e.error || e),
              e.filename ? `${e.filename}:${e.lineno}:${e.colno}` : '',
              e.error && e.error.stack);
  });
  window.addEventListener('unhandledrejection', e=>{
    const r = e.reason;
    registrar('Promesa rechazada: ' + (r && r.message ? r.message : String(r)), '', r && r.stack);
  });
})();


// Superadministrador: «Volver al panel» cierra la empresa que estaba viendo.
document.addEventListener('DOMContentLoaded', ()=>{
  const b=document.getElementById('btnSalirEmpresa');
  if(b) b.onclick = async ()=>{ await api('/api/admin/salir-empresa',{method:'POST',body:{}}); location.href='/admin'; };
});
