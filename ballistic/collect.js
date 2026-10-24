// Ballistic stock collector — run with Claude in Chrome's javascript_tool on a ballistic.com.ua tab
// (owner's Chrome, signed in). `python3 ballistic/build_ballistic.py js` prints this file with
// __URLS__ filled in. It starts in the background; poll `window.__BAL.done`, then run DUMP below.
// One request at a time with pauses (Prom/supplier politeness rule, 12 Oct 2026).
window.__BAL = {done: false, lines: [], errors: []};
(async () => {
  const URLS = __URLS__;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const P2 = h => new DOMParser().parseFromString(h, 'text/html');
  const txt = h => { const d = P2(h); d.querySelectorAll('script,style').forEach(s => s.remove());
    return d.body.innerText.replace(/[ \t]+/g, ' ').replace(/\n\s*\n+/g, '\n'); };
  const info = t => {
    const a = t.match(/Артикул:\s*(\S+)/);
    const p = t.match(/([\d ]+)грн\s*\n?РРЦ:\s*([\d ]+)грн/);
    const st = t.match(/(В наявності(?::\s*\d+)?|Розпродано|Немає в наявності|Під замовлення[^\n]*|Очікується[^\n]*|Закінчився)\s*\n?Артикул:/);
    return {art: a && a[1], status: st ? st[1] : '?', rrp: p ? p[2].replace(/\s/g, '') : ''};
  };
  for (const [pid, u] of URLS) {
    try {
      const h = await (await fetch(u, {credentials: 'include'})).text();
      const d = P2(h);
      const form = d.querySelector('form[data-action*="load-modification"]');
      const base = info(txt(h));
      if (!form) { window.__BAL.lines.push([pid, base.art, 'ONE', base.status, base.rrp].join('|')); await sleep(1500); continue; }
      const id = form.getAttribute('data-action').match(/load-modification\/(\d+)/)[1];
      const props = {};
      form.querySelectorAll('input[type=hidden][name^="param["]').forEach(i => { props[i.name.slice(6, -1)] = {cur: i.value, opts: []}; });
      form.querySelectorAll('[data-value]').forEach(b => {
        const m = (b.getAttribute('onclick') || '').match(/j-mod-prop-([a-z0-9_]+)/i);
        if (m && props[m[1]]) props[m[1]].opts.push({v: b.dataset.value, l: b.textContent.trim().split('\n')[0].trim()});
      });
      for (const k in props) if (!props[k].opts.some(o => o.v === props[k].cur)) props[k].opts.push({v: props[k].cur, l: 'CUR'});
      const keys = Object.keys(props);
      const sizeK = keys.find(k => /razmer/.test(k)) || keys[0];
      for (const o of props[sizeK].opts) {
        const par = keys.map(k => ['param[' + k + ']', k === sizeK ? o.v : props[k].cur]);
        const r = await fetch('/catalog/load-modification/' + id + '/' + sizeK + '/', {method: 'POST', credentials: 'include',
          headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8', 'X-Requested-With': 'XMLHttpRequest'},
          body: new URLSearchParams(par).toString()});
        const j = await r.json();
        if (j.status === 'OK') {
          const x = info(txt(j.response.html.map(y => y.content).join('\n')));
          window.__BAL.lines.push([pid, x.art, o.l, x.status, x.rrp].join('|'));
        } else window.__BAL.errors.push(pid + ' ' + o.l + ' HTTP ' + (j.response && j.response.code));
        await sleep(1200);
      }
    } catch (e) { window.__BAL.errors.push(pid + ' ERR ' + e.message); }
    await sleep(1500);
  }
  window.__BAL.done = true;
})();
'started';
// DUMP (second javascript_tool call, after window.__BAL.done is true):
// document.body.innerHTML = '<main><pre>BALSTART\n' + window.__BAL.lines.join('\n') + '\nERRORS\n' + window.__BAL.errors.join('\n') + '\nBALEND</pre></main>'; window.__BAL.lines.length
