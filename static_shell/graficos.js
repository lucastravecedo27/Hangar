// Gráficas en SVG, sin librerías externas: series temporales, barras, rankings y donas.
// Todas comparten paleta, rejilla, ejes y una etiqueta flotante con el valor bajo el puntero.
(function(){
  const NS = 'http://www.w3.org/2000/svg';
  const PALETA = ['#fdb913','#1a1d24','#0d9488','#9757c9','#3b6fb6','#2f8f4e','#737a86','#e0473e'];
  // Trazos finos sobre blanco: el amarillo de marca se oscurece para que la línea se lea (≥3:1).
  const TRAZO = {'#fdb913':'#c08600'};
  const trazo = c => TRAZO[String(c).toLowerCase()] || c;
  const NIVEL = {ok:'#2f8f4e', proximo:'#e8a400', critico:'#e0473e', vencido:'#b3261e'};

  // Colores que dependen del tema (claro/oscuro): se pintan con var(--…) en el atributo style, así
  // la gráfica cambia sola al pasar a oscuro sin redibujarse. En claro cada variable vale lo mismo
  // que el color original.
  const TEMA = {'#1a1d24':'var(--cat-2,#1a1d24)', '#fff':'var(--bg2,#fff)', '#ffffff':'var(--bg2,#fff)',
                '#d3d6dc':'var(--o-rejilla-base,#d3d6dc)', '#ededf0':'var(--o-rejilla,#ededf0)',
                '#c08600':'var(--acc-linea,#c08600)'};
  const tema = c => TEMA[String(c).toLowerCase()] || c;
  window.colorTema = tema;
  const el = (nombre, attrs={}, texto)=>{
    const n = document.createElementNS(NS, nombre);
    for(const k in attrs){
      n.setAttribute(k, attrs[k]);
      if((k==='fill'||k==='stroke'||k==='stop-color') && TEMA[String(attrs[k]).toLowerCase()])
        n.style.setProperty(k, tema(attrs[k]));
    }
    if(texto !== undefined) n.textContent = texto;
    return n;
  };
  const numero = (v)=> (v===null||v===undefined||isNaN(v)) ? 0 : Number(v);
  const compacto = (v)=>{
    const n = Math.abs(v);
    if(n >= 1e6) return (v/1e6).toFixed(1).replace('.0','')+' M';
    if(n >= 1e4) return Math.round(v/1e3)+' k';
    if(n >= 1e3) return (v/1e3).toFixed(1).replace('.0','')+' k';
    return Number(v).toLocaleString('es-CO', {maximumFractionDigits: n<10?1:0});
  };

  // Escala «bonita»: redondea el máximo a 1/2/5 × 10^n para que la rejilla dé números legibles.
  function escala(max, pasos=4){
    if(max <= 0) return {max:1, paso:0.25};
    const bruto = max / pasos;
    const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
    const norm = bruto / mag;
    const paso = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
    return {max: Math.ceil(max/paso)*paso, paso};
  }

  function lienzo(destino, alto){
    const nodo = typeof destino === 'string' ? document.getElementById(destino) : destino;
    if(!nodo) return null;
    nodo.innerHTML = '';
    nodo.classList.add('g-lienzo');
    const ancho = Math.max(nodo.clientWidth || nodo.parentElement?.clientWidth || 520, 260);
    const svg = el('svg', {viewBox:`0 0 ${ancho} ${alto}`, width:'100%', height:alto,
                          preserveAspectRatio:'none', role:'img'});
    svg.style.display = 'block';
    svg.style.overflow = 'visible';
    nodo.appendChild(svg);
    return {nodo, svg, ancho, alto};
  }

  function vacio(nodo, texto='Sin datos en el período.'){
    nodo.innerHTML = `<div class="empty" style="padding:34px 12px">${texto}</div>`;
  }

  // Etiqueta flotante compartida por todas las gráficas.
  let globo;
  function mostrarGlobo(nodo, x, y, html){
    if(!globo){
      globo = document.createElement('div');
      globo.className = 'g-globo';
      document.body.appendChild(globo);
    }
    globo.innerHTML = html;
    globo.classList.add('ver');
    const r = nodo.getBoundingClientRect();
    const gx = r.left + x, gy = r.top + y;
    globo.style.left = Math.min(innerWidth - globo.offsetWidth - 10, Math.max(8, gx - globo.offsetWidth/2)) + 'px';
    globo.style.top  = Math.max(8, gy - globo.offsetHeight - 12) + 'px';
  }
  function ocultarGlobo(){ if(globo) globo.classList.remove('ver'); }
  window.addEventListener('scroll', ocultarGlobo, {passive:true});

  function rejilla(svg, x0, x1, y0, y1, esc, formato){
    const pasos = Math.round(esc.max / esc.paso);
    for(let i=0; i<=pasos; i++){
      const v = esc.paso * i;
      const y = y1 - (v/esc.max) * (y1-y0);
      svg.appendChild(el('line', {x1:x0, x2:x1, y1:y, y2:y,
        stroke: i===0 ? '#d3d6dc' : '#ededf0', 'stroke-width': i===0 ? 1 : 1}));
      svg.appendChild(el('text', {x:x0-8, y:y+4, 'text-anchor':'end', class:'g-eje'},
        (formato||compacto)(v)));
    }
  }

  // ---------- Serie temporal (área + línea), una o varias series ----------
  // series: [{nombre, color, datos:[{x, y}]}]
  window.graficoLinea = function(destino, series, opciones={}){
    const alto = opciones.alto || 240;
    const c = lienzo(destino, alto); if(!c) return;
    const activas = series.filter(s=>s.datos && s.datos.length);
    if(!activas.length || activas.every(s=>s.datos.every(d=>!numero(d.y)))) return vacio(c.nodo, opciones.vacio);

    const hayDerecha = activas.some(s=>s.eje === 'derecha');
    // Con dos ejes hace falta una franja arriba para las unidades, o pisan al primer rótulo.
    const m = {t: hayDerecha ? 28 : 16, r: hayDerecha ? 52 : 14, b:26, l:48};
    const x0 = m.l, x1 = c.ancho - m.r, y0 = m.t, y1 = alto - m.b;
    const etiquetas = activas[0].datos.map(d=>d.x);
    const n = etiquetas.length;
    const px = (i)=> n === 1 ? (x0+x1)/2 : x0 + (i/(n-1)) * (x1-x0);
    // Dos series de magnitudes muy distintas (horas frente a hectáreas) se aplastan en un solo
    // eje: cada una lleva su propia escala y la segunda se rotula a la derecha.
    const izq = activas.filter(s=>s.eje !== 'derecha');
    const der = activas.filter(s=>s.eje === 'derecha');
    const escDe = (grupo)=>escala(Math.max(...grupo.flatMap(s=>s.datos.map(d=>numero(d.y))), 0));
    const escI = escDe(izq.length ? izq : activas);
    const escD = der.length ? escDe(der) : null;
    const esc = escI;
    const pyDe = (s)=>{
      const e = (s && s.eje === 'derecha' && escD) ? escD : escI;
      return (v)=> y1 - (numero(v)/e.max) * (y1-y0);
    };
    const py = pyDe(izq[0] || activas[0]);

    rejilla(c.svg, x0, x1, y0, y1, escI, opciones.formatoY);
    if(escD){
      const pasos = Math.round(escD.max / escD.paso);
      for(let i=1; i<=pasos; i++){
        const v = escD.paso * i, y = y1 - (v/escD.max) * (y1-y0);
        c.svg.appendChild(el('text', {x:x1+7, y:y+4, 'text-anchor':'start', class:'g-eje'},
                             (opciones.formatoY2||compacto)(v)));
      }
      c.svg.appendChild(el('text', {x:x1+7, y:y0-12, 'text-anchor':'start', class:'g-eje g-unidad'},
                           der[0].unidad || ''));
      c.svg.appendChild(el('text', {x:x0-8, y:y0-12, 'text-anchor':'end', class:'g-eje g-unidad'},
                           (izq[0]||activas[0]).unidad || ''));
    }

    activas.forEach((s, si)=>{
      const color = s.color || PALETA[si % PALETA.length];
      const py = pyDe(s);
      const puntos = s.datos.map((d,i)=>`${px(i)},${py(d.y)}`).join(' ');
      if(opciones.area !== false){
        const id = 'g-deg-' + Math.random().toString(36).slice(2,8);
        const defs = el('defs');
        const grad = el('linearGradient', {id, x1:'0', y1:'0', x2:'0', y2:'1'});
        grad.appendChild(el('stop', {offset:'0%', 'stop-color':color, 'stop-opacity':'.26'}));
        grad.appendChild(el('stop', {offset:'100%', 'stop-color':color, 'stop-opacity':'0'}));
        defs.appendChild(grad); c.svg.appendChild(defs);
        c.svg.appendChild(el('polygon', {points:`${px(0)},${y1} ${puntos} ${px(n-1)},${y1}`, fill:`url(#${id})`}));
      }
      c.svg.appendChild(el('polyline', {points:puntos, fill:'none', stroke:trazo(color), 'stroke-width':2.2,
                                        'stroke-linejoin':'round', 'stroke-linecap':'round'}));
      if(n <= 40) s.datos.forEach((d,i)=>c.svg.appendChild(
        el('circle', {cx:px(i), cy:py(d.y), r:2.8, fill:'#fff', stroke:trazo(color), 'stroke-width':1.8})));
    });

    // Etiquetas del eje X: se reparten para que nunca se solapen.
    const cada = Math.max(1, Math.ceil(n / Math.max(2, Math.floor((x1-x0)/72))));
    etiquetas.forEach((t,i)=>{
      if(i % cada && i !== n-1) return;
      c.svg.appendChild(el('text', {x:px(i), y:alto-8, 'text-anchor':'middle', class:'g-eje'}, t));
    });

    // Guía vertical que sigue al puntero.
    const guia = el('line', {y1:y0, y2:y1, stroke:'#c08600', 'stroke-width':1, 'stroke-dasharray':'3 3', opacity:0});
    c.svg.appendChild(guia);
    const capa = el('rect', {x:x0, y:y0, width:Math.max(1,x1-x0), height:Math.max(1,y1-y0), fill:'transparent'});
    c.svg.appendChild(capa);
    capa.addEventListener('mousemove', e=>{
      const r = c.svg.getBoundingClientRect();
      const rel = (e.clientX - r.left) / r.width * c.ancho;
      const i = Math.max(0, Math.min(n-1, Math.round(((rel - x0)/(x1-x0)) * (n-1))));
      guia.setAttribute('x1', px(i)); guia.setAttribute('x2', px(i)); guia.setAttribute('opacity', .6);
      const filas = activas.map((s,si)=>`<span><i style="background:${tema(s.color||PALETA[si%PALETA.length])}"></i>
        ${escapar(s.nombre||'')} <b>${compacto(numero(s.datos[i]?.y))}${s.unidad?' '+s.unidad:''}</b></span>`).join('');
      mostrarGlobo(c.nodo, px(i)/c.ancho * c.nodo.clientWidth, py(activas[0].datos[i]?.y),
                   `<div class="tit">${escapar(etiquetas[i])}</div>${filas}`);
    });
    capa.addEventListener('mouseleave', ()=>{ guia.setAttribute('opacity',0); ocultarGlobo(); });
    if(opciones.alClic){
      capa.style.cursor = 'pointer';
      capa.addEventListener('click', e=>{
        const r = c.svg.getBoundingClientRect();
        const rel = (e.clientX - r.left) / r.width * c.ancho;
        const i = Math.max(0, Math.min(n-1, Math.round(((rel - x0)/(x1-x0)) * (n-1))));
        ocultarGlobo();
        opciones.alClic({indice:i, etiqueta:etiquetas[i],
                         valores: activas.map(sr=>({nombre:sr.nombre, valor:numero(sr.datos[i]?.y)}))});
      });
    }
  };

  // ---------- Barras verticales, con series agrupadas (nunca apiladas) ----------
  window.graficoBarras = function(destino, etiquetas, series, opciones={}){
    const alto = opciones.alto || 240;
    const c = lienzo(destino, alto); if(!c) return;
    if(!etiquetas.length) return vacio(c.nodo, opciones.vacio);

    const m = {t:16, r:12, b:28, l:46};
    const x0 = m.l, x1 = c.ancho - m.r, y0 = m.t, y1 = alto - m.b;
    const maximo = Math.max(...series.flatMap(s=>s.datos.map(numero)), 0);
    const esc = escala(maximo);
    rejilla(c.svg, x0, x1, y0, y1, esc, opciones.formatoY);

    const paso = (x1-x0) / etiquetas.length;
    const huecoGrupo = Math.min(paso * .28, 16);
    const anchoGrupo = paso - huecoGrupo;
    const anchoBarra = Math.max(3, (anchoGrupo - (series.length-1)*3) / series.length);

    etiquetas.forEach((etq, i)=>{
      const gx = x0 + paso*i + huecoGrupo/2;
      series.forEach((s, si)=>{
        const v = numero(s.datos[i]);
        const h = esc.max ? (v/esc.max) * (y1-y0) : 0;
        const color = s.color || PALETA[si % PALETA.length];
        const x = gx + si*(anchoBarra+3);
        const barra = el('rect', {x, y: y1-h, width: anchoBarra, height: Math.max(h, v>0?1.5:0),
                                  rx: Math.min(4, anchoBarra/2), fill: color, opacity:.92});
        barra.style.transition = 'opacity .15s';
        barra.addEventListener('mouseenter', ()=>{
          barra.setAttribute('opacity', 1);
          const filas = series.map((s2,j)=>`<span><i style="background:${tema(s2.color||PALETA[j%PALETA.length])}"></i>
            ${escapar(s2.nombre||'')} <b>${compacto(numero(s2.datos[i]))}${s2.unidad?' '+s2.unidad:''}</b></span>`).join('');
          mostrarGlobo(c.nodo, (x+anchoBarra/2)/c.ancho * c.nodo.clientWidth, y1-h,
                       `<div class="tit">${escapar(etq)}</div>${filas}`);
        });
        barra.addEventListener('mouseleave', ()=>{ barra.setAttribute('opacity', .92); ocultarGlobo(); });
        if(opciones.alClic){
          barra.style.cursor = 'pointer';
          barra.addEventListener('click', ()=>{ ocultarGlobo();
            opciones.alClic({indice:i, etiqueta:etq, serie:s.nombre, valor:v,
                             valores: series.map(s2=>({nombre:s2.nombre, valor:numero(s2.datos[i])}))}); });
        }
        c.svg.appendChild(barra);
      });
    });

    const cada = Math.max(1, Math.ceil(etiquetas.length / Math.max(2, Math.floor((x1-x0)/64))));
    etiquetas.forEach((etq, i)=>{
      if(i % cada) return;
      c.svg.appendChild(el('text', {x: x0 + paso*i + paso/2, y: alto-9, 'text-anchor':'middle', class:'g-eje'}, etq));
    });
  };

  // ---------- Ranking horizontal ----------
  // filas: [{etiqueta, valor, detalle, color}]
  window.graficoRanking = function(destino, filas, opciones={}){
    const nodo = typeof destino === 'string' ? document.getElementById(destino) : destino;
    if(!nodo) return;
    if(!filas.length) return vacio(nodo, opciones.vacio);
    const max = Math.max(...filas.map(f=>numero(f.valor)), 1);
    const unidad = opciones.unidad || '';
    const clicable = !!opciones.alClic;
    nodo.innerHTML = `<div class="g-ranking">` + filas.map((f,i)=>{
      const color = f.color || opciones.color || PALETA[0];
      const ancho = Math.max(2, numero(f.valor)/max*100);
      return `<div class="g-fila${clicable?' clicable':''}" data-i="${i}"${clicable?' tabindex="0" role="button"':''}>
        <div class="g-etq" title="${escapar(f.etiqueta)}">${escapar(f.etiqueta)}</div>
        <div class="g-track"><i style="width:${ancho}%;background:${tema(color)}"></i></div>
        <div class="g-val">${compacto(f.valor)}${unidad?' '+unidad:''}
          ${f.detalle?`<span class="g-det">${escapar(f.detalle)}</span>`:''}</div>
      </div>`;
    }).join('') + `</div>`;
    if(clicable) nodo.querySelectorAll('.g-fila').forEach(fila=>{
      const activar = ()=>opciones.alClic({indice:Number(fila.dataset.i), ...filas[fila.dataset.i]});
      fila.addEventListener('click', activar);
      fila.addEventListener('keydown', e=>{ if(e.key==='Enter'||e.key===' '){ e.preventDefault(); activar(); } });
    });
  };

  // ---------- Dona ----------
  // partes: [{etiqueta, valor, color}]
  window.graficoDona = function(destino, partes, opciones={}){
    const alto = opciones.alto || 220;
    const c = lienzo(destino, alto); if(!c) return;
    const total = partes.reduce((a,p)=>a+numero(p.valor), 0);
    if(!total) return vacio(c.nodo, opciones.vacio);

    const cx = c.ancho/2, cy = alto/2, R = Math.min(cx, cy) - 12, r = R * .62;
    let ang = -Math.PI/2;
    partes.forEach((p, i)=>{
      const frac = numero(p.valor)/total;
      if(frac <= 0) return;
      const fin = ang + frac * Math.PI * 2;
      const grande = frac > .5 ? 1 : 0;
      const d = [
        `M ${cx+Math.cos(ang)*R} ${cy+Math.sin(ang)*R}`,
        `A ${R} ${R} 0 ${grande} 1 ${cx+Math.cos(fin)*R} ${cy+Math.sin(fin)*R}`,
        `L ${cx+Math.cos(fin)*r} ${cy+Math.sin(fin)*r}`,
        `A ${r} ${r} 0 ${grande} 0 ${cx+Math.cos(ang)*r} ${cy+Math.sin(ang)*r}`, 'Z',
      ].join(' ');
      const color = p.color || PALETA[i % PALETA.length];
      const trozo = el('path', {d, fill: color, opacity:.92, stroke:'#fff', 'stroke-width':1.5});
      const medio = (ang+fin)/2;
      trozo.addEventListener('mouseenter', ()=>{
        trozo.setAttribute('opacity', 1);
        mostrarGlobo(c.nodo, (cx+Math.cos(medio)*(R+r)/2)/c.ancho*c.nodo.clientWidth,
                     cy+Math.sin(medio)*(R+r)/2,
                     `<div class="tit">${escapar(p.etiqueta)}</div>
                      <span><i style="background:${tema(color)}"></i><b>${compacto(p.valor)}</b> · ${(frac*100).toFixed(1)} %</span>`);
      });
      trozo.addEventListener('mouseleave', ()=>{ trozo.setAttribute('opacity', .92); ocultarGlobo(); });
      if(opciones.alClic){
        trozo.style.cursor = 'pointer';
        trozo.addEventListener('click', ()=>{ ocultarGlobo();
          opciones.alClic({indice:i, ...p, porcentaje: frac*100, total}); });
      }
      c.svg.appendChild(trozo);
      ang = fin;
    });
    c.svg.appendChild(el('text', {x:cx, y:cy-2, 'text-anchor':'middle', class:'g-dona-n'}, compacto(total)));
    c.svg.appendChild(el('text', {x:cx, y:cy+15, 'text-anchor':'middle', class:'g-dona-l'},
                        opciones.centro || 'total'));
  };

  window.leyendaGrafica = function(destino, entradas){
    const nodo = typeof destino === 'string' ? document.getElementById(destino) : destino;
    if(!nodo) return;
    nodo.className = 'leyenda-g';
    nodo.innerHTML = entradas.map((e,i)=>
      `<span><i style="background:${tema(e.color || PALETA[i % PALETA.length])}"></i>${escapar(e.nombre)}</span>`).join('');
  };

  window.PALETA_G = PALETA;
  window.COLOR_NIVEL = NIVEL;

  // Redibuja al cambiar el tamaño: las gráficas se generan con el ancho real del contenedor.
  let temporizador;
  window.redibujarGraficas = function(fn){
    window.addEventListener('resize', ()=>{ clearTimeout(temporizador); temporizador = setTimeout(fn, 180); });
  };
})();
