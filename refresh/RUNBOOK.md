# Stock refresh — runbook for the scheduled run

Schedule (owner, 19 Oct 2026 — each run gets a 30-minute window and must be pushed by the delivery time):
- **BIG checks** (all products, in and out of stock) start 07:30, 15:30, 23:30 Kyiv → pushed by 08:00, 16:00, 00:00.
- **SMALL checks** (only products that are in stock «+» in `refresh/last_state.json`) start 03:30, 11:30, 19:30 Kyiv → pushed by 04:00, 12:00, 20:00.
The steps are the same for both; a SMALL check passes `--small` to `plan` (step 3) and skips step 6. Updates **stock only** in `stock.xml` (prices stay as in `refresh/catalog.json`). Source: MyDrop connector, vendor KIBORG_drop (id 521223).

Goal: exact stock with the fewest MyDrop calls. Never guess: a code gets stock only from a MyDrop size whose sku equals the code exactly.

## Steps

1. **Repo.** Make sure `TSU-git3/tacticalshop-feed` is cloned with push access (add it to the session if needed), `git pull`, work from the repo root.
2. **Sweeps (cheap).** Call MyDrop `search_products` with `vendor=521223`, `in_stock=false`, `limit=300`, once for each query: `Kiborg`, `Militex`, `сітка`, `пакет`, `захист`, `Мультикам`. These results are large, so they are saved to files automatically — **do not read them**; the script reads them.
3. **Plan.** `python3 refresh/build_feed.py plan` (SMALL check: `python3 refresh/build_feed.py plan --small` — only products holding an in-stock code; everything else keeps its last value) → `refresh/todo.json` lists the product ids that still need `get_product` (products the sweep already shows as out of stock are skipped).
4. **Look-ups.** For every id in `todo.json["todo"]`, call MyDrop `get_product(product_id)`. From each result take only `sizes` → `[sku, stock]` pairs (stock = the number, or the exact text such as «В наявності» / «Очікується надходження»). Append one line per product to `refresh/stock_raw.jsonl`:
   `{"pid":"4172414","sku":"<parent sku>","sizes":[["1004-0101-M-L",5]]}` — include the parent `sku` (needed for products with an empty `sizes` list, e.g. armour kits, so they count as «on MyDrop, out of stock» instead of «not found»).
   Append in batches of ~10 lines (Bash heredoc `>>`), so nothing is lost if the run stops. Don't copy descriptions anywhere.
   **How (owner, 19 Oct 2026 — cheapest way):** `python3 refresh/build_feed.py split` (batches of 28 ids → `refresh/work/ids_<n>.txt`, ~12 batches for a BIG check, ~7 for a SMALL one), then start ONE sub-agent per batch, all in parallel, each with `model: "haiku"` and the prompt «Read refresh/LOOKUP_AGENT.md and do it with N=<n>.» Each agent makes up to 14 calls per message: fewer turns means each agent re-reads its growing context fewer times (estimated ~20% fewer tokens than 8 calls per message). Then `python3 refresh/build_feed.py merge`; if it reports missing ids, run one more haiku agent with N=missing and merge again. Haiku matched Sonnet exactly on a 40-product / 136-size test (19 Oct 2026).
5. **Build.** `python3 refresh/build_feed.py build`. It writes `stock.xml`, `refresh/report.md`, `refresh/last_state.json` and prunes `refresh/pids.json` (ids that matched none of our codes are dropped, so later runs need fewer look-ups).
   - If it prints `ABORT`, do **not** commit `stock.xml`. Report the reason.
6. **Missing codes (BIG checks only) (only while `report.md` lists codes not found on MyDrop, max 40 searches per run).** For a not-found code that isn't a camo net (`20…`), call `search_products(query=<code>, vendor=521223, in_stock=false, limit=20)`. Add to `refresh/pids.json["pids"]` any result whose sku equals the code, or whose sku starts with the same model-colour (e.g. `2205-0123-00-1` for `2205-0121-00`). Don't call `get_product` for them in this run — the next run picks them up.
7. **Publish.** `git add stock.xml refresh/pids.json refresh/last_state.json refresh/report.md`, commit «Stock refresh <BIG|SMALL> <date time Kyiv>», push to `main`. Delete `refresh/stock_raw.jsonl`, `refresh/todo.json` and `refresh/work/` before committing (not tracked).
8. **Report** in 2–4 lines: number of look-ups, changes since last run, codes not found, anything aborted.

## Rules

- «Not found on MyDrop» in report.md means no MyDrop product has this exact code (neither a size sku nor the product sku). Codes whose product exists but is out of stock are counted separately («On MyDrop but out of stock»). `plan` adds any sweep product whose product sku equals one of our codes exactly to `pids.json` automatically; `pids.json["parent"]` maps code → product id for those (19 Oct 2026 fix: the first run missed 34 codes, 22 of them in stock, because their product ids weren't listed).

- Code on MyDrop with stock 0 or «Очікується надходження» → made to order: camo nets (`20…`) «під замовлення 5 дн.» (owner, 18 Oct 2026), **every other product «під замовлення 3 дн.»** (owner, 19 Oct 2026). Code NOT on MyDrop at all → out of stock «-» (`quantity_in_stock` 0) — owner, 19 Oct 2026: not on MyDrop = not sold.
- Number > 0 → in stock with that quantity. «В наявності» without a number → in stock, no quantity.
- No drop/partner prices in any file in this repo (it is public).
- If the MyDrop connector is missing or asks to sign in again, stop without changing `stock.xml` and say so.
