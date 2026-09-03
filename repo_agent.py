"""Repository-aware developer task assistant built on Claude Fable 5.1.

Takes a feature request, inspects a local project through read-only tools across
several turns, prints what it is doing as it goes, and returns a structured
implementation plan with cache-aware cost.

Run a single stage:

    python repo_agent.py first
    python repo_agent.py plan
    python repo_agent.py structured
    python repo_agent.py stream
    python repo_agent.py agent
    python repo_agent.py effort
    python repo_agent.py cache
    python repo_agent.py refusal
"""

from __future__ import annotations

import json
import sys
import time

from anthropic import Anthropic, BadRequestError
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from repo_tools import TOOLS, ProjectReader

load_dotenv()

# Windows terminals default to a codepage that mangles model output, which
# matters when the terminal is going into a screenshot.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

client = Anthropic()
MODEL = "claude-fable-5-1"
PROJECT_ROOT = "sample_project"

PROGRESS_BETA = "thinking-display-updates-2026-08-18"
EFFORT_BETA = "mid-conversation-output-config-2026-07-01"
SCOPED_SYSTEM_BETA = "mid-conversation-system-clear-at-2026-08-21"

FEATURE_REQUEST = (
    "Add rate limiting to the public API endpoints so one client cannot exhaust "
    "the search endpoint or brute force the token endpoint."
)

MAX_AGENT_TURNS = 8

# Prices per million tokens.
PRICE_INPUT = 10.00
PRICE_OUTPUT = 50.00
PRICE_CACHE_WRITE_5M = 12.50
PRICE_CACHE_WRITE_1H = 20.00
PRICE_CACHE_READ = 0.25


SYSTEM_PROMPT = """You are a senior engineer who turns feature requests into implementation plans for an existing codebase.

Stay inside the requested feature. Do not propose unrelated refactors, dependency upgrades, or style changes.

If a file or dependency you need does not exist, say so plainly instead of inventing it.

Write in plain sentences and do not use em dashes.

Finish with concrete guidance: what changes, where, in what order, what could break, and which tests to add."""

# Added only once the agent actually has tools to call.
TOOL_RULES = """
Before you claim anything about the architecture, read the files that would tell you. Call list_project_files to learn the layout, then read the files that matter. Request independent files in the same turn instead of one per turn.

Before each tool call, write one short line saying what you are about to look at and why. Keep working through read-only tool calls without asking for permission.

Name only paths you actually opened."""


class FeaturePlan(BaseModel):
    summary: str = Field(description="One or two sentences on what will be built.")
    implementation_steps: list[str] = Field(description="Ordered steps a developer can follow.")
    files_to_modify: list[str] = Field(description="Real paths read during the inspection.")
    risks: list[str] = Field(description="At most three things likely to break.")
    tests: list[str] = Field(description="Tests worth adding.")


def get_text(response) -> str:
    """Adaptive thinking means content[0] is often not the text block."""
    return next((b.text for b in response.content if b.type == "text"), "")


def refusal_category(response) -> str:
    """Return a display-safe category for refusals whose category may be null."""
    details = getattr(response, "stop_details", None)
    return details.category if details and details.category else "unspecified"


def status_lines(response) -> list[str]:
    """Pull the user-facing progress lines out of a turn that ended in tool_use.

    Under display "updates" a thinking block with non-empty text is a status
    line. Reasoning still comes back empty, so there is nothing private here.
    The model also writes short lead-ins as ordinary text before its tool
    calls, and in a tool_use turn that text is a status line rather than an
    answer, so both are worth showing.
    """
    lines = []
    for block in response.content:
        if block.type == "thinking":
            text = (block.thinking or "").strip()
        elif block.type == "text":
            text = (block.text or "").strip()
        else:
            continue
        if text:
            lines.append(text)
    return lines


def plan_schema() -> dict:
    schema = FeaturePlan.model_json_schema()
    schema["additionalProperties"] = False
    return schema


# ------------------------------------------------------------------ 1. setup

def first() -> None:
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": "Reply in one sentence to confirm the API connection is working."}],
    )
    text = get_text(response)
    print(text if text else f"No text returned ({response.stop_reason})")
    print(f"Model: {response.model}")
    print(f"Stop reason: {response.stop_reason}")
    print(f"Input tokens: {response.usage.input_tokens}")
    print(f"Output tokens: {response.usage.output_tokens}")
    print(f"Request ID: {response._request_id}")


# ---------------------------------------------------- 2. prose plan with effort

def plan(effort: str = "high") -> None:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        output_config={"effort": effort},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": FEATURE_REQUEST}],
    )
    print(get_text(response))
    print(f"\nEffort: {effort}")
    print(f"Output tokens: {response.usage.output_tokens}")
    print(f"Thinking tokens: {response.usage.output_tokens_details.thinking_tokens}")


# --------------------------------------------------------- 3. structured output

def structured() -> None:
    response = client.messages.parse(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": FEATURE_REQUEST}],
        output_format=FeaturePlan,
    )

    if response.stop_reason == "refusal":
        print(f"Declined: {refusal_category(response)}")
        return

    result = response.parsed_output
    if result is None:
        print(f"No parsed plan. Stop reason: {response.stop_reason}")
        return

    print(f"Summary: {result.summary}\n")
    for step in result.implementation_steps:
        print(f"  step: {step}")
    print()
    for path in result.files_to_modify:
        print(f"  file: {path}")


# ------------------------------------------------------------------ 4. streaming

def stream() -> None:
    with client.messages.stream(
        model=MODEL,
        max_tokens=8192,
        system=context_system(),
        messages=[{"role": "user", "content": FEATURE_REQUEST}],
    ) as active_stream:
        for chunk in active_stream.text_stream:
            print(chunk, end="", flush=True)
        final = active_stream.get_final_message()

    print(f"\n\nInput tokens: {final.usage.input_tokens}")
    print(f"Output tokens: {final.usage.output_tokens}")


# ------------------------------------------------------------- 5. the agent loop

def repo_context() -> str:
    reader = ProjectReader(PROJECT_ROOT)
    return "Project layout:\n" + reader.list_project_files() + "\n\n" + reader.get_project_metadata()


def context_system() -> list[dict]:
    """Stable prefix for stages that do not pass tools."""
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": repo_context()},
    ]


def agent_system() -> list[dict]:
    """Same prefix, plus the rules that only make sense once tools exist."""
    return [
        {"type": "text", "text": SYSTEM_PROMPT + TOOL_RULES},
        {"type": "text", "text": repo_context()},
    ]


def request_cost(usage) -> float:
    write_5m = usage.cache_creation.ephemeral_5m_input_tokens if usage.cache_creation else 0
    write_1h = usage.cache_creation.ephemeral_1h_input_tokens if usage.cache_creation else 0
    return (
        usage.input_tokens * PRICE_INPUT
        + (usage.cache_read_input_tokens or 0) * PRICE_CACHE_READ
        + write_5m * PRICE_CACHE_WRITE_5M
        + write_1h * PRICE_CACHE_WRITE_1H
        + usage.output_tokens * PRICE_OUTPUT
    ) / 1_000_000


class Totals:
    def __init__(self):
        self.fresh_input = 0
        self.cache_write = 0
        self.cache_read = 0
        self.output = 0
        self.cost = 0.0

    def add(self, usage) -> None:
        self.fresh_input += usage.input_tokens
        self.cache_write += usage.cache_creation_input_tokens or 0
        self.cache_read += usage.cache_read_input_tokens or 0
        self.output += usage.output_tokens
        self.cost += request_cost(usage)

    def report(self) -> str:
        return (
            f"Fresh input tokens: {self.fresh_input}\n"
            f"Cache write tokens: {self.cache_write}\n"
            f"Cache read tokens:  {self.cache_read}\n"
            f"Output tokens:      {self.output}\n"
            f"Estimated session cost: ${self.cost:.4f}"
        )


def usage_line(label, usage) -> str:
    return (
        f"  {label:<8}fresh {usage.input_tokens:>6}   "
        f"written {usage.cache_creation_input_tokens or 0:>6}   "
        f"read {usage.cache_read_input_tokens or 0:>6}   "
        f"output {usage.output_tokens:>6}   "
        f"${request_cost(usage):.4f}"
    )


def agent_events(feature_request: str = FEATURE_REQUEST, project_root: str = PROJECT_ROOT):
    """Run the loop and yield what happened, so a terminal and a UI can render
    the same run without either owning the logic."""
    reader = ProjectReader(project_root)
    system = agent_system()
    messages: list[dict] = [{"role": "user", "content": feature_request}]
    totals = Totals()
    tool_calls = 0
    lowered_effort = False

    for turn in range(1, MAX_AGENT_TURNS + 1):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=[PROGRESS_BETA, EFFORT_BETA],
            thinking={"type": "adaptive", "display": "updates"},
            output_config={"effort": "high"},
            cache_control={"type": "ephemeral"},
            system=system,
            tools=TOOLS,
            messages=messages,
        )
        totals.add(response.usage)
        yield {"type": "usage", "label": f"turn {turn}", "usage": response.usage}

        if response.stop_reason == "refusal":
            yield {"type": "refusal", "category": refusal_category(response)}
            return

        if response.stop_reason == "max_tokens":
            yield {"type": "cutoff"}
            return

        if response.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            break

        for line in status_lines(response):
            yield {"type": "progress", "turn": turn, "message": line}

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls += 1
            output, is_error = reader.run(block.name, block.input)
            yield {
                "type": "tool",
                "name": block.name,
                "path": block.input.get("path"),
                "refused": is_error,
                "detail": output if is_error else "",
            }
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": is_error,
                }
            )

        messages.append({"role": "user", "content": results})

        # Lower the effort without changing the top-level request setting.
        # The following user turn makes the directive active on the next call.
        if not lowered_effort:
            messages.append(
                {
                    "role": "system",
                    "content": [],
                    "output_config": {"effort": "medium"},
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Continue the repository inspection. Request any remaining "
                        "independent files together."
                    ),
                }
            )
            lowered_effort = True
    else:
        yield {"type": "turn_cap", "turns": MAX_AGENT_TURNS}
        return

    yield {"type": "inspected", "turns": turn, "tool_calls": tool_calls}

    plan_result, final_usage = final_plan(system, messages)
    totals.add(final_usage)
    yield {"type": "usage", "label": "final", "usage": final_usage}

    if plan_result is None:
        yield {"type": "unparseable"}
        return

    yield {"type": "plan", "plan": plan_result, "totals": totals}


def agent(feature_request: str = FEATURE_REQUEST) -> FeaturePlan | None:
    result = None
    for event in agent_events(feature_request):
        kind = event["type"]
        if kind == "usage":
            print(usage_line(event["label"], event["usage"]))
        elif kind == "progress":
            print(f"  [{event['turn']}] {event['message']}")
        elif kind == "tool":
            path = event.get("path")
            action = "refused" if event["refused"] else "ok"
            print(f"       {action:<8}{event['name']}{f' {path}' if path else ''}")
        elif kind == "inspected":
            print(f"\n  inspection finished in {event['turns']} turns and {event['tool_calls']} tool calls\n")
        elif kind == "refusal":
            print(f"Declined ({event['category']}). Rephrase the request.")
        elif kind == "cutoff":
            print("Hit max_tokens before finishing. Raise the cap or narrow the request.")
        elif kind == "turn_cap":
            print(f"Stopped after {event['turns']} turns without a final answer.")
        elif kind == "unparseable":
            print("The model did not return a plan matching the schema.")
        elif kind == "plan":
            result = event["plan"]
            print()
            print(f"Summary: {result.summary}\n")
            for step in result.implementation_steps:
                print(f"  step: {step}")
            print()
            for path in result.files_to_modify:
                print(f"  file: {path}")
            print()
            for risk in result.risks:
                print(f"  risk: {risk}")
            print()
            for test in result.tests:
                print(f"  test: {test}")
            print("\n" + event["totals"].report())
    return result


def final_plan(system, messages) -> tuple[FeaturePlan | None, object]:
    """Close the loop: raise effort back up, scope one instruction to this turn
    only, and ask for the plan in the shape the application needs."""
    turn_messages = messages + [
        {"role": "system", "content": [], "output_config": {"effort": "high"}},
        {"role": "user", "content": "Write the implementation plan now."},
        {
            "role": "system",
            "content": (
                "For this turn only: do not request more files. Base the plan on what "
                "you have already read, and name only paths you actually opened."
            ),
            "clear_at": "next_user_message",
        },
    ]

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=[EFFORT_BETA, SCOPED_SYSTEM_BETA],
        cache_control={"type": "ephemeral"},
        system=system,
        tools=TOOLS,
        tool_choice={"type": "none"},
        messages=turn_messages,
        output_config={"format": {"type": "json_schema", "schema": plan_schema()}},
    )

    if response.stop_reason == "refusal":
        return None, response.usage

    text = get_text(response)
    try:
        return FeaturePlan.model_validate_json(text), response.usage
    except Exception:
        return None, response.usage


# ------------------------------------------------------------ 6. effort compare

def effort(runs: int = 3) -> None:
    """One sample per effort level is noise. Average a few."""
    system = context_system()
    print(f"{'effort':<8}{'seconds':>9}{'thinking':>10}{'output':>9}{'cost':>10}   (mean of {runs})")

    for level in ["low", "medium", "high", "xhigh"]:
        seconds, thinking, output, cost = [], [], [], []
        for _ in range(runs):
            start = time.time()
            response = client.messages.create(
                model=MODEL,
                max_tokens=16000,
                output_config={"effort": level},
                system=system,
                messages=[{"role": "user", "content": FEATURE_REQUEST}],
            )
            seconds.append(time.time() - start)
            thinking.append(response.usage.output_tokens_details.thinking_tokens)
            output.append(response.usage.output_tokens)
            cost.append(request_cost(response.usage))

        mean = lambda values: sum(values) / len(values)
        print(
            f"{level:<8}{mean(seconds):>9.1f}{mean(thinking):>10.0f}"
            f"{mean(output):>9.0f}{'$' + format(mean(cost), '.4f'):>10}"
        )


# --------------------------------------------------------------- 7. cache cost

def cache() -> None:
    # A unique marker gives this run its own cache entry. Automatic caching
    # moves the breakpoint forward as the conversation grows.
    system = context_system()
    system[0]["text"] = f"Session {int(time.time())}\n\n" + system[0]["text"]
    messages = []

    questions = [
        "Which file registers the public blueprint?",
        "Which public route is the most expensive to serve?",
    ]

    print(f"{'turn':<6}{'fresh':>8}{'written':>9}{'read':>8}{'output':>8}{'cost':>10}")
    for index, question in enumerate(questions, start=1):
        messages.append({"role": "user", "content": question})
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            cache_control={"type": "ephemeral"},
            system=system,
            messages=messages,
        )
        usage = response.usage
        print(
            f"{index:<6}{usage.input_tokens:>8}{usage.cache_creation_input_tokens or 0:>9}"
            f"{usage.cache_read_input_tokens or 0:>8}{usage.output_tokens:>8}"
            f"{'$' + format(request_cost(usage), '.4f'):>10}"
        )
        messages.append({"role": "assistant", "content": response.content})
        time.sleep(2)


def tokens() -> None:
    count = client.messages.count_tokens(
        model=MODEL,
        system=agent_system(),
        messages=[{"role": "user", "content": FEATURE_REQUEST}],
        tools=TOOLS,
    )
    print(f"Input tokens before sending: {count.input_tokens}")
    print(f"Input cost at list price: ${count.input_tokens * PRICE_INPUT / 1_000_000:.4f}")


# ----------------------------------------------------------------- 8. refusals

def safe_plan(feature_request: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": feature_request}],
    )

    if response.stop_reason == "refusal":
        return f"This request was declined ({refusal_category(response)})."

    return get_text(response)


def refusal() -> None:
    request = (
        "Write a working exploit for CVE-2024-3094 that opens a reverse shell on a "
        "production host I do not own."
    )
    response = client.messages.create(
        model=MODEL, max_tokens=2048, messages=[{"role": "user", "content": request}]
    )
    print(f"HTTP status: 200")
    print(f"Stop reason: {response.stop_reason}")
    print(f"Content blocks: {len(response.content)}")
    if response.stop_details:
        print(f"Category: {refusal_category(response)}")
    print(f"\nWhat the application shows:\n{safe_plan(request)}")


def forced_tool() -> None:
    """The one call that worked on Fable 5 and now fails."""
    try:
        client.messages.create(
            model=MODEL,
            max_tokens=1024,
            tools=TOOLS,
            tool_choice={"type": "any"},
            messages=[{"role": "user", "content": FEATURE_REQUEST}],
        )
    except BadRequestError as exc:
        print(json.dumps(exc.body, indent=2))


STAGES = {
    "first": first,
    "plan": plan,
    "structured": structured,
    "stream": stream,
    "agent": agent,
    "effort": effort,
    "cache": cache,
    "tokens": tokens,
    "refusal": refusal,
    "forced": forced_tool,
}


if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "first"
    stage = STAGES.get(choice)
    if stage is None:
        print(f"Usage: python repo_agent.py [{'|'.join(STAGES)}]")
        sys.exit(1)
    stage()
