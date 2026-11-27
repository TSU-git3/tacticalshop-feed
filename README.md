# tacticalshop-feed

Stock and retail-price feeds for Tactical Shop Ukraine, for HugeProfit. One link per supplier (owner, 14 and 17 Nov 2026):

- **Kiborg / Militex** — `stock.xml`: https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/main/stock.xml (source: MyDrop, KIBORG_drop).
- **Ballistic** — `ballistic.xml`: https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/main/ballistic.xml (source: ballistic.com.ua). Every Ballistic article is its own offer.
- **GUN POWER NATION (GPN) tuning** — `gpn.xml`: https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/main/gpn.xml (source: the GPN listings as they are on Prom, snapshot `gpn/items.json`; netprice = selling price − 20 %). Built by hand with `python3 gpn/build_gpn.py` — no scheduled run updates it. Since 27 Nov 2026 every GPN tuning row has its own code on Prom (gun-power.com.ua variation codes; 8569-01…06 and …-SPLASH are the shop's own), so nothing is held back.

Both are YML. offer id = vendorCode = supplier article. price = selling price on Prom. quantity_in_stock = supplier stock when known; 0 = out of stock; missing = in stock without a number or made to order (param «Наявність Prom»). netprice = the shop's buy price (MyDrop drop price / Ballistic partner price) — HugeProfit reads it into «Собівр.»; published here by the owner's decision (14 Nov 2026). name, picture and param «Prom ID» = the listing as it is on Prom now (`prom/prom_live.json`). In ballistic.xml, param «Код товару Prom» shows the Prom listing's code where it differs from the Ballistic article.

Updated by Claude's scheduled stock checks (see `refresh/RUNBOOK.md`, `ballistic/RUNBOOK.md`).
