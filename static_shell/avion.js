/* =====================================================================
   Diagrama de zonas de la aeronave: avión agrícola y dron multirrotor
   ---------------------------------------------------------------------
   window.diagramaAeronave(contenedor, componentes, opciones={}) dibuja un esquema
   técnico propio (vista en planta + vista lateral pequeña) con zonas clicables
   coloreadas por el peor nivel de sus componentes. El motor (agrupación, colores,
   tooltip, chips, selección, recorte en estrecho) es común; cada tipo de activo
   aporta su «plano» (PLANOS.avion, PLANOS.dron) con sus zonas y su dibujo.

   Avión (monomotor, ala baja, tren convencional) — zonas ↔ `modulo` del catálogo:
     «Motor», «Hélice», «Célula y tren», «Sistema de aspersión», «Emergencia»
     e «Inspecciones» (insignia circular).
   Dron (Agras de cuatro brazos con rotores coaxiales) — zonas ↔ `modulo`:
     «Propulsión», «Estructura», «Sistema de aspersión», «Batería», «Radar»,
     «Percepción», «Posicionamiento», «Electrónica», «Tren de aterrizaje»,
     «Sistema de esparcido» y «Sistema de elevación» (sólo si el modelo los trae)
     y «Control remoto» (insignia circular: equipo de tierra).
   Módulos desconocidos → zona «Otros» (sólo aparece en los chips).

   opciones:
     tipo     ('avion')      — 'avion' | 'dron'.
     modelo   ('')           — clave o nombre del modelo (T50, T70P…): ajusta el dron.
     alElegir(zona, items)   — callback al hacer clic en una zona.
     seleccion               — zona elegida al iniciar (sin disparar alElegir).
     lateral  (true)         — dibuja la vista lateral.
     chips    (true)         — fila de chips de zonas debajo (útil en móvil).
     titulo   ('')           — texto del cajetín (p. ej. «HK-4521 · C188A»).
   Devuelve { seleccionar(zona, avisar), actualizar(componentes), zonas(), zonaDe(c), peorZona() }.
   window.diagramaAvion y window.diagramaDron son atajos con el tipo ya fijado.
   Esquemas genéricos propios: no reproducen planos ni marcas de ningún fabricante.
   ===================================================================== */
(function(){
  'use strict';

  const ORDEN = { vencido: 3, critico: 2, proximo: 1, ok: 0 };
  const NIVEL_TXT = { vencido: 'Vencido', critico: 'Crítico', proximo: 'Próximo', ok: 'Al día', sin: 'Sin ítems' };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const r1 = n => Math.round(n * 10) / 10;

  function zonaDe(c, plano){
    plano = plano || PLANOS.avion;
    // En el avión manda la `zona` del catálogo; en el dron la `zona` es el conjunto del despiece
    // («Marco delantero», «Batería y cargador»…) y el sistema lo da el `modulo`.
    const m = String((plano.porModulo ? (c.modulo || c.zona) : (c.zona || c.modulo)) || '').trim();
    return plano.alias[m.toLowerCase()] || (plano.zonas.includes(m) ? m : 'Otros');
  }

  function agrupar(componentes, plano){
    plano = plano || PLANOS.avion;
    const g = {};
    [...plano.zonas, 'Otros'].forEach(z => g[z] = { zona: z, items: [], nivel: 'sin', alertas: 0, peor: null, cuenta: { vencido: 0, critico: 0, proximo: 0, ok: 0 } });
    (componentes || []).forEach(c => {
      const z = g[zonaDe(c, plano)]; z.items.push(c);
      const n = ORDEN[c.nivel] != null ? c.nivel : 'ok';
      z.cuenta[n]++;
      if (n !== 'ok') z.alertas++;
      if (!z.peor || ORDEN[n] > ORDEN[z.peor.nivel] || (ORDEN[n] === ORDEN[z.peor.nivel] && (+c.pct || 0) > (+z.peor.pct || 0))) z.peor = c;
    });
    Object.values(g).forEach(z => {
      if (z.peor) z.nivel = ORDEN[z.peor.nivel] != null ? z.peor.nivel : 'ok';
      z.items.sort((a, b) => (ORDEN[b.nivel] || 0) - (ORDEN[a.nivel] || 0) || (+b.pct || 0) - (+a.pct || 0));
    });
    return g;
  }

  // Zonas que se enseñan: las opcionales (cargas intercambiables del dron) sólo si el modelo tiene ítems.
  function zonasVisibles(plano, grupos){
    return plano.zonas.filter(z => !(plano.opcionales || []).includes(z) || grupos[z].items.length);
  }

  // ---------------------------------------------------------------- estilos
  const CSS = `
.avd{position:relative;--avd-ln:var(--o-avd-ln,#1a1d24);--avd-ln2:var(--o-avd-ln2,#5b616d);--avd-grid:var(--o-avd-grid,#eef0f3);--avd-grid2:var(--o-avd-grid2,#e2e5ea);
  --avd-papel:var(--o-avd-papel,#fcfcfd);--avd-hoja:var(--o-sup,#fff);--avd-marco:var(--o-avd-marco,#c9cdd4)}
.avd svg{display:block;width:100%;height:auto;user-select:none;-webkit-user-select:none}
.avd .z,.avd .cal{cursor:pointer;outline:none}
.avd .cal:focus-visible .caja{stroke:#e5a200;stroke-width:2.6}
.avd .z .f{transition:fill .18s,stroke .18s,opacity .18s}
.avd .z.n-sin .f{fill:var(--o-avd-sin,#f3f4f6)}
.avd .z.n-ok .f{fill:var(--o-avd-ok,#e3f1e7)}
.avd .z.n-proximo .f{fill:var(--o-avd-proximo,#fdefc4)}
.avd .z.n-critico .f{fill:var(--o-avd-critico,#f8cdc9)}
.avd .z.n-vencido .f{fill:var(--o-avd-vencido,#f2b3ae)}
.avd .z .f{stroke:var(--avd-ln);stroke-width:1.6;stroke-linejoin:round}
.avd .z .d{fill:none;stroke:var(--avd-ln2);stroke-width:1;stroke-linecap:round}
.avd .z .h{fill:none;stroke:var(--avd-ln2);stroke-width:1.1;stroke-dasharray:5 4}
.avd .z .s{fill:var(--avd-hoja);stroke:var(--avd-ln);stroke-width:1.3}
.avd .z .k{fill:var(--avd-ln)}
.avd .z .hit{fill:transparent;stroke:none}
.avd .z .rot{font:700 11px/1 -apple-system,Helvetica,Arial,sans-serif;fill:var(--avd-ln2);letter-spacing:.08em;text-anchor:middle}
.avd .z:hover .f,.avd .z:focus-visible .f{stroke:var(--acc-ink,#8a5f00);stroke-width:2.4}
.avd .z.sel .f{stroke:#e5a200;stroke-width:3}
.avd.con-sel .z:not(.sel):not(.cal) .f{opacity:.55}
.avd.con-sel .z:not(.sel):not(.cal) .d,.avd.con-sel .z:not(.sel):not(.cal) .h{opacity:.5}
.avd .z.sel{filter:none}
.avd .cal .caja{fill:var(--avd-hoja);stroke:var(--avd-ln);stroke-width:1.3}
.avd .cal:hover .caja,.avd .cal:focus-visible .caja{stroke:var(--acc-ink,#8a5f00);stroke-width:2}
.avd .cal.sel .caja{fill:#fdb913;stroke:#e5a200;stroke-width:2}
.avd .cal .t1{font:800 16px/1 Manrope,-apple-system,Helvetica,Arial,sans-serif;letter-spacing:.04em;fill:var(--avd-ln)}
.avd .cal .t2{font:600 13px/1 -apple-system,Helvetica,Arial,sans-serif;fill:var(--avd-ln2)}
.avd .cal.sel .t1{fill:#1a1d24}.avd .cal.sel .t2{fill:#3a3f4a}
.avd .cal .ld{fill:none;stroke:var(--avd-ln);stroke-width:1;stroke-dasharray:none}
.avd .cal .pt{fill:var(--avd-ln)}
.avd .bd circle{stroke:var(--avd-hoja);stroke-width:2}
.avd .bd text{font:800 14px/1 -apple-system,Helvetica,Arial,sans-serif;fill:#fff;text-anchor:middle;dominant-baseline:central}
.avd .bd.n-vencido circle.b{fill:#b3261e}.avd .bd.n-critico circle.b{fill:#e0473e}
.avd .bd.n-proximo circle.b{fill:#e8a400}.avd .bd.n-proximo text{fill:#1a1d24}
.avd .bd.n-ok circle.b{fill:#2f8f4e}.avd .bd.n-sin circle.b{fill:#b5bac3}
.avd .bd .pulso{fill:none;stroke:#b3261e;stroke-width:2;opacity:0}
@media (prefers-reduced-motion:no-preference){.avd .bd.n-vencido .pulso{animation:avdPulso 1.8s ease-out infinite}}
@keyframes avdPulso{0%{r:13;opacity:.7}100%{r:24;opacity:0}}
.avd .ins .anillo-bg{fill:none;stroke:var(--line,#e6e7ea);stroke-width:9}
.avd .ins .anillo{fill:none;stroke-width:9;stroke-linecap:round;transform:rotate(-90deg);transform-box:fill-box;transform-origin:center}
.avd .ins.n-ok .anillo{stroke:#2f8f4e}.avd .ins.n-proximo .anillo{stroke:#e8a400}.avd .ins.n-critico .anillo{stroke:#e0473e}.avd .ins.n-vencido .anillo{stroke:#b3261e}.avd .ins.n-sin .anillo{stroke:#b5bac3}
.avd .ins .fondo{fill:var(--avd-hoja);stroke:var(--avd-ln);stroke-width:1.3}
.avd .ins.sel .fondo{fill:var(--acc-soft,#fff6db);stroke:#e5a200;stroke-width:2.4}
.avd .ins:hover .fondo{stroke:var(--acc-ink,#8a5f00);stroke-width:2}
.avd .tx{font:600 12px/1 -apple-system,Helvetica,Arial,sans-serif;fill:var(--mut,#737a86);letter-spacing:.08em}
.avd .txb{font:800 13px/1 Manrope,-apple-system,Helvetica,Arial,sans-serif;fill:var(--avd-ln);letter-spacing:.08em}
.avd .cota{stroke:var(--mut,#737a86);stroke-width:1;fill:none}
.avd .eje{stroke:#9aa0aa;stroke-width:1;stroke-dasharray:22 5 3 5;fill:none}
.avd .suelo{stroke:var(--avd-ln);stroke-width:1.4}
.avd .suelo-h{stroke:#b5bac3;stroke-width:1}
.avd.estrecho .cal:not(.ins),.avd.estrecho .solo-ancho,.avd.estrecho .lat{display:none}
.avd-tip{position:absolute;z-index:5;pointer-events:none;min-width:170px;max-width:260px;background:var(--o-globo,#1a1d24);border:.5px solid var(--o-borde-globo,transparent);color:#fff;border-radius:12px;padding:10px 12px;font-size:12.5px;line-height:1.4;box-shadow:0 10px 30px rgba(0,0,0,.25);opacity:0;transform:translateY(4px);transition:opacity .12s,transform .12s}
.avd-tip.ver{opacity:1;transform:none}
.avd-tip b{display:block;font-size:13.5px;margin-bottom:2px}
.avd-tip .l{display:flex;align-items:center;gap:6px;color:#c9ccd2}
.avd-tip .p{width:8px;height:8px;border-radius:50%;flex:none}
.avd-chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.avd-chip{display:inline-flex;align-items:center;gap:7px;font:600 12.5px/1 -apple-system,Helvetica,Arial,sans-serif;color:var(--ink2,#3a3f4a);background:var(--o-sup,#fff);border:.5px solid var(--line2,#d3d6dc);border-radius:980px;padding:6px 11px 6px 9px;cursor:pointer;transition:.15s}
.avd-chip:hover{border-color:#fdb913;color:var(--acc-ink,#8a5f00)}
.avd-chip.sel{background:#fdb913;border-color:#e5a200;color:#1a1d24}
.avd-chip .p{width:9px;height:9px;border-radius:50%}
.avd-chip .c{font-weight:800;font-variant-numeric:tabular-nums}
.avd-p-vencido{background:#b3261e}.avd-p-critico{background:#e0473e}.avd-p-proximo{background:#e8a400}.avd-p-ok{background:#2f8f4e}.avd-p-sin{background:#b5bac3}
`;
  function inyectarCSS(){
    if (document.getElementById('avd-css')) return;
    const s = document.createElement('style'); s.id = 'avd-css'; s.textContent = CSS; document.head.appendChild(s);
  }

  // ---------------------------------------------------------------- piezas comunes del plano
  // Todas las hojas usan viewBox de 1000 de ancho, planta arriba (0–712) y lateral abajo.
  function hoja(H, etiqueta){
    return `<defs>
        <pattern id="avdG1" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="var(--avd-grid)" stroke-width="1"/></pattern>
        <pattern id="avdG2" width="100" height="100" patternUnits="userSpaceOnUse"><rect width="100" height="100" fill="url(#avdG1)"/><path d="M100 0H0V100" fill="none" stroke="var(--avd-grid2)" stroke-width="1"/></pattern>
        <marker id="avdFl" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 1 L10 5 L0 9 Z" fill="#737a86" style="fill:var(--mut)"/></marker>
      </defs>
      <rect x="0" y="0" width="1000" height="${H}" rx="14" fill="#fcfcfd" style="fill:var(--avd-papel)"/>
      <rect x="0" y="0" width="1000" height="${H}" rx="14" fill="url(#avdG2)"/>
      <rect x="10" y="10" width="980" height="${H - 20}" rx="8" fill="none" stroke="#c9cdd4" style="stroke:var(--avd-marco)" stroke-width="1"/>
      <g class="solo-ancho">
        <text class="txb" x="36" y="42">VISTA EN PLANTA</text>
        <text class="tx" x="176" y="42">ESQUEMA DE ZONAS · SIN ESCALA</text>
      </g>`;
  }

  // Calloutes: [zona, x caja, y caja, ancho, punto de anclaje en el dibujo, rótulo opcional]
  function callouts(lista){
    return lista.map(([z, x, y, w, [ax, ay], rotulo]) => {
      const der = x > 500; const bx = der ? x : x + w; const by = y + 26;
      const codo = der ? Math.max(ax + 20, bx - 40) : Math.min(ax - 20, bx + 40);
      return `<g class="cal" data-zona="${esc(z)}" tabindex="0" role="button" aria-label="${esc(z)}">
          <path class="ld" d="M${bx} ${by} H${codo} L${ax} ${ay}"/><circle class="pt" cx="${ax}" cy="${ay}" r="3.2"/>
          <rect class="caja" x="${x}" y="${y}" width="${w}" height="52" rx="10"/>
          <text class="t1" x="${x + 16}" y="${y + 23}">${esc((rotulo || z).toUpperCase())}</text>
          <text class="t2" x="${x + 16}" y="${y + 41}" data-sub></text>
          <g class="bd" transform="translate(${x + w - 24} ${y + 26})"><circle class="pulso" r="13"/><circle class="b" r="13"/><text data-n></text></g>
        </g>`;
    }).join('');
  }

  // Glifos de la insignia circular (coordenadas centradas en 0,0).
  const GLIFO = {
    lista: `<path d="M-13 -18 h26 v36 h-26 z M-7 -22 h14 v7 h-14 z" fill="#fff" stroke="#1a1d24" style="fill:var(--avd-hoja);stroke:var(--avd-ln)" stroke-width="2" stroke-linejoin="round"/>
        <path d="M-7 -6 l3 3 l6 -6 M-7 7 l3 3 l6 -6" fill="none" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`,
    mando: `<path d="M-12 -9 L-16 -21 M12 -9 L16 -21" fill="none" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="2" stroke-linecap="round"/>
        <rect x="-21" y="-10" width="42" height="26" rx="7" fill="#fff" stroke="#1a1d24" style="fill:var(--avd-hoja);stroke:var(--avd-ln)" stroke-width="2"/>
        <rect x="-7" y="-5" width="14" height="10" rx="2" fill="none" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="1.6"/>
        <circle cx="-13.5" cy="6" r="3.2" fill="none" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="1.8"/>
        <circle cx="13.5" cy="6" r="3.2" fill="none" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="1.8"/>`,
  };

  // Insignia circular (anillo de avance + glifo + contador). Se recoloca en estrecho (ver `ajustar`).
  function insignia(ins){
    const [x, y] = ins.ancho;
    return `<g class="z ins cal" data-zona="${esc(ins.zona)}" data-ins tabindex="0" role="button" aria-label="${esc(ins.zona)}" transform="translate(${x} ${y})">
        <rect class="hit" x="-110" y="-66" width="220" height="176" fill="transparent"/>
        <circle class="fondo" r="56"/>
        <circle class="anillo-bg" r="44"/>
        <circle class="anillo" r="44" pathLength="100" stroke-dasharray="0 100" data-anillo/>
        ${GLIFO[ins.glifo] || GLIFO.lista}
        <text class="t1" x="0" y="84" text-anchor="middle" style="font:800 16px Manrope,-apple-system,Helvetica,Arial,sans-serif;letter-spacing:.06em;fill:var(--avd-ln)">${esc(ins.zona.toUpperCase())}</text>
        <text class="t2" x="0" y="103" text-anchor="middle" data-sub></text>
        <g class="bd" transform="translate(42 -42)"><circle class="pulso" r="13"/><circle class="b" r="13"/><text data-n></text></g>
      </g>`;
  }

  // Cajetín de la hoja (esquina inferior derecha de la vista lateral).
  function cajetin(titulo, porDefecto, configuracion){
    return `<g class="solo-ancho" transform="translate(560 770)">
        <rect width="410" height="130" fill="#fff" stroke="#1a1d24" style="fill:var(--avd-hoja);stroke:var(--avd-ln)" stroke-width="1.3"/>
        <path d="M0 44 H410 M0 88 H410 M270 44 V130" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="1"/>
        <text class="tx" x="14" y="18">ACTIVO</text>
        <text class="txb" x="14" y="36" style="font-size:15px" data-titulo>${esc(titulo) || porDefecto}</text>
        <text class="tx" x="14" y="62">CONFIGURACIÓN</text>
        <text class="txb" x="14" y="80" style="font-size:12px">${configuracion}</text>
        <text class="tx" x="284" y="62">DOCUMENTO</text>
        <text class="txb" x="284" y="80" style="font-size:12px">ESQUEMA ZONAS</text>
        <text class="tx" x="14" y="106">NIVEL DE ZONA</text>
        <text class="txb" x="14" y="122" style="font-size:12px">PEOR ÍTEM DEL MÓDULO</text>
        <text class="tx" x="284" y="106">HOJA</text>
        <text class="txb" x="284" y="122" style="font-size:12px">1 / 1 · S/E</text>
      </g>`;
  }

  function sueloLateral(y, x1, x2){
    const n = Math.floor((x2 - x1 - 20) / 20);
    return `<path class="suelo" d="M${x1} ${y} H${x2}"/>
      <path class="suelo-h" d="${Array.from({ length: n }, (_, i) => `M${x1 + 10 + i * 20} ${y + 1} l-10 10`).join(' ')}"/>`;
  }

  // ================================================================ AVIÓN
  // Coordenadas del viewBox: 1000 de ancho. Vista en planta con la nariz arriba (eje x=500).
  function espejo(d){ return `<g transform="translate(1000 0) scale(-1 1)">${d}</g>`; }
  function boquillas(x1, x2, y){
    let s = '';
    for (let x = x1; x <= x2; x += 24) s += `<circle class="k" cx="${x}" cy="${y}" r="2.6"/>`;
    return s;
  }

  // Planta — cada función devuelve el contenido de su grupo de zona.
  const PLANTA_AVION = {
    'Célula y tren': () => {
      const ala = `
        <path class="f" d="M458 262 L104 262 Q88 262 86 276 L84 358 Q86 372 102 372 L458 372 Z"/>
        <path class="d" d="M106 344 H300 M300 344 V372 M312 346 H452 M312 346 V372"/>
        <path class="d" d="M96 266 V368" stroke-dasharray="2 3"/>
        <circle class="s" cx="380" cy="282" r="5"/>
        <path class="d" d="M170 300 L170 330 M230 300 L230 330" stroke-dasharray="3 4"/>
        <path class="f" d="M488 580 L362 588 Q350 590 350 600 L352 624 Q354 630 362 630 L488 632 Z"/>
        <path class="d" d="M356 612 L488 614"/>
        <rect class="s" x="392" y="212" width="16" height="36" rx="6"/>
        <path class="d" d="M408 234 L458 250" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="2.2"/>`;
      return `
        ${ala}${espejo(ala)}
        <path class="f" d="M458 348 L542 348 C542 420 530 560 512 640 L488 640 C470 560 458 420 458 348 Z"/>
        <path class="f" d="M496 520 L504 520 L506 668 Q500 674 494 668 Z"/>
        <path class="d" d="M495 640 H505"/>
        <rect class="h" x="495" y="620" width="10" height="20" rx="4"/>
        <path class="d" d="M470 420 H530 M476 500 H524" stroke-dasharray="2 4"/>`;
    },
    'Motor': () => `
        <path class="f" d="M474 114 L526 114 C538 118 542 136 542 158 L542 202 L458 202 L458 158 C458 136 462 118 474 114 Z"/>
        <ellipse class="s" cx="484" cy="128" rx="8" ry="5"/><ellipse class="s" cx="516" cy="128" rx="8" ry="5"/>
        <path class="d" d="M470 150 H530 M468 160 H532 M468 170 H532"/>
        <circle class="s" cx="500" cy="186" r="5"/>
        <rect class="s" x="448" y="178" width="10" height="16" rx="3"/><rect class="s" x="542" y="178" width="10" height="16" rx="3"/>`,
    'Hélice': () => `
        <rect class="hit" x="400" y="84" width="200" height="36"/>
        <ellipse class="h" cx="500" cy="109" rx="94" ry="9"/>
        <path class="f" d="M500 106 L412 104 Q404 106 404 110 Q404 114 412 115 L500 113 Z"/>
        <path class="f" d="M500 106 L588 104 Q596 106 596 110 Q596 114 588 115 L500 113 Z"/>
        <path class="f" d="M484 114 Q486 90 500 84 Q514 90 516 114 Z"/>`,
    'Sistema de aspersión': () => {
      const barra = `<rect class="f" x="110" y="382" width="344" height="7" rx="3.5"/>${boquillas(122, 446, 396)}
        <path class="h" d="M454 386 L474 372"/>`;
      return `
        <path class="f" d="M456 202 L544 202 L546 268 L454 268 Z"/>
        <circle class="s" cx="500" cy="232" r="17"/><circle class="d" cx="500" cy="232" r="11"/>
        <path class="d" d="M462 256 H538"/>
        ${barra}${espejo(barra)}
        <circle class="f" cx="434" cy="236" r="11"/>
        <path class="d" d="M426 236 H442 M434 228 V244"/>
        <path class="h" d="M445 238 L456 240 M480 268 L480 372"/>`;
    },
    'Emergencia': () => `
        <path class="f" d="M458 268 L542 268 L542 350 L458 350 Z"/>
        <path class="s" d="M466 274 L534 274 L530 294 L470 294 Z"/>
        <rect class="s" x="466" y="300" width="68" height="44" rx="6"/>
        <rect class="k" x="474" y="314" width="16" height="12" rx="2"/><path class="d" d="M482 314 V304" stroke="#1a1d24" style="stroke:var(--avd-ln)" stroke-width="1.6"/>
        <rect class="k" x="512" y="310" width="9" height="22" rx="4.5"/><rect class="k" x="514" y="306" width="5" height="4"/>`,
  };

  // Vista lateral (coordenadas locales: nariz a la izquierda, eje del fuselaje en y=0).
  const LATERAL_AVION = {
    'Hélice': () => `<rect class="hit" x="4" y="-78" width="24" height="156"/>
        <path class="f" d="M13 -74 Q18 -76 20 -70 L20 70 Q18 76 13 74 Z"/>
        <path class="f" d="M2 0 Q4 -12 16 -14 L16 14 Q4 12 2 0 Z"/>`,
    'Motor': () => `<path class="f" d="M20 -16 C24 -26 34 -30 48 -30 L106 -32 L106 34 L48 34 C34 34 24 24 20 16 Z"/>
        <path class="d" d="M60 -18 V22 M72 -18 V22"/><rect class="s" x="78" y="32" width="12" height="10" rx="3"/>`,
    'Sistema de aspersión': () => `<path class="f" d="M106 -32 L112 -50 L158 -52 L162 -40 L162 34 L106 34 Z"/>
        <rect class="s" x="124" y="-58" width="22" height="7" rx="3"/>
        <circle class="f" cx="190" cy="48" r="8"/><path class="d" d="M184 48 H196"/>
        <circle class="f" cx="270" cy="46" r="5"/><path class="d" d="M270 51 V58"/>`,
    'Emergencia': () => `<path class="f" d="M162 -40 L188 -74 L238 -74 L262 -46 L262 34 L162 34 Z"/>
        <path class="s" d="M172 -38 L192 -66 L214 -66 L214 -38 Z"/><path class="s" d="M222 -66 L236 -66 L254 -42 L222 -42 Z"/>`,
    'Célula y tren': () => `<path class="f" d="M262 -46 L506 -14 L528 -10 L528 6 L262 34 Z"/>
        <path class="f" d="M470 -20 L498 -86 L528 -90 L536 -10 Z"/><path class="d" d="M512 -88 L518 -12"/>
        <path class="f" d="M462 -12 L540 -10 L540 -4 L462 -4 Z"/>
        <path class="f" d="M146 36 C160 26 206 26 262 34 L262 42 L146 42 Z"/>
        <path class="f" d="M138 36 L144 36 L130 98 L124 98 Z"/>
        <circle class="f" cx="125" cy="100" r="20"/><circle class="s" cx="125" cy="100" r="6"/>
        <path class="f" d="M506 2 L512 0 L524 22 L518 24 Z"/>
        <circle class="f" cx="522" cy="26" r="7"/>`,
  };

  const CALLOUTS_AVION = [
    ['Hélice', 30, 64, 280, [404, 110]],
    ['Motor', 690, 64, 280, [542, 150]],
    ['Sistema de aspersión', 30, 164, 280, [423, 236]],
    ['Emergencia', 690, 164, 280, [534, 322]],
    ['Célula y tren', 30, 480, 280, [360, 606]],
  ];

  function svgAvion(opts, plano){
    const lat = opts.lateral !== false;
    const H = lat ? 930 : 700;
    const zonaPlanta = z => `<g class="z" data-zona="${esc(z)}" tabindex="0" role="button" aria-label="${esc(z)}">${PLANTA_AVION[z]()}</g>`;
    const zonaLat = z => `<g class="z" data-zona="${esc(z)}">${LATERAL_AVION[z]()}</g>`;
    const orden = ['Célula y tren', 'Sistema de aspersión', 'Emergencia', 'Motor', 'Hélice'];
    // Vista lateral: escala 0,52, girada 12,4° (actitud de tren convencional en tierra) sobre la rueda principal.
    const lx = 96, ly = 806, ls = 0.52;
    const sueloY = ly + 120 * ls;
    return `<svg viewBox="0 0 1000 ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Diagrama de zonas del avión">
      ${hoja(H)}
      <path class="eje" d="M500 70 V690"/>
      ${orden.map(zonaPlanta).join('')}
      <g class="solo-ancho">
        <path class="cota" d="M86 440 H914" marker-start="url(#avdFl)" marker-end="url(#avdFl)"/>
        <path class="cota" d="M86 380 V450 M914 380 V450"/>
        <rect x="438" y="430" width="124" height="20" fill="#fcfcfd" style="fill:var(--avd-papel)"/>
        <text class="tx" x="500" y="444" text-anchor="middle">ENVERGADURA</text>
        <text class="tx" x="110" y="416">BARRA DE ASPERSIÓN · BOQUILLAS</text>
      </g>
      ${callouts(CALLOUTS_AVION)}
      ${insignia(plano.insignia)}
      ${lat ? `<g class="lat">
      <path d="M24 712 H976" stroke="#c9cdd4" style="stroke:var(--avd-marco)" stroke-width="1" stroke-dasharray="4 4"/>
      <g class="solo-ancho"><text class="txb" x="36" y="744">VISTA LATERAL</text><text class="tx" x="162" y="744">ACTITUD EN TIERRA · TREN CONVENCIONAL</text></g>
      <path class="suelo" d="M60 ${sueloY} H440"/>
      <path class="suelo-h" d="${Array.from({ length: 19 }, (_, i) => `M${70 + i * 20} ${sueloY + 1} l-10 10`).join(' ')}"/>
      <g transform="translate(${lx} ${ly}) scale(${ls}) rotate(12.4 125 120)">
        ${['Célula y tren', 'Sistema de aspersión', 'Emergencia', 'Motor', 'Hélice'].map(zonaLat).join('')}
      </g>
      ${cajetin(opts.titulo, 'AVIÓN AGRÍCOLA', 'MONOMOTOR · ALA BAJA')}</g>` : ''}
    </svg>`;
  }

  // ================================================================ DRON
  // Agras de cuatro brazos en X con rotores coaxiales (arriba y abajo de cada motor): la
  // configuración de T50, T70P, T100 y T100DB. Vista en planta con el frente (radar delantero)
  // arriba y el centro en (500, 370). Lo que cambia por modelo es la capacidad del tanque y si
  // lleva una o dos baterías; las cargas de esparcido y elevación se dibujan sólo si hay ítems.
  const MODELOS_DRON = {
    T100DB: { tanque: '90 L', baterias: 2 },
    T100: { tanque: '100 L', baterias: 1 },
    T70P: { tanque: '70 L', baterias: 1 },
    T55: { tanque: '50 L', baterias: 2 },
    T50: { tanque: '40 L', baterias: 1 },
    T25: { tanque: '20 L', baterias: 1 },
  };
  function perfilDron(modelo){
    const m = String(modelo || '').toUpperCase();
    const clave = Object.keys(MODELOS_DRON).find(k => new RegExp(`(^|[^A-Z0-9])${k}($|[^A-Z0-9])`).test(m));
    return Object.assign({ tanque: '', baterias: 1, clave: clave || '' }, clave ? MODELOS_DRON[clave] : {});
  }

  const DC = { x: 500, y: 370 };                      // centro del dron
  const MOT = [[350, 220], [650, 220], [350, 520], [650, 520]];   // DI, DD, TI, TD
  const R_HELICE = 96;
  // Ángulo de la pala superior de cada rotor (simétricos respecto al eje); la inferior va a +70°.
  const ANG_PALA = [-20, 20, 20, -20];

  // Barra (brazo, puntal) de ancho w entre dos puntos.
  function barra(x1, y1, x2, y2, w){
    const L = Math.hypot(x2 - x1, y2 - y1), nx = -(y2 - y1) / L * w / 2, ny = (x2 - x1) / L * w / 2;
    return `M${r1(x1 + nx)} ${r1(y1 + ny)} L${r1(x2 + nx)} ${r1(y2 + ny)} L${r1(x2 - nx)} ${r1(y2 - ny)} L${r1(x1 - nx)} ${r1(y1 - ny)} Z`;
  }
  // Par de palas opuestas centradas en el motor.
  function palas(x, y, ang, cls){
    const d = 'M14 -4.5 C38 -10 72 -8.5 90 -3 Q95 0 90 3 C72 7.5 38 9.5 14 4.5 Z';
    return `<g transform="translate(${x} ${y}) rotate(${ang})"><path class="${cls}" d="${d}"/><path class="${cls}" d="${d}" transform="rotate(180)"/></g>`;
  }
  // Aspersor centrífugo bajo el brazo trasero.
  function aspersor(x, y){
    return `<circle class="f" cx="${x}" cy="${y}" r="15"/>
        <path class="d" d="M${x - 10} ${y} H${x + 10} M${x} ${y - 10} V${y + 10} M${x - 7} ${y - 7} L${x + 7} ${y + 7} M${x + 7} ${y - 7} L${x - 7} ${y + 7}"/>
        <circle class="k" cx="${x}" cy="${y}" r="3"/>
        <circle class="h" cx="${x}" cy="${y}" r="24"/>`;
  }

  function plantaDron(perfil, cargas){
    const mitad = (d) => d + espejo(d);
    const P = {};
    P['Tren de aterrizaje'] = () => mitad(`
        <rect class="f" x="400" y="288" width="13" height="166" rx="6.5"/>
        <rect class="f" x="413" y="313" width="31" height="9" rx="3"/><rect class="f" x="413" y="420" width="31" height="9" rx="3"/>
        <path class="d" d="M406.5 298 V444" stroke-dasharray="2 4"/>`);
    // Palas inferiores del coaxial: bajo los brazos, sólo contorno.
    P['Propulsión·inf'] = () => MOT.map(([x, y], i) => palas(x, y, ANG_PALA[i] + 70, 'd')).join('');
    P['Estructura'] = () => {
      const raiz = [[466, 336], [534, 336], [466, 404], [534, 404]];
      const bisagra = [[420, 290], [580, 290], [420, 450], [580, 450]];
      return `${raiz.map(([x, y], i) => `<path class="f" d="${barra(x, y, MOT[i][0], MOT[i][1], 20)}"/>
          <path class="d" d="M${x} ${y} L${MOT[i][0]} ${MOT[i][1]}" stroke-dasharray="2 5"/>`).join('')}
        ${bisagra.map(([x, y]) => `<circle class="s" cx="${x}" cy="${y}" r="6.5"/>`).join('')}
        <path class="f" d="M470 236 H530 Q556 236 556 262 V478 Q556 504 530 504 H470 Q444 504 444 478 V262 Q444 236 470 236 Z"/>
        <path class="d" d="M452 266 V474 M548 266 V474"/>`;
    };
    P['Propulsión'] = () => MOT.map(([x, y], i) => `
        <circle class="h" cx="${x}" cy="${y}" r="${R_HELICE}"/>
        ${palas(x, y, ANG_PALA[i], 'f')}
        <circle class="f" cx="${x}" cy="${y}" r="21"/><circle class="d" cx="${x}" cy="${y}" r="13"/><circle class="k" cx="${x}" cy="${y}" r="3.5"/>`).join('');
    P['Sistema de aspersión'] = () => `
        <path class="h" d="M492 402 C470 430 420 470 392 484 M508 402 C530 430 580 470 608 484"/>
        ${aspersor(378, 492)}${aspersor(622, 492)}
        <rect class="f" x="462" y="268" width="76" height="120" rx="18"/>
        <circle class="s" cx="500" cy="296" r="12"/><circle class="d" cx="500" cy="296" r="7"/>
        <path class="d" d="M470 322 H480 M470 342 H480 M470 362 H480"/>
        ${perfil.tanque ? `<text class="rot" x="506" y="352">${esc(perfil.tanque)}</text>` : ''}
        <rect class="f" x="488" y="391" width="24" height="12" rx="3"/>`;
    P['Batería'] = () => {
      const pack = (x, w) => `<rect class="f" x="${x}" y="408" width="${w}" height="52" rx="6"/>
          <rect class="s" x="${x + w / 2 - 14}" y="413" width="28" height="8" rx="3"/>
          <path class="d" d="M${x + 8} 432 H${x + w - 8} M${x + 8} 446 H${x + w - 8}"/>`;
      return perfil.baterias > 1 ? pack(449, 48) + pack(503, 48) : pack(466, 68);
    };
    P['Electrónica'] = () => `<rect class="f" x="470" y="466" width="60" height="18" rx="4"/>
        <path class="d" d="M480 470 V480 M490 470 V480 M500 470 V480 M510 470 V480 M520 470 V480"/>`;
    P['Percepción'] = () => `<rect class="f" x="482" y="242" width="36" height="17" rx="5"/>
        <circle class="s" cx="492" cy="250.5" r="4.2"/><circle class="s" cx="508" cy="250.5" r="4.2"/>
        <rect class="f" x="486" y="488" width="28" height="12" rx="4"/><circle class="s" cx="500" cy="494" r="3.6"/>`;
    P['Radar'] = () => `<path class="d" d="M486 232 V238 M514 232 V238 M488 504 V508 M512 504 V508"/>
        <rect class="f" x="472" y="211" width="56" height="21" rx="10.5"/><path class="d" d="M484 222 Q500 215 516 222"/>
        <rect class="f" x="476" y="508" width="48" height="18" rx="9"/><path class="d" d="M488 518 Q500 512 512 518"/>`;
    P['Posicionamiento'] = () => mitad(`<path class="d" d="M437 256 L446 262"/>
        <circle class="f" cx="428" cy="250" r="11"/><circle class="d" cx="428" cy="250" r="5"/>`);
    // Cargas intercambiables: fuera del dron, en una franja bajo la planta.
    const xs = cargas.length > 1 ? [430, 570] : [500];
    const pos = {}; cargas.forEach((z, i) => pos[z] = xs[i]);
    P['Sistema de esparcido'] = () => { const x = pos['Sistema de esparcido']; return `
        <path class="f" d="M${x - 16} 628 H${x + 16} L${x + 9} 646 H${x - 9} Z"/>
        <rect class="f" x="${x - 4}" y="646" width="8" height="8"/>
        <ellipse class="f" cx="${x}" cy="660" rx="30" ry="8"/>
        <path class="d" d="M${x - 22} 660 H${x + 22} M${x - 14} 655 L${x + 14} 665 M${x + 14} 655 L${x - 14} 665"/>
        <text class="rot" x="${x}" y="690">ESPARCIDO</text>`; };
    P['Sistema de elevación'] = () => { const x = pos['Sistema de elevación']; return `
        <rect class="f" x="${x - 30}" y="628" width="60" height="9" rx="3"/>
        <rect class="f" x="${x - 4}" y="637" width="8" height="8"/>
        <path class="h" d="M${x} 645 V660"/>
        <path class="f" d="M${x - 3} 660 H${x + 3} V668 Q${x + 3} 678 ${x - 6} 678 Q${x - 13} 678 ${x - 14} 671 L${x - 9} 670 Q${x - 8} 673 ${x - 6} 673 Q${x - 2} 673 ${x - 2} 668 Z"/>
        <text class="rot" x="${x}" y="690">ELEVACIÓN</text>`; };
    return P;
  }

  // Vista lateral del dron (coordenadas locales: frente a la izquierda, suelo en y=0).
  function lateralDron(perfil, cargas){
    const L = {};
    L['Tren de aterrizaje'] = () => `<path class="f" d="M-46 -94 L-39 -94 L-66 -10 L-73 -10 Z"/><path class="f" d="M46 -94 L39 -94 L66 -10 L73 -10 Z"/>
        <rect class="f" x="-100" y="-10" width="200" height="8" rx="4"/>`;
    L['Estructura'] = () => `<rect class="f" x="-150" y="-126" width="300" height="10" rx="5"/>
        <path class="f" d="M-52 -156 H52 Q68 -156 70 -140 L72 -104 Q72 -92 58 -92 H-58 Q-72 -92 -72 -104 L-70 -140 Q-68 -156 -52 -156 Z"/>`;
    L['Sistema de aspersión'] = () => `<path class="h" d="M30 -86 Q72 -92 106 -108 M104 -94 L88 -56 M120 -94 L136 -56"/>
        <path class="f" d="M-40 -150 H34 Q42 -150 42 -142 V-92 Q42 -80 30 -78 H-28 Q-40 -80 -40 -92 Z"/>
        <rect class="s" x="-12" y="-158" width="16" height="8" rx="2"/>
        <rect class="f" x="108" y="-116" width="8" height="12"/><ellipse class="f" cx="112" cy="-100" rx="16" ry="4.5"/>`;
    L['Propulsión'] = () => [-150, 150].map(x => `
        <ellipse class="f" cx="${x}" cy="-100" rx="${R_HELICE - 6}" ry="3.2"/>
        <ellipse class="f" cx="${x}" cy="-144" rx="${R_HELICE - 6}" ry="3.2"/>
        <rect class="f" x="${x - 10}" y="-140" width="20" height="36" rx="5"/>
        <path class="d" d="M${x - 10} -122 H${x + 10}"/>
        <circle class="k" cx="${x}" cy="-144" r="3"/><circle class="k" cx="${x}" cy="-100" r="3"/>`).join('');
    L['Batería'] = () => perfil.baterias > 1
      ? `<rect class="f" x="-2" y="-176" width="30" height="22" rx="4"/><rect class="f" x="30" y="-176" width="30" height="22" rx="4"/>
         <rect class="s" x="6" y="-181" width="14" height="5" rx="2.5"/><rect class="s" x="38" y="-181" width="14" height="5" rx="2.5"/>`
      : `<rect class="f" x="8" y="-176" width="46" height="22" rx="4"/><rect class="s" x="20" y="-182" width="22" height="6" rx="3"/>`;
    L['Electrónica'] = () => `<rect class="f" x="-46" y="-168" width="38" height="14" rx="3"/><path class="d" d="M-40 -161 H-14"/>`;
    L['Posicionamiento'] = () => `<path class="d" d="M-58 -156 V-180"/><ellipse class="f" cx="-58" cy="-183" rx="11" ry="4.5"/>`;
    L['Percepción'] = () => `<rect class="f" x="-80" y="-146" width="12" height="16" rx="3"/><circle class="k" cx="-80" cy="-138" r="2.2"/>
        <rect class="f" x="68" y="-146" width="12" height="16" rx="3"/><circle class="k" cx="80" cy="-138" r="2.2"/>`;
    L['Radar'] = () => `<path class="d" d="M-78 -104 H-70 M78 -104 H70"/>
        <rect class="f" x="-94" y="-114" width="16" height="22" rx="6"/><rect class="f" x="78" y="-114" width="16" height="22" rx="6"/>`;
    const dos = cargas.length > 1;
    L['Sistema de esparcido'] = () => { const x = dos ? -18 : 0; return `<rect class="f" x="${x - 4}" y="-78" width="8" height="10"/>
        <ellipse class="f" cx="${x}" cy="-66" rx="24" ry="5"/>`; };
    L['Sistema de elevación'] = () => { const x = dos ? 18 : 0; return `<path class="h" d="M${x} -78 V-36"/>
        <path class="f" d="M${x - 3} -36 H${x + 3} V-26 Q${x + 3} -16 ${x - 6} -16 Q${x - 13} -16 ${x - 14} -23 L${x - 9} -24 Q${x - 8} -21 ${x - 6} -21 Q${x - 2} -21 ${x - 2} -26 Z"/>`; };
    return L;
  }

  // Callouts del dron: columna izquierda y derecha, filas fijas; el anclaje es el punto del dibujo.
  const CALLOUTS_DRON = [
    ['Propulsión', 16, 64, [329, 224]],
    ['Estructura', 16, 156, [414, 284]],
    ['Sistema de aspersión', 16, 248, [462, 330], 'Aspersión'],
    ['Tren de aterrizaje', 16, 340, [400, 400], 'Tren'],
    ['Batería', 16, 432, [449, 440]],
    ['Sistema de esparcido', 16, 524, [null, 660], 'Esparcido'],
    ['Radar', 754, 64, [528, 222]],
    ['Posicionamiento', 754, 156, [583, 250], 'GNSS · RTK'],
    ['Electrónica', 754, 248, [530, 475]],
    ['Percepción', 754, 340, [514, 494], 'Cámaras'],
    ['Sistema de elevación', 754, 432, [null, 632], 'Elevación'],
  ];

  function svgDron(opts, plano, grupos){
    const lat = opts.lateral !== false;
    const H = lat ? 930 : 712;
    const perfil = perfilDron(opts.modelo);
    const visibles = zonasVisibles(plano, grupos);
    const cargas = ['Sistema de esparcido', 'Sistema de elevación'].filter(z => visibles.includes(z));
    const P = plantaDron(perfil, cargas), L = lateralDron(perfil, cargas);
    const grupo = (z, cuerpo, foco = true) => `<g class="z" data-zona="${esc(z)}"${foco ? ` tabindex="0" role="button" aria-label="${esc(z)}"` : ''}>${cuerpo}</g>`;
    const orden = ['Tren de aterrizaje', 'Propulsión·inf', 'Estructura', 'Propulsión', 'Sistema de aspersión', 'Batería',
      'Electrónica', 'Percepción', 'Radar', 'Posicionamiento', ...cargas];
    const planta = orden.map(k => {
      const z = k.split('·')[0];
      return grupo(z, P[k](), !k.includes('·'));
    }).join('');
    const ordenLat = ['Tren de aterrizaje', 'Sistema de esparcido', 'Sistema de elevación', 'Estructura', 'Sistema de aspersión',
      'Propulsión', 'Batería', 'Electrónica', 'Posicionamiento', 'Percepción', 'Radar'].filter(z => visibles.includes(z));
    const xCarga = z => cargas.length > 1 ? (cargas.indexOf(z) ? 570 : 430) : 500;
    const lista = CALLOUTS_DRON.filter(([z]) => visibles.includes(z))
      .map(([z, x, y, [ax, ay], rotulo]) => [z, x, y, 230, [ax == null ? xCarga(z) + (x > 500 ? 30 : -30) : ax, ay], rotulo]);
    const conf = perfil.baterias > 1 ? '4 BRAZOS · 8 ROTORES · 2 BATERÍAS' : '4 BRAZOS · 8 ROTORES COAXIALES';
    const sueloY = 910;
    return `<svg viewBox="0 0 1000 ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Diagrama de zonas del dron">
      ${hoja(H)}
      <path class="eje" d="M${DC.x} 100 V612 M258 ${DC.y} H742"/>
      <g class="solo-ancho">
        <path class="cota" d="M254 104 H746" marker-start="url(#avdFl)" marker-end="url(#avdFl)"/>
        <path class="cota" d="M254 96 V214 M746 96 V214"/>
        <rect x="408" y="94" width="184" height="20" fill="#fcfcfd" style="fill:var(--avd-papel)"/>
        <text class="tx" x="500" y="108" text-anchor="middle">ENVERGADURA CON HÉLICES</text>
        <text class="tx" x="500" y="202" text-anchor="middle">FRENTE</text>
        ${cargas.length ? `<text class="tx" x="500" y="712" text-anchor="middle" dy="-4" style="font-size:10.5px">CARGAS INTERCAMBIABLES</text>` : ''}
      </g>
      ${planta}
      ${callouts(lista)}
      ${insignia(plano.insignia)}
      ${lat ? `<g class="lat">
      <path d="M24 712 H976" stroke="#c9cdd4" style="stroke:var(--avd-marco)" stroke-width="1" stroke-dasharray="4 4"/>
      <g class="solo-ancho"><text class="txb" x="36" y="744">VISTA LATERAL</text><text class="tx" x="162" y="744">EN TIERRA · ROTORES COAXIALES · FRENTE A LA IZQUIERDA</text></g>
      ${sueloLateral(sueloY, 40, 480)}
      <g transform="translate(260 ${sueloY - 2}) scale(.82)">
        ${ordenLat.map(z => grupo(z, L[z](), false)).join('')}
      </g>
      ${cajetin(opts.titulo, 'DRON AGRÍCOLA', conf)}</g>` : ''}
    </svg>`;
  }

  // ---------------------------------------------------------------- planos por tipo de activo
  const PLANOS = {
    avion: {
      nombre: 'avión',
      zonas: ['Motor', 'Hélice', 'Célula y tren', 'Sistema de aspersión', 'Emergencia', 'Inspecciones'],
      alias: {
        'motor': 'Motor', 'helice': 'Hélice', 'hélice': 'Hélice',
        'celula y tren': 'Célula y tren', 'célula y tren': 'Célula y tren', 'celula': 'Célula y tren', 'célula': 'Célula y tren', 'tren': 'Célula y tren',
        'sistema de aspersion': 'Sistema de aspersión', 'sistema de aspersión': 'Sistema de aspersión', 'aspersion': 'Sistema de aspersión', 'aspersión': 'Sistema de aspersión',
        'emergencia': 'Emergencia', 'inspecciones': 'Inspecciones', 'inspeccion': 'Inspecciones', 'inspección': 'Inspecciones',
      },
      insignia: { zona: 'Inspecciones', glifo: 'lista', ancho: [840, 540], estrecho: [840, 540] },
      recorte: '70 72 860 612',   // en estrecho se recorta a la vista en planta
      porDefecto: 'Motor',
      svg: svgAvion,
    },
    dron: {
      nombre: 'dron',
      porModulo: true,
      zonas: ['Propulsión', 'Estructura', 'Sistema de aspersión', 'Sistema de esparcido', 'Sistema de elevación', 'Batería',
        'Radar', 'Percepción', 'Posicionamiento', 'Electrónica', 'Tren de aterrizaje', 'Control remoto'],
      opcionales: ['Sistema de esparcido', 'Sistema de elevación'],
      alias: {
        'propulsion': 'Propulsión', 'propulsión': 'Propulsión', 'motores': 'Propulsión', 'helices': 'Propulsión', 'hélices': 'Propulsión',
        'estructura': 'Estructura', 'brazos': 'Estructura', 'marco': 'Estructura',
        'sistema de aspersion': 'Sistema de aspersión', 'sistema de aspersión': 'Sistema de aspersión', 'aspersion': 'Sistema de aspersión', 'aspersión': 'Sistema de aspersión',
        'sistema de esparcido': 'Sistema de esparcido', 'esparcido': 'Sistema de esparcido',
        'sistema de elevacion': 'Sistema de elevación', 'sistema de elevación': 'Sistema de elevación', 'elevacion': 'Sistema de elevación', 'elevación': 'Sistema de elevación',
        'bateria': 'Batería', 'batería': 'Batería', 'baterias': 'Batería', 'baterías': 'Batería', 'energia': 'Batería', 'energía': 'Batería',
        'radar': 'Radar', 'percepcion': 'Percepción', 'percepción': 'Percepción', 'camaras': 'Percepción', 'cámaras': 'Percepción',
        'posicionamiento': 'Posicionamiento', 'gnss': 'Posicionamiento', 'rtk': 'Posicionamiento',
        'electronica': 'Electrónica', 'electrónica': 'Electrónica',
        'tren de aterrizaje': 'Tren de aterrizaje', 'tren': 'Tren de aterrizaje',
        'control remoto': 'Control remoto', 'radiocontrol': 'Control remoto',
      },
      insignia: { zona: 'Control remoto', glifo: 'mando', ancho: [868, 590], estrecho: [780, 620] },
      recorte: '222 96 648 640',
      porDefecto: 'Propulsión',
      svg: svgDron,
    },
  };

  // ---------------------------------------------------------------- componente
  window.diagramaAeronave = function(contenedor, componentes, opciones = {}){
    inyectarCSS();
    const cont = typeof contenedor === 'string' ? document.querySelector(contenedor) : contenedor;
    if (!cont) return null;
    const opts = Object.assign({ tipo: 'avion', lateral: true, chips: true }, opciones);
    const plano = PLANOS[opts.tipo] || PLANOS.avion;
    let grupos = agrupar(componentes, plano);
    let actual = null;

    cont.innerHTML = `<div class="avd avd-${opts.tipo === 'dron' ? 'dron' : 'avion'}">${plano.svg(opts, plano, grupos)}<div class="avd-tip" role="tooltip"></div>${opts.chips ? '<div class="avd-chips"></div>' : ''}</div>`;
    const raiz = cont.querySelector('.avd');
    const tip = raiz.querySelector('.avd-tip');
    const chips = raiz.querySelector('.avd-chips');

    function pintar(){
      raiz.querySelectorAll('[data-zona]').forEach(el => {
        const z = grupos[el.dataset.zona]; if (!z) return;
        el.classList.remove('n-sin', 'n-ok', 'n-proximo', 'n-critico', 'n-vencido');
        el.classList.add('n-' + z.nivel);
        const bd = el.querySelector('.bd');
        if (bd){
          bd.setAttribute('class', 'bd n-' + (z.alertas ? z.nivel : (z.items.length ? 'ok' : 'sin')));
          const n = bd.querySelector('[data-n]'); if (n) n.textContent = z.alertas ? z.alertas : (z.items.length ? '✓' : '–');
        }
        const sub = el.querySelector('[data-sub]');
        if (sub) sub.textContent = z.items.length
          ? `${z.items.length} ${z.items.length === 1 ? 'ítem' : 'ítems'} · ${z.alertas ? (z.alertas + (z.alertas === 1 ? ' alerta' : ' alertas')) : 'al día'}`
          : 'sin ítems';
        const an = el.querySelector('[data-anillo]');
        if (an){
          const pct = z.items.length ? Math.min(100, Math.max(3, +(z.peor?.pct) || 0)) : 0;
          an.setAttribute('stroke-dasharray', `${pct} 100`);
        }
      });
      if (chips){
        const lista = [...zonasVisibles(plano, grupos), ...(grupos['Otros'].items.length ? ['Otros'] : [])];
        chips.innerHTML = lista.map(zn => {
          const z = grupos[zn];
          return `<button type="button" class="avd-chip${actual === zn ? ' sel' : ''}" data-chip="${esc(zn)}">
            <span class="p avd-p-${z.nivel}"></span>${esc(zn)}<span class="c">${z.alertas || (z.items.length ? '✓' : '–')}</span></button>`;
        }).join('');
      }
    }

    function marcar(){
      raiz.classList.toggle('con-sel', !!actual);
      raiz.querySelectorAll('[data-zona]').forEach(el => el.classList.toggle('sel', el.dataset.zona === actual));
      if (chips) chips.querySelectorAll('[data-chip]').forEach(b => b.classList.toggle('sel', b.dataset.chip === actual));
    }

    function elegir(zona, avisar = true){
      if (!grupos[zona]) return;
      actual = zona; marcar();
      if (avisar && typeof opts.alElegir === 'function') opts.alElegir(zona, grupos[zona].items.slice(), grupos[zona]);
    }

    function mostrarTip(el, ev){
      const z = grupos[el.dataset.zona]; if (!z) return;
      const color = { vencido: '#ff8a80', critico: '#ff8a80', proximo: '#ffd166', ok: '#7fd99a', sin: '#b5bac3' }[z.nivel];
      tip.innerHTML = `<b>${esc(z.zona)}</b>
        <div class="l"><span class="p" style="background:${color}"></span>${NIVEL_TXT[z.nivel]} · ${z.items.length} ${z.items.length === 1 ? 'ítem' : 'ítems'}${z.alertas ? ` · ${z.alertas} con alerta` : ''}</div>
        ${z.peor ? `<div style="margin-top:6px">${esc(z.peor.nombre)}<div style="color:${color};font-weight:650">${esc(z.peor.plazo_txt || '')}</div></div>` : ''}`;
      const r = raiz.getBoundingClientRect();
      let x, y;
      if (ev && ev.clientX != null){ x = ev.clientX - r.left + 14; y = ev.clientY - r.top + 14; }
      else { const b = el.getBoundingClientRect(); x = b.left - r.left + b.width / 2; y = b.bottom - r.top + 6; }
      tip.classList.add('ver');
      const w = tip.offsetWidth, h = tip.offsetHeight;
      if (x + w > r.width - 4) x = Math.max(4, x - w - 28);
      if (y + h > r.height - 4) y = Math.max(4, y - h - 28);
      tip.style.left = x + 'px'; tip.style.top = y + 'px';
    }
    const ocultarTip = () => tip.classList.remove('ver');

    raiz.querySelectorAll('[data-zona]').forEach(el => {
      el.addEventListener('click', ev => { ev.stopPropagation(); elegir(el.dataset.zona); });
      el.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' '){ ev.preventDefault(); elegir(el.dataset.zona); } });
      el.addEventListener('mousemove', ev => mostrarTip(el, ev));
      el.addEventListener('mouseleave', ocultarTip);
      el.addEventListener('focus', () => mostrarTip(el));
      el.addEventListener('blur', ocultarTip);
    });
    if (chips) chips.addEventListener('click', ev => { const b = ev.target.closest('[data-chip]'); if (b) elegir(b.dataset.chip); });

    // Callouts y rótulos se ocultan cuando el dibujo queda muy estrecho (los chips los reemplazan).
    const lienzo = raiz.querySelector('svg'), vbAncho = lienzo.getAttribute('viewBox');
    const ins = raiz.querySelector('[data-ins]');
    const ajustar = () => {
      const estrecho = raiz.clientWidth < 560;
      if (estrecho === raiz.classList.contains('estrecho') && lienzo.dataset.ok) return;
      lienzo.dataset.ok = 1;
      raiz.classList.toggle('estrecho', estrecho);
      // En estrecho se recorta a la vista en planta para que la aeronave ocupe todo el ancho,
      // y la insignia se acerca al dibujo si en ancho vive junto a los callouts.
      lienzo.setAttribute('viewBox', estrecho ? plano.recorte : vbAncho);
      if (ins){
        const [x, y] = estrecho ? plano.insignia.estrecho : plano.insignia.ancho;
        ins.setAttribute('transform', `translate(${x} ${y})`);
      }
    };
    ajustar();
    if (window.ResizeObserver) new ResizeObserver(ajustar).observe(raiz);
    else window.addEventListener('resize', ajustar);

    pintar();
    if (opts.seleccion) elegir(opts.seleccion, false);

    return {
      tipo: opts.tipo,
      seleccionar: (zona, avisar = true) => elegir(zona, avisar),
      actualizar(nuevos){ grupos = agrupar(nuevos, plano); pintar(); marcar(); },
      zonas: () => grupos,
      zonaDe: c => zonaDe(c, plano),
      porDefecto: plano.porDefecto,
      peorZona(){
        return Object.values(grupos).filter(z => z.items.length)
          .sort((a, b) => ORDEN[b.nivel] - ORDEN[a.nivel] || b.cuenta.vencido - a.cuenta.vencido || b.cuenta.critico - a.cuenta.critico || b.alertas - a.alertas || (+b.peor.pct || 0) - (+a.peor.pct || 0))[0]?.zona || null;
      },
    };
  };
  window.diagramaAeronave.zonaDe = (c, tipo) => zonaDe(c, PLANOS[tipo] || PLANOS.avion);
  window.diagramaAeronave.agrupar = (componentes, tipo) => agrupar(componentes, PLANOS[tipo] || PLANOS.avion);

  // Atajos con el tipo fijado (diagramaAvion conserva su firma original).
  window.diagramaAvion = (contenedor, componentes, opciones = {}) =>
    window.diagramaAeronave(contenedor, componentes, Object.assign({}, opciones, { tipo: 'avion' }));
  window.diagramaAvion.zonaDe = c => zonaDe(c, PLANOS.avion);
  window.diagramaAvion.agrupar = componentes => agrupar(componentes, PLANOS.avion);
  window.diagramaDron = (contenedor, componentes, opciones = {}) =>
    window.diagramaAeronave(contenedor, componentes, Object.assign({}, opciones, { tipo: 'dron' }));
})();
