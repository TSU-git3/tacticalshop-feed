#!/usr/bin/env python3
"""Rozetka marketplace feed (YML/XML) for Tactical Shop Ukraine.

Owner decisions 8 Nov 2026 (SEO hand-over For_Import_2026-11-08_Rozetka.md + owner's answers):
  * Kiborg / Militex without armour (packs, armour kits, blankets, plates, and anything with a ballistic pack inside);
  * Ballistic: Tennier Level 7 (7 listings) + Carinthia MIG 4.0 set and jacket;
  * Starlink: the 3 Prom groups, stock always 5;
  * only real stock: made-to-order / out of stock -> available="false", stock_quantity 0;
    in stock without a count -> 1;
  * price = Prom price x (1 - Prom fee - 1.5 %) / (1 - Rozetka rate x 1.08 - 1.5 %), band by the result,
    rounded up to ...9; Starlink = Prom price; per-offer overrides in rozetka/price_override.json.

Commands
  python3 rozetka/build_rozetka.py snapshot EXPORT.xlsx   rebuild rozetka/source.json from a Prom export
  python3 rozetka/build_rozetka.py build [--draft PATH]   write the feed (only if config publish=true) + report
  python3 rozetka/build_rozetka.py photos                 refresh rozetka/main_photos.json from tacticalshop-images

build reads live stock/prices from prom/prom_stock.csv (Kiborg) and ballistic/state.json (Ballistic),
so it is called at the end of refresh/build_feed.write_xml() (every Kiborg and Ballistic run).
"""
import csv, datetime, html, json, math, os, re, subprocess, sys, tempfile
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def P(*a):
    return os.path.join(HERE, *a)


def load(path, default=None):
    if not os.path.exists(path):
        return default
    return json.load(open(path, encoding='utf-8'))


def dump(obj, path):
    json.dump(obj, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)


CFG = load(P('config.json'))
RZ = load(P('rz_values.json'))

# ----------------------------------------------------------------------------- ids
TR = {'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g', 'д': 'd', 'е': 'e', 'є': 'ie', 'ж': 'zh', 'з': 'z', 'и': 'y',
      'і': 'i', 'ї': 'i', 'й': 'i', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's',
      'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ь': '', 'ю': 'iu',
      'я': 'ia', 'ы': 'y', 'э': 'e', 'ъ': '', 'ё': 'e'}


def latin(s):
    out = []
    for ch in s:
        lo = ch.lower()
        if lo in TR:
            t = TR[lo]
            out.append(t.upper() if ch != lo else t)
        else:
            out.append(ch)
    return re.sub(r'[^A-Za-z0-9]', '', ''.join(out))


def offer_id(line, code, uid):
    if line == 'sl':
        return 'SL' + str(uid)
    return ('KIB' if line == 'kib' else 'BAL') + latin(str(code))


# ----------------------------------------------------------------------------- snapshot
def chars_of(row, header):
    out = {}
    for i, h in enumerate(header):
        if h == 'Назва_Характеристики' and i < len(row) and row[i]:
            v = row[i + 2] if i + 2 < len(row) else None
            u = row[i + 1] if i + 1 < len(row) else None
            if v not in (None, ''):
                out.setdefault(str(row[i]).strip(), (str(v).strip(), u))
    return out


def snapshot(xlsx):
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, read_only=True)['Export Products Sheet']
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    ix = {}
    for i, h in enumerate(header):
        ix.setdefault(h, i)
    content = {r['Унікальний_ідентифікатор']: r for r in
               csv.DictReader(open(os.path.join(ROOT, 'prom', 'content.csv'), encoding='utf-8'))}
    bcat = load(os.path.join(ROOT, 'ballistic', 'catalog.json'))['products']
    art2pid = {a: pid for pid, p in bcat.items() for a in p.get('sizes', {})}
    sc = CFG['scope']
    exg = set(sc['kib_exclude_groups_ru'])
    exn = re.compile(sc['kib_exclude_name_regex'], re.I)
    src, skipped = {}, []
    for r in rows:
        g = lambda k: r[ix[k]] if ix[k] < len(r) else None
        uid = str(g('Унікальний_ідентифікатор') or '')
        ident = str(g('Ідентифікатор_товару') or '')
        grp_no = str(g('Номер_групи') or '')
        code = str(g('Код_товару') or '')
        name_ua, name_ru = str(g('Назва_позиції_укр') or ''), str(g('Назва_позиції') or '')
        line = None
        if ident.startswith('KIB'):
            line = 'kib'
        elif ident.startswith('BAL-'):
            line = 'bal'
        elif grp_no in sc['sl_groups']:
            line = 'sl'
        if not line:
            continue
        gru = str(g('Назва_групи') or '')
        if line == 'kib':
            if gru in exg:
                skipped.append([code, uid, name_ua, 'armour/excluded group: ' + gru]); continue
            if exn.search(name_ua):
                skipped.append([code, uid, name_ua, 'ballistic pack / plates inside']); continue
        art = ident[4:] if line == 'bal' else None
        if line == 'bal' and art2pid.get(art) not in sc['bal_products']:
            skipped.append([code, uid, name_ua, 'Ballistic product not in Rozetka scope']); continue
        photos = [u.strip() for u in str(g('Посилання_зображення') or '').split(',') if u.strip()]
        d_ua, d_ru = str(g('Опис_укр') or ''), str(g('Опис') or '')
        if line == 'kib' and uid in content:          # Import's newest Опис (fixes + photo-extras note)
            d_ua, d_ru = content[uid]['Опис_укр'] or d_ua, content[uid]['Опис'] or d_ru
        oid = offer_id(line, art or code, uid)
        if oid in src:
            raise SystemExit(f'ABORT duplicate offer id {oid} ({code} / {src[oid]["code"]})')
        src[oid] = {'line': line, 'uid': uid, 'code': code, 'article': art or code,
                    'bal_pid': art2pid.get(art) if art else None,
                    'vgrp': str(g('ID_групи_різновидів') or ''), 'group_ru': gru, 'group_no': grp_no,
                    'name_ua': name_ua, 'name_ru': name_ru, 'desc_ua': d_ua, 'desc_ru': d_ru,
                    'photos': photos, 'vendor': str(g('Виробник') or ''),
                    'chars': {k: v[0] for k, v in chars_of(r, header).items()},
                    'prom_price': g('Ціна')}
    # Ballistic rows not in the export yet: names + photos from ballistic/catalog.json, no description
    have = {s['article'] for s in src.values() if s['line'] == 'bal'}
    for pid in sc['bal_products']:
        p = bcat[pid]
        for art, s in p['sizes'].items():
            if art in have:
                continue
            src['BAL' + art] = {'line': 'bal', 'uid': '', 'code': art, 'article': art, 'bal_pid': pid, 'vgrp': str(p.get('vg', '')),
                                'group_ru': 'Level 7', 'group_no': '', 'name_ua': s.get('name_uk', ''), 'name_ru': s.get('name_ru', ''),
                                'desc_ua': '', 'desc_ru': '', 'photos': p.get('pics', []), 'vendor': p.get('brand', ''),
                                'chars': {}, 'prom_price': s.get('price'), 'from_catalog': True}
    meta = {'_note': 'Rozetka source snapshot: listing content per offer from a Prom export (Kiborg Опис from prom/content.csv). '
                     'Rebuild with `build_rozetka.py snapshot <export.xlsx>` after content changes. Stock and prices are NOT taken from here '
                     '(except Starlink price = Prom price).',
            'export': os.path.basename(xlsx), 'built': now_kyiv(), 'skipped': skipped}
    dump({'meta': meta, 'offers': src}, P('source.json'))
    by = {}
    for s in src.values():
        by[s['line']] = by.get(s['line'], 0) + 1
    print(f'snapshot: {len(src)} offers {by}; skipped {len(skipped)}; Ballistic from catalog (no export row): '
          f'{sum(1 for s in src.values() if s.get("from_catalog"))}')


# ----------------------------------------------------------------------------- prices
def round9(x):
    return int(math.ceil((x + 1) / 10.0) * 10 - 1)


def rz_price(prom_price, line, kind):
    pr = CFG['prices']
    if line == 'sl':
        return int(round(float(prom_price)))
    keep = float(prom_price) * (1 - pr['prom_fee'][line] - pr['prompay'])
    bands = pr['bands']['clothing' if kind == 'clothing' else 'gear']
    results = []
    for lo, hi, rate in sorted(bands, key=lambda b: b[2]):     # lowest rate first
        x = keep / (1 - rate * pr['rz_mult'] - pr['rzpay'])
        results.append(x)
        if lo <= x <= hi:
            return round9(x)
    return round9(max(results))                              # gap between bands: keep the margin


# ----------------------------------------------------------------------------- descriptions
ALLOWED = {'p', 'br', 'strong', 'b', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th',
           'tbody', 'thead', 'div', 'span'}
DROP_BLOCK = re.compile(
    r'0\s*\(800\)|33-27-67|Tactical Shop|tacticalshop|Нов(ою|ой|а) Пошт|Відправк|Отправк|доставк|оплат|повернен|возврат|'
    r'гаранті|гаранти|реставрац|сервіс|сервис|знижк|скидк|акці|акци|купити|купить|напишіть|напишите|зателефону|позвоніть|'
    r'позвоните|розрахуємо|рассчитаем|ціна є|цена является|\bціни\b|\bцены\b|у нашому магазині|в нашем магазине', re.I)
SHOP_TAIL = [
    (re.compile(r'\s*[—–-]\s*(їх|його|її|его|её|их)\s+можна придбати окремо в нашому магазині\.?', re.I), '.'),
    (re.compile(r'\s*[—–-]\s*(их|его|её)\s+можно (купить|приобрести) отдельно в нашем магазине\.?', re.I), '.'),
    (re.compile(r',\s*які можна придбати у нас[^.<]*', re.I), ''),
    (re.compile(r',\s*которые можно (купить|приобрести) у нас[^.<]*', re.I), ''),
    (re.compile(r'\s*(можна придбати|можно (купить|приобрести)) (у нас|в нашому магазині|в нашем магазине)[^.<]*', re.I), ''),
]
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿⭐⬆↔-⇿️]')


def clean_desc(t):
    if not t:
        return ''
    t = EMOJI.sub('', t)
    t = re.sub(r'<a\b[^>]*>(.*?)</a>', r'\1', t, flags=re.S | re.I)
    t = re.sub(r'https?://\S+', '', t)
    for rx, rep in SHOP_TAIL:
        t = rx.sub(rep, t)
    t = t.replace('..', '.')
    # drop whole blocks (p / li / h*) that talk about the shop, delivery, payment, warranty, prices
    def drop(m):
        inner = re.sub(r'<[^>]+>', ' ', m.group(0))
        return '' if DROP_BLOCK.search(inner) else m.group(0)
    t = re.sub(r'<(p|li|h[1-6])\b[^>]*>.*?</\1>', drop, t, flags=re.S | re.I)
    # strip attributes and disallowed tags (keep their text)
    def tag(m):
        close, name = m.group(1), m.group(2).lower()
        if name not in ALLOWED:
            return ''
        return f'<{close}{name}>' if name != 'br' else '<br/>'
    t = re.sub(r'<\s*(/?)\s*([a-zA-Z0-9]+)[^>]*?/?>', tag, t)
    t = re.sub(r'<(p|li|strong|b|span|div)>\s*</\1>', '', t)
    t = re.sub(r'<ul>\s*</ul>', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t.replace(']]>', ']] >')


# ----------------------------------------------------------------------------- names
def provisional_name(n):
    n = re.sub(r',?\s*(оригінал|оригинал)\b', '', n, flags=re.I)
    n = n.replace('™', '').replace('®', '').replace('★', '')
    n = re.sub(r'\s*[,;]\s*', ' ', n)
    n = re.sub(r'\s+[—–-]\s+', ' ', n)
    return re.sub(r'\s+', ' ', n).strip(' .')


# ----------------------------------------------------------------------------- params
COLOUR_KEYS = sorted([k for k in CFG['colours'] if not k.startswith('_')], key=len, reverse=True)


def pick(cands, allowed):
    for c in cands:
        if c in allowed:
            return c
    return None


def colour_for(s, cat):
    allowed = RZ['Колір'].get(cat, [])
    if s['line'] == 'sl':
        m = re.search(r'-(BK|WT|GR|OL)$', s['code'])
        return CFG['sl_colours'].get(m.group(1)) if m else None
    n = s['name_ua'].lower()
    for k in COLOUR_KEYS:
        if re.search(r'(^|[ ,(])' + re.escape(k) + r'($|[ ,)])', n):
            return pick(CFG['colours'][k], allowed)
    return None


BAL_SIZE = {'X-Small': 'XS', 'Small': 'S', 'Medium': 'M', 'Large': 'L', 'X-Large': 'XL', 'XX-Large': '2XL', 'XXX-Large': '3XL'}
BAL_LEN = {'Short': 'Short', 'Regular': 'Regular', 'Long': 'Long', 'X-Long': 'XLong'}


def size_for(s, cat, bal_label=None):
    if bal_label:
        parts = bal_label.split()
        base = BAL_SIZE.get(parts[0])
        if not base:
            return None
        if len(parts) > 1 and parts[1] in BAL_LEN and cat in RZ['Розмір']['suffix_ok']:
            return f'{base}-{BAL_LEN[parts[1]]}'
        return base
    m = re.search(r'розмір\s+([A-Za-z0-9-]+)', s['name_ua'])
    v = m.group(1).upper() if m else (s['chars'].get('Размер') or s['chars'].get('Розмір') or '')
    v = v.replace('XXL', '2XL').replace('XXXL', '3XL')
    return v if v in RZ['Розмір']['letters'] else None


def material_for(s, cat):
    allowed = RZ['Матеріал'].get(cat)
    if not allowed:
        return None
    txt = ' '.join([s['name_ua'], s['chars'].get('Ткань', ''), s['chars'].get('Матеріал', ''),
                    s['chars'].get('Склад тканини', ''), s['chars'].get('Тип тканини', '')]).lower()
    cands = []
    if 'cordura' in txt or 'кордур' in txt:
        cands += ['1000D Cordura'] if '1000d' in txt else []
        cands += ['Cordura 500D'] if '500d' in txt else []
        cands += ['Cordura', 'Кордура']
    if 'оксфорд' in txt or 'oxford' in txt:
        cands.append('Оксфорд')
    if 'нейлон' in txt or 'nylon' in txt:
        cands.append('Нейлон')
    if 'поліамід' in txt or 'polyamide' in txt or 'нейлон' in txt:
        cands.append('Поліамід')
    if 'поліестер' in txt or 'поліефір' in txt or 'polyester' in txt:
        cands.append('Поліестер')
    if 'фліс' in txt:
        cands.append('Поліестер')
    return pick(cands, allowed)


EXTRA_TEXT = {'2101392': 'Додаткові характеристики', '4674292': 'Додаткові характеристики', '4674894': 'Матеріал (склад)',
              '449744': 'Додаткові характеристики', '290826': 'Особливості', '4674304': 'Додаткові характеристики',
              '4674355': 'Додаткові характеристики', '4674286': 'Додаткові характеристики', '454024': 'Додаткові характеристики',
              '4675899': 'Додаткові характеристики'}


def kind_of(s):
    if s['line'] == 'bal':
        n = s['name_ua'].lower()
        if 'комплект' in n or 'костюм' in n:
            return 'set'
        if 'штани' in n:
            return 'trousers'
        return 'jacket'
    if s['line'] == 'sl':
        return 'sl'
    return s['group_ru']


def category_and_params(s, bal_label=None):
    k = kind_of(s)
    params = {}
    if s['line'] == 'bal':
        spec = CFG['bal_kinds'][k]
    elif s['line'] == 'sl':
        spec = dict(CFG['sl'])
        n = s['name_ua']
        params['Вид'] = 'Комплекти' if n.lower().startswith('комплект') else 'Аксесуари'
        params['Модель'] = 'Mini' if 'Mini' in n else ('Gen 3' if re.search(r'Gen\s?3', n) else None)
    else:
        spec = CFG['kib_groups'].get(k)
        if not spec:
            return None, None, f'no category mapping for group «{k}»'
        for rx, sub in spec.get('name_cat', {}).items():
            if re.search(rx, s['name_ua']):
                spec = sub
                break
    cat = spec['cat']
    params.update(spec.get('params', {}))
    col = colour_for(s, cat)
    if col:
        params['Колір'] = col
    sz = size_for(s, cat, bal_label)
    if sz:
        params['Розмір'] = sz
    mat = material_for(s, cat)
    if mat:
        params['Матеріал'] = mat
    if cat == '290826' and s['chars'].get('Размер'):
        params['Розміри'] = s['chars']['Размер']
    if cat == '4674286':
        m = re.search(r'(\d+)\s*л\b', s['name_ua'])
        if m:
            params["Об'єм"] = m.group(1)
    if cat == '4674304':
        n = s['name_ua'].lower()
        params['Тип'] = 'Комплекти' if 'комплект' in n else ('Налокотники' if 'налокітник' in n and 'наколінник' not in n else 'Наколінники')
    if cat == '1100234':
        m = re.search(r'Cordura[^,]*', s['name_ua'])
        if m:
            params['Матеріал жилета'] = m.group(0).strip()
    params = {a: b for a, b in params.items() if b}
    if len(params) < 3 and cat in EXTRA_TEXT:      # top up with the listing's own Prom characteristics (real data)
        extra = '; '.join(f'{a}: {b}' for a, b in s['chars'].items() if a not in ('Стан',) and b)
        if extra:
            params[EXTRA_TEXT[cat]] = extra[:1000]
    return cat, params, None


# ----------------------------------------------------------------------------- pictures
def main_photos():
    return set(load(P('main_photos.json'), {'files': []}).get('files', []))


def refresh_main_photos():
    d = tempfile.mkdtemp()
    try:
        subprocess.run(['git', 'clone', '-q', '--depth', '1', '--filter=blob:none', '--no-checkout', CFG['images_repo'], d],
                       check=True, timeout=120)
        out = subprocess.run(['git', '-C', d, 'ls-tree', '-r', '--name-only', 'HEAD', 'rozetka/'], check=True,
                             capture_output=True, text=True, timeout=60).stdout.split()
        files = sorted(f.split('/', 1)[1] for f in out if re.match(r'rozetka/(p\d+|bal\d+)\.jpg$', f))
        old = load(P('main_photos.json'), {}).get('files')
        if files != old:
            dump({'_note': 'Clean Rozetka main photos in tacticalshop-images/rozetka/ (SEO): p<Prom id>.jpg = that row only, '
                           'bal<variant group>.jpg = all sizes of that Ballistic listing.', 'files': files}, P('main_photos.json'))
        return len(files)
    except Exception as e:
        print('main photos: could not read tacticalshop-images (' + str(e)[:120] + ') — kept the last list')
        return None


def pictures_for(s, mains, excl):
    pics = [u for u in s['photos'] if u.startswith('https://') and not re.search(r'[^\x00-\x7f]', u)]
    if s['line'] == 'bal':     # size charts: English (Tennier) / Russian text (Carinthia) — not allowed on Rozetka
        pics = [u for u in pics if 'tennierindustries.com' not in u and 'size_chart' not in u]
    pics = [u for u in pics if not any(x in u for x in excl)]
    clean = None
    if s['uid'] and f"p{s['uid']}.jpg" in mains:
        clean = f"p{s['uid']}.jpg"
    elif s['line'] == 'bal' and f"bal{s['vgrp']}.jpg" in mains:
        clean = f"bal{s['vgrp']}.jpg"
    if clean:                  # SEO's clean version of Prom photo 1 replaces it
        pics = [CFG['main_photo_url'].format(file=clean)] + pics[1:]
    # without a clean version, Prom photo 1 is the supplier's own product photo (SEO check 8 Nov 2026)
    return pics[:CFG['max_pictures']], bool(clean)


# ----------------------------------------------------------------------------- build
def vendor_for(s):
    vm = CFG['vendors']
    if s['line'] == 'sl':
        return vm['sl_kit'] if s['name_ua'].lower().startswith('комплект') else vm['sl_other']
    return vm.get(s['vendor'], s['vendor'] or '')


def now_kyiv():
    return datetime.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')


def esc(s):
    return html.escape(str(s), quote=True)


def live_stock():
    kib = {}
    for r in csv.DictReader(open(os.path.join(ROOT, 'prom', 'prom_stock.csv'), encoding='utf-8')):
        kib[r['Унікальний_ідентифікатор']] = (r['Наявність'], r['Кількість'], r['Ціна'])
    st = load(os.path.join(ROOT, 'ballistic', 'state.json'), {'state': {}})['state']
    return kib, st


def build(draft=None):
    src = load(P('source.json'))
    if not src:
        return 'rozetka: no source.json — run snapshot first'
    names = load(P('names.json'), {'offers': {}}).get('offers', {})
    ovr = load(P('price_override.json'), {'offers': {}, 'bal_products': {}})
    excl = load(P('photo_exclude.json'), {'contains': []})['contains']
    mains = main_photos()
    kib, bal = live_stock()
    gdesc = {}
    for s0 in src['offers'].values():          # variants without their own text get the group's (base) description
        if s0['vgrp'] and s0['desc_ua'] and s0['vgrp'] not in gdesc:
            gdesc[s0['vgrp']] = (s0['desc_ua'], s0['desc_ru'])
    bcat = load(os.path.join(ROOT, 'ballistic', 'catalog.json'))['products']
    offers, issues, stats = [], [], {'offers': 0, 'available': 0, 'by_line': {}, 'provisional_names': 0,
                                    'no_main_photo': 0, 'clean_main': 0, 'no_desc': 0, 'few_params': 0, 'no_stock_row': 0}
    used_cats = set()
    for oid, s in src['offers'].items():
        line = s['line']
        label = None
        if line == 'kib':
            row = kib.get(s['uid'])
            if not row:
                stats['no_stock_row'] += 1; issues.append(f'{oid}: not in prom_stock.csv — left out'); continue
            a, q, prom_price = row
            avail = a in ('+', '!')
            qty = (int(q) if q.strip() else CFG['no_count_qty']) if avail else 0
        elif line == 'bal':
            row = bal.get(s['article'])
            if not row:
                stats['no_stock_row'] += 1; issues.append(f'{oid}: not in ballistic/state.json — left out'); continue
            a, q, prom_price = row
            avail = a == '+' and int(q or 0) > 0
            qty = int(q or 0) if avail else 0
            label = bcat.get(s['bal_pid'], {}).get('sizes', {}).get(s['article'], {}).get('label')
        else:
            prom_price, avail, qty = s['prom_price'], True, CFG['starlink_qty']
        cat, params, err = category_and_params(s, label)
        if err:
            issues.append(f'{oid}: {err} — left out'); continue
        kind = 'clothing' if (line == 'bal' or CFG['kib_groups'].get(s['group_ru'], {}).get('clothing')) else 'gear'
        price = rz_price(prom_price, line, kind)
        why = 'formula'
        if oid in ovr.get('offers', {}):
            price, why = int(ovr['offers'][oid]), 'override (offer)'
        elif line == 'bal' and s['bal_pid'] in ovr.get('bal_products', {}):
            price, why = int(ovr['bal_products'][s['bal_pid']]), 'override (listing)'
        nm = names.get(oid)
        if nm:
            name_ru, name_ua = nm['ru'], nm['ua']
        else:
            name_ru, name_ua = provisional_name(s['name_ru']), provisional_name(s['name_ua'])
            stats['provisional_names'] += 1
        pics, has_main = pictures_for(s, mains, excl)
        if has_main:
            stats['clean_main'] += 1
        if not pics:
            stats['no_main_photo'] += 1; issues.append(f'{oid}: no usable photo')
        du, dr = s['desc_ua'], s['desc_ru']
        if (not du or not dr) and s['vgrp'] in gdesc:
            du, dr = du or gdesc[s['vgrp']][0], dr or gdesc[s['vgrp']][1]
        d_ua, d_ru = clean_desc(du), clean_desc(dr)
        if not d_ua or not d_ru:
            stats['no_desc'] += 1
        if len(params) < 3:
            stats['few_params'] += 1; issues.append(f'{oid}: only {len(params)} params {params}')
        used_cats.add(cat)
        stats['offers'] += 1
        stats['available'] += 1 if avail else 0
        stats['by_line'][line] = stats['by_line'].get(line, 0) + 1
        o = [f'<offer id="{oid}" available="{"true" if avail else "false"}">',
             f'<price>{price}</price>', '<currencyId>UAH</currencyId>', f'<categoryId>{cat}</categoryId>']
        o += [f'<picture>{esc(u)}</picture>' for u in pics]
        o += [f'<vendor>{esc(vendor_for(s))}</vendor>', f'<article>{esc(s["article"])}</article>',
              f'<stock_quantity>{qty}</stock_quantity>',
              f'<name>{esc(name_ru)}</name>', f'<name_ua>{esc(name_ua)}</name_ua>',
              f'<description><![CDATA[{d_ru}]]></description>', f'<description_ua><![CDATA[{d_ua}]]></description_ua>']
        for pn, pv in params.items():
            for v in str(pv).split('|'):
                o.append(f'<param name="{esc(pn)}">{esc(v)}</param>')
        o.append('</offer>')
        offers.append(('\n'.join(o), oid, price, prom_price, why, avail, qty))
    head = ['<?xml version="1.0" encoding="UTF-8"?>', f'<yml_catalog date="{now_kyiv()}">', '<shop>',
            f'<name>{esc(CFG["shop"]["name"])}</name>', f'<company>{esc(CFG["shop"]["company"])}</company>',
            f'<url>{CFG["shop"]["url"]}</url>', '<currencies><currency id="UAH" rate="1"/></currencies>', '<categories>']
    head += [f'<category id="{c}" rz_id="{c}">{esc(CFG["categories"][c])}</category>' for c in sorted(used_cats, key=int)]
    xml = '\n'.join(head + ['</categories>', '<offers>'] + [x[0] for x in offers] + ['</offers>', '</shop>', '</yml_catalog>']) + '\n'
    ready = stats['provisional_names'] == 0 and stats['no_main_photo'] == 0 and stats['no_desc'] == 0
    target = draft or (os.path.join(ROOT, CFG['feed_path']) if CFG.get('publish') else None)
    if target:
        open(target, 'w', encoding='utf-8').write(xml)
    write_report(stats, issues, offers, ready, target, src)
    return (f'rozetka: {stats["offers"]} offers ({stats["available"]} available) {stats["by_line"]}; '
            f'provisional names {stats["provisional_names"]}, no clean main photo {stats["no_main_photo"]}, '
            f'no description {stats["no_desc"]}; ' + (f'written {os.path.relpath(target, ROOT)}' if target else 'publish=false: feed not written'))


def write_report(stats, issues, offers, ready, target, src):
    L = [f'# Rozetka feed report — {now_kyiv()} (Kyiv)', '',
         f'- Feed: {"written to " + os.path.relpath(target, ROOT) if target else "NOT published (config publish=false)"}; '
         f'ready to publish: **{"yes" if ready else "no"}**',
         f'- Offers: {stats["offers"]} ({stats["available"]} available); by line {stats["by_line"]}',
         f'- Names without SEO entry (provisional): {stats["provisional_names"]}; offers without any photo: {stats["no_main_photo"]}; with SEO clean main photo: {stats["clean_main"]}',
         f'- No description: {stats["no_desc"]}; fewer than 3 params: {stats["few_params"]}; missing stock row: {stats["no_stock_row"]}',
         f'- Source snapshot: {src["meta"]["export"]} ({src["meta"]["built"]}); skipped at snapshot: {len(src["meta"]["skipped"])}', '']
    ov = [x for x in offers if x[4] != 'formula']
    if ov:
        L += ['## Price overrides', ''] + [f'- {x[1]}: {x[2]} ({x[4]}; Prom {x[3]})' for x in ov] + ['']
    if issues:
        L += ['## Issues', ''] + [f'- {i}' for i in issues[:200]] + ([f'- … +{len(issues) - 200}'] if len(issues) > 200 else []) + ['']
    open(P('report.md'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')


def hook():
    """Called at the end of refresh/build_feed.write_xml() (Kiborg BIG/SMALL and Ballistic runs)."""
    if not CFG.get('publish'):
        return 'rozetka: publish=false — feed not built'
    refresh_main_photos()
    return build()


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'build'
    if cmd == 'snapshot':
        snapshot(sys.argv[2])
    elif cmd == 'photos':
        print('main photos:', refresh_main_photos())
    elif cmd == 'build':
        d = sys.argv[sys.argv.index('--draft') + 1] if '--draft' in sys.argv else None
        print(build(d))
    else:
        raise SystemExit(__doc__)
