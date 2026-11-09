# Rozetka feed — runbook

One combined YML/XML for Rozetka (owner, 8 Nov 2026; SEO hand-over For_Import_2026-11-08_Rozetka.md).
Static link once published: https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/main/rozetka/rozetka.xml

## What is in it
- **Kiborg / Militex** — every live row except armour: groups «Балістичні пакети», «Бронежилети з балістичним захистом», «Бронековдри», and any name with «балістичний пакет / балістичний захист / плити» (owner: «anything that has ballistic tag»). Also out: the custom-size net listing (sold per m², 100 m² minimum).
- **Ballistic** — Tennier Level 7 (14261, 16728, 16856, 23191, 16720, 27130, 27294) + Carinthia MIG 4.0 (26345, 26425). Not FR, not braces.
- **Starlink** — Prom groups 156994021 / 156994033 / 156994035, stock always 5 (owner, no checks).

## Data
| File | What | Changed by |
|---|---|---|
| `config.json` | scope, price bands, categories, group → Rozetka category + params, colour words, `publish` switch | Import (by hand) |
| `rz_values.json` | Rozetka directory values (colours, sizes, materials) read 8 Nov 2026 | Import (by hand) |
| `source.json` | listing content per offer (names, descriptions, photos, Prom characteristics) from a Prom export | `snapshot` command |
| `names.json` | SEO's Rozetka names per offer id | SEO / Import |
| `price_override.json` | owner/SEO prices that replace the formula (offer id, or Ballistic product id for all sizes) | owner / SEO |
| `photo_exclude.json` | URL substrings of photos to leave out (text, Russian text, hanger, hand) | SEO / Import |
| `main_photos.json` | Prom ids that have a clean main photo in tacticalshop-images/rozetka/pNNN.jpg | every build (git ls-tree) |

Live stock and price are read on every build: Kiborg from `prom/prom_stock.csv` (owner price overrides included), Ballistic from `ballistic/state.json` (= Prom selling price). Starlink price = Prom price in `source.json`.

## Rules in the code
- `available="true"` only for real stock: Kiborg «+»/«!» (no count → 1), Ballistic «+» with a count, Starlink 5. Made to order / out → `false`, 0.
- Price = Prom × (1 − Prom fee − 0.015) ÷ (1 − rate × 1.08 − 0.015), lowest rate whose band holds the result, rounded up to …9. Gear vs clothing bands (fleece + Ballistic = clothing). Starlink = Prom price. Overrides win.
- Offer ids: `KIB` + article in Latin letters/digits, `BAL` + Ballistic article, `SL` + Prom id. **Never change an id after Rozetka loaded it.**
- Descriptions: shop / phone / delivery / payment / warranty / price / «у нас» blocks removed, attributes and other tags stripped. Variants without their own text get their group's description.
- Pictures: clean main photo first (when SEO has it), then the Prom set without Prom photo 1; Ballistic size charts left out; max 15.
- Feed is written **only when `publish` is true** in config.json. Turn it on only when report.md says «ready to publish: yes» (all SEO names, clean main photos, descriptions) and SEO has checked a draft.

## Commands
- Draft for checks (any time, not committed): `python3 rozetka/build_rozetka.py build --draft /tmp/rz.xml` → also writes `rozetka/report.md`.
- After a new Prom export: `python3 rozetka/build_rozetka.py snapshot export.xlsx`, then a draft build; commit `rozetka/source.json`.
- Scheduled runs: nothing extra — `refresh/build_feed.write_xml()` calls the builder at the end. They commit with `git add -A rozetka/`. If a push conflicts in `rozetka/rozetka.xml`, take origin's files and rebuild with `python3 rozetka/build_rozetka.py build` (the feed is fully derived).
- Not in a stock window (Kiborg xx:27–xx:00, Ballistic xx:35–xx:45 Kyiv) when editing by hand.

## Excluded Rozetka categories (owner 9 Nov 2026 — permanent)
Rozetka bans military-purpose goods; the owner doesn't want masking nets or Starlink there either. `config.json` `exclude_categories` lists 290826 (Засоби для маскування), 4674292 (Розвантажувальні жилети), 1100234 (Бронежилети), 4675899 (Супутникові термінали); `build()` skips any offer mapped to them (count in report.md). Every other category stays. Don't remove an entry without the owner.
- `config.json` `desc_remove`: per-offer [old, new] text edits on the Rozetka description (e.g. KIB2611012100 cross-sell sentence); a no-longer-matching edit shows in report.md Issues.
- Helmet bags (2318-…) stay in 454024 «Чохли та кейси для зброї»: the better fit 4674289 «Каски та шоломи» (Тип «Аксесуари») is a stop-category for the shop (validator 9 Nov 2026). The mapping is parked in config `kib_groups` → `name_cat_parked`; rename it to `name_cat` once the manager opens 4674289.
