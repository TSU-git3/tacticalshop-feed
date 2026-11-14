# MyDrop stock look-up — instructions for one sub-agent (model: haiku)

Read-only look-ups in the shop owner's own MyDrop supplier catalogue (vendor KIBORG_drop, 521223).
Repo root: the directory that contains `refresh/`. Your batch number is N.

1. Load the tool: ToolSearch "select:mcp__f297e698-7edf-4446-a242-c835a29f35ce__get_product".
2. Read `refresh/work/ids_N.txt` (one product id per line).
3. Call get_product(product_id=<id>) for the ids in as few messages as possible: up to 14 parallel calls per message (so a 28-id batch takes 2 messages). If one fails, retry it once.
4. Write one line per product to `refresh/work/raw_N.jsonl` with a single Bash heredoc (cat > file <<'EOF' … EOF):
   {"pid":"4172414","sku":"<the result's own sku, exactly>","drop":7725,"sizes":[["1004-0101-M-L",5]]}
   - drop = the result's `drop_price` as a number (the shop's buy price; owner, 14 Nov 2026: it goes into the feed). Leave the key out if the result has no drop price.
   - sizes = every entry of the result's `sizes` list as [sku, stock]; [] if the list is empty.
   - stock = the number as given, or the exact text with surrounding spaces trimmed («В наявності», «Очікується надходження»).
   - Copy every sku exactly as given. Never copy descriptions, retail or wholesale prices, or size charts.
   - A call that still fails: {"pid":"<id>","error":"<short reason>"}.
5. Reply only: lines written, errors, and whether the connector asked to sign in.
