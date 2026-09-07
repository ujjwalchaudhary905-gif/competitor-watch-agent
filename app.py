"""Streamlit frontend for the Competitor Watch Agent.

A thin UI over the same backend validated on the CLI (src/agent.py): edit your
business profile and competitor list, run the pipeline, and see the final report
plus the full step-by-step reasoning trace (which competitor, what changed, why
it was prioritized, why that action/tool was recommended).
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from src.agent import run_pipeline
from src.config import (
    BusinessProfile,
    Competitor,
    load_business_profile,
    load_competitors,
    save_business_profile,
    save_competitors,
)
from src.tools.discover_tool import discover_competitors

_DB_PATH = Path("data/snapshots.db")
_LOG_PATH = Path("data/run_log.jsonl")

_STAGE_LABELS = {
    "fetch": "🌐 Fetch",
    "snapshot": "📸 Snapshot / diff",
    "materiality": "⚖️ Materiality judgment",
    "impact": "💥 Impact analysis",
    "prioritize": "🎯 Prioritization",
    "recommend": "✅ Recommendation",
    "discover": "🔍 Discovery",
    "visual": "🎨 Visual/UX assessment",
    "profile": "🏢 Company profile",
    "cadence": "📅 Update cadence",
    "worthiness": "🚦 Worthiness gate",
    "own_site": "🏠 Your own site",
    "description_gap": "📝 Description gap analysis",
}

st.set_page_config(page_title="Competitor Watch Agent", page_icon="🕵️", layout="wide")
st.title("🕵️ Competitor Watch Agent")
st.caption(
    "Built with the Strands Agents SDK + Claude — compares your business against "
    "multiple competitors and recommends what to act on this week."
)

left, right = st.columns([1, 1.4], gap="large")

with left:
    st.subheader("Your business")
    current_business = load_business_profile()
    biz_name = st.text_input("Name", value=current_business.name)
    biz_site = st.text_input("Site", value=current_business.site)
    biz_region = st.text_input(
        "Target region (optional)",
        value=current_business.region,
        help="e.g. 'Canada', 'United States', 'Morocco'. Leave blank if global/not region-specific. Used to filter out competitors that don't actually serve your market.",
    )
    biz_description = st.text_area(
        "Description (include your pricing)",
        value=current_business.description,
        height=120,
    )

    st.subheader("Competitors")

    if "competitors_data" not in st.session_state:
        st.session_state.competitors_data = pd.DataFrame(
            [{"id": c.id, "name": c.name, "urls": "\n".join(c.urls)} for c in load_competitors()]
        )
    st.session_state.setdefault("competitors_editor_version", 0)

    discover_clicked = st.button(
        "🔍 Discover competitors for me",
        help="Uses Claude's knowledge of your market to propose real competitors, then verifies each one with a live fetch before adding it below.",
    )
    if discover_clicked:
        if not biz_description.strip():
            st.error("Add a business description above first, so the agent knows what market to look in.")
        else:
            with st.spinner("Proposing competitors and verifying their sites live..."):
                try:
                    discovered = discover_competitors(
                        biz_name, biz_description, count=4, region=biz_region.strip(), business_site=biz_site.strip()
                    )
                except Exception as exc:  # noqa: BLE001 - surface any backend error in the UI
                    st.exception(exc)
                    discovered = []
            if discovered:
                st.session_state.competitors_data = pd.DataFrame(
                    [{"id": d["id"], "name": d["name"], "urls": "\n".join(d["urls"])} for d in discovered]
                )
                st.session_state.competitors_editor_version += 1
                st.success(f"Found {len(discovered)} competitor(s) — review the URLs below before running.")
            else:
                st.warning("Couldn't confidently resolve any real competitors automatically. Add them manually below.")

    st.caption("One row per competitor. Put multiple URLs on separate lines within a cell. Edit freely before running.")
    edited_df = st.data_editor(
        st.session_state.competitors_data,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "id": st.column_config.TextColumn("id", help="Short unique id, e.g. 'acme'"),
            "name": st.column_config.TextColumn("name"),
            "urls": st.column_config.TextColumn("urls (one per line)", width="large"),
        },
        key=f"competitors_editor_{st.session_state.competitors_editor_version}",
    )

    reset_snapshots = st.checkbox(
        "Treat all pages as new (reset snapshot history)",
        value=False,
        help="Deletes data/snapshots.db before running, so every page is fetched fresh with nothing to diff against yet.",
    )

    run_clicked = st.button("💾 Save & Run analysis", type="primary", width="stretch")

with right:
    st.subheader("Results")
    results_container = st.container()

if run_clicked:
    business = BusinessProfile(name=biz_name, site=biz_site, description=biz_description, region=biz_region.strip())

    competitors = []
    for _, row in edited_df.iterrows():
        comp_id = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        urls_raw = str(row.get("urls") or "")
        urls = [u.strip() for u in urls_raw.splitlines() if u.strip()]
        if comp_id and name and urls:
            competitors.append(Competitor(id=comp_id, name=name, urls=urls))

    if not competitors:
        st.error("Add at least one competitor with an id, name, and at least one URL.")
    else:
        save_business_profile(business)
        save_competitors(competitors)

        if reset_snapshots and _DB_PATH.exists():
            _DB_PATH.unlink()

        log_lines_before = _LOG_PATH.read_text().splitlines() if _LOG_PATH.exists() else []
        start_index = len(log_lines_before)

        with results_container:
            with st.spinner("Running the pipeline: fetch → diff → judge → impact → prioritize → recommend..."):
                try:
                    final_report = run_pipeline()
                except Exception as exc:  # noqa: BLE001 - surface any backend error in the UI
                    st.exception(exc)
                    final_report = None

        if final_report is not None:
            with results_container:
                st.markdown("### Final report")
                st.markdown(final_report)

                new_lines = (
                    _LOG_PATH.read_text().splitlines()[start_index:]
                    if _LOG_PATH.exists()
                    else []
                )
                records = [json.loads(line) for line in new_lines]

                st.markdown("### Reasoning trace")
                if not records:
                    st.info("No trace entries were recorded for this run.")
                for record in records:
                    stage = record.get("stage", "?")
                    label = _STAGE_LABELS.get(stage, stage)
                    fields = {k: v for k, v in record.items() if k not in ("stage", "ts")}
                    headline = " · ".join(
                        f"**{k}**: {v}" for k, v in fields.items() if not isinstance(v, (list, dict))
                    )
                    with st.expander(f"{label} — {headline[:100]}"):
                        st.json(record)
else:
    with results_container:
        st.info("Edit your business profile and competitors on the left, then click **Save & Run analysis**.")
