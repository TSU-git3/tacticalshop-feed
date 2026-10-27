#!/usr/bin/env python3
"""Ballistic (ballistic.com.ua) stock + price sync for Tactical Shop Ukraine (Level 7 clothing).

Ballistic gives no XML; stock is read from the owner's signed-in Ballistic account in his Chrome
(scheduled task runs on his computer). See ballistic/RUNBOOK.md.

  python3 ballistic/build_ballistic.py js            -> prints the collector JS (paste into javascript_tool)
  python3 ballistic/build_ballistic.py build RAW.txt -> RAW.txt = the get_page_text output of the dump;
                                                       writes ballistic/state.json, ballistic/catalog.json (prices),
                                                       prom/ballistic_stock.csv, stock.xml, ballistic/report.md

Rules (owner, 24 Oct 2026): price = Ballistic РРЦ for that exact size; in stock with more than 2 units -> «!»
(«Готово до відправки»), 1–2 or no count -> «+», sold out -> «-». Match only by Ballistic article (exact).
Market price (owner, 27 Oct 2026): when at least 2 other Prom sellers offer the same model + colour in stock (new, not
discounted) and the cheapest of them is above our РРЦ, we sell just under the cheapest (−1 %, rounded down to 50 ₴);
never below РРЦ. Targets live in ballistic/market_prices.json (written by `python3 ballistic/market.py`, re-checked twice
a week); every run applies price = max(РРЦ of the size, listing target).

  python3 ballistic/build_ballistic.py prices        -> re-applies РРЦ + market targets to state, CSV and stock.xml (no Ballistic read)
"""
import json, os, sys, csv, datetime, re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CATP, STATEP, UIDP = (os.path.join(HERE, n) for n in ('catalog.json', 'state.json', 'uid_map.json'))
MARKETP = os.path.join(HERE, 'market_prices.json')
READY_MIN = 2
HDR = ['Код_товару', 'Назва_позиції', 'Назва_позиції_укр', 'Унікальний_ідентифікатор', 'Ідентифікатор_товару', 'ID_групи_різновидів',
       'Ціна', 'Валюта', 'Одиниця_виміру', 'Наявність', 'Кількість']


def load(p):
    return json.load(open(p, encoding='utf-8'))


def now_kyiv():
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')


def market_targets():
    try:
        return {pid: v.get('target') for pid, v in load(MARKETP).get('listings', {}).items() if v.get('target')}
    except (OSError, ValueError):
        return {}


def sell_price(rrp, pid, targets):
    t = targets.get(pid)
    return max(rrp, t) if t else rrp


def js():
    cat = load(CATP)['products']
    urls = json.dumps([[pid, p['url']] for pid, p in cat.items()], ensure_ascii=False)
    print(open(os.path.join(HERE, 'collect.js'), encoding='utf-8').read().replace('__URLS__', urls))


def parse_raw(path):
    t = open(path, encoding='utf-8').read()
    if 'BALSTART' not in t or 'BALEND' not in t:
        sys.exit('ABORT: raw text has no BALSTART/BALEND markers — nothing changed.')
    body = t.split('BALSTART', 1)[1].split('BALEND', 1)[0]
    lines, errors = body.split('ERRORS', 1)
    got = {}
    for ln in lines.strip().splitlines():
        parts = ln.strip().split('|')
        if len(parts) != 5 or not parts[1] or parts[1] == 'null':
            continue
        pid, art, label, status, rrp = parts
        got[art] = (pid, label, status, rrp)
    return got, [e for e in errors.strip().splitlines() if e.strip()]


def to_state(status):
    m = re.match(r'В наявності(?::\s*(\d+))?$', status.strip())
    if m:
        return '+', (int(m.group(1)) if m.group(1) else None)
    return '-', 0


def write_csv(cat, state):
    uids = load(UIDP).get('map', {})
    rows = []
    for pid, p in cat.items():
        if not p.get('in_csv', True):
            continue  # Excel import not confirmed yet -> a link row would create a bare product
        for art, sz in p['sizes'].items():
            a, q, price = state[art]
            if a == '+':
                nal, kil = ('!' if (q is not None and q > READY_MIN) else '+'), ('' if q is None else str(q))
            else:
                nal, kil = '-', '0'
            rows.append([art, sz['name_ru'], sz['name_uk'], uids.get(art, ''), 'BAL-' + art, str(p['vg']), str(price), 'UAH', 'шт.', nal, kil])
    with open(os.path.join(REPO, 'prom', 'ballistic_stock.csv'), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(HDR)
        w.writerows(rows)
    return rows


def rebuild_stock_xml():
    """stock.xml holds Kiborg (refresh/last_state.json) + Ballistic offers; build_feed.write_xml adds ours."""
    sys.path.insert(0, os.path.join(REPO, 'refresh'))
    import build_feed
    prev = load(os.path.join(REPO, 'refresh', 'last_state.json'))
    build_feed.write_xml({c: tuple(v) for c, v in prev.items()})


def build(raw):
    cat_all = load(CATP)
    cat = cat_all['products']
    old = load(STATEP)['state']
    got, errors = parse_raw(raw)
    codes = [a for p in cat.values() for a in p['sizes']]
    found = [a for a in codes if a in got]
    if len(found) < 0.8 * len(codes):
        sys.exit(f'ABORT: only {len(found)} of {len(codes)} Ballistic codes read (signed out? site changed?) — nothing changed. Errors: {errors[:10]}')
    state, changes, prices, missing, odd = {}, [], [], [], []
    targets = market_targets()
    for pid, p in cat.items():
        for art, s in p['sizes'].items():
            if art not in got:
                st = list(old.get(art, ['-', 0, s['price']]))
                st[2] = sell_price(s['price'], pid, targets)
                state[art] = st
                missing.append(f'{art} ({p["name_ua"][:40]}…, {s["size"]}) — not read this run, last value kept')
                continue
            _, label, status, rrp = got[art]
            a, q = to_state(status)
            if a == '-' and not status.startswith('Розпродано'):
                odd.append(f'{art} {s["size"]}: Ballistic status «{status}» → treated as out of stock')
            price = s['price']
            if rrp.isdigit() and int(rrp) != price:
                prices.append(f'{art} {s["size"]}: {price} → {rrp}')
                price = int(rrp)
                s['price'] = price
            sp = sell_price(price, pid, targets)
            if old.get(art) and old[art][2] != sp:
                prices.append(f'{art} {s["size"]}: selling price {old[art][2]} → {sp} (РРЦ {price}' + (f', market target {targets[pid]})' if pid in targets else ')'))
            state[art] = [a, q, sp]
            if old.get(art, [None, None])[:2] != [a, q]:
                changes.append(f'{art} {p["name_ua"][:45]}…, {s["size"]}: {old.get(art)} → {[a, q]}')
    known = set(codes)
    new_sizes = [f'{v[0]} {art} «{v[1]}» {v[2]}' for art, v in got.items() if art not in known]
    json.dump(cat_all, open(CATP, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump({'checked': now_kyiv(), 'state': state}, open(STATEP, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    rows = write_csv(cat, state)
    rebuild_stock_xml()
    cnt = {k: sum(1 for r in rows if r[HDR.index('Наявність')] == k) for k in ('!', '+', '-')}
    rep = [f'# Ballistic stock check {now_kyiv()} Kyiv', '',
           f'Codes: {len(codes)} · read: {len(found)} · CSV: «!» {cnt["!"]}, «+» {cnt["+"]}, «-» {cnt["-"]}', '',
           '## Stock changes since last run', *(changes or ['none']), '',
           '## Price changes (Ballistic РРЦ / market target)', *(prices or ['none']), '',
           '## Not read this run', *(missing or ['none']), '',
           '## Sizes on Ballistic that are not on Prom (need an import)', *(new_sizes or ['none']), '',
           '## Unusual statuses', *(odd or ['none']), '', '## Collector errors', *(errors or ['none'])]
    open(os.path.join(HERE, 'report.md'), 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
    print('\n'.join(rep[:4]))
    print(f'{len(changes)} stock changes, {len(prices)} price changes, {len(missing)} not read, {len(new_sizes)} new sizes on Ballistic')


def reprice():
    cat = load(CATP)['products']
    st_all = load(STATEP)
    targets = market_targets()
    ch = []
    for pid, p in cat.items():
        for art, s in p['sizes'].items():
            if art in st_all['state']:
                sp = sell_price(s['price'], pid, targets)
                if st_all['state'][art][2] != sp:
                    ch.append(f'{art} {s["size"]}: {st_all["state"][art][2]} → {sp}')
                    st_all['state'][art][2] = sp
    json.dump(st_all, open(STATEP, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    write_csv(cat, st_all['state'])
    rebuild_stock_xml()
    print(f'{len(ch)} selling prices changed'); print('\n'.join(ch))


def csv_only():
    cat = load(CATP)['products']
    write_csv(cat, load(STATEP)['state'])
    print('prom/ballistic_stock.csv written')


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'js':
        js()
    elif cmd == 'build' and len(sys.argv) > 2:
        build(sys.argv[2])
    elif cmd == 'prices':
        reprice()
    elif cmd == 'csv':
        csv_only()
    else:
        print(__doc__)
