"""Streamlit front end for the repository-aware developer task assistant.

    streamlit run app_streamlit.py

On Windows, `python run.py` starts the same app on an event loop that does not
print a harmless connection-reset warning.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from repo_agent import (
    FEATURE_REQUEST,
    MAX_AGENT_TURNS,
    MODEL,
    PRICE_CACHE_READ,
    PRICE_CACHE_WRITE_5M,
    PRICE_INPUT,
    PRICE_OUTPUT,
    agent_events,
)

PROJECTS = {"Bookmarks API (Flask)": "sample_project"}

EXAMPLES = {
    "Rate limiting": FEATURE_REQUEST,
    "Pagination": "Add cursor based pagination to the search endpoint so clients can page through results reliably.",
    "Audit log": "Record who deleted a bookmark and when, and expose the log to admins only.",
    "API key rotation": "Let a user rotate an API key without losing access during the switch.",
}

st.set_page_config(page_title="Fable 5.1 Repo Agent", page_icon="::", layout="wide")

st.markdown(
    """
    <style>
      .stApp { background-color: #f7f5f2; }
      section[data-testid="stSidebar"] { background-color: #ffffff; }
      div[data-testid="stMetricValue"] { font-size: 1.35rem; }
      .progress-line { font-family: ui-monospace, monospace; font-size: 0.86rem; margin: 0.15rem 0; }
      .tool-line { font-family: ui-monospace, monospace; font-size: 0.82rem; color: #6b6b6b; margin-left: 1.2rem; }
      .tool-refused { color: #b3261e; }
    </style>
    """,
    unsafe_allow_html=True,
)

if "history" not in st.session_state:
    st.session_state.history = []

# ----------------------------------------------------------------- sidebar

with st.sidebar:
    logo = Path("assets/datacamp-logo.png")
    if logo.is_file():
        st.image(str(logo), width=140)

    st.markdown("### Repository agent")
    st.caption(f"Model `{MODEL}`")
    st.caption(f"Turn cap {MAX_AGENT_TURNS}. Tools are read only.")

    project_label = st.selectbox("Project", list(PROJECTS))
    project_root = PROJECTS[project_label]

    st.markdown("**Examples**")
    for label, text in EXAMPLES.items():
        if st.button(label, width="stretch", key=f"ex_{label}"):
            st.session_state.request_text = text

    if st.session_state.history:
        spent = sum(run["cost"] for run in st.session_state.history)
        st.divider()
        st.metric("Session spend", f"${spent:.4f}")
        st.caption(f"{len(st.session_state.history)} runs this session")

# -------------------------------------------------------------------- main

st.title("Repository-Aware Developer Task Assistant")
st.write(
    "Describe a feature. The agent reads the project through read-only tools, "
    "reports what it is looking at, and returns a plan grounded in real paths."
)

request_text = st.text_area(
    "Feature request",
    value=st.session_state.get("request_text", FEATURE_REQUEST),
    height=110,
)

run = st.button("Plan the feature", type="primary")

if run and request_text.strip():
    progress_box = st.container()
    lines: list[str] = []
    plan = None
    totals = None
    usage_rows = []

    with st.status("Inspecting the project", expanded=True) as status:
        for event in agent_events(request_text.strip(), project_root):
            kind = event["type"]

            if kind == "progress":
                lines.append(f'<div class="progress-line">[{event["turn"]}] {event["message"]}</div>')
            elif kind == "tool":
                path = event.get("path") or ""
                css = "tool-line tool-refused" if event["refused"] else "tool-line"
                label = "refused" if event["refused"] else "read"
                lines.append(f'<div class="{css}">{label} {event["name"]} {path}</div>')
            elif kind == "usage":
                usage = event["usage"]
                usage_rows.append(
                    {
                        "step": event["label"],
                        "fresh input": usage.input_tokens,
                        "cache write": usage.cache_creation_input_tokens or 0,
                        "cache read": usage.cache_read_input_tokens or 0,
                        "output": usage.output_tokens,
                    }
                )
            elif kind == "inspected":
                status.update(
                    label=f"Read the project in {event['turns']} turns and {event['tool_calls']} tool calls",
                )
            elif kind == "refusal":
                status.update(label=f"Declined ({event['category']})", state="error")
                st.error(f"This request was declined ({event['category']}). Rewrite it and try again.")
            elif kind == "cutoff":
                status.update(label="Hit the output cap", state="error")
                st.error("The model ran out of output tokens before finishing.")
            elif kind == "turn_cap":
                status.update(label="Turn cap reached", state="error")
                st.error(f"No plan after {event['turns']} turns.")
            elif kind == "unparseable":
                status.update(label="Plan did not match the schema", state="error")
                st.error("The model returned something that did not validate.")
            elif kind == "plan":
                plan, totals = event["plan"], event["totals"]
                status.update(label="Plan ready", state="complete", expanded=False)

            progress_box.markdown("".join(lines), unsafe_allow_html=True)

    if plan is not None and totals is not None:
        st.session_state.history.append({"request": request_text.strip(), "cost": totals.cost})

        st.success(plan.summary)

        plan_tab, json_tab, cost_tab = st.tabs(["Plan", "JSON", "Cost"])

        with plan_tab:
            left, right = st.columns(2)
            with left:
                st.subheader("Steps")
                for step in plan.implementation_steps:
                    st.markdown(f"- {step}")
                st.subheader("Files")
                for path in plan.files_to_modify:
                    st.markdown(f"- `{path}`")
            with right:
                st.subheader("Risks")
                for risk in plan.risks:
                    st.markdown(f"- {risk}")
                st.subheader("Tests")
                for test in plan.tests:
                    st.markdown(f"- {test}")

        with json_tab:
            st.json(plan.model_dump())
            st.download_button(
                "Download plan.json",
                data=plan.model_dump_json(indent=2),
                file_name="plan.json",
                mime="application/json",
            )

        with cost_tab:
            a, b, c, d = st.columns(4)
            a.metric("Fresh input", f"{totals.fresh_input:,}")
            b.metric("Cache write", f"{totals.cache_write:,}")
            c.metric("Cache read", f"{totals.cache_read:,}")
            d.metric("Output", f"{totals.output:,}")
            st.metric("Run cost", f"${totals.cost:.4f}")

            breakdown = {
                "fresh input": totals.fresh_input * PRICE_INPUT / 1_000_000,
                "cache write": totals.cache_write * PRICE_CACHE_WRITE_5M / 1_000_000,
                "cache read": totals.cache_read * PRICE_CACHE_READ / 1_000_000,
                "output": totals.output * PRICE_OUTPUT / 1_000_000,
            }
            st.bar_chart(breakdown, horizontal=True, y_label="cost in dollars")
            st.caption(
                "Cache reads are the cheapest line on this bill. Output is almost "
                "always the largest, which is why raising effort matters more to cost "
                "than caching does."
            )

            if usage_rows:
                st.dataframe(usage_rows, width="stretch", hide_index=True)

elif run:
    st.warning("Write a feature request first.")
