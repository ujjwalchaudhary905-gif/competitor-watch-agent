# Competitor Watch Agent

**An AI agent that does the work of a competitive-intelligence analyst for a small
business — not a chatbot you ask questions, an agent that actually goes and finds out,
judges what matters, and tells you what to do about it.**

Built for the AWS *"Agents for Humans"* hackathon (Professional Agents track) with the
[Strands Agents SDK](https://strandsagents.com/), using Anthropic Claude directly as
the model provider — no AWS Bedrock, no billed AWS services required to run it.

> Built entirely during the hackathon submission period. No pre-existing code was
> incorporated beyond standard open-source frameworks/libraries (Strands Agents SDK,
> the Anthropic SDK, Streamlit, Playwright, BeautifulSoup, SQLite — all used under
> their own open-source licenses, no proprietary or third-party project code included).

## The problem

A small business owner knows they should be watching their competitors — pricing
moves, new features, positioning shifts — but doing it properly takes real analyst
work: knowing who to watch, checking their sites regularly, telling a real change from
a copy tweak, and translating "they cut their price" into "here's what you should
actually do about it, this week." Most founders either pay for expensive competitive-
intelligence software built for enterprise teams, or they just don't do it at all.

## Who it's for

Solo founders and small teams who have zero competitive-intelligence budget or
headcount, don't necessarily know who their real competitors are yet, and need a
straight answer — not a dashboard full of numbers they have to interpret themselves.

## Why it matters

The gap this fills isn't "no tool exists" — it's that existing tools (SEMrush, Klue,
Crayon) are priced and built for teams with a dedicated analyst. This agent gives a
one-person company the same judgment calls a human analyst would make — *is this
change real, does it matter to me specifically, what should I do about it* — for the
cost of an API key.

## What makes this an agent, not a wrapper

Every step below is a genuine, separately-verified judgment call — several of them are
themselves a small nested Strands `Agent` with a focused system prompt and forced
structured output, not one prompt asked to do everything. A single run involves
10-45+ real model calls, each doing one narrow job well.

1. **Discovers your competitors, if you don't already know them.** Tries three
   sources in order: a real "X alternatives" web page (verified it's actually about
   *your* business — names collide), then a category/feature search when no such page
   exists (works even in niches too small for G2), then the model's own market
   knowledge as a last resort. Every candidate is gated by a skeptical worthiness
   check — legitimate, genuinely relevant (same primary function, not shared
   buzzwords), and region-appropriate if you set a target region — verified against
   the competitor's real site, never taken on faith.
2. **Grounds itself in your actual site**, not just what you typed about your
   business — live-fetched, compared against your description to surface gaps.
3. **Fetches and diffs** each competitor's public pages against the last snapshot
   (SQLite), and distinguishes a genuine detected change from a first-ever look at a
   page (which gets baseline framing, never invented "they just pivoted" language).
4. **Judges materiality** — trivial copy tweak vs. substantive change — from meaning,
   not keyword matching.
5. **Analyzes impact specifically for your business** — "Competitor X cut price to
   $14.99, undercutting your $19.99 tier" — not a generic summary of their change.
6. **Prioritizes across every competitor** into a top-3 (or fewer — padding a weak
   3rd slot is treated as a bug, not a feature) list, recognizing when multiple
   competitors share a pattern (a category norm, not one urgent threat).
7. **Recommends a concrete action and names a real tool** for each item — and treats
   pricing/packaging/positioning changes as a *decision to evaluate* with evidence to
   gather, never as a one-week ship task, since those are the highest-risk, hardest-to-
   reverse moves a small business can make.
8. **Builds a profile of every competitor** — a visual/UX critique (screenshots
   compared side-by-side so scores actually differentiate, not a template), company
   background from their own public About page (never LinkedIn or any login-gated
   source), and update cadence derived from this project's own monitoring history.

The full reasoning trace — which competitor, what was found, why it was prioritized,
why that tool was recommended — is logged at every step, not just the final answer.

## What it deliberately does *not* do

No login-gated scraping, no social/LinkedIn APIs, no paid SEO/SEO-intelligence tools.
Every page fetched is public, plain HTTP, same as a human visiting the site.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full diagram and the design
rationale behind each non-obvious decision (why fetch+diff are one tool call, why
visual scoring is comparative not independent, why change vs. baseline is a
structurally-enforced distinction, why a discovery candidate needs three verification
layers before it's trusted).

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-ui.txt   # includes requirements.txt + Streamlit
playwright install chromium          # one-time browser download, for visual UI assessment
cp .env.example .env                 # add your ANTHROPIC_API_KEY
```

## Run

**Web UI (recommended):**

```bash
streamlit run app.py
```

Edit your business profile (name, site, description, optional target region) and
competitor list, or click **Discover competitors for me** if you don't know them.
Click **Save & Run analysis**. Results show the final report plus an expandable
step-by-step reasoning trace.

**CLI** (reads the same `config/business.json` / `config/competitors.json`):

```bash
python -m src.main
```

The shipped example config analyzes the author's own real product, [Frenchly](https://frenchly.app)
(an AI French exam-prep app for Canadian immigration candidates), against competitors
the agent discovered and vetted itself.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

26 unit tests cover every deterministic piece (fetch/HTML parsing, snapshot diffing,
cadence math, config loading, the duplicate-score detector, the relevance filter) with
no API key needed. The LLM-driven judgment calls have been verified live, repeatedly,
against real businesses across four different industries (an eyewear retailer, a B2B
sales-enablement SaaS, a proptech platform, and a digital health platform), including
adversarial testing that caught and fixed real bugs (fabricated "change" events on
first-ever runs, visual-score template regression, a rejected competitor's finding
leaking into the top recommendation, a scraping bug reading unrendered JS counters as
literal zeros).

## Tech stack

Python · [Strands Agents SDK](https://strandsagents.com/) · Anthropic Claude
(Sonnet 4.5, direct API) · Streamlit · Playwright · BeautifulSoup · SQLite

No AWS Bedrock, no billed AWS service of any kind — the only cost to run this is an
Anthropic API key.

## License

MIT — see [LICENSE](LICENSE).
