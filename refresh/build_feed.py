#!/usr/bin/env python3
"""Stock refresh for stock.xml (Tactical Shop Ukraine, Kiborg/Militex via MyDrop).

Two HugeProfit links since 14 Nov 2026 (owner): stock.xml = Kiborg / Militex only; ballistic.xml = the Ballistic supplier
(write_ballistic_xml, called by ballistic/build_ballistic.py). Names, photos and «Prom ID» in both come from
prom/prom_live.json (the shop's own Prom feed; `promjs` / `promlive`); prices and stock from the supplier checks.

Usage (run from the repo root):
  python3 refresh/build_feed.py plan    -> reads today's MyDrop search results saved by Claude Code,
                                           writes refresh/todo.json = product ids that need get_product
  python3 refresh/build_feed.py build   -> reads refresh/stock_raw.jsonl (one line per get_product),
                                           writes stock.xml, refresh/report.md, updates refresh/pids.json

Matching is by exact supplier article only (size sku == our code). No guessing.
Prices are NOT refreshed (owner, 18 Oct 2026): price comes from refresh/catalog.json, except the codes in
refresh/price_override.json (owner's own prices below MyDrop RRP, 5 Nov 2026), which win in every output.
"""
import json, glob, os, re, sys, time, datetime
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.abspath(__file__))
CAT = json.load(open(os.path.join(ROOT, 'catalog.json'), encoding='utf-8'))
PIDS_PATH = os.path.join(ROOT, 'pids.json')
PIDS = json.load(open(PIDS_PATH, encoding='utf-8'))
PRODUCTS = CAT['products']
# Owner's own retail prices (owner, 5 Nov 2026 — plate carriers below MyDrop RRP): they replace the catalog
# price in stock.xml and prom/prom_stock.csv. catalog.json keeps the MyDrop RRP and is never written back.
OVERRIDE_PATH = os.path.join(ROOT, 'price_override.json')
PRICE_OVERRIDE = json.load(open(OVERRIDE_PATH, encoding='utf-8'))['prices'] if os.path.exists(OVERRIDE_PATH) else {}
for _c, _o in PRICE_OVERRIDE.items():
    if _c in PRODUCTS:
        PRODUCTS[_c]['price'] = _o['price']
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
    now = datetime.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
    cnt = {}
    for a, q in result.values():
        cnt[a] = cnt.get(a, 0) + 1
    rep = [f'# Stock refresh {now} (Kyiv) — ' + ('SMALL check (in-stock items only)' if small else 'BIG check'), '',
           f'- Offers: {len(result)}; status counts: {cnt}',
           f'- get_product lookups: {len(looked)}; skipped as out of stock by sweep: {len(out_pids)}',
           f'- Changed since last run: {len(changes)}',
           f'- On MyDrop but out of stock (no size with stock): {len(on_md_out)}',
           f'- Codes not found on MyDrop (written as out of stock «-»): {len(unmapped)}',
           f'- Product ids dropped from the list (matched none of our codes): {len(dropped)}',
           f'- Owner price overrides applied (refresh/price_override.json): {sum(c in PRODUCTS for c in PRICE_OVERRIDE)} of {len(PRICE_OVERRIDE)}', '',
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


# ---- Prom live data (owner, 14 Nov 2026: the HugeProfit XMLs carry the CURRENT Prom names, photos and Prom IDs) ----
# prom/prom_live.json = what the shop's own Prom product feed shows for our listings: Prom ID -> Код_товару, UA name,
# photo ids, Prom group. Refreshed by the Ballistic run (`promjs` / `promlive`, ballistic/RUNBOOK.md step 2b). Every
# output falls back to the catalog name / supplier photos for a listing that is not in it.
PROM_LIVE_PATH = os.path.join(os.path.dirname(ROOT), 'prom', 'prom_live.json')
IMG = 'https://images.prom.ua/'


def load_live():
    try:
        return json.load(open(PROM_LIVE_PATH, encoding='utf-8'))
    except (OSError, ValueError):
        return {'items': {}, 'cats': {}}


def live_name_pics(live, uid):
    """(name, [photo urls]) as on Prom now, or (None, None) when the listing is not in prom_live.json."""
    it = live['items'].get(str(uid))
    if not it:
        return None, None
    slug, ids = it[2], it[3]
    if slug == '*':
        pics = [IMG + x for x in ids.split(',') if x]
    else:
        pics = [IMG + x + '_' + slug for x in ids.split(',') if x]
    return (it[1] or None), (pics or None)


def live_groups(live):
    """Prom variant group -> names of its listings (to see when a base listing's name leaves its own size out)."""
    g = {}
    for it in live['items'].values():
        if it[5]:
            g.setdefault(it[5], []).append(it[1])
    return g


SIZES = {'XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', '2XL', '3XL', 'XXXL'}


def with_size(name, token, siblings, sizes=None):
    """Owner's rule (13 Nov 2026): the BASE listing of a size group carries no size in its Prom name («…, мультикам»),
    its variants do («…, мультикам, M»). In HugeProfit each size is its own product, so the base gets its size back —
    only when the group's other names prove the pattern (this name + «, X», or «, X» before «, оригінал») and, for
    Kiborg / Militex codes (sizes=SIZES), only when the code ends in a clothing size and X is one too. Never guessed."""
    END = ', оригінал'
    if not token or not name or token in [x.strip() for x in name.split(',')] or (sizes is not None and token not in sizes):
        return name
    if name.endswith(END):
        stem = name[:-len(END)]
        mid = [x[len(stem) + 2:-len(END)] for x in siblings if x != name and x.startswith(stem + ', ') and x.endswith(END)]
        if any(m and ',' not in m for m in mid):
            return stem + ', ' + token + END
    tails = [x[len(name) + 2:] for x in siblings if x.startswith(name + ', ')]
    if any(t and ',' not in t and (sizes is None or t in sizes) for t in tails):
        return name + ', ' + token
    return name


def xml_head(now, cat_lines):
    return ['<?xml version="1.0" encoding="UTF-8"?>', f'<yml_catalog date="{now}">', '<shop>',
            '<name>Tactical Shop Ukraine</name>', '<company>Tactical Shop Ukraine</company>', '<url>https://tacticalshop.com.ua</url>',
            '<currencies><currency id="UAH" rate="1"/></currencies>', '<categories>'] + cat_lines + ['</categories>', '<offers>']


def write_xml(result):
    """stock.xml = Kiborg / Militex ONLY (owner, 14 Nov 2026: Kiborg/Militex and Ballistic are two separate XML links;
    Ballistic lives in ballistic.xml, written by write_ballistic_xml()). Offer id and vendorCode stay the supplier
    article (= Prom Код_товару), so HugeProfit keeps matching its products; name and photos = Prom's current ones
    (prom/prom_live.json); param «Prom ID» = Prom Унікальний_ідентифікатор."""
    now = datetime.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
    cats = CAT['categories']
    used = {str(p['cat']) for p in PRODUCTS.values()}
    used |= {str(cats[c][1]) for c in used if c in cats and cats[c][1]}
    cat_lines = []
    for cid in sorted(used, key=lambda x: int(x)):
        if cid in cats:
            n, p = cats[cid]
            cat_lines.append(f'<category id="{cid}"' + (f' parentId="{p}"' if p else '') + f'>{escape(n)}</category>')
    out = xml_head(now, cat_lines)
    live = load_live()
    groups = live_groups(live)
    try:
        umap = json.load(open(os.path.join(os.path.dirname(ROOT), 'prom', 'uid_map.json'), encoding='utf-8'))['map']
    except (OSError, ValueError, KeyError):
        umap = {}
    for code, p in PRODUCTS.items():
        a, q = result[code]
        if a == '+':
            avail, status = 'true', 'в наявності'
        elif a.isdigit():
            avail, status, q = 'true', f'під замовлення {a} дн.', None
        else:
            avail, status, q = 'false', 'немає в наявності', 0
        uid = umap.get(code, {}).get('uid', '')
        lname, lpics = live_name_pics(live, uid) if uid else (None, None)
        if lname and live['items'][uid][5]:
            lname = with_size(lname, code.rsplit('-', 1)[-1] if '-' in code else '', groups.get(live['items'][uid][5], []), SIZES)
        o = [f'<offer id="{escape(code)}" available="{avail}">', f'<name>{escape(lname or p["name"])}</name>',
             f'<price>{p["price"]}</price>', '<currencyId>UAH</currencyId>', f'<categoryId>{p["cat"]}</categoryId>',
             f'<vendor>{escape(p["vendor"])}</vendor>', f'<vendorCode>{escape(code)}</vendorCode>']
        o += [f'<picture>{escape(u)}</picture>' for u in (lpics or p['pics'])]
        if q is not None:
            o.append(f'<quantity_in_stock>{q}</quantity_in_stock>')
        o.append(f'<param name="Наявність Prom">{escape(status)}</param>')
        if uid:
            o.append(f'<param name="Prom ID">{escape(uid)}</param>')
        o.append('</offer>')
        out.append(''.join(o))
    out += ['</offers>', '</shop>', '</yml_catalog>']
    open(os.path.join(os.path.dirname(ROOT), 'stock.xml'), 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    write_prom_csv(result)
    rozetka_hook()


BAL_XML = os.path.join(os.path.dirname(ROOT), 'ballistic.xml')
BAL_FALLBACK_CAT = ('9810', 'Зимовий одяг Level 7')


def write_ballistic_xml():
    """ballistic.xml — the Ballistic supplier's own XML link for HugeProfit (owner, 14 Nov 2026).
    EVERY Ballistic article is its own offer, id = vendorCode = the Ballistic article, also where the Prom listing of the
    same product carries another Код_товару (ESS reopened listings keep our own articles, earmuffs the maker's code):
    owner — «ALL Ballistic stock gets its own listing (even if we already have the same product)», so Ballistic stock
    never merges with our own stock of the same model in HugeProfit. The Prom side is shown in params: «Prom ID»
    (one article can sit on two twin listings) and «Код товару Prom» when it differs from the article.
    Name, photos and category (= Prom group) come from prom/prom_live.json; price and stock from ballistic/state.json.
    Called by ballistic/build_ballistic.py (build / prices). Kiborg runs never write this file."""
    bdir = os.path.join(os.path.dirname(ROOT), 'ballistic')
    try:
        bcat = json.load(open(os.path.join(bdir, 'catalog.json'), encoding='utf-8'))['products']
        bst = json.load(open(os.path.join(bdir, 'state.json'), encoding='utf-8'))['state']
    except (OSError, ValueError, KeyError):
        return 0
    try:
        buid = json.load(open(os.path.join(bdir, 'uid_map.json'), encoding='utf-8')).get('map', {})
    except (OSError, ValueError):
        buid = {}
    live = load_live()
    groups = live_groups(live)
    fallback = '157945845' if '157945845' in live['cats'] else BAL_FALLBACK_CAT[0]   # Prom group «Зимовий одяг (Level 7)»
    by_code = {}
    for uid, it in live['items'].items():
        by_code.setdefault(it[0], []).append(uid)
    offers, used = [], set()
    for pid, p in bcat.items():
        for code, s in p['sizes'].items():
            a, q, price = bst.get(code, ['-', 0, s['price']])
            if 'prom' in s:
                listings = [(L['uid'], L['code'], L.get('name_uk')) for L in s['prom']]
            else:
                uids = by_code.get(code, [])
                uid = uids[0] if len(uids) == 1 else buid.get(code, '')
                listings = [(uid, code, s.get('name_uk'))] if uid else []
            lname = lpics = cat = None
            vendor = ''
            for uid, _, _ in listings:
                lname, lpics = live_name_pics(live, uid)
                if lname:
                    it = live['items'][str(uid)]
                    cat, vendor = it[4], (it[6] if len(it) > 6 else '')
                    if it[5] and len(p['sizes']) > 1:
                        lname = with_size(lname, s.get('size', ''), groups.get(it[5], []))
                    break
            if not vendor:
                vendor = p['brand'] if not p['brand'].startswith('(') else 'US Army (контрактний виробник)'
            name = lname or (listings[0][2] if listings and listings[0][2] else None) or s.get('name_uk') \
                or (p['name_ua'] + ', ' + s['size'] + ', оригінал')
            if not cat or cat not in live['cats']:
                cat = fallback
            used.add(cat)
            avail = 'true' if a == '+' else 'false'
            status = 'в наявності' if a == '+' else 'немає в наявності'
            o = [f'<offer id="{escape(code)}" available="{avail}">', f'<name>{escape(name)}</name>',
                 f'<price>{price}</price>', '<currencyId>UAH</currencyId>', f'<categoryId>{cat}</categoryId>',
                 f'<vendor>{escape(vendor)}</vendor>', f'<vendorCode>{escape(code)}</vendorCode>']
            o += [f'<picture>{escape(u)}</picture>' for u in (lpics or p.get('pics') or [])]
            if a == '+' and q is not None:
                o.append(f'<quantity_in_stock>{q}</quantity_in_stock>')
            elif a != '+':
                o.append('<quantity_in_stock>0</quantity_in_stock>')
            o.append(f'<param name="Наявність Prom">{escape(status)}</param>')
            if listings:
                o.append('<param name="Prom ID">' + escape(', '.join(u for u, _, _ in listings)) + '</param>')
                other = [c for _, c, _ in listings if c != code]
                if other:
                    o.append('<param name="Код товару Prom">' + escape(', '.join(dict.fromkeys(other))) + '</param>')
            o.append('</offer>')
            offers.append(''.join(o))
    # categories = the Prom groups of these listings, with their parents
    lc, cat_ids = live['cats'], set()
    for c in used:
        while c and c in lc and c not in cat_ids:
            cat_ids.add(c)
            c = lc[c][1]
    cat_lines = []
    for c in sorted(cat_ids, key=int):
        n, par = lc[c]
        cat_lines.append(f'<category id="{c}"' + (f' parentId="{par}"' if par and par in cat_ids else '') + f'>{escape(n)}</category>')
    if BAL_FALLBACK_CAT[0] in used:
        cat_lines.append(f'<category id="{BAL_FALLBACK_CAT[0]}">{escape(BAL_FALLBACK_CAT[1])}</category>')
    now = datetime.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
    out = xml_head(now, cat_lines) + offers + ['</offers>', '</shop>', '</yml_catalog>']
    open(BAL_XML, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    return len(offers)


PROMJS = r"""window.__PL={done:false};(async()=>{try{const ids=new Set(__IDS__);const r=await fetch(__FEED__);window.__PL.status=r.status;const t=await r.text();const d=new DOMParser().parseFromString(t,'text/xml');const offs=[...d.querySelectorAll('offer')];window.__PL.total=offs.length;const g=(o,n)=>{const e=o.querySelector(n);return e?e.textContent.replace(/[\t\n\r]+/g,' ').trim():''};const lines=[];for(const o of offs){const v=g(o,'vendor'),vc=g(o,'vendorCode'),id=o.getAttribute('id');if(!(v==='Kiborg'||v==='Militex'||/^\d{13}$/.test(vc)||ids.has(id)))continue;const pics=[...o.querySelectorAll('picture')].map(p=>p.textContent.trim().replace('https://images.prom.ua/',''));const sl=pics.map(p=>p.slice(p.indexOf('_')+1));const same=sl.every(s=>s===sl[0]);const pstr=same?(sl[0]||'')+'\t'+pics.map(p=>p.slice(0,p.indexOf('_'))).join(','):'*\t'+pics.join(',');lines.push([id,vc,o.getAttribute('group_id')||'',g(o,'categoryId'),v,g(o,'name'),pstr].join('\t'))}lines.sort();const cats=[...d.querySelectorAll('category')].map(c=>c.getAttribute('id')+'\t'+(c.getAttribute('parentId')||'')+'\t'+c.textContent.replace(/[\t\n\r]+/g,' ').trim()).sort();const canon='CATS\n'+cats.join('\n')+'\nOFFERS\n'+lines.join('\n')+'\nEND\n';const h=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canon)))].map(b=>b.toString(16).padStart(2,'0')).join('');window.__PL.n=lines.length;window.__PL.sha=h;if(h==='__SHA__'){window.__PL.msg='PROMLIVE same '+lines.length}else{const txt='DATE\t'+d.documentElement.getAttribute('date')+'\nTOTAL\t'+offs.length+'\n'+canon;const cs=new Blob([txt]).stream().pipeThrough(new CompressionStream('gzip'));const buf=new Uint8Array(await new Response(cs).arrayBuffer());let bin='';for(let i=0;i<buf.length;i+=8192)bin+=String.fromCharCode.apply(null,buf.subarray(i,i+8192));const w=btoa(bin).match(/.{1,100}/g).join('\n');const pad=Math.max(0,115000-w.length);document.documentElement.innerHTML='<body><main><pre>PLSTART\n'+w+'\nPLEND\n'+('pad '.repeat(Math.ceil(pad/4)))+'</pre></main></body>';window.__PL.msg='PROMLIVE changed '+lines.length+' — page ready, read it with get_page_text (max_chars 200000)'}}catch(e){window.__PL.msg='PROMLIVE error '+String(e)}window.__PL.done=true})();'started'"""


def promjs():
    """Print the collector that reads the shop's own Prom product feed in a browser tab on tacticalshop.com.ua.
    The feed link (it carries the shop's export hash) is NOT kept in this public repo: pass it as the argument."""
    if len(sys.argv) < 3 or 'products_feed.xml' not in sys.argv[2]:
        sys.exit('usage: python3 refresh/build_feed.py promjs "<Prom product feed link>"  (the link is in the scheduled task prompt)')
    url = sys.argv[2]
    if 'languages=' not in url:
        url += '&languages=uk'
    bcat = json.load(open(os.path.join(os.path.dirname(ROOT), 'ballistic', 'catalog.json'), encoding='utf-8'))['products']
    ids = sorted({L['uid'] for p in bcat.values() for s in p['sizes'].values() for L in s.get('prom', [])
                  if not re.fullmatch(r'\d{13}', L['code'])})
    print(PROMJS.replace('__IDS__', json.dumps(ids)).replace('__FEED__', json.dumps(url)).replace('__SHA__', load_live().get('sha', '')))


def promlive():
    """python3 refresh/build_feed.py promlive <file> — <file> = the get_page_text result of the collector page (the saved
    tool-result file or the text itself). Rewrites prom/prom_live.json. ABORT (nothing changed) when the dump is broken
    or covers under 95 % of the Prom IDs we know — a short feed must never blank names or photos."""
    import base64, gzip, hashlib
    raw = open(sys.argv[2], encoding='utf-8').read()
    try:
        arr = json.loads(raw)
        if isinstance(arr, list):
            raw = ''.join(x.get('text', '') for x in arr if isinstance(x, dict))
    except ValueError:
        pass
    if 'PLSTART' in raw and 'PLEND' in raw:
        b = re.sub(r'\s+', '', raw.split('PLSTART', 1)[1].split('PLEND', 1)[0])
        try:
            raw = gzip.decompress(base64.b64decode(b)).decode('utf-8')
        except Exception as e:
            sys.exit('ABORT: Prom live dump could not be decoded (' + str(e)[:80] + ') — prom_live.json NOT changed.')
    if 'CATS\n' not in raw or not raw.endswith('END\n') or '\nOFFERS\n' not in raw:
        sys.exit('ABORT: Prom live dump is incomplete (no CATS / OFFERS / END) — prom_live.json NOT changed.')
    canon = raw[raw.index('CATS\n'):]
    date = re.search(r'DATE\t([^\n]*)', raw)
    cpart, opart = canon[len('CATS\n'):-len('END\n')].split('\nOFFERS\n', 1)
    cats = {}
    for ln in cpart.split('\n'):
        f = ln.split('\t')
        if len(f) == 3:
            cats[f[0]] = [f[2], f[1]]
    items = {}
    for ln in opart.split('\n'):
        f = ln.split('\t')
        if len(f) != 8:
            continue
        items[f[0]] = [f[1], f[5], f[6], f[7], f[3], f[2], f[4]]   # code, name, slug, photo ids, Prom group, variant group, vendor
    old = load_live()
    umap = json.load(open(os.path.join(os.path.dirname(ROOT), 'prom', 'uid_map.json'), encoding='utf-8'))['map']
    known = {u['uid'] for u in umap.values()}
    bcat = json.load(open(os.path.join(os.path.dirname(ROOT), 'ballistic', 'catalog.json'), encoding='utf-8'))['products']
    known |= {L['uid'] for p in bcat.values() for s in p['sizes'].values() for L in s.get('prom', [])}
    got = len(known & set(items))
    if got < 0.95 * len(known):
        sys.exit(f'ABORT: Prom feed shows only {got} of {len(known)} known listings — prom_live.json NOT changed.')
    oi = old.get('items', {})
    names = sum(1 for u, v in items.items() if u in oi and oi[u][1] != v[1])
    photos = sum(1 for u, v in items.items() if u in oi and (oi[u][2], oi[u][3]) != (v[2], v[3]))
    new = sum(1 for u in items if u not in oi)
    gone = sorted(u for u in known if u not in items)
    for u in gone:
        if u in oi:
            items[u] = oi[u]   # not in the feed any more (hidden on Prom?) -> keep the last known name and photos
    out = ['{', '"_note": "Our listings as the shop\'s own Prom product feed shows them (refresh/build_feed.py promlive). item = Prom ID: [Код_товару, UA name, photo slug, photo ids, Prom group id, variant group, Виробник].",',
           '"checked": ' + json.dumps((date.group(1) if date else '')) + ',',
           '"sha": "' + hashlib.sha256(canon.encode('utf-8')).hexdigest() + '",',
           '"cats": ' + json.dumps(cats, ensure_ascii=False, separators=(',', ':')) + ',', '"items": {']
    keys = sorted(items)
    out += [json.dumps(k) + ':' + json.dumps(items[k], ensure_ascii=False, separators=(',', ':')) + (',' if k != keys[-1] else '') for k in keys]
    out += ['}', '}']
    open(PROM_LIVE_PATH, 'w', encoding='utf-8').write('\n'.join(out) + '\n')
    print(f'prom_live.json: {len(items)} listings ({got} of {len(known)} known), names changed {names}, photos changed {photos}, new {new}')
    if gone:
        print('Known listings NOT in the Prom feed (hidden or deleted on Prom? they keep their last name/photos): ' + ', '.join(gone[:30]))


def restamp():
    """Rewrite stock.xml (+ Prom CSV, Rozetka) from refresh/last_state.json — after prom_live.json or a rule changed."""
    prev = json.load(open(os.path.join(ROOT, 'last_state.json'), encoding='utf-8'))
    write_xml({c: tuple(v) for c, v in prev.items()})
    print('stock.xml rewritten from last_state.json')


def rozetka_hook():
    """Rozetka feed (rozetka/build_rozetka.py, owner 8 Nov 2026) from the files just written. Never fails the run."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(ROOT), 'rozetka'))
        import build_rozetka
        print(build_rozetka.hook())
    except Exception as e:
        print('rozetka: skipped (' + str(e)[:200] + ')')


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
    {'plan': plan, 'build': build, 'split': split, 'merge': merge, 'restate': restate, 'kits': kits, 'prom': prom,
     'promjs': promjs, 'promlive': promlive, 'restamp': restamp, 'ballistic': lambda: print('ballistic.xml:', write_ballistic_xml(), 'offers')}[sys.argv[1]]()
