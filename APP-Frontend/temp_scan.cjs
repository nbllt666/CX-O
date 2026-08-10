const fs = require('fs');
const d = fs.readdirSync('dist/assets').filter((f) => f.startsWith('index-') && f.endsWith('.js'));
const b = fs.readFileSync('dist/assets/' + d[0], 'utf8');
const re = /(?:const|var)\s+([A-Za-z_$]+)\s*=\s*require\s*,\s*\1\s*\(\s*"([a-z]+)"\s*\)/g;
let m, n = 0;
const seen = new Set();
while ((m = re.exec(b))) { n++; seen.add(m[2]); console.log('require("' + m[2] + '") at', m.index); }
console.log('total shims:', n, 'unique builtins:', Array.from(seen));
