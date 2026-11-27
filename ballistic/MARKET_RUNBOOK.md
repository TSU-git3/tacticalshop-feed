# Ballistic market-price check — runbook (twice a week)

Owner, 27 Oct 2026: Ballistic Level 7 prices follow the cheapest Prom competitor when it sits above our РРЦ.
Owner, 27 Nov 2026: the same rule covers the Carinthia Defence 6 / Defence 4 sleeping bags (market.py keys 23877 / 23878,
kind «sleeping_bag»; Tropen, liners, bivy covers and combo sets are other products). Defence 6 is made only in olive
(carinthia.eu), so a Defence 6 offer without a colour in its name can be recorded as «olive» in colour_checked.
- Same model + colour only (maker's name in the offer, or the offer uses our Ballistic article as its SKU); in stock
  («Готово до відправки» / «В наявності»); new (no б/у / уцінка); at least 2 other sellers.
- Cheapest of them above our РРЦ → our price = cheapest −1 %, rounded UP to the next …99 (owner, 27 Oct 2026), still below the cheapest. Never below РРЦ
  (build_ballistic.py: price = max(РРЦ of the size, listing target)). Any same-model offer at/below РРЦ → stay at РРЦ.
- An offer of the same model whose name has no colour and that is cheaper than the target blocks the raise until its
  colour is read on its page and recorded in `ballistic/market_prices.json` → `colour_checked` (+ `colour_notes`).

## Steps
1. Repo cloned with push access, `git pull`. Don't push inside a Kiborg/Ballistic stock window (xx:27–xx:00 Kyiv at
   03/07/11/15/19/23) — the scheduled check runs at 13:10 Kyiv.
2. Chrome (Claude in Chrome): NEW tab on https://prom.ua/ua/ . One request at a time (the collector pauses 2.5 s).
3. `python3 ballistic/market.py js` → run with javascript_tool (returns «started», ~2–3 min). Poll
   `await new Promise(r=>setTimeout(r,30000)); window.__MK.done+' '+Object.keys(window.__MK.rows).length` until true.
4. `python3 ballistic/market.py match` → run with javascript_tool (writes MKSTART {json} MKEND into the page, <15 KB),
   then get_page_text and save the text to `ballistic/market_raw.txt` (Write tool).
5. `python3 ballistic/market.py apply ballistic/market_raw.txt`. ABORT → change nothing, report. A «blocked by …»
   line → open that offer's page (`/ua/p<id>-<urlText>.html`, urlText from the search JSON), read «Колір», record it in
   colour_checked, run apply again.
6. `python3 ballistic/build_ballistic.py prices` (re-applies РРЦ + targets to state.json, prom/ballistic_stock.csv, ballistic.xml — the Ballistic HugeProfit link since 14 Nov 2026 — and rewrites stock.xml unchanged).
7. Delete ballistic/market_raw.txt. `git pull --rebase`; on a stock.xml conflict take theirs and re-run step 6.
   `git add ballistic/market_prices.json ballistic/market_report.md ballistic/state.json prom/ballistic_stock.csv stock.xml ballistic.xml` and `git add -A rozetka/`,
   commit «Ballistic market prices <date time> Kyiv», push to main. Close every tab you opened (also after an early stop — see Rules).
8. Report (2–4 lines): targets set/changed (listing, РРЦ → new price, cheapest competitor), blocked listings, aborts.
   Notify the owner only when a selling price changed or the run failed.

## Rules

- **Browser tabs (owner, 20 Nov 2026: close each Chrome tab when you are done with it, so tabs don't pile up):** note the id of every tab you open. Close each tab as soon as you no longer need it, and before the report close every tab you opened that is still open — also when the run stops early (extension error after a tab was opened, ABORT, signed out, a script error, a timeout). Tab ids can change during a long run (16 Nov 2026): call tabs_context_mcp first and close your tabs by id or by URL. Never close a tab you didn't open. Close a helper tab only when no collector is still running in another tab (16 Nov 2026: closing one tab once dropped the whole tab group with the running collector).
