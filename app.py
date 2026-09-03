"""FastAPI service around the repository-aware agent.

    uvicorn app:app --reload

Then open http://localhost:8000/docs
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from anthropic import APIStatusError, AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from repo_agent import (
    EFFORT_BETA,
    MAX_AGENT_TURNS,
    MODEL,
    PROGRESS_BETA,
    SCOPED_SYSTEM_BETA,
    FeaturePlan,
    Totals,
    agent_system,
    plan_schema,
    refusal_category,
    status_lines,
)
from repo_tools import TOOLS, ProjectReader

load_dotenv()

# One client for the process. Creating an AsyncAnthropic per request leaks
# connections and throws away connection reuse.
client: AsyncAnthropic | None = None

# Only these project roots can be inspected. A caller cannot name an arbitrary
# path on the server.
ALLOWED_PROJECTS = {"bookmarks-api": "sample_project"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    global client
    client = AsyncAnthropic()
    try:
        yield
    finally:
        await client.close()


app = FastAPI(
    title="Repository-Aware Developer Task Assistant",
    description="Turns a feature request into an implementation plan for a known project.",
    lifespan=lifespan,
)


class PlanRequest(BaseModel):
    feature_request: str = Field(min_length=10, examples=["Add rate limiting to the public API endpoints."])
    project: str = Field(default="bookmarks-api", examples=["bookmarks-api"])


class Usage(BaseModel):
    fresh_input_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class PlanResponse(BaseModel):
    plan: FeaturePlan
    turns: int
    tool_calls: int
    usage: Usage


def resolve_project(name: str) -> ProjectReader:
    root = ALLOWED_PROJECTS.get(name)
    if root is None:
        raise HTTPException(status_code=404, detail=f"unknown project: {name}")
    return ProjectReader(root)


async def inspect(reader: ProjectReader, feature_request: str, on_progress=None):
    """Run the tool loop. Returns (messages, totals, turns, tool_calls)."""
    system = agent_system()
    messages: list[dict] = [{"role": "user", "content": feature_request}]
    totals = Totals()
    tool_calls = 0
    lowered_effort = False

    for turn in range(1, MAX_AGENT_TURNS + 1):
        response = await client.beta.messages.create(
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

        if response.stop_reason == "refusal":
            raise HTTPException(
                status_code=422,
                detail=f"request declined ({refusal_category(response)})",
            )

        if response.stop_reason == "max_tokens":
            raise HTTPException(status_code=502, detail="model hit max_tokens before finishing")

        if response.stop_reason != "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            return messages, totals, turn, tool_calls

        if on_progress:
            for line in status_lines(response):
                await on_progress({"type": "progress", "turn": turn, "message": line})

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_calls += 1
            output, is_error = reader.run(block.name, block.input)
            if on_progress:
                await on_progress(
                    {
                        "type": "tool",
                        "name": block.name,
                        "path": block.input.get("path"),
                        "refused": is_error,
                    }
                )
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": is_error,
                }
            )
        messages.append({"role": "user", "content": results})

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

    raise HTTPException(status_code=504, detail=f"no plan after {MAX_AGENT_TURNS} turns")


async def write_plan(messages: list[dict]):
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

    response = await client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=[EFFORT_BETA, SCOPED_SYSTEM_BETA],
        cache_control={"type": "ephemeral"},
        system=agent_system(),
        tools=TOOLS,
        tool_choice={"type": "none"},
        messages=turn_messages,
        output_config={"format": {"type": "json_schema", "schema": plan_schema()}},
    )

    if response.stop_reason == "refusal":
        raise HTTPException(
            status_code=422,
            detail=f"request declined ({refusal_category(response)})",
        )

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return FeaturePlan.model_validate_json(text), response.usage
    except Exception:
        raise HTTPException(status_code=502, detail="model returned a plan that did not match the schema")


def as_usage(totals: Totals) -> Usage:
    return Usage(
        fresh_input_tokens=totals.fresh_input,
        cache_write_tokens=totals.cache_write,
        cache_read_tokens=totals.cache_read,
        output_tokens=totals.output,
        estimated_cost_usd=round(totals.cost, 4),
    )


@app.post("/plan", response_model=PlanResponse)
async def create_plan(body: PlanRequest):
    reader = resolve_project(body.project)
    try:
        messages, totals, turns, tool_calls = await inspect(reader, body.feature_request)
        plan, final_usage = await write_plan(messages)
    except APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"upstream error {exc.status_code}") from exc

    totals.add(final_usage)
    return PlanResponse(plan=plan, turns=turns, tool_calls=tool_calls, usage=as_usage(totals))


@app.post("/plan/stream")
async def stream_plan(body: PlanRequest):
    """Server-sent events, so a caller sees the status lines while the agent works."""
    reader = resolve_project(body.project)
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: dict):
        await queue.put(event)

    async def work():
        try:
            messages, totals, turns, tool_calls = await inspect(reader, body.feature_request, emit)
            plan, final_usage = await write_plan(messages)
            totals.add(final_usage)
            await emit(
                {
                    "type": "plan",
                    "turns": turns,
                    "tool_calls": tool_calls,
                    "plan": plan.model_dump(),
                    "usage": as_usage(totals).model_dump(),
                }
            )
        except HTTPException as exc:
            await emit({"type": "error", "detail": exc.detail})
        except Exception as exc:
            await emit({"type": "error", "detail": f"{type(exc).__name__}"})
        finally:
            await queue.put(None)

    async def events():
        task = asyncio.create_task(work())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL, "projects": sorted(ALLOWED_PROJECTS)}
