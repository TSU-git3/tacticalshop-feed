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


def ua_chars(xlsx):
    """Characteristic values per Prom id from a Ukrainian-language Prom export (values in Ukrainian)."""
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, read_only=True)['Export Products Sheet']
    rows = ws.iter_rows(values_only=True)
    header = list(next(rows))
    iu = header.index('Унікальний_ідентифікатор')
    return {str(r[iu]): {k: v[0] for k, v in chars_of(r, header).items()} for r in rows if r and r[iu]}


def snapshot(xlsx, ua_xlsx=None):
    import openpyxl
    ua = ua_chars(ua_xlsx) if ua_xlsx else {}
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
                    'units': {k: v[1] for k, v in chars_of(r, header).items() if v[1]},
                    'chars_ua': ua.get(uid, {}), 'country': str(g('Країна_виробник') or ''),
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
            'export': os.path.basename(xlsx), 'export_ua': os.path.basename(ua_xlsx) if ua_xlsx else None,
            'built': now_kyiv(), 'skipped': skipped}
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


OLD_EXTRA_TEXT = {'2101392': 'Додаткові характеристики', '4674292': 'Додаткові характеристики', '4674894': 'Матеріал (склад)',
              '449744': 'Додаткові характеристики', '290826': 'Особливості', '4674304': 'Додаткові характеристики',
              '4674355': 'Додаткові характеристики', '4674286': 'Додаткові характеристики', '454024': 'Додаткові характеристики',
              '4675899': 'Додаткові характеристики'}


CHAR_NAMES = load(P('char_names.json'), {'names': {}})['names']
RU_WORD = re.compile(r'[ыэёъ]|\b(и|с|со|от|из|при|или|есть|нет|да|не|для|мм|см|мбит|шт|год|сзади|спереди|сверху|снизу|внутри|сбоку)\b', re.I)
VAL_FIX = {'Да': 'Так', 'Нет': 'Ні', 'Есть': 'Є', 'Новое': 'Новий', 'Зима': 'Зимовий', 'Магнитный': 'Магнітний', 'Без сверління': 'Без свердління'}
FIELDS = {   # Rozetka's own fields per category (directory read 8 Nov 2026) that we fill from facts we have
    'code': ['1100234', '2101392', '4674292', '4674286', '454024', '290826', '4674894', '4674304', '449744', '4674355',
             '4674417', '4674402', '4674369', '4674310', '4675899', '4674289'],
    'extra': {'4674289': 'Додаткові характеристики', '1100234': 'Додаткові характеристики', '2101392': 'Додаткові характеристики', '4674292': 'Додаткові характеристики',
              '4674286': 'Додаткові характеристики', '454024': 'Додаткові характеристики', '290826': 'Особливості',
              '4674304': 'Додаткові характеристики', '449744': 'Додаткові характеристики', '4674355': 'Додаткові характеристики',
              '4674417': 'Додаткові характеристики', '4674402': 'Додаткові характеристики', '4674369': 'Додаткові характеристики',
              '4674310': 'Додаткові характеристики', '4675899': 'Додаткові характеристики'},
    'weight_text': ['1100234', '4674292', '4674286', '4674304', '4674289'],
    'kit': ['4674292', '4674286', '4674304'],
    'molle': ['1100234', '4674292', '4674286'],
    'fabric': ['4674417', '4674402', '4674369', '4674310'],
}
COUNTRIES = {'Україна', 'США', 'Австрія', 'Вірменія', 'Китай', 'Польща', 'Німеччина'}


UA_LETTER = re.compile(r"[іїєґІЇЄҐ'’]")
NEUTRAL_CYR = {'мм', 'см', 'м', 'г', 'кг', 'шт', 'л', 'вт', 'в', 'мах', 'до', 'х'}


VALUE_UA = load(P('value_ua.json'), {'values': {}})['values']


def is_ua(v):
    """Safe to show as Ukrainian: has a Ukrainian letter and no Russian one, or only neutral Cyrillic (units)."""
    if re.search(r'[ыэёъЫЭЁЪ]', v):
        return False
    if UA_LETTER.search(v):
        return not RU_WORD.search(v)
    return all(w.lower() in NEUTRAL_CYR for w in re.findall(r'[А-Яа-яІіЇїЄєҐґ]+', v))


def cval(s, name):
    """Characteristic value in Ukrainian: Ukrainian export first, then the export value only if it is safely Ukrainian."""
    for k in ([name] if isinstance(name, str) else name):
        v = s.get('chars_ua', {}).get(k)
        if v not in (None, ''):
            return VAL_FIX.get(str(v).strip(), str(v).strip())
        v = s['chars'].get(k)
        if v not in (None, ''):
            v = str(v).strip()
            if v in VALUE_UA:
                return VALUE_UA[v]
            v = VAL_FIX.get(v, v)
            if is_ua(v):
                return v
    return None


def num(v):
    m = re.search(r'\d+(?:[.,]\d+)?', str(v or ''))
    return float(m.group(0).replace(',', '.')) if m else None


def fmt(x):
    return str(int(x)) if float(x).is_integer() else str(x)


def enrich(s, cat, params):
    """Fill Rozetka's own fields from our facts; the rest of the Prom characteristics go to «Додаткові характеристики»."""
    used = set()
    def put(field, value, *src):
        if value not in (None, '') and field not in params:
            params[field] = value
        used.update(src)
    if cat in FIELDS['code'] and s['line'] != 'bal':
        put('Код виробника', s['article'])
    if s.get('country') in COUNTRIES:
        put('Країна-виробник товару', s['country'])
    w = num(s['chars'].get('Вага'))
    if w and s.get('units', {}).get('Вага') == 'г':
        w = w / 1000
    if w:
        if cat in FIELDS['weight_text']:
            put('Вага', fmt(w) + ' кг', 'Вага')
        elif cat == '4675899':
            put('Вага', fmt(round(w * 1000)), 'Вага')
    if cat in FIELDS['kit']:
        put('Комплектація', cval(s, 'Комплектация'), 'Комплектация')
    if cat in FIELDS['molle']:
        sk = ' '.join(str(s['chars'].get(k, '')) for k in ('Система крепления снаряжения', 'Система кріплення спорядження'))
        if 'molle' in sk.lower():
            put('Система кріплення спорядження', 'База для модульної системи (Molle)')
    if 'Матеріал' in params:
        used.add('Матеріал')       # Rozetka's own Матеріал already set from the maker's fabric
    if cat == '1100234':
        m = re.search(r'Cordura[^,]*', s['name_ua'])
        put('Матеріал жилета', cval(s, 'Ткань') or (m.group(0).strip() if m else None), 'Ткань')
        put('Розміри пластини', cval(s, 'Размер бронеплит'), 'Размер бронеплит')
    if cat == '2101392':
        put('Розміри', cval(s, ['Размеры', 'Габариты']), 'Размеры', 'Габариты')
        v = num(s['chars'].get('Об`єм'))
        if v:
            put("Об'єм", fmt(v), 'Об`єм')
    if cat == '4674286':
        v = num(s['chars'].get('Об`єм'))
        if v:
            put("Об'єм", fmt(v), 'Об`єм')
        put('Розмір', cval(s, ['Размеры', 'Габариты']), 'Размеры', 'Габариты')
    if cat == '454024':
        put('Розміри', cval(s, ['Габариты', 'Размеры']), 'Габариты', 'Размеры')
        put('Сумісність', cval(s, ['Рассчитан на оружие', 'Совместимость']), 'Рассчитан на оружие', 'Совместимость')
        put('Призначення', 'Для аксесуарів' if 'шолом' in s['name_ua'].lower() else 'Для рушниць')
    if cat == '290826':
        m = re.search(r'(\d+(?:,\d+)?)\s*[×х]\s*(\d+(?:,\d+)?)', str(s['chars'].get('Размер') or s['name_ua']))
        if m:
            a, b2 = sorted([float(m.group(1).replace(',', '.')), float(m.group(2).replace(',', '.'))])
            if fmt(a * 100) in RZ_NET['Ширина']:
                put('Ширина', fmt(a * 100))
            if fmt(b2 * 100) in RZ_NET['Довжина']:
                put('Довжина', fmt(b2 * 100))
    if cat == '4674894':
        put('Розміри (Д x Ш x В)', cval(s, ['Размеры сиденья', 'Размер в разложенном виде', 'Размеры']),
            'Размеры сиденья', 'Размер в разложенном виде', 'Размеры')
        mat = '; '.join(x for x in [cval(s, 'Ткань'), cval(s, 'Наполнитель'), cval(s, 'Материал коврика')] if x)
        put('Матеріал (склад)', mat or None, 'Ткань', 'Наполнитель', 'Материал коврика')
        if s['chars'].get('Количество секций') and 'Тип' not in params:
            put('Тип', 'Складані')
    if cat == '449744':
        v = num(s['chars'].get('Ширина основной стропы') or s['chars'].get('Ширина стропы'))
        if v and fmt(v / 10) in RZ_BELT:
            put('Ширина ременя', fmt(v / 10), 'Ширина основной стропы', 'Ширина стропы')
        if 'полиамид' in str(s['chars'].get('Материал изделия', '')).lower() or 'полиамид' in str(s['chars'].get('Стропа', '')).lower():
            put('Матеріал', 'Поліамід')
    if cat == '4674355':
        if 'сталев' in s['name_ua'].lower():
            put('Матеріал', 'Сталь')
        elif 'алюмін' in str(s['chars'].get('Сплав', '')).lower() or 'алюмин' in str(s['chars'].get('Сплав', '')).lower():
            put('Матеріал', 'Алюміній')
    if cat in FIELDS['fabric']:
        mat = '; '.join(x for x in [cval(s, ['Состав ткани', 'Тип тканини']), cval(s, 'Утеплитель')] if x)
        put('Матеріал (склад)', mat or None, 'Состав ткани', 'Утеплитель')
        if num(s['chars'].get('Сезон')) is None and str(s['chars'].get('Сезон', '')).startswith('Зим'):
            put('Сезон', 'Зимовий')
    if cat == '4675899':
        put('Живлення', cval(s, 'Питание'), 'Питание')
        put('Габарити (Д x Ш x В)', (cval(s, 'Размер (мм) (ДхШхВ):') or '').replace('*', 'x') or None, 'Размер (мм) (ДхШхВ):')
        v = s['chars'].get('Среднее потребление')
        if v:
            put('Споживана потужність', re.sub(r'\s*W$', '', str(v).strip()), 'Среднее потребление')
    # everything else that has a Ukrainian value → the category's free-text field
    tgt = FIELDS['extra'].get(cat)
    if tgt and tgt not in params:
        lines, missed, seen = [], [], set()
        for k in s['chars']:
            nm = CHAR_NAMES.get(k)
            if not nm or k in used or nm in seen:
                continue
            seen.add(nm)
            v = cval(s, k)
            if v:
                u = s.get('units', {}).get(k)
                lines.append(f'{nm}: ' + v.replace('|', ', ') + (f' {u}' if u and not v.endswith(u) else ''))
            else:
                missed.append(k)
        if lines:
            params[tgt] = '\n'.join(dict.fromkeys(lines))[:3000]
        if missed:
            MISSED_RU.append((s['article'], missed))


MISSED_RU = []
RZ_NET = {'Довжина': ['20', '23', '125', '140', '170', '180', '190', '200', '210', '250', '300', '366', '400', '450', '500', '600', '700', '800', '900', '915', '1000', '1500', '2000'],
          'Ширина': ['2.5', '4.5', '5', '6', '7', '22', '30', '40', '50', '80', '90', '100', '140', '150', '160', '180', '200', '300', '400', '500', '600', '700', '800', '900', '1000', '1200', '1500', '2000']}
RZ_BELT = ['2', '2.5', '2.8', '3', '3.1', '3.4', '3.5', '3.6', '3.7', '3.8', '3.9', '4', '4.3', '4.4', '4.5', '4.6', '4.8', '5', '5.2', '5.3', '5.5', '6', '7', '7.9', '8', '9', '9.5', '10', '14', '25']


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
    params = {a: b for a, b in params.items() if b}
    enrich(s, cat, params)
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


def borrow(text, donor):
    """A variant without its own text gets its group's description minus the donor's own lines
    (its «Ця позиція» line and the intro that repeats the donor's name with its colour/size)."""
    art, n_ua, n_ru = donor[2], donor[3], donor[4]
    keys = [k for k in (art, n_ua.split(',')[0][:40], n_ru.split(',')[0][:40]) if k]
    def drop(m):
        inner = re.sub(r'<[^>]+>', ' ', m.group(0))
        if re.search(r'Ця позиція|Эта позиция', inner) or any(k in inner for k in keys[:1]):
            return ''
        if any(k and k in inner for k in keys[1:]) and re.search(r'продукці[яї] українського|продукция украинского', inner):
            return ''
        return m.group(0)
    return re.sub(r'<p\b[^>]*>.*?</p>', drop, text, flags=re.S | re.I)


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
            gdesc[s0['vgrp']] = (s0['desc_ua'], s0['desc_ru'], s0['article'], s0['name_ua'], s0['name_ru'])
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
        if cat in CFG.get('exclude_categories', []):          # owner 9 Nov 2026: banned / unwanted on Rozetka
            stats['excluded_cat'] = stats.get('excluded_cat', 0) + 1; continue
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
            g = gdesc[s['vgrp']]
            du, dr = du or borrow(g[0], g), dr or borrow(g[1], g)
        for a, b in CFG.get('desc_remove', {}).get(oid, []):  # per-offer text edits (owner)
            if a not in (du or '') and a not in (dr or ''):
                issues.append(f'{oid}: description edit no longer matches — «{a[:60]}…»')
            du, dr = (du or '').replace(a, b), (dr or '').replace(a, b)
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
            v = str(pv)
            if pn == 'Комплектація' and '\n' not in v:   # multi-select list: one param, values joined by «;»
                v = ';'.join(x.strip() for x in v.split('|') if x.strip())   # (validator 9 Nov: repeated params = «Дубль параметра»)
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
         f'- Left out by excluded Rozetka categories {CFG.get("exclude_categories", [])}: {stats.get("excluded_cat", 0)}',
         f'- Source snapshot: {src["meta"]["export"]} ({src["meta"]["built"]}); skipped at snapshot: {len(src["meta"]["skipped"])}', '']
    ov = [x for x in offers if x[4] != 'formula']
    if ov:
        L += ['## Price overrides', ''] + [f'- {x[1]}: {x[2]} ({x[4]}; Prom {x[3]})' for x in ov] + ['']
    if MISSED_RU:
        L += [f'- Characteristics left out (Russian value, no Ukrainian source): {sum(len(m[1]) for m in MISSED_RU)} values on {len(MISSED_RU)} offers', '']
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
        snapshot(sys.argv[2], sys.argv[sys.argv.index('--ua') + 1] if '--ua' in sys.argv else None)
    elif cmd == 'photos':
        print('main photos:', refresh_main_photos())
    elif cmd == 'build':
        d = sys.argv[sys.argv.index('--draft') + 1] if '--draft' in sys.argv else None
        print(build(d))
    else:
        raise SystemExit(__doc__)
