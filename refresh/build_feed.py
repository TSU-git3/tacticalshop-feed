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
import json, glob, os, sys, time, datetime
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(ROOT, 'catalog.json'), encoding='utf-8'))
PIDS_PATH = os.path.join(ROOT, 'pids.json')
PIDS = json.load(open(PIDS_PATH, encoding='utf-8'))
PRODUCTS = CAT['products']


def sweep_flags(max_age_h=4):
    """product_id -> in_stock flag, from search_products results saved to files this run."""
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
            except Exception:
                continue
    return flags


def plan():
    flags = sweep_flags()
    todo, skipped = [], []
    for pid in PIDS['pids']:
        if flags.get(pid) is False:
            skipped.append(pid)
        else:
            todo.append(pid)
    json.dump({'todo': todo, 'out_of_stock_by_sweep': skipped, 'flags_seen': len(flags)},
              open(os.path.join(ROOT, 'todo.json'), 'w'), ensure_ascii=False)
    print(f'flags from sweeps: {len(flags)}; get_product needed: {len(todo)}; skipped (sweep says out of stock): {len(skipped)}')


def status_for(code, stock):
    """stock: int, 'В наявності', 'Очікується надходження', None (not found)."""
    net = PRODUCTS[code]['net']
    if isinstance(stock, (int, float)) and stock > 0:
        return '+', int(stock)
    if isinstance(stock, str) and 'наявн' in stock.lower() and 'очіку' not in stock.lower():
        return '+', None
    return ('5', None) if net else ('-', 0)


def build():
    todo = json.load(open(os.path.join(ROOT, 'todo.json'), encoding='utf-8'))
    out_pids = set(todo['out_of_stock_by_sweep'])
    sizes = {}            # sku -> (stock, pid)
    looked = set()
    raw = os.path.join(ROOT, 'stock_raw.jsonl')
    for line in open(raw, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        looked.add(str(d['pid']))
        for sku, stock in d['sizes']:
            sizes[str(sku).strip()] = (stock, str(d['pid']))
    need = set(todo['todo'])
    missing = need - looked
    if len(missing) > 0.1 * max(1, len(need)):
        sys.exit(f'ABORT: only {len(need) - len(missing)} of {len(need)} products looked up — stock.xml NOT changed. Missing ids: {sorted(missing)[:50]}')
    cmap = PIDS.get('map', {})
    prev = {}
    try:
        prev = json.load(open(os.path.join(ROOT, 'last_state.json'), encoding='utf-8'))
    except Exception:
        pass
    result, unmapped, changes = {}, [], []
    for code in PRODUCTS:
        if code in sizes:
            st, pid = sizes[code]
            cmap[code] = pid
            result[code] = status_for(code, st)
        elif cmap.get(code) in out_pids:
            result[code] = status_for(code, 0)
        else:
            result[code] = status_for(code, None)
            unmapped.append(code)
        p = prev.get(code)
        if p and tuple(p) != tuple(result[code]):
            changes.append((code, p, result[code]))
    plus_prev = sum(1 for v in prev.values() if v and v[0] == '+')
    plus_now = sum(1 for v in result.values() if v[0] == '+')
    if plus_prev and plus_now < 0.5 * plus_prev and '--force' not in sys.argv:
        sys.exit(f'ABORT: in-stock items fell from {plus_prev} to {plus_now} — looks like a data problem, stock.xml NOT changed. Re-run with --force only if MyDrop really shows this.')
    # prune: keep pids that matched a code, or not yet looked up
    matched = set(cmap.values())
    keep = {pid: s for pid, s in PIDS['pids'].items() if pid in matched or pid not in looked}
    dropped = [pid for pid in PIDS['pids'] if pid not in keep]
    PIDS['pids'] = keep
    PIDS['map'] = cmap
    json.dump(PIDS, open(PIDS_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    json.dump({k: list(v) for k, v in result.items()}, open(os.path.join(ROOT, 'last_state.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    write_xml(result)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime('%Y-%m-%d %H:%M')
    cnt = {}
    for a, q in result.values():
        cnt[a] = cnt.get(a, 0) + 1
    rep = [f'# Stock refresh {now} (Kyiv)', '',
           f'- Offers: {len(result)}; status counts: {cnt}',
           f'- get_product lookups: {len(looked)}; skipped as out of stock by sweep: {len(out_pids)}',
           f'- Changed since last run: {len(changes)}',
           f'- Codes not found on MyDrop (written as out of stock / nets made to order): {len(unmapped)}',
           f'- Product ids dropped from the list (matched none of our codes): {len(dropped)}', '',
           '## Changes', ''] + [f'- {c}: {a[0]} {a[1]} → {b[0]} {b[1]}' for c, a, b in changes[:300]] + \
          ['', '## Not found on MyDrop', '', ' '.join(unmapped)]
    open(os.path.join(ROOT, 'report.md'), 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
    print('\n'.join(rep[:8]))


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
    out += ['</categories>', '<offers>']
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


if __name__ == '__main__':
    {'plan': plan, 'build': build}[sys.argv[1]]()
