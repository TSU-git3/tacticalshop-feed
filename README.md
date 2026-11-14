# tacticalshop-feed

Stock and retail-price feeds for Tactical Shop Ukraine, for HugeProfit. Two links, one per supplier (owner, 14 Nov 2026):

- **Kiborg / Militex** — `stock.xml`: https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/main/stock.xml (source: MyDrop, KIBORG_drop).
- **Ballistic** — `ballistic.xml`: https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/main/ballistic.xml (source: ballistic.com.ua). Every Ballistic article is its own offer.

Both are YML. offer id = vendorCode = supplier article. price = selling price on Prom. quantity_in_stock = supplier stock when known; 0 = out of stock; missing = in stock without a number or made to order (param «Наявність Prom»). name, picture and param «Prom ID» = the listing as it is on Prom now (`prom/prom_live.json`). In ballistic.xml, param «Код товару Prom» shows the Prom listing's code where it differs from the Ballistic article.

Updated by Claude's scheduled stock checks (see `refresh/RUNBOOK.md`, `ballistic/RUNBOOK.md`).
