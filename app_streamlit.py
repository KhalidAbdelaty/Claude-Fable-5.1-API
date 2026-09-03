"""Streamlit front end for the repository-aware developer task assistant.

    streamlit run app_streamlit.py

On Windows, `python run.py` starts the same app on an event loop that does not
print a harmless connection-reset warning.
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from repo_agent import (
    EFFORT_BETA,
    FEATURE_REQUEST,
    MAX_AGENT_TURNS,
    MODEL,
    PRICE_CACHE_READ,
    PRICE_CACHE_WRITE_5M,
    PRICE_INPUT,
    PRICE_OUTPUT,
    PROGRESS_BETA,
    SCOPED_SYSTEM_BETA,
    agent_events,
)

LOGO = Path("assets/datacamp-logo.png")


def logo_link(path: Path, width: int, href: str) -> str:
    """Center the logo and make it a link. st.image cannot do either."""
    data = base64.b64encode(path.read_bytes()).decode()
    return (
        f"<a href='{href}' target='_blank' rel='noopener' "
        "style='display:flex; justify-content:center; margin:.1rem 0 .7rem;'>"
        f"<img src='data:image/png;base64,{data}' width='{width}' "
        "style='max-width:100%;'/></a>"
    )

PROJECTS = {"Bookmarks API (Flask)": "sample_project"}

EXAMPLES = {
    "Rate limiting": FEATURE_REQUEST,
    "Pagination": "Add cursor based pagination to the search endpoint so clients can page through results reliably.",
    "Audit log": "Record who deleted a bookmark and when, and expose the log to admins only.",
    "API key rotation": "Let a user rotate an API key without losing access during the switch.",
}

# Fable 5.1 capabilities the workflow exercises. Shown in the sidebar so the demo
# doubles as a map of what the model and the tutorial cover.
CAPABILITIES = [
    ("1M context, adaptive thinking", "Always-on reasoning, tuned with effort rather than an on/off switch."),
    ("Staged effort", "high while planning, medium for routine file reads, high again for the final plan."),
    ("Progress updates", "Readable status lines between tool calls, streamed live below."),
    ("Read-only tool loop", "Three tools behind a path boundary. The model never touches the filesystem."),
    ("Structured output", "The final plan is validated against a Pydantic schema."),
    ("Prompt caching", "The repeated prefix is cached, so later turns read it back at $0.25 / MTok."),
    ("Append-only history", "Turns are only appended, so thinking blocks stay valid."),
    ("Refusal handling", "A declined request is surfaced as a state, not an exception."),
]

st.set_page_config(
    page_title="Fable 5.1 Repository Agent",
    page_icon=str(LOGO) if LOGO.is_file() else None,
    layout="wide",
)

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600&display=swap');

      :root {
        --japonica:  #D97757;
        --terracotta-dark: #C15F3C;
        --pampas:    #F4F3EE;
        --cloudy:    #B1ADA1;
        --tuatara:   #373734;
        --line:      #E7E3DA;
        --muted:     #6B6862;
        --card:      #FFFFFF;
      }

      /* Base type */
      html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
        font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
      }
      h1, h2, h3 { font-family: 'Fraunces', Georgia, 'Times New Roman', serif !important; color: var(--tuatara); letter-spacing: -0.01em; }

      /* Blend the top toolbar into the cream background */
      [data-testid="stHeader"] { background: transparent; }
      [data-testid="stAppViewContainer"] { background: var(--pampas); }
      [data-testid="stSidebar"] { border-right: 1px solid var(--line); }

      .block-container { padding-top: 2.2rem; max-width: 1180px; }

      /* Hero */
      .hero-badge {
        display:inline-flex; align-items:center; gap:.5rem;
        background: #FBF0EB; color: var(--terracotta-dark);
        border: 1px solid #EFD9CF; border-radius: 999px;
        padding: .28rem .8rem; font-size: .78rem; font-weight: 600;
        font-family: ui-monospace, "SF Mono", Menlo, monospace;
      }
      .hero-dot { width:7px; height:7px; border-radius:50%; background: var(--japonica); }
      .hero-title { font-size: 2.5rem; font-weight: 600; margin: .55rem 0 .35rem; line-height: 1.08; }
      .hero-sub { color: var(--muted); font-size: 1.02rem; max-width: 720px; margin-bottom: .2rem; }

      /* Buttons: primary = terracotta, secondary = white card */
      .stButton > button {
        border-radius: 10px; font-weight: 600; transition: all .15s ease;
        border: 1px solid var(--line);
      }
      .stButton > button[kind="primary"] {
        background: var(--japonica); border-color: var(--japonica); color: #fff;
        box-shadow: 0 1px 2px rgba(55,55,52,.12);
      }
      .stButton > button[kind="primary"]:hover {
        background: var(--terracotta-dark); border-color: var(--terracotta-dark);
        transform: translateY(-1px); box-shadow: 0 4px 12px rgba(193,95,60,.28);
      }
      .stButton > button[kind="primary"]:active { transform: translateY(0); }
      .stButton > button[kind="secondary"] {
        background: var(--card); color: var(--tuatara);
      }
      .stButton > button[kind="secondary"]:hover {
        border-color: var(--japonica); color: var(--terracotta-dark);
        background: #FCF4F0; transform: translateY(-1px);
      }

      /* Inputs */
      [data-testid="stTextArea"] textarea {
        border-radius: 12px; border: 1px solid var(--line); background: var(--card);
        font-size: .98rem;
      }
      [data-testid="stTextArea"] textarea:focus {
        border-color: var(--japonica); box-shadow: 0 0 0 3px rgba(217,119,87,.15);
      }

      /* Progress + tool lines */
      .progress-line {
        font-size: .9rem; color: var(--tuatara); background: var(--card);
        border: 1px solid var(--line); border-left: 3px solid var(--japonica);
        border-radius: 8px; padding: .5rem .7rem; margin: .35rem 0;
      }
      .progress-turn { color: var(--japonica); font-weight: 600; font-family: ui-monospace, monospace; }
      .tool-line {
        font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: .8rem;
        color: var(--muted); margin: .12rem 0 .12rem 1.4rem;
      }
      .tool-line .badge-ok { color: #3B7A57; font-weight: 600; }
      .tool-refused .badge-no { color: #B3261E; font-weight: 600; }

      /* Capability rows */
      .cap { padding: .5rem 0; border-bottom: 1px solid var(--line); }
      .cap:last-child { border-bottom: none; }
      .cap-name { font-weight: 600; font-size: .86rem; color: var(--tuatara); }
      .cap-desc { font-size: .78rem; color: var(--muted); line-height: 1.35; margin-top: .1rem; }

      /* Tabs */
      .stTabs [data-baseweb="tab-list"] { gap: .3rem; border-bottom: 1px solid var(--line); }
      .stTabs [data-baseweb="tab"] { font-weight: 600; color: var(--muted); }
      .stTabs [aria-selected="true"] { color: var(--terracotta-dark) !important; }
      .stTabs [data-baseweb="tab-highlight"] { background: var(--japonica) !important; }

      [data-testid="stMetric"] {
        background: var(--card); border: 1px solid var(--line);
        border-radius: 12px; padding: .8rem 1rem;
      }
      div[data-testid="stMetricValue"] { font-size: 1.35rem; color: var(--tuatara); }

      hr { border-color: var(--line); }
    </style>
    """,
    unsafe_allow_html=True,
)

if "history" not in st.session_state:
    st.session_state.history = []

# ----------------------------------------------------------------- sidebar

with st.sidebar:
    if LOGO.is_file():
        st.markdown(
            logo_link(LOGO, 190, "https://www.datacamp.com/blog"),
            unsafe_allow_html=True,
        )

    st.markdown(f"<div class='hero-badge'><span class='hero-dot'></span>{MODEL}</div>", unsafe_allow_html=True)
    st.caption(f"Turn cap {MAX_AGENT_TURNS}  ::  tools are read only")

    project_label = st.selectbox("Project", list(PROJECTS))
    project_root = PROJECTS[project_label]

    st.markdown("#### Try an example")
    for label, text in EXAMPLES.items():
        if st.button(label, width="stretch", key=f"ex_{label}"):
            st.session_state.request_text = text

    with st.expander("What Fable 5.1 does here", expanded=False):
        for name, desc in CAPABILITIES:
            st.markdown(
                f"<div class='cap'><div class='cap-name'>{name}</div>"
                f"<div class='cap-desc'>{desc}</div></div>",
                unsafe_allow_html=True,
            )

    with st.expander("Beta headers in use", expanded=False):
        st.markdown(
            f"- `{PROGRESS_BETA}`\n"
            f"- `{EFFORT_BETA}`\n"
            f"- `{SCOPED_SYSTEM_BETA}`"
        )

    with st.expander("Pricing (per MTok)", expanded=False):
        st.markdown(
            f"- Input  ${PRICE_INPUT:.2f}\n"
            f"- Output  ${PRICE_OUTPUT:.2f}\n"
            f"- Cache write (5m)  ${PRICE_CACHE_WRITE_5M:.2f}\n"
            f"- Cache read  ${PRICE_CACHE_READ:.2f}"
        )

    if st.session_state.history:
        spent = sum(run["cost"] for run in st.session_state.history)
        st.divider()
        st.metric("Session spend", f"${spent:.4f}")
        st.caption(f"{len(st.session_state.history)} runs this session")

# -------------------------------------------------------------------- hero

st.markdown(
    "<div class='hero-badge'><span class='hero-dot'></span>Powered by "
    f"{MODEL}</div>",
    unsafe_allow_html=True,
)
st.markdown("<div class='hero-title'>Repository-Aware Developer Task Assistant</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='hero-sub'>Describe a feature. The agent reads the project through read-only tools, "
    "reports what it is looking at, and returns a plan grounded in the files it actually opened.</div>",
    unsafe_allow_html=True,
)

st.write("")

request_text = st.text_area(
    "Feature request",
    value=st.session_state.get("request_text", FEATURE_REQUEST),
    height=110,
    label_visibility="collapsed",
)

run = st.button("Plan the feature", type="primary")

# -------------------------------------------------------------------- run

if run and request_text.strip():
    lines: list[str] = []
    plan = None
    totals = None
    usage_rows = []

    timeline = st.container()

    with st.status("Inspecting the project", expanded=True) as status:
        stream_box = timeline.empty()
        for event in agent_events(request_text.strip(), project_root):
            kind = event["type"]

            if kind == "progress":
                lines.append(
                    f"<div class='progress-line'><span class='progress-turn'>turn {event['turn']}</span>&nbsp; "
                    f"{event['message']}</div>"
                )
            elif kind == "tool":
                path = event.get("path") or ""
                if event["refused"]:
                    lines.append(
                        f"<div class='tool-line tool-refused'><span class='badge-no'>refused</span> "
                        f"{event['name']} {path}</div>"
                    )
                else:
                    lines.append(
                        f"<div class='tool-line'><span class='badge-ok'>read</span> "
                        f"{event['name']} {path}</div>"
                    )
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

            stream_box.markdown("".join(lines), unsafe_allow_html=True)

    if plan is not None and totals is not None:
        st.session_state.history.append({"request": request_text.strip(), "cost": totals.cost})

        st.markdown(f"### {plan.summary}")

        plan_tab, json_tab, cost_tab, usage_tab = st.tabs(["Plan", "JSON", "Cost", "Usage"])

        with plan_tab:
            left, right = st.columns(2)
            with left:
                with st.container(border=True):
                    st.markdown("#### Implementation steps")
                    for i, step in enumerate(plan.implementation_steps, start=1):
                        st.markdown(f"**{i}.** {step}")
                with st.container(border=True):
                    st.markdown("#### Files to modify")
                    for path in plan.files_to_modify:
                        st.markdown(f"- `{path}`")
            with right:
                with st.container(border=True):
                    st.markdown("#### Risks")
                    for risk in plan.risks:
                        st.markdown(f"- {risk}")
                with st.container(border=True):
                    st.markdown("#### Tests to add")
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

            breakdown = [
                {"line item": "fresh input", "cost": totals.fresh_input * PRICE_INPUT / 1_000_000},
                {"line item": "cache write", "cost": totals.cache_write * PRICE_CACHE_WRITE_5M / 1_000_000},
                {"line item": "cache read", "cost": totals.cache_read * PRICE_CACHE_READ / 1_000_000},
                {"line item": "output", "cost": totals.output * PRICE_OUTPUT / 1_000_000},
            ]
            st.bar_chart(
                breakdown, x="line item", y="cost",
                horizontal=True, x_label="cost in dollars", color="#D97757",
            )
            st.caption(
                "Cache reads are the cheapest line on this bill. Output is almost "
                "always the largest, which is why raising effort matters more to cost "
                "than caching does."
            )

        with usage_tab:
            if usage_rows:
                st.dataframe(usage_rows, width="stretch", hide_index=True)
            st.caption("Per-request token split across the inspection turns and the final plan.")

elif run:
    st.warning("Write a feature request first.")
