# Ballistic stock check — runbook for the scheduled run

Supplier: Ballistic (ballistic.com.ua) — Level 7 winter clothing (Tennier Industries, Carinthia). Ballistic gives no XML,
so stock and prices are read from the owner's signed-in Ballistic account in **his Chrome** (Claude in Chrome tools).
The scheduled task requires the owner's computer (Chrome open and signed in to ballistic.com.ua).

Braces (owner, 30 Oct 2026): «Оригінальні підтяжки ECWCS і PCU» — 5 colour pages (catalog keys braces-fg / -tan / -grey /
-coyote / -black), 14 articles, one Prom variant group 612012 (switches Колір + Розмір). Selling price fixed at 1,099 ₴
(catalog «price_fixed»; never below РРЦ). Coyote and black pages have only Regular — their other size buttons are
«Схожа модель» links and return the same article (harmless). in_csv=false until the owner confirms the Excel import.


Schedule (owner, 25 Oct 2026: same time frame as the Kiborg/Militex checks): starts 03:35, 07:35, 11:35, 15:35, 19:35,
23:35 Kyiv — 8 minutes after the Kiborg BIG/SMALL start (xx:27), which usually pushes by ~xx:30 — and MUST be pushed by
04:00, 08:00, 12:00, 16:00, 20:00, 00:00 (the same delivery times as Kiborg). If the push is rejected, follow step 6
(pull --rebase; on a stock.xml conflict take theirs and rebuild) — never force-push. (24 Oct 2026 schedule was
06:40, 09:40, 12:40, 14:40, 17:40, 20:40 Kyiv.)

Outputs (same data):
- `prom/ballistic_stock.csv` — pulled by Prom's import-by-link (second link; ticks: price, Наявність, Кількість only;
  «Залишити без змін»; «Раз на 4 години»).
- `stock.xml` — Ballistic offers are added by `refresh/build_feed.py` (`ballistic_offers()`) for HugeProfit (owner, 24 Oct 2026).

## Steps

1. **Repo.** `TSU-git3/tacticalshop-feed` cloned with push access; `git pull`; work from the repo root.
2. **Chrome.** Load the Claude in Chrome tools in one ToolSearch call (tabs_context_mcp, tabs_create_mcp, navigate,
   javascript_tool, get_page_text, tabs_close_mcp). Open a NEW tab on `https://ballistic.com.ua/`. If the extension is not
   connected, stop and report — change nothing.
3. **Collect.** `python3 ballistic/build_ballistic.py js` prints the collector. Run it with javascript_tool on the
   Ballistic tab (it returns «started» and keeps running in the page, ~3 minutes). Poll with
   `await new Promise(r=>setTimeout(r,30000)); window.__BAL.done+' '+window.__BAL.lines.length` until `true`.
   Never run requests in parallel (supplier politeness rule).
4. **Dump.** javascript_tool: `document.body.innerHTML='<main><pre>BALSTART\n'+window.__BAL.lines.join('\n')+'\nERRORS\n'+window.__BAL.errors.join('\n')+'\nBALEND</pre></main>'; window.__BAL.lines.length`
   then `get_page_text` on that tab. Save the text exactly (from `BALSTART` to `BALEND`) to `ballistic/raw.txt` with the Write tool.
5. **Build.** `python3 ballistic/build_ballistic.py build ballistic/raw.txt`. If it prints `ABORT` (e.g. signed out:
   fewer than 80% of codes read), commit nothing and report it.
6. **Publish.** Delete `ballistic/raw.txt`. `git pull --rebase` first; if `stock.xml` conflicts (a Kiborg run pushed
   meanwhile), take theirs (`git checkout --theirs stock.xml`), re-run `python3 ballistic/build_ballistic.py csv` and
   `python3 -c "import sys;sys.path.insert(0,'ballistic');import build_ballistic as b;b.rebuild_stock_xml()"`.
   `git add stock.xml prom/ballistic_stock.csv prom/prom_stock.csv ballistic/state.json ballistic/catalog.json ballistic/report.md`,
   commit «Ballistic stock <date time Kyiv>», push to `main`.
7. **Close** the tab you opened. **Report** in 2–4 lines: codes read, stock and price changes, sizes on Ballistic that
   are not on Prom, anything aborted.

## Rules

- Match only by Ballistic article (= our Код_товару; Prom Ідентифікатор_товару `BAL-<article>`). Never guess.
- Price = Ballistic «РРЦ» for that exact size (owner, 24 Oct 2026) — never the partner price shown next to it.
  Since 27 Oct 2026 (owner): selling price = max(РРЦ, market target from `ballistic/market_prices.json`) — the target
  is set by the twice-weekly Prom competitor check (`ballistic/MARKET_RUNBOOK.md`); the stock run never edits targets.
- «В наявності: N» → in stock N; more than 2 → «!» («Готово до відправки»), 1–2 or no count → «+»; «Розпродано» or
  anything else → «-» (unusual statuses are listed in report.md).
- A size that appears on Ballistic but is not in `ballistic/catalog.json` is only reported — new rows need a Prom import first.
- `ballistic/uid_map.json` = article → Prom Унікальний_ідентифікатор; filled from the owner's export after the first import.
- Nothing private in this public repo: no partner prices, no account data.
