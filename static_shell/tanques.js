// Tanques animados compartidos: los depósitos de combustible y los tanques de insumos de la
// bodega se dibujan igual. El recipiente es un cilindro (o tambor, garrafa, IBC) con el líquido
// del color de lo que contiene y una ola SVG que se desplaza encima. El estilo vive en
// modulos.css (.tanque, .cil, .liquido).
//
//   Tanques.html({pct, color, forma, clase, attrs, cuerpo})  → tarjeta clicable completa
//   Tanques.cilindro({pct, color, forma})                     → sólo el recipiente
//   llenarTanques(raiz)                                        → sube el líquido con animación
(function(){
  const OLA = 'M0 4 Q12.5 0 25 4 T50 4 T75 4 T100 4 T125 4 T150 4 T175 4 T200 4 V8 H0Z';
  const limitar = p => (p === null || p === undefined || isNaN(p)) ? 0 : Math.max(0, Math.min(100, Number(p)));

  function cilindro({pct = 0, color = '#9aa0aa', forma = ''} = {}){
    return `<div class="cil ${forma && forma !== 'tanque' ? forma : ''}"><div class="liquido" style="height:0%;background:${color}" data-h="${limitar(pct)}">
      <svg viewBox="0 0 200 8" preserveAspectRatio="none"><path d="${OLA}" fill="${color}"/></svg></div>
      <div class="marcas"><i></i><i></i><i></i><i></i><i></i></div></div>`;
  }

  window.Tanques = {
    cilindro,
    html({pct, color, forma, clase = '', attrs = '', cuerpo = ''} = {}){
      return `<button class="tanque ${clase}" type="button" ${attrs}>
    ${cilindro({pct, color, forma})}
    ${cuerpo}
  </button>`;
    },
    // Semáforo del nivel: por debajo del 10 % crítico, del 20 % bajo.
    alerta(pct){ return pct != null && pct < 10 ? 'critico' : (pct != null && pct < 20 ? 'bajo' : ''); },
    llenar(raiz){
      requestAnimationFrame(()=>(raiz || document).querySelectorAll('.liquido').forEach(l=>l.style.height = l.dataset.h + '%'));
    },
  };
  window.llenarTanques = raiz => window.Tanques.llenar(raiz);
})();
