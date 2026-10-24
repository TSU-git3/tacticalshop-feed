#!/usr/bin/env python3
"""Stock refresh for stock.xml (Tactical Shop Ukraine, Kiborg/Militex via MyDrop).

Usage (run from the repo root):
  python3 refresh/build_feed.py plan    -> reads today's MyDrop search results saved by Claude Code,
                                           writes refresh/todo.json = product ids that need get_product
  python3 refresh/build_feed.py build   -> reads refresh/stock_raw.jsonl (one line per get_product),
                                           writes stock.xml, refresh/report.md, updates refresh/pids.json

Matching is by exact supplier article only (size sku == our code). No guessing.
Prices are NOT refreshed (owner, 18 Oct 2026): price comes from refresh/catalog.json.
"""
import json, glob, os, re, sys, time, datetime
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(ROOT, 'catalog.json'), encoding='utf-8'))
PIDS_PATH = os.path.join(ROOT, 'pids.json')
PIDS = json.load(open(PIDS_PATH, encoding='utf-8'))
PRODUCTS = CAT['products']
# Kits built from separately listed MyDrop parts (owner, 19 Oct 2026): refresh/kits.json
_K = json.load(open(os.path.join(ROOT, 'kits.json'), encoding='utf-8'))
KITS = {k: v['parts'] for k, v in _K['kits'].items() if k in PRODUCTS}
EXTRA_PARTS = _K.get('extra_parts', {})          # part sku (not one of our codes) -> MyDrop product id
EXTRA_PIDS = sorted(set(EXTRA_PARTS.values()))
PARTS_STATE_PATH = os.path.join(ROOT, 'kit_parts_state.json')


TITLES_PATH = os.path.join(ROOT, 'mydrop_titles.json')
NAME_OK_PATH = os.path.join(ROOT, 'name_check_ok.json')
# product-type words: a listing's first type word must also appear in the MyDrop title of its product
# (added 19 Oct 2026 after 18000 «Бронековдра» had been listed as «Бронежилет»)
TYPE_GROUPS = {
    'жилет/плитоноска': r'бронежилет|плитоноск|модульн', 'ковдра': r'ковдр|одеял',
    'пояс/РПС': r'пояс|рпс|розвантаж', 'підсумок': r'підсум|pouch|аптечк', 'напашник': r'напашник',
    'камербанд': r'камербанд', 'каремат/сидушка': r'каремат|сидушк|килим', 'сітка': r'сітк|сетк',
    'пакет/плита': r'пакет|бронекомплект|пластин|бронеплит', 'захист': r'захист',
    'ремінь/антабка': r'ремін|ремен|антабк|\bqd\b|вертлюг', 'наколінники': r'наколін|налокіт',
    'кофта': r'кофт|фліс|windblock', 'рюкзак/сумка': r'рюкзак|баул|сумк|bag', 'панель': r'панел',
    'кавер/чохол/кейс': r'кавер|чохол|кейс|case', 'лямки': r'лямк',
}


def type_groups(s):
    s = s.lower().replace('c', 'с')          # Latin c in some MyDrop titles («Cумка»)
    return {g for g, rx in TYPE_GROUPS.items() if re.search(rx, s)}


def name_check(cmap, pmap):
    """Compare each listing's product type with the MyDrop title of its product."""
    try:
        titles = json.load(open(TITLES_PATH, encoding='utf-8'))
    except Exception:
        return ['- no MyDrop titles saved yet (plan saves them from the sweeps)']
    try:
        ok = json.load(open(NAME_OK_PATH, encoding='utf-8'))
    except Exception:
        ok = {}
    code2pid = {c: p for p, c in PIDS.get('pids', {}).items()}
    code2pid.update(cmap); code2pid.update(pmap)
    bad, unclear = [], []
    for code, p in PRODUCTS.items():
        t = titles.get(code2pid.get(code) or '')
        if not t or code in ok:
            continue
        ours = p['name'].lower().replace('c', 'с')
        hits = [(re.search(rx, ours).start(), g) for g, rx in TYPE_GROUPS.items() if re.search(rx, ours)]
        if not hits:
            continue
        first = min(hits)[1]
        theirs = type_groups(t)
        if not theirs:
            unclear.append(f'- {code}: «{p["name"]}» — MyDrop: «{t.strip()}» (no type word)')
        elif first not in theirs:
            bad.append(f'- **{code}: «{p["name"]}» — MyDrop: «{t.strip()}»**')
    return (bad or ['- none']) + ([''] + ['Not checkable (MyDrop title has no type word):'] + unclear if unclear else [])


def sweep_flags(max_age_h=4, parents=None, titles=None):
    """product_id -> in_stock flag, from search_products results saved to files this run.
    If `parents` is a dict, it is filled with product_id -> parent sku."""
    flags = {}
    pats = [os.path.expanduser('~/.claude/projects/**/tool-results/*search_products*'),
            os.path.expanduser('~/.claude/projects/**/tool-results/*.json'),
            os.path.expanduser('~/.claude/projects/**/tool-results/*.txt'),
            os.path.join(ROOT, 'sweeps', '*')]
    now = time.time()
    for pat in pats:
        for f in glob.glob(pat, recursive=True):
            if now - os.path.getmtime(f) > max_age_h * 3600:
                continue
            try:
                t = open(f, encoding='utf-8').read()
                d = json.loads(t)
                if isinstance(d, list):
                    d = json.loads(d[0]['text'])
                for it in d.get('items', []):
                    if it.get('vendor_id') == 521223:
                        flags[str(it['product_id'])] = bool(it.get('in_stock'))
                        if titles is not None and it.get('title'):
                            titles[str(it['product_id'])] = it['title']
                        if parents is not None and it.get('sku'):
                            parents[str(it['product_id'])] = str(it['sku']).strip()
            except Exception:
                continue
    return flags


def plan():
    parents, titles = {}, {}
    flags = sweep_flags(parents=parents, titles=titles)
    if titles:
        try:
            old_t = json.load(open(TITLES_PATH, encoding='utf-8'))
        except Exception:
            old_t = {}
        old_t.update(titles)
        json.dump(old_t, open(TITLES_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    # Self-heal the product list: a sweep product whose parent sku equals one of our codes EXACTLY
    # is ours (added 19 Oct 2026 after 34 codes were missed because their product ids weren't listed).
    pmap = PIDS.setdefault('parent', {})
    added = 0
    for pid, sku in parents.items():
        if sku in PRODUCTS:
            pmap[sku] = pid
            if pid not in PIDS['pids']:
                PIDS['pids'][pid] = sku
                added += 1
    json.dump(PIDS, open(PIDS_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    small = '--small' in sys.argv
    scope = sorted(set(PIDS['pids']) | set(EXTRA_PIDS))
    if small:
        # small check: only products that hold a code currently in stock («+») in last_state.json
        prev = json.load(open(os.path.join(ROOT, 'last_state.json'), encoding='utf-8'))
        cm, pm = PIDS.get('map', {}), PIDS.get('parent', {})
        plus = {c for c, v in prev.items() if v and v[0] == '+'}
        # a kit in stock from its parts: re-check all its parts too
        for kit in [k for k in KITS if k in plus]:
            for sku, _n in KITS[kit]:
                plus.add(sku)
        scope = {cm.get(c) or pm.get(c) for c in plus} | {EXTRA_PARTS[c] for c in plus if c in EXTRA_PARTS}
        scope = sorted(scope - {None})
    todo, skipped = [], []
    for pid in scope:
        if flags.get(pid) is False:
            skipped.append(pid)
        else:
            todo.append(pid)
    json.dump({'todo': todo, 'out_of_stock_by_sweep': skipped, 'flags_seen': len(flags),
               'mode': 'small' if small else 'big'},
              open(os.path.join(ROOT, 'todo.json'), 'w'), ensure_ascii=False)
    print(f'product ids added from sweeps (exact parent sku): {added}')
    print(f'flags from sweeps: {len(flags)}; get_product needed: {len(todo)}; skipped (sweep says out of stock): {len(skipped)}')


NET_DAYS = '5'     # camo nets made to order (owner, 18 Oct 2026)
OTHER_DAYS = '3'   # every other product made to order (owner, 19 Oct 2026)
READY_MIN = 2      # Prom CSV: in stock with MORE than this many units -> '!' «Готово до відправки» (owner, 22 Oct 2026)


def status_for(code, stock):
    """stock: int, 'В наявності', 'Очікується надходження', or None = code NOT on MyDrop.
    In stock -> '+'. On MyDrop but out of stock -> made to order: nets 5 days, others 3 days.
    Not on MyDrop at all -> '-' (owner, 19 Oct 2026: not on MyDrop = not sold)."""
    net = PRODUCTS[code]['net']
    if isinstance(stock, (int, float)) and stock > 0:
        return '+', int(stock)
    if isinstance(stock, str) and 'наявн' in stock.lower() and 'очіку' not in stock.lower():
        return '+', None
    if stock is None:
        return '-', 0
    return (NET_DAYS if net else OTHER_DAYS), None


def build():
    todo = json.load(open(os.path.join(ROOT, 'todo.json'), encoding='utf-8'))
    out_pids = set(todo['out_of_stock_by_sweep'])
    small = todo.get('mode') == 'small' 
    sizes = {}            # sku -> (stock, pid)
    looked = set()
    raw = os.path.join(ROOT, 'stock_raw.jsonl')
    for line in open(raw, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        looked.add(str(d['pid']))
        if d.get('sku'):
            PIDS.setdefault('parent', {})
            if str(d['sku']).strip() in PRODUCTS:
                PIDS['parent'][str(d['sku']).strip()] = str(d['pid'])
        for sku, stock in d['sizes']:
            sizes[str(sku).strip()] = (stock, str(d['pid']))
    need = set(todo['todo'])
    missing = need - looked
    if len(missing) > 0.1 * max(1, len(need)):
        sys.exit(f'ABORT: only {len(need) - len(missing)} of {len(need)} products looked up — stock.xml NOT changed. Missing ids: {sorted(missing)[:50]}')
    cmap = PIDS.get('map', {})
    pmap = PIDS.get('parent', {})
    prev = {}
    try:
        prev = json.load(open(os.path.join(ROOT, 'last_state.json'), encoding='utf-8'))
    except Exception:
        pass
    result, unmapped, changes, on_md_out = {}, [], [], []
    for code in PRODUCTS:
        if small and code not in sizes and prev.get(code) and not (
                {cmap.get(code), pmap.get(code)} & (looked | out_pids)):
            result[code] = tuple(prev[code])      # not part of this small check: keep last value
            continue
        if code in sizes:
            st, pid = sizes[code]
            cmap[code] = pid
            result[code] = status_for(code, st)
        elif cmap.get(code) in out_pids or cmap.get(code) in looked \
                or pmap.get(code) in out_pids or pmap.get(code) in looked:
            # on MyDrop (exact sku known) but no size with stock: sweep says out of stock,
            # or get_product lists no size with this sku -> out of stock, NOT "not found"
            result[code] = status_for(code, 0)
            on_md_out.append(code)
        else:
            result[code] = status_for(code, None)
            unmapped.append(code)
        p = prev.get(code)
        if p and tuple(p) != tuple(result[code]):
            changes.append((code, p, result[code]))
    kit_lines, pstate = apply_kits(result, sizes, out_pids, looked)
    changes = [ch for ch in changes if ch[0] not in KITS]
    for code in KITS:
        p = prev.get(code)
        if p and tuple(p) != tuple(result[code]):
            changes.append((code, p, result[code]))
    plus_prev = sum(1 for v in prev.values() if v and v[0] == '+')
    plus_now = sum(1 for v in result.values() if v[0] == '+')
    if plus_prev and plus_now < 0.5 * plus_prev and '--force' not in sys.argv:
        sys.exit(f'ABORT: in-stock items fell from {plus_prev} to {plus_now} — looks like a data problem, stock.xml NOT changed. Re-run with --force only if MyDrop really shows this.')
    save_parts_state(pstate)
    # prune: keep pids that matched a code, or not yet looked up
    matched = set(cmap.values()) | set(pmap.values())
    keep = {pid: s for pid, s in PIDS['pids'].items() if small or pid in matched or pid not in looked or pid in EXTRA_PIDS}
    dropped = [pid for pid in PIDS['pids'] if pid not in keep]
    PIDS['pids'] = keep
    PIDS['map'] = cmap
    PIDS['parent'] = pmap
    json.dump(PIDS, open(PIDS_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    json.dump({k: list(v) for k, v in result.items()}, open(os.path.join(ROOT, 'last_state.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    write_xml(result)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')
    cnt = {}
    for a, q in result.values():
        cnt[a] = cnt.get(a, 0) + 1
    rep = [f'# Stock refresh {now} (Kyiv) — ' + ('SMALL check (in-stock items only)' if small else 'BIG check'), '',
           f'- Offers: {len(result)}; status counts: {cnt}',
           f'- get_product lookups: {len(looked)}; skipped as out of stock by sweep: {len(out_pids)}',
           f'- Changed since last run: {len(changes)}',
           f'- On MyDrop but out of stock (no size with stock): {len(on_md_out)}',
           f'- Codes not found on MyDrop (written as out of stock «-»): {len(unmapped)}',
           f'- Product ids dropped from the list (matched none of our codes): {len(dropped)}', '',
           '## Changes', ''] + [f'- {c}: {a[0]} {a[1]} → {b[0]} {b[1]}' for c, a, b in changes[:300]] + \
          ['', '## Kits in stock from their parts (kits.json)', ''] + kit_lines + \
          ['', '## Name check — listing type vs MyDrop title (fix any line in bold before it sells)', ''] + name_check(cmap, pmap) + \
          ['', '## Not found on MyDrop', '', ' '.join(unmapped)]
    open(os.path.join(ROOT, 'report.md'), 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
    print('\n'.join(rep[:8]))


def part_status(stock):
    if isinstance(stock, (int, float)) and stock > 0:
        return '+', int(stock)
    if isinstance(stock, str) and 'наявн' in stock.lower() and 'очіку' not in stock.lower():
        return '+', None
    return OTHER_DAYS, None


def apply_kits(result, sizes, out_pids=(), looked=()):
    """Kit with no stock of its own on MyDrop but every part in stock -> in stock (owner, 19 Oct 2026).
    Quantity = number of complete kits (lowest part stock / parts needed); no number if a part has none.
    A kit that is not on MyDrop at all ('-') stays '-'."""
    try:
        pstate = json.load(open(PARTS_STATE_PATH, encoding='utf-8'))
    except Exception:
        pstate = {}
    for sku, pid in EXTRA_PARTS.items():
        if sku in sizes:
            pstate[sku] = list(part_status(sizes[sku][0]))
        elif pid in out_pids or pid in looked:
            pstate[sku] = [OTHER_DAYS, None]      # product out of stock / size not listed
    lines = []
    for kit, parts in KITS.items():
        own = result[kit]
        if own[0] == '+' and kit not in sizes:
            # MyDrop kits have no sizes, so a '+' here was derived from parts earlier -> recompute
            own = result[kit] = (OTHER_DAYS, None)
        if own[0] == '+' or own[0] == '-':
            continue
        counts, ok = [], True
        for sku, n in parts:
            st = result.get(sku) if sku in PRODUCTS else tuple(pstate.get(sku, ('?', None)))
            if not st or st[0] != '+':
                ok = False
                break
            if st[1] is not None:
                if st[1] // n < 1:
                    ok = False
                    break
                counts.append(st[1] // n)
            else:
                counts.append(None)
        if ok:
            q = None if (not counts or None in counts) else min(counts)
            result[kit] = ('+', q)
            lines.append(f'- {kit}: + {q if q is not None else "(no number)"}')
    return lines, pstate


def save_parts_state(pstate):
    json.dump(pstate, open(PARTS_STATE_PATH, 'w', encoding='utf-8'), ensure_ascii=False)


def write_xml(result):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')
    cats = CAT['categories']
    used = {str(p['cat']) for p in PRODUCTS.values()}
    used |= {str(cats[c][1]) for c in used if c in cats and cats[c][1]}
    out = ['<?xml version="1.0" encoding="UTF-8"?>', f'<yml_catalog date="{now}">', '<shop>',
           '<name>Tactical Shop Ukraine</name>', '<company>Tactical Shop Ukraine</company>', '<url>https://tacticalshop.com.ua</url>',
           '<currencies><currency id="UAH" rate="1"/></currencies>', '<categories>']
    for cid in sorted(used, key=lambda x: int(x)):
        if cid in cats:
            n, p = cats[cid]
            out.append(f'<category id="{cid}"' + (f' parentId="{p}"' if p else '') + f'>{escape(n)}</category>')
    bal = ballistic_offers()
    if bal:
        out.append('<category id="9810">Зимовий одяг Level 7</category>')
    out += ['</categories>', '<offers>']
    out += bal
    for code, p in PRODUCTS.items():
        a, q = result[code]
        if a == '+':
            avail, status = 'true', 'в наявності'
        elif a.isdigit():
            avail, status, q = 'true', f'під замовлення {a} дн.', None
        else:
            avail, status, q = 'false', 'немає в наявності', 0
        o = [f'<offer id="{escape(code)}" available="{avail}">', f'<name>{escape(p["name"])}</name>',
             f'<price>{p["price"]}</price>', '<currencyId>UAH</currencyId>', f'<categoryId>{p["cat"]}</categoryId>',
             f'<vendor>{escape(p["vendor"])}</vendor>', f'<vendorCode>{escape(code)}</vendorCode>']
        o += [f'<picture>{escape(u)}</picture>' for u in p['pics']]
        if q is not None:
            o.append(f'<quantity_in_stock>{q}</quantity_in_stock>')
        o.append(f'<param name="Наявність Prom">{escape(status)}</param></offer>')
        out.append(''.join(o))
    out += ['</offers>', '</shop>', '</yml_catalog>']
    open(os.path.join(os.path.dirname(ROOT), 'stock.xml'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    write_prom_csv(result)


def ballistic_offers():
    """Ballistic Level 7 offers for stock.xml (owner, 24 Oct 2026: HugeProfit gets this supplier too).
    Data: ballistic/catalog.json + ballistic/state.json, written by ballistic/build_ballistic.py.
    Every Kiborg run keeps them as last written; only the Ballistic run changes them."""
    bdir = os.path.join(os.path.dirname(ROOT), 'ballistic')
    try:
        bcat = json.load(open(os.path.join(bdir, 'catalog.json'), encoding='utf-8'))['products']
        bst = json.load(open(os.path.join(bdir, 'state.json'), encoding='utf-8'))['state']
    except (OSError, ValueError, KeyError):
        return []
    out = []
    for pid, p in bcat.items():
        for code, s in p['sizes'].items():
            a, q, price = bst.get(code, ['-', 0, s['price']])
            avail = 'true' if a == '+' else 'false'
            status = 'в наявності' if a == '+' else 'немає в наявності'
            o = [f'<offer id="{escape(code)}" available="{avail}">', f'<name>{escape(p["name_ua"] + ", " + s["size"] + ", оригінал")}</name>',
                 f'<price>{price}</price>', '<currencyId>UAH</currencyId>', '<categoryId>9810</categoryId>',
                 f'<vendor>{escape(p["brand"])}</vendor>', f'<vendorCode>{escape(code)}</vendorCode>']
            o += [f'<picture>{escape(u)}</picture>' for u in p['pics']]
            if a == '+' and q is not None:
                o.append(f'<quantity_in_stock>{q}</quantity_in_stock>')
            elif a != '+':
                o.append('<quantity_in_stock>0</quantity_in_stock>')
            o.append(f'<param name="Наявність Prom">{escape(status)}</param></offer>')
            out.append(''.join(o))
    return out


PROM_DIR = os.path.join(os.path.dirname(ROOT), 'prom')
PROM_HDR = ['Код_товару', 'Унікальний_ідентифікатор', 'Ідентифікатор_товару', 'ID_групи_різновидів',
            'Ціна', 'Валюта', 'Одиниця_виміру', 'Наявність', 'Кількість']


def write_prom_csv(result):
    """prom/prom_stock.csv — pulled by Prom's import-by-link (owner, 20 Oct 2026: XML can't carry
    «під замовлення», Prom's CSV can). Наявність: '+' / days ('3', '5') / '-'. Only rows that exist
    on Prom (prom/uid_map.json, matched by Унікальний_ідентифікатор). Stock and price only — the
    names / phrases / HTML fields belong to the SEO project and are never written here."""
    import csv
    umap = json.load(open(os.path.join(PROM_DIR, 'uid_map.json'), encoding='utf-8'))['map']
    rows = []
    for code, u in umap.items():
        if code not in result:
            continue
        a, q = result[code]
        if a == '+':
            # Owner, 22 Oct 2026: more than READY_MIN units -> '!' («Готово до відправки»);
            # 2 or fewer, or no count from MyDrop -> '+' («В наявності»). Re-applied on every run,
            # so items move both ways as stock changes. stock.xml (HugeProfit) is not affected.
            nal = '!' if (q is not None and q > READY_MIN) else '+'
            kil = '' if q is None else str(q)
        elif a.isdigit():
            nal, kil = a, ''
        else:
            nal, kil = '-', '0'
        rows.append([code, u['uid'], 'KIB-' + code, u['grp'], str(PRODUCTS[code]['price']), 'UAH', u['unit'], nal, kil])
    content_path = os.path.join(PROM_DIR, 'content.csv')
    if os.path.exists(content_path):
        # FIRST-IMPORT MODE (owner, 20 Oct 2026): the first link import also updates names, phrases,
        # descriptions and groups. prom/content.csv = SEO master + Import fixes (no photos, no
        # characteristics, no private notes); price / Наявність / Кількість are overlaid here.
        # Delete prom/content.csv once the owner confirms that import -> back to stock + price only,
        # so a later run can never put back old names over SEO's newer ones.
        live = {r[1]: r for r in rows}
        with open(content_path, encoding='utf-8', newline='') as f:
            crow = list(csv.reader(f))
        ch, body = crow[0], crow[1:]
        ci = {k: n for n, k in enumerate(ch)}
        out = []
        for r in body:
            s = live.get(r[ci['Унікальний_ідентифікатор']])
            if not s:
                continue
            r = list(r)
            r[ci['Ціна']], r[ci['Наявність']], r[ci['Кількість']] = s[4], s[7], s[8]
            out.append(r)
        hdr, rows = ch, out
    else:
        hdr = PROM_HDR
    with open(os.path.join(PROM_DIR, 'prom_stock.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(hdr)
        w.writerows(rows)


def prom():
    """Rewrite prom/prom_stock.csv from refresh/last_state.json (no look-ups)."""
    prev = json.load(open(os.path.join(ROOT, 'last_state.json'), encoding='utf-8'))
    write_prom_csv({c: tuple(v) for c, v in prev.items()})
    print('prom_stock.csv written')


def split():
    """Split todo.json into batches of ~28 ids for parallel haiku sub-agents (refresh/work/ids_<n>.txt)."""
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 28
    todo = json.load(open(os.path.join(ROOT, 'todo.json'), encoding='utf-8'))['todo']
    work = os.path.join(ROOT, 'work')
    os.makedirs(work, exist_ok=True)
    for f in glob.glob(os.path.join(work, '*')):
        os.remove(f)
    n = 0
    for i in range(0, len(todo), size):
        n += 1
        open(os.path.join(work, f'ids_{n}.txt'), 'w').write('\n'.join(todo[i:i + size]) + '\n')
    print(f'{len(todo)} ids -> {n} batches in refresh/work/ (ids_1.txt … ids_{n}.txt). '
          f'Start one haiku sub-agent per batch with: "Read refresh/LOOKUP_AGENT.md and do it with N=<n>."')


def merge():
    """Concatenate refresh/work/raw_<n>.jsonl into refresh/stock_raw.jsonl; list ids still missing."""
    todo = json.load(open(os.path.join(ROOT, 'todo.json'), encoding='utf-8'))['todo']
    seen, lines, bad = {}, [], 0
    for f in sorted(glob.glob(os.path.join(ROOT, 'work', 'raw_*.jsonl'))):
        for line in open(f, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                bad += 1
                continue
            if 'error' in d or 'sizes' not in d:
                continue
            seen[str(d['pid'])] = line
    missing = [p for p in todo if p not in seen]
    open(os.path.join(ROOT, 'stock_raw.jsonl'), 'w', encoding='utf-8').write('\n'.join(seen[p] for p in todo if p in seen) + '\n')
    open(os.path.join(ROOT, 'work', 'missing.txt'), 'w').write('\n'.join(missing) + ('\n' if missing else ''))
    print(f'merged {len(seen)} of {len(todo)} products; bad lines {bad}; missing {len(missing)}' +
          (' -> re-run them: one haiku sub-agent with N=missing (ids in refresh/work/ids_missing.txt)' if missing else ''))
    if missing:
        open(os.path.join(ROOT, 'work', 'ids_missing.txt'), 'w').write('\n'.join(missing) + '\n')



def restate():
    """Re-apply the stock rules to refresh/last_state.json without new look-ups
    (codes listed under «Not found on MyDrop» in report.md count as not on MyDrop)."""
    prev = json.load(open(os.path.join(ROOT, 'last_state.json'), encoding='utf-8'))
    rep = open(os.path.join(ROOT, 'report.md'), encoding='utf-8').read()
    nf = set(rep.split('## Not found on MyDrop', 1)[1].split()) if '## Not found on MyDrop' in rep else set()
    res = {}
    for code in PRODUCTS:
        a, q = prev[code]
        res[code] = (a, q) if a == '+' else status_for(code, None if code in nf else 0)
    json.dump({k: list(v) for k, v in res.items()}, open(os.path.join(ROOT, 'last_state.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    write_xml(res)
    cnt = {}
    for a, q in res.values():
        cnt[a] = cnt.get(a, 0) + 1
    print('restated:', cnt, '; not on MyDrop:', len(nf & set(PRODUCTS)))



def kits():
    """Re-apply the kit rule to refresh/last_state.json without new look-ups (parts from last_state /
    kit_parts_state.json). MyDrop kits have no sizes of their own, so a kit's own status is never '+'."""
    prev = json.load(open(os.path.join(ROOT, 'last_state.json'), encoding='utf-8'))
    res = {c: tuple(prev[c]) for c in PRODUCTS}
    lines, pstate = apply_kits(res, {})
    save_parts_state(pstate)
    json.dump({k: list(v) for k, v in res.items()}, open(os.path.join(ROOT, 'last_state.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    write_xml(res)
    print('\n'.join(lines) or 'no kit in stock from parts')


if __name__ == '__main__':
    {'plan': plan, 'build': build, 'split': split, 'merge': merge, 'restate': restate, 'kits': kits, 'prom': prom}[sys.argv[1]]()
