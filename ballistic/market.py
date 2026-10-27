#!/usr/bin/env python3
"""Prom competitor prices for the Ballistic Level 7 listings (owner, 27 Oct 2026).

Rule: if at least 2 OTHER Prom sellers offer the same model + colour, in stock («Готово до відправки» / «В наявності»),
new (no б/у / уцінка), and the cheapest of them is above our РРЦ, we sell at cheapest −1 %, rounded down to 10 ₴.
Never below РРЦ: build_ballistic.py applies price = max(РРЦ of the size, listing target). Any same-model offer at or
below our РРЦ keeps us at РРЦ. Re-checked twice a week (scheduled task, owner's Chrome) — ballistic/MARKET_RUNBOOK.md.

  python3 ballistic/market.py js            -> collector JS (market_collect.js) for a prom.ua tab
  python3 ballistic/market.py match         -> matcher JS (market_match.js); dumps MKSTART {json} MKEND into the page
  python3 ballistic/market.py apply RAW.txt -> RAW = get_page_text of that dump; writes ballistic/market_prices.json
                                               + ballistic/market_report.md; then run `build_ballistic.py prices`

Same model with the colour not in the offer's name: listed as «colour not in name». If such an offer is cheaper than
the target it BLOCKS the raise until its colour is read on its page and recorded in market_prices.json
«colour_checked» {offer id: grey|multicam|coyote|olive|other}.
"""
import json, os, sys, datetime, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CATP, MARKETP = os.path.join(HERE, 'catalog.json'), os.path.join(HERE, 'market_prices.json')
OUR_SHOP = 'Tactical Shop Ukraine'
QUERIES = ['tennier level 7', 'level 7 ecwcs', 'tennier ecwcs gen iii level 7 parka', 'куртка level 7 сіра',
           'куртка level 7 мультикам', 'куртка level 7 койот', 'штани level 7 сірі', 'штани level 7 мультикам',
           'комплект level 7 сірий', 'комплект level 7 койот', 'комплект level 7', 'carinthia mig 4.0',
           'carinthia mig 4.0 комплект', 'carinthia mig 4.0 multicam', 'carinthia fr', 'carinthia slj',
           'зимова куртка carinthia', 'level 7 parka', 'level 7 trousers']
COLOURS = {'grey': r'сір|сер[ыий]|grey|gray|urban', 'multicam': r'мульти|multi\s?cam',
           'coyote': r'койот|coyote', 'olive': r'олив|olive|зелен'}
KIND = {'jacket': [r'куртк|parka|парка|jacket', r'комплект|костюм|штан|брюк|trouser|pants|\bset\b'],
        'trousers': [r'штан|брюк|trouser|pants', r'комплект|костюм|куртк|parka|jacket'],
        'set': [r'комплект|костюм|\bset\b|куртка\s*\+\s*штани', None]}
# Same model = the maker's name is in the offer (or the offer uses our Ballistic article as SKU). Generic «ECWCS Gen III
# Level 7» offers without «Tennier» (other contractors, PrimaLoft surplus, Helikon/North copies) are NOT the same model.
TENNIER = r'tennier.*(level|layer|левел)\s*7|(level|layer|левел)\s*7.*tennier'
CARINTHIA_MIG = r'(carinthia|карентія|карінтія).*mig\s*4'
LISTINGS = {  # Ballistic page id -> (kind, model regex, colour)
    '14261': ('jacket', TENNIER, 'grey'), '16728': ('trousers', TENNIER, 'multicam'), '16856': ('trousers', TENNIER, 'grey'),
    '23191': ('set', TENNIER, 'grey'), '16720': ('jacket', TENNIER, 'multicam'), '27130': ('set', TENNIER, 'coyote'),
    '27294': ('jacket', TENNIER, 'coyote'), '26345': ('set', CARINTHIA_MIG, 'olive'), '26425': ('jacket', CARINTHIA_MIG, 'multicam'),
    '27502': ('set', r'carinthia.*(slj|fjt|flame|вогнест|\bfr\b)', 'olive'),
    '29895': ('jacket', r'carinthia.*(slj|flame|вогнест|\bfr\b)', 'olive'),
}
EXCLUDE = r'б/у|б\.у\.|вживан|уцінк|уценк|second|level\s*[56]\b|\bhig\b|ecig|isg|esg'


def load(p, default=None):
    try:
        return json.load(open(p, encoding='utf-8'))
    except (OSError, ValueError):
        return default


def now_kyiv():
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')


def js():
    print(open(os.path.join(HERE, 'market_collect.js'), encoding='utf-8').read().replace('__QUERIES__', json.dumps(QUERIES, ensure_ascii=False)))


def match_js():
    cat = load(CATP)['products']
    L = {pid: {'kind': k, 'model': m, 'colour': c, 'arts': list(cat[pid]['sizes'])} for pid, (k, m, c) in LISTINGS.items()}
    t = open(os.path.join(HERE, 'market_match.js'), encoding='utf-8').read()
    for k, v in (('__L__', L), ('__KIND__', KIND), ('__COL__', COLOURS), ('__EXC__', EXCLUDE), ('__OUR__', OUR_SHOP)):
        t = t.replace(k, json.dumps(v, ensure_ascii=False))
    print(t)


def apply(raw):
    t = open(raw, encoding='utf-8').read()
    if 'MKSTART' not in t or 'MKEND' not in t:
        sys.exit('ABORT: no MKSTART/MKEND in the dump — nothing changed.')
    res = json.loads(t.split('MKSTART', 1)[1].split('MKEND', 1)[0].strip())
    if sum(len(v) for v in res.values()) < 10:
        sys.exit('ABORT: fewer than 10 matching offers (Prom changed? search failed?) — nothing changed.')
    cat = load(CATP)['products']
    old = load(MARKETP, {}) or {}
    checked = old.get('colour_checked', {})
    out, rep = {}, [f'# Ballistic market check {now_kyiv()} Kyiv', '',
                    'Rule: ≥2 other sellers, same model + colour, in stock; cheapest above РРЦ → cheapest −1 %, rounded down to 10 ₴; never below РРЦ.', '']
    for pid, (kind, model_rx, colour) in LISTINGS.items():
        p = cat[pid]
        rrp = statistics.mode(s['price'] for s in p['sizes'].values())
        same, unknown = [], []
        for oid, shop, price, cols, name in res.get(pid, []):
            c = checked.get(str(oid), cols)
            if c in ('sku', colour):
                same.append((price, shop, oid, name))
            elif c == '?':
                unknown.append((price, shop, oid, name))
        shops = sorted({o[1] for o in same})
        cheapest = min((o[0] for o in same), default=None)
        target = None
        if len(shops) < 2:
            why = f'only {len(shops)} other seller(s) with this model + colour in stock'
        elif cheapest <= rrp:
            why = f'cheapest competitor {cheapest:.0f} ≤ our РРЦ {rrp}'
        else:
            t_ = int(cheapest * 0.99) // 10 * 10
            blockers = [o for o in unknown if o[0] < t_]
            if t_ <= rrp:
                why = f'cheapest {cheapest:.0f} −1 % rounds to {t_} ≤ РРЦ {rrp}'
            elif blockers:
                why = ('blocked by offer(s) with no colour in the name, below the target: '
                       + ', '.join(f'p{b[2]} {b[1]} {b[0]:.0f}' for b in blockers) + ' — open the page, record the colour in colour_checked')
            else:
                target, why = t_, f'cheapest competitor {cheapest:.0f} ({len(shops)} sellers) −1 % → {t_}'
        out[pid] = {'name': p['name_ua'], 'rrp': rrp, 'target': target, 'cheapest': cheapest, 'sellers': len(shops), 'why': why,
                    'offers': sorted(same)[:12], 'review': sorted(unknown)[:8]}
        rep += [f'## {pid} {p["name_ua"]}', f'РРЦ {rrp} → selling target: {target or "РРЦ"} ({why})',
                *[f'- {o[0]:.0f} {o[1]} (p{o[2]}) {o[3]}' for o in out[pid]['offers']],
                *[f'- colour not in name: {o[0]:.0f} {o[1]} (p{o[2]}) {o[3]}' for o in out[pid]['review']], '']
    json.dump({'note': 'Prom competitor targets (see ballistic/market.py)', 'checked': now_kyiv(), 'colour_checked': checked,
               'colour_notes': old.get('colour_notes', {}), 'listings': out},
              open(MARKETP, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(HERE, 'market_report.md'), 'w', encoding='utf-8').write('\n'.join(rep) + '\n')
    print('\n'.join(l for l in rep if l.startswith('##') or l.startswith('РРЦ')))


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    if cmd == 'js':
        js()
    elif cmd == 'match':
        match_js()
    elif cmd == 'apply' and len(sys.argv) > 2:
        apply(sys.argv[2])
    else:
        print(__doc__)
