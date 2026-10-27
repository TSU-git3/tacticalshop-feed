// Prom competitor collector for the Ballistic listings — run with Claude in Chrome's javascript_tool on a prom.ua tab.
// `python3 ballistic/market.py js` prints this file with __QUERIES__ filled in. One request at a time, 2.5 s pause.
window.__ext = function (t) {
  const o = []; let i = 0; const k = '{"__typename":"ProductItem"';
  while ((i = t.indexOf(k, i)) >= 0) {
    let d = 0, s = false, e = false, j = i;
    for (; j < t.length; j++) {
      const c = t[j];
      if (s) { if (e) e = false; else if (c === '\\') e = true; else if (c === '"') s = false; }
      else { if (c === '"') s = true; else if (c === '{') d++; else if (c === '}') { d--; if (d === 0) break; } }
    }
    try { o.push(JSON.parse(t.slice(i, j + 1))); } catch (x) {}
    i = j + 1;
  }
  return o;
};
window.__MK = {done: false, rows: {}, log: []};
(async () => {
  const Q = __QUERIES__;
  const sl = ms => new Promise(r => setTimeout(r, ms));
  for (const q of Q) {
    for (const pg of [1, 2]) {
      let n = 0;
      try {
        const h = await (await fetch('/ua/search?search_term=' + encodeURIComponent(q) + (pg > 1 ? '&page=' + pg : ''), {credentials: 'include'})).text();
        const it = window.__ext(h); n = it.length;
        window.__MK.log.push(q + ' p' + pg + ' ' + n);
        for (const x of it) {
          const p = x.product;
          if (!p || window.__MK.rows[p.id]) continue;
          const nm = (p.name || '').replace(/[|\n]/g, ' ');
          if (!/level\s*7|layer\s*7|левел\s*7|tennier|carinthia|карентія|карінтія/i.test(nm)) continue;
          window.__MK.rows[p.id] = [p.id, ((p.company && p.company.name) || '').replace(/\|/g, '/'), p.discountedPrice || p.price,
            (p.catalogPresence && p.catalogPresence.title) || '', (p.sku || '').replace(/\|/g, '/'), nm].join('|');
        }
      } catch (e) { window.__MK.log.push(q + ' ERR ' + e.message); }
      await sl(2500);
      if (n < 20) break;
    }
  }
  window.__MK.done = true;
})();
'started';
// poll: await new Promise(r=>setTimeout(r,30000)); window.__MK.done+' '+Object.keys(window.__MK.rows).length
// then: python3 ballistic/market.py match  -> paste that JS (it classifies the offers in the page and dumps a small summary)
