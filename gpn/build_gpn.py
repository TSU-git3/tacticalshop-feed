#!/usr/bin/env python3
"""gpn.xml — HugeProfit XML link for the GUN POWER NATION (GPN) tuning line (owner, 17 Nov 2026).

Owner's decisions (17 Nov 2026): the whole GPN tuning line goes in (130 Prom listings / 608 rows); its own link
gpn.xml (not stock.xml / ballistic.xml); buy price («Собівр.», tag <netprice>) = selling price minus 20 %;
built once now and rebuilt on request (no scheduled refresh yet).

Source: gpn/items.json — a snapshot of the rows as they are on Prom (name, price, Prom group, photos and Prom ID from
the shop's Prom product feed; presence and quantity from the Prom cabinet). Rows marked «hold» are left out: on Prom
they have no code of their own (variants sharing the listing's code, or no code), and HugeProfit matches products by
article, so they would merge (owner, 17 Nov 2026: «XML now without them»; they join once Prom has the maker's
variant codes).

Offer id = vendorCode = Prom Код_товару (the maker's variation code). quantity_in_stock = Prom's quantity; out of stock
and made to order → available="false", 0 (HugeProfit shows made-to-order as out of stock, as for Kiborg).

Usage: python3 gpn/build_gpn.py   (writes gpn.xml in the repo root, prints a summary).
No scheduled run writes this file or items.json.
"""
import datetime
import json
import os
from decimal import Decimal, ROUND_HALF_UP
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'gpn.xml')
COST_SHARE = Decimal('0.80')   # owner, 17 Nov 2026: buy price = retail − 20 %
STATUS = {'+': 'в наявності', '-': 'немає в наявності', 'order': 'під замовлення'}


def hp_name(name):
    # HugeProfit drops «−» (U+2212) from names; write a plain hyphen-minus (same rule as the other two XMLs)
    return name.replace('−', '-')


def pic_urls(it):
    if it['slug'] == '*':
        return ['https://images.prom.ua/' + p for p in it['pics']]
    return ['https://images.prom.ua/%s_%s' % (p, it['slug']) for p in it['pics']]


def main():
    d = json.load(open(os.path.join(HERE, 'items.json'), encoding='utf-8'))
    cats, items = d['cats'], d['items']
    rows = [(uid, it) for uid, it in items.items() if 'hold' not in it]
    codes = [it['code'] for _, it in rows]
    if len(set(codes)) != len(codes) or not all(codes):
        raise SystemExit('ABORT: empty or repeated code among the rows that go into gpn.xml')
    offers, used = [], set()
    for uid, it in rows:
        code, price, pres = it['code'], it['price'], it['presence']
        avail = 'true' if pres == '+' else 'false'
        q = it['qty'] if pres == '+' else 0
        net = int((Decimal(price) * COST_SHARE).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        o = [f'<offer id="{escape(code)}" available="{avail}">', f'<name>{escape(hp_name(it["name"]))}</name>',
             f'<price>{price}</price>', '<currencyId>UAH</currencyId>', f'<categoryId>{it["cat"]}</categoryId>',
             '<vendor>Gun Power Nation</vendor>', f'<vendorCode>{escape(code)}</vendorCode>']
        o += [f'<picture>{escape(u)}</picture>' for u in pic_urls(it)]
        if q is not None:
            o.append(f'<quantity_in_stock>{q}</quantity_in_stock>')
        if 0 < net < price:
            o.append(f'<netprice>{net}</netprice>')
        o.append(f'<param name="Наявність Prom">{STATUS[pres]}</param>')
        o.append(f'<param name="Prom ID">{uid}</param>')
        o.append('</offer>')
        offers.append(''.join(o))
        c = it['cat']
        while c and c in cats and c not in used:
            used.add(c)
            c = cats[c][1]
    cat_lines = []
    for c in sorted(used, key=int):
        n, par = cats[c]
        cat_lines.append(f'<category id="{c}"' + (f' parentId="{par}"' if par and par in used else '') + f'>{escape(n)}</category>')
    now = datetime.datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
    head = ['<?xml version="1.0" encoding="UTF-8"?>', f'<yml_catalog date="{now}">', '<shop>',
            '<name>Tactical Shop Ukraine</name>', '<company>Tactical Shop Ukraine</company>', '<url>https://tacticalshop.com.ua</url>',
            '<currencies><currency id="UAH" rate="1"/></currencies>', '<categories>'] + cat_lines + ['</categories>', '<offers>']
    open(OUT, 'w', encoding='utf-8').write('\n'.join(head + offers + ['</offers>', '</shop>', '</yml_catalog>']) + '\n')
    held = len(items) - len(rows)
    n_in = sum(1 for _, it in rows if it['presence'] == '+')
    print(f'gpn.xml: {len(offers)} offers ({n_in} in stock), {held} rows held back (no own code on Prom), {len(cat_lines)} categories')


if __name__ == '__main__':
    main()
