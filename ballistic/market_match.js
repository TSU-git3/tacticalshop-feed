// In-page matcher (after market_collect.js is done). `python3 ballistic/market.py match` fills in __L__ etc.
// Keeps in-stock offers of other shops that match one of our listings (by our Ballistic article = their SKU, or by
// model + kind words) and dumps a compact JSON summary between MKSTART / MKEND for get_page_text.
const L = __L__, KIND = __KIND__, COL = __COL__, EXC = __EXC__, OUR = __OUR__;
const res = {};
for (const pid in L) res[pid] = [];
for (const r of Object.values(window.__MK.rows)) {
  const f = r.split('|');
  const o = {id: f[0], shop: f[1], price: +f[2], pres: f[3], sku: f[4].trim(), name: f.slice(5).join('|')};
  if (o.shop === OUR || !/Готово|В наявності/.test(o.pres) || !(o.price > 0)) continue;
  for (const pid in L) {
    const l = L[pid];
    const bySku = l.arts.includes(o.sku);
    if (!bySku) {
      if (new RegExp(EXC, 'i').test(o.name) || !new RegExp(l.model, 'i').test(o.name) || !new RegExp(KIND[l.kind][0], 'i').test(o.name)
          || (KIND[l.kind][1] && new RegExp(KIND[l.kind][1], 'i').test(o.name))) continue;
    }
    const cols = Object.keys(COL).filter(c => new RegExp(COL[c], 'i').test(o.name));
    const c = bySku ? 'sku' : (cols.join('+') || '?');
    if (c === 'sku' || c === l.colour || c === '?') res[pid].push([o.id, o.shop.slice(0, 18), o.price, c, o.name.slice(0, 45)]);
  }
}
// per listing: cheapest offer per shop; 10 same-colour + 6 colour-unknown, so the dump stays small (<15 KB)
const out = {};
for (const pid in res) {
  const best = {};
  for (const x of res[pid].sort((a, b) => a[2] - b[2])) { const k = x[1] + (x[3] === '?' ? '?' : ''); if (!best[k]) best[k] = x; }
  const v = Object.values(best);
  out[pid] = v.filter(x => x[3] !== '?').slice(0, 10).concat(v.filter(x => x[3] === '?').slice(0, 6));
}
document.body.innerHTML = '<main><pre>MKSTART\n' + JSON.stringify(out) + '\nMKEND</pre></main>';
JSON.stringify(out).length;
