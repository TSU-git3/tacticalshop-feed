# Ballistic stock check — runbook for the scheduled run

Supplier: Ballistic (ballistic.com.ua) — Level 7 winter clothing (Tennier Industries, Carinthia). Ballistic gives no XML,
so stock and prices are read from the owner's signed-in Ballistic account in **his Chrome** (Claude in Chrome tools).
The scheduled task requires the owner's computer (Chrome open and signed in to ballistic.com.ua).

Braces (owner, 30 Oct 2026): «Оригінальні підтяжки ECWCS і PCU» — 5 colour pages (catalog keys braces-fg / -tan / -grey /
-coyote / -black), 14 articles, one Prom variant group 612012 (switches Колір + Розмір). Selling price fixed at 1,099 ₴
(catalog «price_fixed»; never below РРЦ). Coyote and black pages have only Regular — their other size buttons are
«Схожа модель» links and return the same article (harmless). in_csv=false until the owner confirms the Excel import.


ESS glasses (owner, 10–11 Nov 2026): 16 Ballistic pages (catalog keys ess-*), 17 articles, 20 Prom listings (ESS Suppressor One
copper / clear and ICE One smoke each have two Prom «twin» listings of one article). Each article's Prom listings sit in the
catalog size field «prom» (Унікальний_ідентифікатор + that listing's own Код_товару / Ідентифікатор_товару / names); the CSV
writes one row per listing. Selling price = max(РРЦ, size «price_fixed») — price_fixed is the Prom-median price set by the
Import project; this run never changes it. The CDI Max page holds Tan and Black (colour swatches, read since 11 Nov); the 5B page
also shows a black frame that is not on Prom (it is reported under «not on Prom» — that is expected). ESS is in ballistic.xml
since 14 Nov 2026 (one offer per Ballistic article; our own ESS stock stays a separate product in HugeProfit) and NOT in Rozetka. Listings enter prom/ballistic_stock.csv only with «in_csv»: true (one-row link test
first: p2246116560, 11 Nov 2026).

Active earmuffs (owner, 11 Nov 2026): 15 Ballistic pages (catalog keys ear-*), 24 articles, 24 Prom listings (Walker's, Howard
Leight, Sordin, Earmor; same «prom» structure and selling-price rule as ESS). One Walker's Razor Slim page carries 7 colour
swatches (FDE, Multicam, black, Battle Brown, Multicam Black + sold-out Kryptek 2000000027937 and pink 2000000050874 — those two
show under «not on Prom», expected); the Tacti-Grip page also shows black 2000000111414 (1 pc, not on Prom — expected). Patriot,
Pro-X Neckband and M32 PLUS are one page each with swatches. In ballistic.xml since 14 Nov 2026, not in Rozetka. One-row link test: p3270707847
(Razor Slim FDE), pushed 11 Nov 2026 ~15:00 Kyiv, passed (Prom 16:05 London: 90 of 90, no duplicate); all 24 in the CSV since 11 Nov 2026 19:08 Kyiv.

Schedule (owner, 25 Oct 2026: same time frame as the Kiborg/Militex checks): starts 03:35, 07:35, 11:35, 15:35, 19:35,
23:35 Kyiv — 8 minutes after the Kiborg BIG/SMALL start (xx:27), which usually pushes by ~xx:30 — and MUST be pushed by
04:00, 08:00, 12:00, 16:00, 20:00, 00:00 (the same delivery times as Kiborg). If the push is rejected, follow step 6
(pull --rebase; on a stock.xml conflict take theirs and rebuild) — never force-push. (24 Oct 2026 schedule was
06:40, 09:40, 12:40, 14:40, 17:40, 20:40 Kyiv.)

Outputs (same data):
- `prom/ballistic_stock.csv` — pulled by Prom's import-by-link (second link; ticks: price, Наявність, Кількість only;
  «Залишити без змін»; «Раз на 4 години»).
- `ballistic.xml` — **the Ballistic link for HugeProfit** (owner, 14 Nov 2026: Kiborg/Militex and Ballistic are two separate
  XML links): https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/main/ballistic.xml. EVERY Ballistic article in
  `catalog.json` is its own offer (Level 7, braces, ESS, earmuffs, Revision / Wiley X, slings, ECWCS Level 5/6, Snugpak) —
  id = vendorCode = the Ballistic article, also where the Prom listing carries another code (owner: «ALL Ballistic stock
  gets its own listing, even if we already have the same product» — Ballistic stock must never merge with our own stock in
  HugeProfit). Params: «Prom ID» (two IDs for twin listings), «Код товару Prom» when it differs from the article.
  Written by `refresh/build_feed.py` `write_ballistic_xml()`, called from `build` / `prices` here. The old «in_xml» flag is
  no longer read.
- `stock.xml` — Kiborg / Militex only since 14 Nov 2026 (no Ballistic offers); this run still rewrites it (stock unchanged)
  so it carries fresh Prom names and photos.
- Names, photos, Prom IDs and categories in both XMLs = the shop's listings as Prom shows them now: `prom/prom_live.json`,
  refreshed in step 2b. A listing that is not in it falls back to the catalog name and supplier photos.

## Steps

1. **Repo.** `TSU-git3/tacticalshop-feed` cloned with push access; `git pull`; work from the repo root.
2. **Chrome.** Load the Claude in Chrome tools in one ToolSearch call (tabs_context_mcp, tabs_create_mcp, navigate,
   javascript_tool, get_page_text, tabs_close_mcp). Open a NEW tab on `https://ballistic.com.ua/`. If the extension is not
   connected, stop and report — change nothing.
2b. **Prom names and photos (owner, 14 Nov 2026 — optional step: if anything here fails, skip it, say so in the report and
   go on; it must never stop the stock check).** The scheduled task prompt holds the shop's Prom product feed link
   (it carries the shop's export hash — **never write it into this public repo or into a report**). No link in the prompt →
   skip. Open one more NEW tab on `https://tacticalshop.com.ua/robots.txt`. `python3 refresh/build_feed.py promjs "<link>"`
   prints a collector; run it with javascript_tool on that tab (returns «started»), then poll
   `await new Promise(r=>setTimeout(r,5000)); window.__PL.done+' '+window.__PL.msg` until `true`.
   - `PROMLIVE same N` → Prom shows the same names and photos as `prom/prom_live.json`; nothing to do.
   - `PROMLIVE changed N …` → the page now holds the data (gzip + base64 between PLSTART and PLEND, padded so the result
     is saved to a file). Call get_page_text on that tab with `max_chars: 200000`; the tool saves the result to a file
     and gives its path — **do not read the file**; run `python3 refresh/build_feed.py promlive <that path>`. It prints how
     many names / photos changed (put that line in the report) or `ABORT` (then nothing changed — go on). If get_page_text
     has no `max_chars` parameter or returns the text inline / cut (no PLEND), don't copy it by hand: skip and report
     «Prom names not refreshed».
   - `PROMLIVE error …` → skip and report it.
   Close that tab. Step 5 then writes both XMLs with the new names and photos.
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
   `python3 -c "import sys;sys.path.insert(0,'ballistic');import build_ballistic as b;b.rebuild_stock_xml()"` (rewrites ballistic.xml and stock.xml).
   `git add stock.xml ballistic.xml prom/prom_live.json prom/ballistic_stock.csv prom/prom_stock.csv ballistic/state.json ballistic/catalog.json ballistic/report.md` and `git add -A rozetka/`,
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
