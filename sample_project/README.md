# Bookmarks API

A small Flask JSON API for saving and searching bookmarks. It exists so the
Claude Fable 5.1 agent in this tutorial has a real project to inspect instead of
a single toy file.

## Layout

- `app.py` builds the app with a `create_app()` factory and registers three blueprints
- `config.py` holds `Config` and `TestConfig`
- `extensions.py` holds the shared `db` object
- `models.py` defines `User` and `Bookmark`
- `routes/public.py` exposes `/api/status`, `/api/search`, and `/api/feedback` with no authentication
- `routes/auth.py` exposes `/api/auth/token`
- `routes/admin.py` exposes `/api/admin/stats` and a delete route behind an `X-API-Key` header
- `tests/` holds a small pytest suite with an app fixture and a client fixture

## Known gap

Nothing in this project limits how often a client can call an endpoint. The
search route runs an unbounded `ILIKE` query on every request and the token
route has no attempt counter, no delay, and no lockout.

## Run it

```bash
pip install -r requirements.txt
python app.py
pytest
```
