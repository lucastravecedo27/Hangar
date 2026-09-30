// Añade `nombre_es` a cada pieza de un despiece (core/diagramas/<modelo>.json).
//
// Usa el MISMO traductor que la pantalla de diagramas y el panel del 3D
// (static_shell/traduccion.js), para que una pieza se llame igual en el buscador, en la lámina,
// en la bitácora y en la orden de trabajo. Por eso se carga el archivo tal cual en vez de
// reescribir el diccionario aquí: si el traductor mejora, basta con volver a pasar esto.
//
// Uso:  node herramientas/traducir_diagramas.js t100
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const raiz = path.resolve(__dirname, '..');
const modelo = (process.argv[2] || '').toLowerCase();
if (!modelo) { console.error('Uso: node herramientas/traducir_diagramas.js <modelo>'); process.exit(1); }

// traduccion.js se escribió para el navegador: espera un `window` al que colgarse.
const contexto = { window: {}, console };
vm.createContext(contexto);
vm.runInContext(fs.readFileSync(path.join(raiz, 'static_shell', 'traduccion.js'), 'utf8'), contexto);
const traducir = contexto.window.traducirPieza;

// Piezas que el Excel de DJI trae sólo con el nombre chino (la columna en inglés viene vacía).
// Se les da aquí el nombre en inglés para que no aparezcan en blanco en la lámina ni en el
// buscador; la clave es el código de pieza, que no cambia entre libros ni entre modelos.
const SIN_NOMBRE_EN = {
  'YC.JG.MY001723': 'Liquid Level Gauge Gasket',              // 液位计密封垫
  'YC.JG.MY001803': 'Distribution Board Damping Rubber',      // 分电减震软胶
  'YC.JG.MQ002156': 'Duct Tape',                              // 布基胶带
  'YC.DZ.AA000415': 'External SDR Antenna (Sleeve End)',      // 外置SDR天线（套筒端）
};

const archivo = path.join(raiz, 'core', 'diagramas', modelo + '.json');
const laminas = JSON.parse(fs.readFileSync(archivo, 'utf8'));
let n = 0;
for (const lamina of laminas) {
  for (const parte of lamina.partes || []) {
    if (!parte.nombre_en && SIN_NOMBRE_EN[parte.codigo]) parte.nombre_en = SIN_NOMBRE_EN[parte.codigo];
    parte.nombre_es = traducir(parte.nombre_en || '') || parte.nombre_en || '';
    n++;
  }
}
fs.writeFileSync(archivo, JSON.stringify(laminas, null, 1) + '\n', 'utf8');
console.log(`${n} piezas traducidas en ${laminas.length} láminas -> ${path.relative(raiz, archivo)}`);
