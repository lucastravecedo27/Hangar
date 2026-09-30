// Traducción EN→ES de los nombres de pieza del catálogo DJI. Compartida por la pantalla de
// diagramas y por el panel del modelo 3D, para que una misma pieza se llame igual en las dos.
(function(global){
// Traducción EN→ES del listado DJI: no es sustitución palabra a palabra, sino que separa
// núcleos y modificadores para respetar el orden y la concordancia del castellano.
const NUCLEOS={
 // Términos del despiece del T100 que el listado del T50 no traía.
 'auger':'sinfín','spinner disk':'disco esparcidor','spinner':'disco esparcidor','hopper':'tolva',
 'funnel':'embudo','feeder':'alimentador','crossbar':'travesaño','airframe':'estructura',
 'spotlight':'foco','dongle':'adaptador','stick':'palanca','dial':'rueda de ajuste',
 'scroll wheel':'rueda de desplazamiento','shutter':'obturador','array':'matriz',
 'laser radar':'radar láser','lidar':'lidar','pipe':'tubería','slider':'guía',
 'block':'bloque','support':'soporte','trap':'trampilla','insulation':'aislamiento',
 'hole':'orificio','dosing part':'pieza de dosificación','payload':'carga útil',
 'lifting':'elevación','lift':'elevación','controller':'controlador','button':'botón',
 'buttons':'botones','compression':'compresión','sponge strip':'tira de esponja',

 'sealing ring':'anillo de sellado','sealing gasket':'empaque de sellado','sealing stopper':'tapón de sellado',
 'sealing pad':'almohadilla de sellado','rubber pad':'almohadilla de goma','landing gear':'tren de aterrizaje',
 'spray lance':'lanza de aspersión','spinner disk':'disco giratorio','heat sink':'disipador',
 'silicone rubber':'goma de silicona','o-ring':'junta tórica','screw':'tornillo','nut':'tuerca',
 'bracket':'soporte','cover':'cubierta','module':'módulo','motor':'motor','hose':'manguera','shell':'carcasa',
 'frame':'marco','plate':'placa','antenna':'antena','radar':'radar','propeller':'hélice','pump':'bomba',
 'tank':'tanque','valve':'válvula','sensor':'sensor','board':'placa','light':'luz','arm':'brazo','tube':'tubo',
 'clip':'clip','foam':'espuma','sleeve':'manguito','impeller':'impulsor','filter':'filtro','cable':'cable',
 'sprinkler':'aspersor','buckle':'hebilla','base':'base','flowmeter':'caudalímetro','battery':'batería',
 'compartment':'compartimento','radiator':'radiador','fan':'ventilador','camera':'cámara','lens':'lente',
 'cap':'tapa','connector':'conector','adapter':'adaptador','spring':'resorte','piece':'pieza',
 'assembly':'conjunto','gauge':'medidor','washer':'arandela','gasket':'empaque','ring':'anillo',
 'holder':'soporte','handle':'manija','lock':'seguro','lever':'palanca','pin':'pasador','bolt':'perno',
 'wire':'cable','port':'puerto','kit':'kit','set':'juego','blade':'pala','rotor':'rotor','stator':'estátor',
 'housing':'alojamiento','body':'cuerpo','guard':'protector','mount':'montura','bumper':'parachoques',
 'hook':'gancho','strap':'correa','label':'etiqueta','sticker':'adhesivo','sponge':'esponja',
 'damping':'amortiguación','gear':'engranaje','shaft':'eje','bearing':'rodamiento','seal':'retén',
 'nozzle':'boquilla','disk':'disco','disc':'disco','box':'caja','pad':'almohadilla','cushion':'almohadilla',
 'wheel':'rueda','leg':'pata','rod':'varilla','bar':'barra','hinge':'bisagra','latch':'pestillo',
 'switch':'interruptor','button':'botón','display':'pantalla','fuse':'fusible','terminal':'borne',
 'roller':'rodillo','meter':'medidor','barometer':'barómetro','part':'pieza','sheet':'lámina','strip':'tira','buzzer':'zumbador','speaker':'altavoz','fitting':'racor','elbow':'codo','union':'unión','bush':'casquillo','stopper':'tapón','plug':'tapón','membrane':'membrana','sprayer':'aspersor',
 'coil':'bobina','magnet':'imán','bushing':'casquillo','spacer':'separador','shim':'suplemento',
 'nozzle tip':'punta de boquilla','quick release':'liberación rápida','o ring':'junta tórica',
 'gimbal':'suspensión','propeller blade':'pala de hélice','power module':'módulo de potencia',
 'circuit board':'placa de circuito','esc':'ESC','rtk':'RTK','gps':'GPS','led':'LED','fpv':'FPV',
 'harness':'mazo de cables','grommet':'pasacables','clamp':'abrazadera','duct':'conducto','vent':'respiradero',
 // Términos que aparecían en el listado DJI y quedaban sin traducir.
 'y-tee':'pieza en Y','tee':'te','hood':'visera','grating':'rejilla','grid':'rejilla','flow':'caudal',
 'lance':'lanza','aerial-electronics':'electrónica aérea','transmitter':'transmisor','receiver':'receptor',
 'permeability':'permeabilidad','outlet':'salida','inlet':'entrada','patch':'parche','crossbeam':'travesaño',
 'film':'lámina','system':'sistema','installation':'instalación','phase':'fase','detector':'detector',
 'circlip':'anillo de retención','connection':'conexión','sink':'disipador','shielding':'blindaje',
 'insert':'inserto','glue':'adhesivo','baffle':'deflector','locknut':'contratuerca','lanyard':'cordón',
 'throttle':'acelerador','core':'núcleo','panel':'panel','charger':'cargador','counterweight':'contrapeso',
 'sensors':'sensores','communicate':'comunicación','rotation':'rotación','propulsion':'propulsión',
 'rf':'RF','fpc':'FPC','sdr':'SDR','usb':'USB','ptc':'PTC',
 // Términos del despiece del T70P y del T100 (láminas de esparcido, elevación y control remoto).
 'rope':'cuerda','knob':'perilla','slot':'ranura','microphone':'micrófono','cloth':'tela',
 'screws':'tornillos','holes':'orificios','avionics':'aviónica','bus':'bus','hdmi':'HDMI',
 'air intake':'toma de aire','ball bearing':'rodamiento de bolas','end cap':'tapa de extremo',
 'limit block':'tope','duct tape':'cinta americana','reduction gearbox':'reductor',
 'flat cable':'cable plano','gauge gasket':'junta del medidor','sleeve end':'extremo del manguito',
};
// Nombres que el análisis por núcleo y modificadores no deja bien: se traducen enteros.
const FRASES={
 'plastic-coated steel wire rope':'Cable de acero plastificado',
 'cable threading hole foam pad':'Almohadilla de espuma del orificio pasacables',
 'hexagonal socket head cap screws m2.5*12':'Tornillos Allen de cabeza cilíndrica M2.5*12',
 'filter with 50 holes':'Filtro de 50 orificios',
 'quad-fisheye vision sensor module':'Módulo del sensor de visión de cuatro ojos (ojo de pez)',
 'flexible flat cable connecting right button board and core board':'Cable plano flexible entre la placa de botones derecha y la placa principal',
 'inspire 1 remote controller ball bearing':'Rodamiento de bolas (control remoto Inspire 1)',
};
const MODIF={
 'dustproof':['antipolvo','antipolvo'],'sliding':['deslizante','deslizante'],
 'r-type':['tipo R','tipo R'],'y-type':['tipo Y','tipo Y'],'ceramic':['cerámico','cerámica'],
 'quad':['de cuatro ojos','de cuatro ojos'],'fisheye':['ojo de pez','ojo de pez'],
 'phased':['en fase','en fase'],'laser':['láser','láser'],'downward':['inferior','inferior'],
 'large':['grande','grande'],'medium':['mediano','mediana'],'small':['pequeño','pequeña'],
 'single':['simple','simple'],'long':['largo','larga'],'short':['corto','corta'],
 'thermally conductive':['termoconductor','termoconductora'],'thermally':['térmicamente','térmicamente'],
 'wear resistant':['antidesgaste','antidesgaste'],'wear-resistant':['antidesgaste','antidesgaste'],
 'resistant':['resistente','resistente'],'decorative':['decorativo','decorativa'],
 'overseas':['de exportación','de exportación'],'built-in':['integrado','integrada'],
 'pause':['de pausa','de pausa'],'release':['de liberación','de liberación'],
 'scroll':['de desplazamiento','de desplazamiento'],'spreading':['de esparcido','de esparcido'],
 'hoisting':['de elevación','de elevación'],'type-c':['USB-C','USB-C'],

 'front':['delantero','delantera'],'rear':['trasero','trasera'],'upper':['superior','superior'],
 'lower':['inferior','inferior'],'top':['superior','superior'],'bottom':['inferior','inferior'],
 'left':['izquierdo','izquierda'],'right':['derecho','derecha'],'inner':['interior','interior'],
 'outer':['exterior','exterior'],'side':['lateral','lateral'],'main':['principal','principal'],
 'auxiliary':['auxiliar','auxiliar'],'centrifugal':['centrífugo','centrífuga'],'atomized':['atomizado','atomizada'],
 'soft':['flexible','flexible'],'thumb':['manual','manual'],'female':['hembra','hembra'],'male':['macho','macho'],
 'aluminum':['de aluminio','de aluminio'],'signal':['de señal','de señal'],'power':['de potencia','de potencia'],
 'vision':['de visión','de visión'],'distribution':['de distribución','de distribución'],
 'fixing':['de fijación','de fijación'],'supporting':['de soporte','de soporte'],'weight':['de peso','de peso'],
 'level':['de nivel','de nivel'],'bellow':['de fuelle','de fuelle'],'quick':['rápido','rápida'],
 'spray':['de aspersión','de aspersión'],'spraying':['de aspersión','de aspersión'],
 'water':['de agua','de agua'],'air':['de aire','de aire'],'oil':['de aceite','de aceite'],
 'rubber':['de goma','de goma'],'metal':['metálico','metálica'],'plastic':['de plástico','de plástico'],
 'anti-collision':['anticolisión','anticolisión'],'navigation':['de navegación','de navegación'],
 'forward':['frontal','frontal'],'backward':['trasero','trasera'],'solenoid':['solenoide','solenoide'],
 'binocular':['binocular','binocular'],'obstacle':['de obstáculos','de obstáculos'],'charging':['de carga','de carga'],
 'flight':['de vuelo','de vuelo'],'control':['de control','de control'],'remote':['remoto','remota'],
 'standard':['estándar','estándar'],'intelligent':['inteligente','inteligente'],'protective':['protector','protectora'],
 'fixed':['fijo','fija'],'rotating':['giratorio','giratoria'],'threaded':['roscado','roscada'],
 'aircraft':['del dron','del dron'],'weighing':['de pesaje','de pesaje'],'load':['de carga','de carga'],
 'cooling':['de refrigeración','de refrigeración'],'liquid':['de líquido','de líquido'],
 'delivery':['de suministro','de suministro'],'three-way':['de tres vías','de tres vías'],
 'anti-wear':['antidesgaste','antidesgaste'],'waterproof':['impermeable','impermeable'],
 'reflective':['reflectante','reflectante'],'conductive':['conductor','conductora'],
 'stainless':['inoxidable','inoxidable'],'positive':['positivo','positiva'],'negative':['negativo','negativa'],
 'locking':['de bloqueo','de bloqueo'],'digital':['digital','digital'],'external':['externo','externa'],'internal':['interno','interna'],'complete':['completo','completa'],
 // «One-Way Valve» es la válvula antirretorno: el técnico la busca por ese nombre, no por «una vía».
 'one-way':['antirretorno','antirretorno'],'one way':['antirretorno','antirretorno'],
 'middle':['central','central'],'sensing':['de detección','de detección'],'composite':['compuesto','compuesta'],
 'thermal':['térmico','térmica'],'coaxial':['coaxial','coaxial'],'mounting':['de montaje','de montaje'],
 'protection':['de protección','de protección'],'spacing':['de separación','de separación'],
 'straight':['recto','recta'],'flat':['plano','plana'],'adaptive':['adaptativo','adaptativa'],
 'curving':['curvado','curvada'],'torsion':['de torsión','de torsión'],'connecting':['de conexión','de conexión'],
 'sealing':['de sellado','de sellado'],'in-position':['de posición','de posición'],
 'e-shaped':['en E','en E'],'o-type':['tórico','tórica'],'type-c':['USB-C','USB-C'],
 'quick-release':['de liberación rápida','de liberación rápida'],'air-cooled':['por aire','por aire'],
 'three-phase':['trifásico','trifásica'],'three':['tres','tres'],'spread':['de esparcido','de esparcido'],
 'spreading':['de esparcido','de esparcido'],'nozzle':['de boquilla','de boquilla'],
 'mist':['de niebla','de niebla'],'socket':['de la toma','de la toma'],'curve':['curvo','curva'],
 'e-type':['tipo E','tipo E'],'c-type':['tipo C','tipo C'],'t-shaped':['en T','en T'],
 'damper':['amortiguado','amortiguada'],'three-axis':['de tres ejes','de tres ejes'],
 'force':['de fuerza','de fuerza'],'extra large':['extragrande','extragrande'],
 'drain':['de drenaje','de drenaje'],'material detection':['de detección de material','de detección de material'],
 'optional':['opcional','opcional'],'anti-rotation':['antirrotación','antirrotación'],
 'ground':['de tierra','de tierra'],'status':['de estado','de estado'],'flexible':['flexible','flexible'],
 'white':['blanco','blanca'],'black':['negro','negra'],'gray':['gris','gris'],'grey':['gris','gris'],
 'red':['rojo','roja'],'blue':['azul','azul'],'green':['verde','verde'],'yellow':['amarillo','amarilla'],
 'orange':['naranja','naranja'],
};
const CONECTOR={'of':'de','for':'para','with':'con','and':'y','to':'a','incl.':'incluye','incl':'incluye','&':'y'};
// Referencias del fabricante (M30-HC060060-55-85, T30-…): no son sustantivos, van al final tal cual.
// Un número suelto («15522 Motor», el sufijo «_02») también es referencia, no sustantivo.
const esReferencia=t=>/^\d[\d.*]*$/.test(t)||(/\d/.test(t)&&/[-A-Z]/.test(t)&&!/^[a-z]+$/.test(t));
// Palabras que pueden aparecer dentro de una medida: «OD=7.6 mm», «12.9 x 53.1 mm», «180 Degrees».
const MEDIDA=new Set(['mm','cm','m','ml','l','v','w','kg','g','x','od','id','degrees','degree','deg']);
const esMedida=c=>/\d/.test(c)&&(c.match(/[A-Za-z]+/g)||[]).every(w=>MEDIDA.has(w.toLowerCase()));

// En inglés el núcleo del compuesto va al final ("Light Sealing Ring" = anillo de la luz);
// en castellano va delante. Por eso se separan unidades núcleo+modificadores y se invierte el orden.
function traducir(en){
  if(!en) return '';
  let texto=String(en).trim();
  if(FRASES[texto.toLowerCase()]) return FRASES[texto.toLowerCase()];
  // Los paréntesis se traducen aparte y se devuelven al final.
  const coletillas=[];
  texto=texto.replace(/\(([^)]*)\)/g, (_,dentro)=>{ coletillas.push(dentro.trim()); return ' '; });

  const items=tokenizar(texto);
  // Los conectores (of, for, with…) parten la frase en tramos independientes.
  const referencias=items.filter(it=>it.t==='s').map(it=>it.v);
  const tramos=[[]], conectores=[];
  items.filter(it=>it.t!=='s').forEach(it=>{ if(it.t==='c'){ conectores.push(it.v); tramos.push([]); } else tramos[tramos.length-1].push(it); });

  const partes=tramos.map(frase=>{
    // Unidad = los modificadores que preceden a un núcleo, más ese núcleo.
    const unidades=[]; let pendientes=[];
    frase.forEach(it=>{
      if(it.t==='m'){ pendientes.push(it); return; }
      unidades.push({nucleo:it, modif:pendientes}); pendientes=[];
    });
    if(!unidades.length) return pendientes.map(m=>m.v[0]).join(' ');
    if(pendientes.length) unidades[unidades.length-1].modif=unidades[unidades.length-1].modif.concat(pendientes);
    const texto=u=>{
      const cabeza=u.nucleo.v, fem=/a$/i.test(cabeza)||/(ción|sión|dad)$/i.test(cabeza);
      const vals=u.modif.map(m=>m.v[fem?1:0]);
      // Los adjetivos conservan el orden; los complementos "de …" se invierten, porque el inglés
      // los encadena del más lejano al núcleo ("Spraying Power Module" = módulo de potencia de aspersión).
      const adj=vals.filter(v=>!/^de(l)? /.test(v)), comp=vals.filter(v=>/^de(l)? /.test(v)).reverse();
      return [cabeza, ...adj, ...comp].join(' ');
    };
    // El núcleo real es la última unidad; las anteriores la complementan, en orden inverso.
    return [texto(unidades[unidades.length-1]), ...unidades.slice(0,-1).reverse().map(texto)].join(' de ');
  });

  let s=partes[0]||'';
  for(let i=1;i<partes.length;i++) s+= (partes[i]? ' '+(conectores[i-1]||'de')+' '+partes[i] : '');
  if(referencias.length) s+=' '+referencias.join(' ');
  const femPrincipal=/a\b/i.test((s.split(' ')[0]||''));
  coletillas.forEach(c=>{
    const fichas=tokenizar(c);
    // Medidas como «OD=7.6 mm» se dejan tal cual: traducirlas desordena la cifra y la unidad.
    if(esMedida(c)){ s+=' ('+c.replace(/\s*=\s*/g,'=').replace(/\bdegrees?\b/gi,'grados')+')'; return; }
    const soloModif=fichas.every(x=>x.t==='m');
    const t=soloModif ? fichas.map(x=>x.v[femPrincipal?1:0]).join(' ') : traducir(c);
    if(!t) return;
    // Sólo se pasa a minúscula si es una palabra traducida, no una referencia tipo M15 ni una
    // sigla como CCW.
    s+=' ('+(/^[A-Z].*\d/.test(t)||/^[A-Z]{2,}\b/.test(t)?t:t.charAt(0).toLowerCase()+t.slice(1))+')';
  });
  s=s.replace(/\s{2,}/g,' ').trim();
  return s.charAt(0).toUpperCase()+s.slice(1);
}
function tokenizar(texto){
  // El listado DJI trae nombres como «Tank_Liquid Level Sensor»: el guion bajo separa palabras,
  // y sin partirlo el token entero quedaba sin traducir.
  const bruto=texto.replace(/_/g,' ').replace(/([\/,])/g,' $1 ').split(/\s+/).filter(Boolean), items=[];
  for(let i=0;i<bruto.length;){
    let hecho=false;
    for(let n=Math.min(2,bruto.length-i); n>=1 && !hecho; n--){
      const k=bruto.slice(i,i+n).join(' ').toLowerCase().replace(/[.,]$/,'');
      if(NUCLEOS[k]){ items.push({t:'n', v:NUCLEOS[k]}); i+=n; hecho=true; }
      else if(MODIF[k]){ items.push({t:'m', v:MODIF[k]}); i+=n; hecho=true; }
      else if(n===1 && CONECTOR[k]){ items.push({t:'c', v:CONECTOR[k]}); i+=n; hecho=true; }
    }
    if(!hecho){ items.push({t:esReferencia(bruto[i])?'s':'n', v:bruto[i]}); i++; }
  }
  return items;
}
  global.traducirPieza = traducir;
})(window);
