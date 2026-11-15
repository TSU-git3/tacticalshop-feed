# MyDrop hidden kit parts — runbook for the scheduled browser check

Why (owner, 15 Nov 2026: «add the chrome check»): 112 of our Kiborg / Militex listings are MyDrop sets («Комплект») that
contain a HIDDEN part — a cover that is not sold alone, or a pack MyDrop shows only inside the set's page. The MyDrop
connector cannot read hidden products, so the cloud stock runs (refresh/RUNBOOK.md) cannot tell whether such a set is
complete. This check reads those parts' stock from the set pages in the owner's **Chrome**, where he is signed in to
mydrop.com.ua, and writes ONE file: `refresh/web_parts_state.json`.

`refresh/build_feed.py` uses that file only while it is under 8 hours old (`WEB_MAX_AGE_H`). If this check does not run
(computer off, Chrome closed, signed out), the file ages out and the 112 sets fall back to «під замовлення 3 дн.» by
themselves — a missed run can never leave a set wrongly in stock. One missed run is tolerated; two in a row = fallback.

Schedule: 03:12, 07:12, 11:12, 15:12, 19:12, 23:12 Kyiv — 15 minutes before each Kiborg stock run (xx:27), which then
applies the fresh data. The whole run takes about 4 minutes and must be pushed before xx:25.

## Steps

1. **Repo.** `TSU-git3/tacticalshop-feed` cloned with push access; `git pull`; work from the repo root. Note the commit:
   `git rev-parse HEAD`.
2. **Chrome.** Load the Claude in Chrome tools in one ToolSearch call (tabs_context_mcp, tabs_create_mcp, navigate,
   javascript_tool, tabs_close_mcp). Open a NEW tab on `https://mydrop.com.ua/ua/p/4014176`. If the extension is not
   connected, stop and report — change nothing.
3. **Collect.** Run this one line with javascript_tool on that tab, with `<commit>` = the commit from step 1 (it loads
   `refresh/sets_collect.js` exactly as cloned and returns «started»; the collector then reads the 112 set pages one at a
   time, 0.6 s apart, about 2 minutes — never run requests in parallel):
   `(0,eval)(await (await fetch('https://raw.githubusercontent.com/TSU-git3/tacticalshop-feed/<commit>/refresh/sets_collect.js',{cache:'no-store'})).text())`
   If the page refuses the fetch or eval, read `refresh/sets_collect.js` from the clone and run its text with javascript_tool instead.
   Poll with `await new Promise(r=>setTimeout(r,30000)); window.__W.done+' '+window.__W.n` until it starts with `true`.
4. **Read.** javascript_tool: `window.__W.out` — one line of about 700 characters, `WEBPARTS|<time>|112/112|err:…|chg:…|n61|sum…|<id>:<count>,…|END`.
   If the tool cuts it, read `window.__W.out.slice(0,400)` and `window.__W.out.slice(400)` and join them exactly.
   Save the line exactly with the Write tool to `refresh/webparts_raw.txt`.
5. **Check and write.** `python3 refresh/build_feed.py webparts refresh/webparts_raw.txt`. It verifies that every set page
   was read and that the line is complete (part count + checksum), then writes `refresh/web_parts_state.json`.
   - `ABORT` → commit nothing. «set pages failed — signed out of MyDrop?» → send a push notification
     «MyDrop hidden-parts check: signed out of MyDrop in Chrome — sets with covers fall back to made to order».
     «copied incompletely» → read the line again (step 4) and retry once.
6. **Publish.** Delete `refresh/webparts_raw.txt`. `git add refresh/web_parts_state.json` — **only this file** — commit
   «MyDrop hidden parts <date time Kyiv>», push to `main` (`git pull --rebase` first if the push is rejected; never force-push).
7. **Close** the tab you opened. **Report** in 2 lines: parts read / in stock, set pages failed, sets whose composition
   changed. If the script lists changed sets, send a push notification «MyDrop changed the set(s) <codes> — they stay
   made to order until re-mapped in the Import chat».

## Rules

- This run writes `refresh/web_parts_state.json` and nothing else. It never runs `build`, `kits`, `plan` or `webjs`, never
  edits `kits.json`, `stock.xml`, `prom/*`, `ballistic/*` or any other file — the Kiborg run at xx:27 applies the data.
- Read only on MyDrop: no orders, no settings, no other pages than the collector's requests.
- Stock meaning (same as the connector): a count shown on the card → that number (0 = out); a count MyDrop hides
  (`…h` in the line) → in stock without a number when above 0. A hidden part is keyed by its MyDrop product id (`h:<id>`).
- A set whose composition no longer matches `kits.json["web_only"][code]["signature"]` is listed under «changed» and is
  not computed (stays made to order) until it is re-mapped in a normal chat: re-read the set page, fix its `parts` and
  `signature` in kits.json, run `python3 refresh/build_feed.py webjs` (regenerates `refresh/sets_collect.js`), commit both.
- Nothing private goes into the repo: only MyDrop product ids and stock counts.
