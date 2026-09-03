# Repository-Aware Developer Task Assistant (Claude Fable 5.1)

A developer agent built on the Claude Fable 5.1 API. Give it a feature request
and it inspects a local project through read-only tools across several turns,
prints what it is looking at as it goes, and returns a validated implementation
plan with a cache-aware cost estimate.

The same workflow ships three ways: a local script, a FastAPI service, and a
Streamlit UI.

## Files

- `repo_agent.py` covers the whole API path: first call, effort, system prompt, structured output, streaming, the tool loop, mid-conversation effort, turn-scoped instructions, prompt caching, cost, and refusals
- `repo_tools.py` holds the three read-only tools and the path boundary that makes them safe
- `app.py` exposes `POST /plan` and a server-sent-events `POST /plan/stream`
- `app_streamlit.py` is the UI, rendering progress lines, the plan, and the estimated cost split
- `run.py` starts the UI on Windows without a noisy connection-reset warning
- `sse_client.py` is a small client for checking the streaming endpoint
- `sample_project/` is the Flask project the agent reads, with no rate limiting anywhere in it

`repo_agent.py` owns the shared contract: the system prompt, the tool schemas,
the plan schema, the prices, and the cost math. The service and the UI import
those rather than redefining them, so a change to the plan shape or the pricing
lands in one place.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS or Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # then paste your key into .env
```

You need an Anthropic API key with access to `claude-fable-5-1`, on an account
configured for 30-day retention.

## Run

```bash
# One stage at a time
python repo_agent.py first        # smallest possible request
python repo_agent.py plan         # prose plan with an effort setting
python repo_agent.py structured   # validated plan object
python repo_agent.py stream       # token by token
python repo_agent.py agent        # the full tool loop
python repo_agent.py effort       # latency, tokens, and cost per effort level
python repo_agent.py cache        # cache write turn versus cache read turn
python repo_agent.py tokens       # count tokens before sending
python repo_agent.py refusal      # a real refusal and how it surfaces
python repo_agent.py forced       # the tool_choice call that Fable 5 allowed

# Service, then open http://localhost:8000/docs
uvicorn app:app --reload
python sse_client.py

# UI
streamlit run app_streamlit.py
python run.py                     # Windows
```

## Notes

- Adaptive thinking is always on. `thinking: {"type": "disabled"}` returns a 400, and effort is the main API control for thinking depth.
- Because a response can lead with a thinking block, the code reads text through a `get_text()` helper instead of indexing `content[0]`.
- Forced tool choice is gone. `tool_choice: {"type": "any"}` and a named tool both return a 400, so the tool schemas set `strict` and the prompt names the tools instead.
- The model never touches the filesystem. `repo_tools.py` resolves every requested path against one allowed root and refuses anything that escapes it, follows a symlink, or names a secret.
- Three beta headers are in use: `thinking-display-updates-2026-08-18` for progress updates, `mid-conversation-output-config-2026-07-01` for per-message effort, and `mid-conversation-system-clear-at-2026-08-21` for turn-scoped instructions.
- The conversation is append-only. Editing an earlier turn discards the reasoning bound to it, so the loop only appends.
- Top-level automatic caching moves the breakpoint forward as the conversation grows, so the next turn can reuse the earlier prefix.
- A refusal arrives as HTTP 200 with `stop_reason: "refusal"`, so the code checks the stop reason before it tries to read a plan.

## License

MIT
