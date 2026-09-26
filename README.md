# Wire Forge

**Any website, an API in minutes.** Give Wire Forge a URL and a goal in plain words. It uses the
site in a real browser, finds the JSON endpoints behind it, writes a tested
[Anakin Wire](https://anakin.io/products/wire) action, and has a second, independent agent prove
the action against the live site before it ships.

Built for Opus Build Day (Breakthrough track) with Claude Opus 5.5, Anakin's Browser API and
Wire.

---

## Results at a glance

Every number below comes from files in this repo: `bench/results.csv` (one row per run, written
by the pipeline) and `bench/head2head/*.json` (receipts with timestamps). Nothing is typed by hand.

### Faster than Wire's own builder, on the same goal

| Site | Wire Forge | Wire `build-request` | Both actions work? |
|---|---|---|---|
| boAt: add a colour variant to the cart | **3m 18s** | 5m 14s | yes / yes |
| Myntra: product search with filters | **3m 39s** | 6m 25s | yes / yes |

On boAt, Wire's action needs a raw Shopify `variant_id`; ours takes a product name or URL plus a
colour name, resolves the variant and checks stock. Ours comes with visible verification (7/7
values matched the live cart); theirs relies on an internal test.

### Wire adopted our interface

We turned our verified boAt spec into a Wire build request (`scripts/spec_to_wire.py`). Wire
rebuilt its catalog action `act_boat_lifestyle_com_add_to_cart`, which now takes our inputs
(`product`, `colour`, `quantity`), and it runs through Wire's own API.

### Opus 5.5 vs the previous Opus

Same sites, same goals, same limits, same verifier (Opus 5.5) for every run.

| | Opus 5.5 | Opus 5 |
|---|---|---|
| Runs verified | **9 / 9** | 5 / 7 |
| Median time to a verified action | **6.0 min** | 10.7 min |

| Site | Opus 5.5 | Opus 5 |
|---|---|---|
| **Snitch** (custom backend, hardest) | **3/3 verified**: 6.0, 7.4, 6.9 min | 1 verified in 45.2 min (22 attempts, 2 repairs); 1 no action after 60 turns; 1 crashed on a dropped connection |
| Myntra | **3.7 min** (and 3.5 min on a rerun) | 6.2 min |
| BMTC | **10.0 min** | 11.4 min |
| RedBus | 11.6 min, 1 repair round | **10.7 min** |
| boAt (write) | 3.3 min | 3.3 min |
| aqicn.org (air quality) | 2.4 min | not run |

Honest reading: one to three runs per model per site, so these are observations, not a ranking.
RedBus went to Opus 5 on time, and boAt was a tie. Claude Sonnet 5 was also tried once on Snitch
and produced no action within 60 turns.

---

## How it works

```
URL + goal
  → forge agent uses the site in a real browser (Anakin Browser API, or local Chromium)
  → every XHR / fetch the page fires is recorded, with headers, bodies and responses
  → it proves each endpoint with direct HTTP calls, changing one parameter at a time
  → it emits a Wire action: spec.json + action.py (no browser) + an auto-generated test
  → the action runs immediately and is checked against a strict return schema
  → an independent verifier (fresh browser, none of the forge's reasoning) runs it twice,
    once with its own inputs, and compares names, prices and counts with the live page
  → rejected? the verifier's report goes back to the forge to repair (up to 2 rounds)
```

**What "verified" means here**

- The action ran at least twice, and at least one run used inputs the verifier chose.
- Concrete values were compared with what the real site shows. An unexplained mismatch fails the run.
- A **write** action (add to cart) only counts as a write if the verifier saw the site store the
  change, by opening the cart with the action's own session. Otherwise it is recorded as a read.
  This rule exists because our first Snitch run looked like a write and wasn't.

**Safety**

- Checkout, payment and order endpoints are refused by the probe tool and by the harness that runs
  every action. Write actions stop at the cart.
- No passwords. Demo sites are public or guest-cart only.
- Everything a website returns is shown as text on the dashboard, never rendered as HTML.

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"            # .venv/bin/pip on macOS / Linux
.venv/Scripts/python -m playwright install chromium
cp .env.example .env                             # add ANTHROPIC_API_KEY; ANAKIN_API_KEY is optional
```

`.env` settings:

| Variable | Needed? | What it does |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | runs the forge and verifier agents |
| `ANTHROPIC_WORKSPACE_ID` | only for keys not scoped to a workspace | sent as the `anthropic-workspace-id` header |
| `ANAKIN_API_KEY` | optional | uses Anakin's hosted browser instead of local Chromium |
| `WIREFORGE_PASSCODE` | optional | required to start runs from the website |

## Usage

```bash
# build one action with Opus 5.5
python -m wireforge forge https://www.boat-lifestyle.com/ \
  --goal "add a product in a given colour variant and quantity to the cart, then return the cart contents"

# the model comparison: the same site with the previous Opus, then Opus 5.5
python -m wireforge compare https://www.myntra.com/ \
  --goal "search products by keyword with brand and price filters, paginated"

# the website: landing page, live Forge Board, actions, results
python -m wireforge.web                          # http://127.0.0.1:8000
```

Each run writes `out/<site>__<model>__<time>/`:

| File | Contents |
|---|---|
| `action/spec.json` | Wire-shaped spec: `action_id`, type, parameters, strict return schema |
| `action/action.py` | one function that calls the site's own endpoints, no browser |
| `action/test_action.py` | auto-generated test: runs it live and checks the schema |
| `transcript.jsonl` | every click, request, tool call and decision, for both agents |
| `verdict.json` | each value the verifier compared with the site |
| `summary.json` | the row appended to `bench/results.csv` |

### Other tools

| Command | Purpose |
|---|---|
| `python -m wireforge check-browser [url]` | check the browser backend (Anakin CDP if a key is set) |
| `python -m wireforge verify-wire <action_id> --site <url>` | run a Wire catalog action through our verifier |
| `python scripts/head2head.py submit <url> --goal "..."` | race Wire's own builder on the same goal |
| `python scripts/spec_to_wire.py <spec.json> [--submit]` | hand a forged spec to Wire as a build request |
| `python -m wireforge.scorecard` | regenerate `docs/HEAD2HEAD.md` from the receipts |

## Tests

```bash
python -m pytest
```

Offline by design: tests use a local browser and a local test site, never Anakin or the Claude
API, whatever `.env` contains.

## Repository map

| Path | What's there |
|---|---|
| `wireforge/` | pipeline, forge and verifier agents, browser capture, action harness, CLI |
| `wireforge/web/` | FastAPI server and the single-page website |
| `bench/results.csv` | every run, one row each, written by the pipeline |
| `bench/head2head/` | head-to-head receipts (timestamps from Anakin's API and our transcripts) |
| `docs/ARCHITECTURE.md` | pipeline diagram, module map, contracts |
| `docs/HEAD2HEAD.md` | generated head-to-head table |
| `docs/DEMO.md`, `docs/DEMO_RUNBOOK.md` | demo run of show |

## Known limits

- One to three runs per model per site: enough to show a pattern, not to rank models.
- Sites with bot walls or captchas are out of scope. Wire Forge does not try to get past them.
- Some sites (RedBus, Myntra) started refusing our browser after repeated runs on the same day.
- On Myntra the verifier checked Opus 5.5's action against Myntra's own backend, because its
  browser could not load the pages.
