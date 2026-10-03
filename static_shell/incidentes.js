// Incidentes: reportar un golpe, caída o aterrizaje duro y firmar su inspección. Lo usan la ficha
// del activo, el chequeo pre-vuelo y Aeronavegabilidad. Depende de app.js y ui.js.
// Un incidente abierto deja el activo «No recomendado volar» hasta que se firma su inspección.

(function(){
  const TIPOS = {golpe:'Golpe', caida:'Caída', aterrizaje_duro:'Aterrizaje duro',
                 colision:'Colisión con obstáculo', falla_vuelo:'Falla en vuelo', otro:'Otro'};
  const hoy = ()=> new Date().toISOString().slice(0,10);

  // reportarIncidente({id, nombre, tipo_activo}, alTerminar)
  window.reportarIncidente = function(equipo, alTerminar){
    const v = ventana({
      titulo: 'Reportar incidente', ancho: 'angosta',
      subtitulo: `${escapar(equipo.nombre)} quedará <b>no recomendado para volar</b> hasta que se firme la inspección.`,
      cuerpo: `<form id="fInc" class="form-grid" style="grid-template-columns:1fr 1fr">
        <div class="campo"><label>Qué pasó</label><select name="tipo">${Object.entries(TIPOS).map(([k,t])=>`<option value="${k}">${t}</option>`).join('')}</select></div>
        <div class="campo"><label>Fecha</label><input name="fecha" type="date" value="${hoy()}" max="${hoy()}" required></div>
        <div class="campo ancho"><label>Descripción</label><textarea name="descripcion" rows="3" required placeholder="Ej.: al aterrizar en la finca La Esperanza tocó una rama con el brazo 2"></textarea></div>
        <div class="campo ancho"><label>Daños que se ven <span class="un">(opcional)</span></label><input name="danos" placeholder="Hélice partida, brazo rayado…"></div>
        <div class="campo"><label>Lugar <span class="un">(opcional)</span></label><input name="lugar"></div>
        <div class="campo"><label>Piloto <span class="un">(opcional)</span></label><input name="piloto"></div>
      </form>
      <p class="pista" style="margin:10px 0 0">Se abre sola una orden de trabajo de inspección para el técnico.</p>`,
      pie: `<div class="der"><button class="btn secundario" data-no type="button">Cancelar</button><button class="btn rojo" data-si type="button">Reportar y dejar en tierra</button></div>`,
    });
    v.$('[data-no]').onclick = ()=>v.cerrar();
    v.$('[data-si]').onclick = async ()=>{
      const f = v.$('#fInc');
      if(!f.reportValidity()) return;
      const d = Object.fromEntries(new FormData(f).entries());
      d.equipo_id = equipo.id;
      try{
        const r = await api('/api/incidentes', {method:'POST', body:d});
        toast('Incidente reportado: se abrió la orden de inspección');
        await v.cerrar();
        if(alTerminar) alTerminar(r);
      }catch(e){ toast(e.message); }
    };
  };

  // inspeccionarIncidente(incidente, rol, alTerminar)
  window.inspeccionarIncidente = function(inc, rol, alTerminar){
    const avion = inc.tipo_activo === 'avion';
    if(rol === 'piloto'){ toast('La inspección la firma un técnico, un inspector o el representante del fabricante'); return; }
    if(avion && !['admin','superadmin','certificador'].includes(rol)){
      toast('La inspección de un avión la firma un inspector o mecánico certificador'); return;
    }
    const v = ventana({
      titulo: 'Cerrar inspección del incidente', ancho: 'angosta',
      subtitulo: `${escapar(inc.equipo)} · ${escapar(TIPOS[inc.tipo]||inc.tipo)} del ${fmtFecha(inc.fecha)}`,
      cuerpo: `<form id="fInsp" class="form-grid" style="grid-template-columns:1fr 1fr">
        <div class="campo ancho"><label>Resultado</label><select name="resultado">
          <option value="apto">Apto: puede volver a volar</option>
          <option value="no_apto">No apto: requiere reparación (pasa a taller)</option></select></div>
        <div class="campo"><label>Firma</label><input name="firmado_por" required placeholder="Nombre de quien inspeccionó"></div>
        ${avion
          ? `<div class="campo"><label>Licencia del inspector</label><input name="licencia" required></div>`
          : `<div class="campo"><label>Firma como</label><select name="cargo">
              <option value="Técnico asignado">Técnico asignado a la tarea</option>
              <option value="Representante del fabricante">Representante del fabricante</option></select></div>`}
        <div class="campo"><label>Fecha</label><input name="fecha" type="date" value="${hoy()}" required></div>
        <div class="campo ancho"><label>Qué se revisó</label><textarea name="nota" rows="3" placeholder="Hélices, brazos, motores y estructura sin daños; prueba en tierra correcta"></textarea></div>
      </form>
      <p class="pista" style="margin:10px 0 0">${avion
        ? 'Aviación tripulada: firma el inspector o mecánico certificador con su licencia (RAC 43).'
        : 'UAS: la norma no fija quién firma; lo hace el técnico asignado o el representante del fabricante.'}</p>`,
      pie: `<div class="der"><button class="btn secundario" data-no type="button">Cancelar</button><button class="btn" data-si type="button">Firmar inspección</button></div>`,
    });
    v.$('[data-no]').onclick = ()=>v.cerrar();
    v.$('[data-si]').onclick = async ()=>{
      const f = v.$('#fInsp');
      if(!f.reportValidity()) return;
      try{
        await api(`/api/incidentes/${inc.id}/inspeccion`, {method:'POST', body:Object.fromEntries(new FormData(f).entries())});
        toast('Inspección firmada');
        await v.cerrar();
        if(alTerminar) alTerminar();
      }catch(e){ toast(e.message); }
    };
  };

  // Lista de incidentes de un activo (o de toda la flota) dentro de `nodo`.
  window.pintarIncidentes = async function(nodo, {equipoId=null, rol='', alCambiar=null, limite=20} = {}){
    let r;
    try{ r = await api('/api/incidentes' + (equipoId ? `?equipo_id=${equipoId}` : '')); }
    catch(e){ nodo.innerHTML = `<div class="empty">${escapar(e.message)}</div>`; return []; }
    const lista = r.incidentes.slice(0, limite);
    if(!lista.length){
      nodo.innerHTML = '<div class="mut" style="font-size:12.5px;padding:4px 0">Sin incidentes registrados.</div>';
      return [];
    }
    nodo.innerHTML = `<div class="lista">${lista.map(i=>`<div class="item">
      <span class="punto ${i.estado==='abierto'?'vencido':(i.inspeccion_resultado==='no_apto'?'critico':'ok')}"></span>
      <div class="cuerpo"><b>${escapar(i.tipo_txt)} · ${fmtFecha(i.fecha)}${equipoId?'':` · ${escapar(i.equipo)}`}</b>
        <div class="mut">${escapar(i.descripcion)}${i.orden_codigo?` · <a href="/ordenes-trabajo?ot=${i.orden_id}">${escapar(i.orden_codigo)}</a>`:''}</div>
        ${i.estado==='cerrado'?`<div class="mut">Inspección ${fmtFecha(i.inspeccion_fecha)}: ${escapar(i.resultado_txt)} · ${escapar(i.inspeccion_firmado_por||'')}${i.inspeccion_licencia?` (lic. ${escapar(i.inspeccion_licencia)})`:i.inspeccion_cargo?` (${escapar(i.inspeccion_cargo)})`:''}</div>`:''}</div>
      <div class="der">${i.estado==='abierto'
        ? (rol!=='piloto' ? `<button class="btn peq" type="button" data-insp="${i.id}">Firmar inspección</button>` : '<span class="tag vencido">Sin inspección</span>')
        : '<span class="tag ok">Cerrado</span>'}</div></div>`).join('')}</div>`;
    nodo.querySelectorAll('[data-insp]').forEach(b=>b.onclick = ()=>
      inspeccionarIncidente(lista.find(x=>x.id==b.dataset.insp), rol, alCambiar));
    return lista;
  };
})();
