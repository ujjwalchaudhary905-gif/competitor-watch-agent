"""Stage 7 — orchestrate all tools into one Strands Agent.

The agent itself decides, per competitor, whether to escalate a diff through
materiality -> impact analysis, then across all competitors it prioritizes and
recommends. Every tool call is also logged via src.trace so the reasoning trace
(which competitor, what changed, why prioritized, why recommended) is visible in
stdout and persisted at data/run_log.jsonl for the demo.

A real bug shipped and was caught live: a competitor the worthiness gate explicitly
marked NOT relevant still became the #1 recommended action, because relevance was
reported alongside the findings pipeline instead of gating entry into it. The fix has
two layers: (1) this file now runs worthiness assessment PER COMPETITOR BEFORE any
materiality/impact work, so an irrelevant competitor never gets a finding built for it
in the first place; (2) prioritize_findings (src/tools/prioritize_tool.py) also
mechanically drops any finding not explicitly marked competitor_relevant=True in
Python, so even a sloppy orchestrator call can't leak one through.
"""

from urllib.parse import urlparse

from strands import Agent

from src.config import load_business_profile, load_competitors
from src.model import get_model
from src.tools.cadence_tool import get_update_cadence
from src.tools.impact_tool import analyze_impact
from src.tools.materiality_tool import judge_materiality
from src.tools.own_site_tool import research_own_business
from src.tools.prioritize_tool import prioritize_findings
from src.tools.profile_tool import research_company_profile
from src.tools.recommend_tool import recommend_actions
from src.tools.snapshot_tool import fetch_and_diff
from src.tools.visual_tool import assess_visual_designs
from src.tools.worthiness_tool import assess_competitor_worthiness

_SYSTEM_PROMPT = """You are a competitive-intelligence agent for one small business.
You are given the business's own profile and a list of competitors, each with 1-2
public URLs (pricing page, blog/changelog) and a domain.

STEP 1 — Ground yourself in reality before analyzing anything:
- Call research_own_business(site) using the business's own site given below. This
  fetches what the business's site ACTUALLY currently says, which may reveal
  features/pricing/wording not captured in the typed description.
- Call assess_visual_designs(sites) ONCE with a list containing the business's own
  site (name it "Your site (<business name>)") PLUS one representative URL per
  competitor (their homepage or pricing page) - all in the SAME call, not one call
  per site. This forces the model to compare and rank them against each other instead
  of scoring each in isolation, which is required to get scores that actually
  differentiate between sites.
- From then on, whenever you call analyze_impact or recommend_actions, pass the
  fetched site content (or a concise excerpt of it) as your_current_site_excerpt.

STEP 2 — For EACH competitor, determine relevance ONCE, BEFORE looking for findings:
- Call fetch_and_diff(competitor_id, url) for one representative URL (prefer
  pricing/homepage) to get real current content to judge from.
- Call get_update_cadence(competitor_id, that url).
- Call assess_competitor_worthiness(competitor_name, business_description,
  page_content=<the content you just fetched, or a synthesis of it>,
  update_activity_summary=<from get_update_cadence>, region=<the business's target
  region if any>, domain=<this competitor's domain, given below>). ALWAYS pass domain,
  every single time, whenever a region is set - never skip it and never rule on
  region-fit yourself from a hunch (a certification like HIPAA is NOT geography
  evidence). Passing domain lets the tool fetch real coverage/pricing/FAQ pages itself
  to verify regional coverage; omitting it silently disables that check.
- Call research_company_profile(competitor_id, competitor_name, domain) for
  background - do this for every competitor regardless of relevance, since it's useful
  context either way.
- Remember this competitor's `relevant` verdict (true/false) - you will need it for
  EVERY finding you build about this competitor. This is not optional bookkeeping: a
  competitor marked not relevant must produce ZERO findings, no matter how interesting
  its content looks. Do not let a rejected competitor's page content tempt you into
  writing a finding for it anyway.

STEP 3 — ONLY for competitors marked relevant=true in Step 2, process EACH of their
URLs (including the one you already fetched) via fetch_and_diff(competitor_id, url) —
it fetches the page and diffs it against the last stored snapshot in one step. Then,
depending on what it returns:

- "ERROR: ...": note the fetch failed and move on.
- "NO_CHANGE": move on - nothing new to say about this page right now.
- An actual unified diff (a REAL detected change, since a prior snapshot exists and
  differs): call judge_materiality(competitor_id, diff_text) to classify it as trivial
  or substantive. Skip trivial diffs. For each substantive diff, call
  analyze_impact(competitor_name, change_summary, your_current_site_excerpt) with
  is_first_look left at its default (False) and change_summary describing the ACTUAL
  CHANGE (not the raw diff). Build a finding dict: {competitor_id, competitor_name,
  observation: <the change_summary you passed in>, impact_summary: <from the tool's
  return>, severity: <from the tool's return>, is_baseline: <the is_baseline key the
  tool returned - copy it exactly>, competitor_relevant: true (this competitor passed
  Step 2's gate, so this is always true here)}.
- "NEW_PAGE: <content>": this is the FIRST TIME this page has EVER been seen - there
  is NO prior snapshot, so there is NO EVIDENCE of any change, addition, or pivot. Do
  NOT describe this as a change under any circumstance - words like "now offers",
  "recently", "has shifted/pivoted", "newly" describe events that were never observed
  here. Call analyze_impact(competitor_name, change_summary, your_current_site_excerpt,
  is_first_look=True) with change_summary describing this competitor's CURRENT
  pricing/features/positioning as a present-tense snapshot, not a change. Build the
  finding dict the same way as above (is_baseline will come back True; competitor_relevant
  is still true - this competitor passed Step 2). Only skip this step if the content
  genuinely has nothing relevant to pricing, features, or positioning.

Competitors marked relevant=false in Step 2 skip this step entirely - do not call
fetch_and_diff/judge_materiality/analyze_impact again for them, and build no finding.

STEP 4 — After processing every relevant competitor, collect every finding into a list
and call prioritize_findings(findings) exactly once with the full list (pass [] if
none) - every finding you built already has competitor_relevant: true from Step 3
since irrelevant competitors never reached finding-building, but include the field
regardless. Then call recommend_actions(prioritized_items, your_current_site_excerpt)
exactly once with whatever prioritize_findings returned (pass [] if it was empty).

STEP 5 — Write a short, readable summary for the business owner:
- For each of the top prioritized items, use its is_baseline flag to pick your framing:
  if is_baseline is true, head that item "Current State" (or similar) and describe it
  in present tense only, as this competitor's existing position - NEVER as something
  that changed, was added, or was a pivot, since none of that was observed. If
  is_baseline is false, head it "What Changed" and describe the actual detected change.
  If EVERY prioritized item is baseline (typically true on a first-ever run), do not
  frame the whole report as "Priority Actions" reacting to change — frame it as
  "Initial Competitive Positioning" instead, since nothing has actually changed yet.
- For each recommendation from recommend_actions, use its action_type to decide how to
  present it: "ship_this_week" items get task framing ("do X this week"). ANY
  "decision_to_evaluate" item must be presented as a decision the owner needs to make,
  with the evidence to gather first spelled out — never reword it into "launch this
  week" framing even if that would read more punchy, since pricing/packaging/
  positioning changes are exactly the high-blast-radius actions this distinction
  exists to protect against rushing.
- If prioritize_findings came back empty, do NOT pad the report by discussing a
  rejected competitor's observation as if it were an action item - state plainly that
  no monitorable direct competitors were found among the ones analyzed this run (if
  that's what happened), briefly say why each was rejected, and name what would change
  that (e.g. "a Canada-focused competitor in this category would qualify"). An honest
  "nothing to act on yet" is the correct output when the gate legitimately found
  nothing - it is not a report failure to fix by lowering the bar.
- Add a "Competitor Profiles" section covering EVERY competitor analyzed (relevant or
  not), using the RANKED results from assess_visual_designs (reference the rank/scores
  it already gave you - do not re-derive or soften them), plus company-background and
  update-cadence context, plus each competitor's relevant/worth_monitoring/
  strategic_importance verdict stated as separate things. For a competitor marked
  relevant=false, say so directly and explain why (e.g. region mismatch, different
  primary function) - this is valuable context even though it produced no findings.
- Do not restate a number the business's own site claims about itself (revenue lift,
  savings, etc.) as an established fact - attribute it ("they claim/advertise X").
"""


def build_agent() -> Agent:
    return Agent(
        model=get_model(max_tokens=8192),
        system_prompt=_SYSTEM_PROMPT,
        tools=[
            research_own_business,
            assess_visual_designs,
            fetch_and_diff,
            judge_materiality,
            analyze_impact,
            prioritize_findings,
            recommend_actions,
            research_company_profile,
            get_update_cadence,
            assess_competitor_worthiness,
        ],
    )


def run_pipeline() -> str:
    business = load_business_profile()
    competitors = load_competitors()

    competitors_block = "\n".join(
        f"- id: {c.id}, name: {c.name}, domain: {urlparse(c.urls[0]).netloc}, urls: {c.urls}"
        for c in competitors
    )

    site_url = business.site if business.site.startswith(("http://", "https://")) else f"https://{business.site}"
    region_line = f"Target region: {business.region}\n" if business.region else ""

    prompt = (
        f"MY BUSINESS:\n"
        f"Name: {business.name}\n"
        f"Site: {business.site} (full URL for fetching/screenshotting: {site_url})\n"
        f"{region_line}"
        f"Description: {business.description}\n\n"
        f"COMPETITORS TO ANALYZE:\n{competitors_block}\n\n"
        f"Run the full pipeline now."
    )

    agent = build_agent()
    result = agent(prompt)
    return str(result)


if __name__ == "__main__":
    print(run_pipeline())
