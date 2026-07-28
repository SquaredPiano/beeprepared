# 01 — Configuration and startup

This is the layer that decides what kind of process you are running before any work happens. Four files: `backend/env.py` finds and loads the `.env` files; `backend/core/config.py` reads every environment variable exactly once into a frozen `Settings` object; `backend/celery_app.py` builds the Celery application and, more importantly, provides the single function that answers "is there actually a broker out there"; `backend/main.py` assembles the FastAPI app, refuses to start when download links would be forgeable, starts and stops everything in the right order, and exposes the two endpoints that tell you what this instance resolved itself to.

They stack bottom-up: `env.py` knows nothing about anything, `config.py` imports only `env.py`, `celery_app.py` imports only `config.py`, and `main.py` imports everything. That is the one-way dependency rule in miniature, and it is why this document reads them in that order rather than starting at `main.py`. Nothing here imports a handler, a service, or a model except `main.py`, which sits at the top and is imported by nobody except uvicorn and the test client.

Versions in the venv, in case it comes up: Python 3.10, FastAPI 0.128.0, Starlette 0.50.0, Celery 5.4.0.

---

## `backend/env.py`

Twenty-four lines. The whole job is: load `.env` files, once, without stepping on real environment variables.

```python
"""Environment file loading."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
```

`env.py:1` is the module docstring. `env.py:3` is `from __future__ import annotations`, which appears at the top of nearly every file in this backend. It makes Python store type annotations as strings instead of evaluating them at import time. Two practical effects: you can write `list[str]` and `X | None` on Python 3.9/3.10 where those would otherwise be runtime errors, and an annotation that names a class defined later, or in a module you would rather not import at runtime, costs nothing. `env.py:5` and `env.py:7` are ordinary imports — `pathlib` and `python-dotenv`.

```python
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
```

`env.py:9-10`. `__file__` here is `backend/env.py`, so `.parent` is `backend/` and its parent is the repo root. The `.resolve()` is the part worth defending: it makes the path absolute and follows symlinks. Without it, if the process was started with a relative path or the package is symlinked into place (which is what an editable install does), `__file__` can be relative to the current working directory, and since the working directory changes depending on how you launched the process, `.parent` would point somewhere different every time. Resolving once at import removes the whole class of problem.

```python
_loaded = False


def load_environment() -> None:
    """Load the project and backend env files, once, without overriding the shell."""
    global _loaded
    if _loaded:
        return
```

`env.py:12` is a module-level flag, and `env.py:15-19` is the idempotency guard. `load_environment()` is called from `get_settings()` in `config.py:162`, and `get_settings()` is called from roughly a dozen modules. The guard means all of those calls after the first are a boolean check. The leading underscore is the usual convention for "this is private to the module".

```python
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_dotenv(BACKEND_DIR / ".env", override=False)
    _loaded = True
```

`env.py:21-23`. Two files are loaded: the repo-root `.env` first, then `backend/.env`. The root one is shared with the frontend — it is where `NEXT_PUBLIC_BACKEND_URL` lives — and the backend one exists so you can keep backend-only settings out of the shared file.

`override=False` is the decision on this line, and it is worth being able to defend properly. It means: if a variable is already set in the actual process environment, the `.env` file does not touch it. Three consequences that all matter.

First, in any real deployment you set configuration through the platform — `docker run -e`, a systemd unit, a Railway or Render dashboard — and a stale `.env` file that got copied into an image must never silently beat the value the operator actually set. With `override=True` it would, and the failure mode is horrible: the deployment looks configured, the dashboard shows the right value, and the process is using something else.

Second, because `override=False` also applies between the two files, the *first* file to define a key wins. Root `.env` is loaded first, so root `.env` beats `backend/.env` for every key they both define. In this repo both files exist and define exactly the same eight keys, which means `backend/.env` is currently dead weight — nothing in it can take effect. Worth knowing, because "why isn't my change taking?" is the obvious question and the answer is "you edited the wrong file".

Third, the test suite depends on this. `backend/tests/conftest.py:54-59` uses `monkeypatch.setenv` to point every test at a temporary directory and to force `CELERY_ENABLED=false`, `REDIS_URL=""` and an empty API key. Those go into `os.environ` before `get_settings()` runs. If `load_dotenv` overrode, every test would pick up your personal `.env` and the suite would behave differently on your machine than in CI.

`env.py:23` sets the flag. Note it is set after both loads, not before, so if `load_dotenv` throws the flag stays false and the next call retries rather than silently running with no configuration.

---

## `backend/core/config.py`

The rule this file enforces is: **every environment variable in the backend is read here, on one line, and nowhere else.** If you grep the codebase for `os.getenv` outside this file you find nothing in `backend/`. That is not tidiness for its own sake — it buys four specific things.

You can see the entire configuration surface of the system by reading one class, which is the difference between a deployment being documentable and not. Every variable gets a real default in the same place it is read, so there is exactly one answer to "what happens if this is unset" rather than one answer per call site. Types are converted once, at the boundary, so no downstream code ever does `int(os.getenv("TIMEOUT", "180"))` and no downstream code can disagree with another about whether `"false"` is truthy. And because the values are read once into a snapshot, two parts of the process cannot observe different configuration — which they can if someone mutates `os.environ` at runtime and half the code has already read it and half has not.

```python
"""Process configuration, resolved once from the environment."""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

from backend.env import load_environment

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent

PUBLISHED_SECRETS = frozenset({"beeprepared-dev-secret", "change-me-in-production"})
```

`config.py:1-19`. Imports are unremarkable except for `secrets` on line 7, which is there for one reason and is explained under the signing key below. `config.py:13` is the only project import in the file, and it points down to `env.py` — `core` sits directly above `env` and below everything else. `config.py:17`: this file is `backend/core/config.py`, so `.parent.parent` walks up through `core/` to `backend/`. Same name as the constant in `env.py` and the same value, computed independently so neither file has to import the other's constant.

`config.py:19` is the set of secrets this repository has published. It is the subject of its own section further down, and it is worth noticing at the top of the file because it is the only constant here that exists to *reject* a configured value rather than to supply one.

### The four readers

```python
def _text(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()
```

`config.py:22-23`. Small, but it makes two decisions.

`os.getenv(name) or default` uses `or`, not the two-argument form of `getenv`. `os.getenv(name, default)` only substitutes the default when the variable is *absent*; `or` substitutes it when the variable is absent **or set to the empty string**. That difference is load-bearing. `.env.example:11` ships `OPENROUTER_API_KEY=` with nothing after it, and `conftest.py:59` sets `REDIS_URL=""` explicitly to force local mode. In both cases the variable exists and is empty, and both need to behave as "not configured". With `getenv(name, default)` an empty `REDIS_URL` would come through as `""`, which happens to still be falsy here, but an empty `OPENROUTER_MODEL` would come through as `""` and you would send an empty model name to OpenRouter and get a confusing 400.

`.strip()` removes surrounding whitespace. This exists because copy-pasting an API key out of a browser very reliably brings a trailing newline or space with it, and that character ends up inside the `Authorization` header, and the server rejects the request with a 401 that says nothing useful. Stripping at the boundary means it can only ever go wrong once, here, rather than at every use.

```python
def _flag(name: str, default: bool) -> bool:
    raw = _text(name).lower()
    return raw in {"1", "true", "yes", "on"} if raw else default
```

`config.py:26-28`. Boolean parsing. Empty or unset falls through to the caller's default; anything set is compared against a small allow-list, so `1`, `true`, `TRUE`, `yes`, `on` are true and everything else — including `0`, `false`, `no`, and typos — is false. The reason for an allow-list of truth rather than an allow-list of falsehood is that a typo should turn a feature *off*, not on. `CELERY_ENABLD=true` should not silently enable Celery, and with this shape it does not, because the variable is not read at all.

```python
def _number(name: str, default: int) -> int:
    try:
        return int(_text(name) or default)
    except ValueError:
        return default
```

`config.py:31-35`. Integer parsing that never raises. `_text(name) or default` handles unset, `int()` handles the conversion, and a garbage value like `API_PORT=eight thousand` falls back to the default instead of killing the process.

Worth knowing: an interviewer may push on this, because swallowing the `ValueError` means a typo in `JOB_TIMEOUT_SECONDS` is completely silent — you get 900 and no warning. The counter-argument is that these all have safe defaults and a config typo taking down the API at boot is worse than one running with a default. Both positions are defensible; know that you chose the lenient one and why.

```python
def _list(name: str, default: List[str]) -> List[str]:
    raw = _text(name)
    return [item.strip() for item in raw.split(",") if item.strip()] if raw else list(default)
```

`config.py:38-40`. Comma-separated lists — only `CORS_ORIGINS` uses it. Split on commas, strip each element (so `a, b` works, not just `a,b`), and drop empties (so a trailing comma is harmless). The `list(default)` on the fallback path is the subtle bit: it returns a *copy*. If it returned `default` directly, every caller falling back would receive the same list object, and one caller appending to its settings would change the default for everyone. It is defensive, but it costs nothing and the bug it prevents is the kind you lose an afternoon to.

### The signing key, and why it is the one setting with no default

This is the longest thing in the file and it is the one to lead with if the conversation turns to configuration, because it is the only place where the safe-default instinct that runs through the rest of this module was actively wrong.

**What the key is for.** `FileStore` (`services/files.py:37`) uses it as the HMAC key for download links. A link looks like `/api/files/<key>?expires=<unix-time>&signature=<hex>`, and the route that serves it (`api/routes/files.py:32`) has no user check at all — the signature *is* the credential. That is a deliberate design, because a PDF preview in an iframe and an image in an `<img>` tag cannot attach an `Authorization` header.

**Why that scheme is sound, and why that was not enough.** The expiry is inside the signed payload rather than beside it: `sign` computes the digest over `f"{key}:{expiry}"` (`services/files.py:110-111`), so a holder cannot extend a link by editing the query string, because changing either half changes what should have been signed. The comparison is `hmac.compare_digest` (`services/files.py:117`), which is constant-time and so does not leak the correct signature one byte at a time through response timing. And the key is canonicalised and confined to the store root before anything is opened (`services/files.py:75-84`), so a signed link to `../../etc/passwd` still fails. Every one of those properties is worth exactly nothing if the HMAC key is a value published in the repository, because then a stranger with no session at all can compute a valid signature for any object in the store and simply construct the download link themselves. The lock was well made and the key was printed in the manual.

```python
PUBLISHED_SECRETS = frozenset({"beeprepared-dev-secret", "change-me-in-production"})
```

`config.py:19`. Two strings, and both of them are in this repository. `beeprepared-dev-secret` used to be the literal default of the `signing_secret` field on the dataclass below, so any deployment that never set `SIGNING_SECRET` used it. `change-me-in-production` is what `.env.example:24` and `docker-compose.yml:24` ship, so any deployment that copied the example file and did not edit that line used that one instead. Between them they covered essentially every install that had not deliberately thought about the problem.

There is now no default on the field at all. `signing_secret: str = ""` at `config.py:132` is an empty string, and `get_settings` resolves it through the function below rather than letting the field default stand.

```python
def _signing_secret(data_dir: Path) -> str:
    """
    The key download links are signed with, never a value published in the repo.

    A configured value is honoured unless it is one of those published values,
    which is the same as having configured nothing at all.
    """
    configured = _text("SIGNING_SECRET")
    if configured and configured not in PUBLISHED_SECRETS:
        return configured

    logger.warning(
        "SIGNING_SECRET is unset or still a published default; signing links with the "
        "private key kept under %s instead. Set SIGNING_SECRET to a private random "
        "value to share links across installations.",
        data_dir,
    )
    return LocalSigningSecret(data_dir).read_or_create()
```

`config.py:94-111`. The rule is one sentence: a configured value is honoured unless it is one of the published ones, and a published one is treated as though nothing had been configured at all.

**The design choice worth defending is that it mints rather than refuses.** Refusing to start on a published secret is the obvious move and it was the wrong one here. `.env.example` and `docker-compose.yml` both ship `change-me-in-production`, and the README's documented way to start the stack is `docker compose up`. Refusing that value outright would mean the documented first run of the project fails with a configuration error, which is a worse outcome than the hole it closes — the hole only matters on something internet-facing, and the broken first run hits everybody. So the fallback is to generate a private key rather than to stop. The warning is logged at `warning` because running on a minted key is a supported state, not a fault; what is not supported is running on a *published* key, and that no longer happens.

`LocalSigningSecret` is the class that does it, at `config.py:43-91`. Its docstring at
`config.py:44-60` is seventeen lines and states the whole argument above; the mechanism is what
follows it.

```python
    FILENAME = "signing_secret.key"
    RANDOM_BYTES = 32

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / self.FILENAME

    def read_or_create(self) -> str:
        """The persisted key for this installation, minting it on first use."""
        return self._read() or self._create()
```

`config.py:62-70`. The key is 32 bytes of `secrets.token_hex`, which is 64 hex characters and 256 bits of entropy from the operating system's cryptographic source — `secrets`, not `random`, because `random` is a Mersenne Twister and its output is reconstructible from enough observed values.

It is persisted at `<data_dir>/signing_secret.key`, next to the database and the file store rather than somewhere else, and that placement is doing real work. Two properties follow from it. Links survive a restart: if the key were held in memory only, every restart would invalidate every outstanding download link, and a user who left a tab open would find their downloads silently 403ing. And the Celery workers agree with the API: in the three-process topology the workers share the same data volume, so they read the same file and sign compatibly, which they could not do if each process minted its own.

```python
    def _create(self) -> str:
        minted = secrets.token_hex(self.RANDOM_BYTES)
        self._path.parent.mkdir(parents=True, exist_ok=True)

        try:
            descriptor = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return self._read() or minted

        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(minted)
```

`config.py:78-88`. Two flags on `os.open` carry the whole argument for using it instead of `Path.write_text`.

`os.O_EXCL` together with `os.O_CREAT` makes the creation fail if the file already exists, and it fails *atomically* — the check and the create are one syscall, so there is no window between them. That matters because the API and several workers can start at the same moment on the same volume, and with a read-then-write they could each see no file, each mint a different key, and each overwrite the last. Whichever wrote last would win, and every link signed by the others would be invalid. With `O_EXCL`, exactly one process creates the file; the losers get `FileExistsError` and take line 85, which reads back the key the winner just wrote.

`0o600` is the file mode: readable and writable by the owner, nothing for group or other. A key file that is world-readable on a shared host is not private, and the mode has to be set at creation rather than chmod'ed afterwards, because otherwise there is a moment where the file exists with the default mode and the secret is already in it.

The `or minted` on line 85 is the last-resort branch: if the file exists but cannot be read back, the process uses the key it just generated in memory rather than raising. Links will not survive that process's restart, which is bad, but it is better than the API failing to boot over a permissions problem on a file it can regenerate.

**The limit of this, and say it before you are asked.** A minted key is per-installation, which is exactly what you want for a single deployment and exactly what you do not want if you ever run two API instances behind a load balancer without a shared volume — they would mint different keys and each would reject the other's links. The answer in that topology is to set `SIGNING_SECRET` explicitly, which is what the warning tells the operator to do, and `require_unforgeable_links` in `main.py` is the thing that makes the whole arrangement enforceable rather than merely advisory.

### The `Settings` dataclass

```python
@dataclass(frozen=True)
class Settings:
    """
    Everything the backend needs to run, with a working default for each.

    `signing_secret` is the exception: it has no default because a published one
    is a forgeable one. `get_settings` resolves it to a private value.
    """
```

`config.py:114-121`. `frozen=True` makes instances immutable — assigning to a field raises `FrozenInstanceError`. This object is handed to a dozen modules across three processes; making it read-only means no module can reconfigure the system out from under another. It also makes the instance hashable, which is tidy given it comes out of an `lru_cache`.

The docstring's first claim — "with a working default for each" — is the design goal for the whole file. A fresh clone with no `.env` at all starts and runs the entire pipeline. That is why the README can say `uvicorn backend.main:app` is a complete install.

The second sentence is the exception carved out of it, and it is stated in the docstring rather than left to be discovered because it is the one place the goal and safety pulled in opposite directions. A default that is written down in the repository is not a default, it is a published key. The rest of the file answers "what happens if this is unset" with a value; this field answers it with "`get_settings` will go and find you a private one", which preserves the fresh-clone property without preserving the hole.

```python
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemini-2.5-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_max_concurrency: int = 6
    llm_max_output_tokens: int = 16384
    llm_timeout_seconds: int = 180
    llm_max_retries: int = 3
```

`config.py:123-129`, the model group. The API key defaults to empty, which is what makes `has_llm_key` false, which is what makes `llm/factory.py:21` return the offline provider. That is the no-key path: the system still works, with a local heuristic engine instead of a model.

The base URL is configurable rather than hard-coded so you can point the whole thing at a local proxy or a mock server without touching code — useful for recording fixtures. Everything from `llm_max_concurrency` down is consumed in one place, `llm/openrouter.py:79-82`: the concurrency becomes an `asyncio.Semaphore` (`openrouter.py:218`) bounding how many model calls are in flight at once (six, because the pipeline fans out over many sections and an unbounded fan-out gets you rate-limited immediately), the timeout and retry count configure the HTTP client, and `llm_max_output_tokens` is sent as `max_tokens`. 16384 is high because a knowledge core for a long lecture is a large structured JSON document and a truncated response fails JSON parsing rather than degrading gracefully.

```python
    data_dir: Path = field(default_factory=lambda: BACKEND_DIR / ".storage")
    signing_secret: str = ""
```

`config.py:131-132`. `data_dir` is the single root under which everything persistent lives: the SQLite file at `data_dir/beeprepared.db` (`config.py:156`), every stored upload and export under `data_dir/files` (`services/files.py:35`), and now the minted signing key at `data_dir/signing_secret.key` (`config.py:62`). One variable moves all three together, which is what makes "delete this directory to reset" a true statement — and it is also why deleting that directory invalidates every outstanding download link, which is correct but worth knowing before you do it during a demo.

`field(default_factory=...)` rather than a plain default: dataclasses reject mutable defaults outright, and while `Path` is actually immutable and would be allowed, using the factory here keeps it consistent with `cors_origins` on line 143 where it is mandatory.

`signing_secret` is the HMAC key used by `FileStore` (`services/files.py:37`) to sign download links so a link cannot be extended or repointed by editing the query string. **It used to default to `"beeprepared-dev-secret"` on this line**, which is to say it defaulted to a value printed in a public repository, and `.env.example:23-24` shipped a second published value for anyone who copied the example file. The default is now the empty string, which is not a usable key and is not meant to be one — `get_settings` never lets it stand, and `require_unforgeable_links` in `main.py` refuses to serve if it somehow does. The full argument is in the signing-key section above; the thing to remember at this line is that the empty string here is not laziness, it is the absence of a default being made explicit.

```python
    redis_url: str = ""
    celery_enabled: bool = True
    worker_concurrency: int = 4
    job_timeout_seconds: int = 900
    job_max_attempts: int = 3
    stale_job_seconds: int = 1800
```

`config.py:134-139`, the queue group. `redis_url` defaults to empty, meaning no Redis, meaning single-process. `celery_enabled` defaults to `True`, which reads oddly until you notice that `broker_available()` at `celery_app.py:46` requires *both* a Redis URL and this flag — so with the default empty URL, the `True` here has no effect. The flag exists as a kill switch: when Redis is up and reachable but you want to debug in one process, `CELERY_ENABLED=false` forces local mode without tearing down Redis. `conftest.py:57` uses exactly that.

`worker_concurrency` is how many worker tasks the in-process pool starts (`job_runner.py:259`). `job_timeout_seconds` is 15 minutes and appears in three places, which is covered below. `job_max_attempts` is read by the database when recording a failure (`database.py:350` and `:396`) — a job that fails transiently goes back to `pending` until it has burned its attempts, then goes to `failed`. `stale_job_seconds` is 30 minutes and drives the reaper (`job_runner.py:260`, `tasks.py:67`), which returns jobs stuck in `running` — because their worker died — back to the queue.

```python
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: List[str] = field(default_factory=lambda: ["http://localhost:3000"])
    upload_max_mb: int = 200
```

`config.py:141-144`, the HTTP group. `0.0.0.0` binds every interface, which is what you need inside a container; `127.0.0.1` would make the port unreachable from outside. `cors_origins` defaults to the Next dev server and *must* use `default_factory` — a bare list default is a `ValueError` at class definition time in dataclasses, because it would be shared across all instances. `upload_max_mb` is enforced while streaming the upload to disk at `api/routes/projects.py:199-214`, so an oversized file is rejected part-way through rather than after the whole thing has been buffered. The same number now also caps a YouTube download, as `max_filesize` on the yt-dlp options at `pipeline/ingestion.py:193`, so the two ways into the file store are bounded by one setting rather than one of them being unbounded.

```python
    @property
    def has_llm_key(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_redis(self) -> bool:
        return bool(self.redis_url)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "beeprepared.db"
```

`config.py:146-156`. Three derived values, as properties rather than fields. The reason is that a derived field can drift: if `has_redis` were a field computed in the constructor and someone later changed how `redis_url` is read, you would have two sources of truth. As a property it is a function of the field, always, and cannot be set inconsistently — especially relevant since the class is frozen and a field would have to be computed in `__post_init__` with `object.__setattr__`, which is ugly.

`has_llm_key` is the switch between the OpenRouter provider and the offline one (`llm/factory.py:21`). `has_redis` is half the switch between three processes and one (`celery_app.py:46`, `services/events.py:182`). `database_path` is the single place the database filename is decided (`database.py:131`).

### `get_settings`

```python
@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build the settings snapshot for this process, once."""
    load_environment()
```

`config.py:159-162`. This is the important function in the file.

`@lru_cache(maxsize=1)` means the body runs at most once per process and every subsequent call returns the identical object. `maxsize=1` rather than the default 128 because the function takes no arguments and there is only ever one entry — saying 1 documents that.

Caching matters for correctness, not speed. If settings were rebuilt on every call, a change to `os.environ` mid-process would be visible to code that called `get_settings()` after the change and invisible to code holding a reference from before, and you would get a process where the database module thinks the data dir is one thing and the file store thinks it is another. Reading once produces a snapshot: whatever the environment said at the moment of the first call is what this process believes for its whole life.

The `lru_cache` choice also gives you `get_settings.cache_clear()` for free, and the test suite needs exactly that. `conftest.py:71` calls it in the fixture that resets every singleton between tests, right after `monkeypatch.setenv` has pointed everything at a fresh temporary directory. A module-level `SETTINGS = Settings(...)` constant would have been simpler to read and impossible to test, because you cannot un-import a module.

`config.py:162` is the ordering guarantee. `load_environment()` is called *inside* `get_settings`, before any `os.getenv`. Since the only route to a settings value is through this function, no module anywhere can read configuration before the `.env` files have been loaded. If instead `load_environment()` were called from `main.py` at startup, then any module that read config at import time — and `celery_app.py:13` does exactly that — could beat it and see an unloaded environment.

```python
    data_dir = Path(
        _text("BEE_DATA_DIR") or _text("BEE_STORAGE_DIR") or str(BACKEND_DIR / ".storage")
    ).expanduser()
```

`config.py:164-166`. Two accepted names for the same thing. `BEE_STORAGE_DIR` is the older name kept working so an existing deployment does not lose its data directory on upgrade and silently start with an empty database. `BEE_DATA_DIR` wins if both are set. This is the only variable in the file with an alias, and it exists specifically because it points at state — getting it wrong does not throw, it just makes all your data disappear.

`.expanduser()` turns a leading `~` into the real home directory. The shell does that for you when you type a path, but a value coming out of a `.env` file has never been through a shell, so `BEE_DATA_DIR=~/bee` would otherwise create a literal directory called `~`. It is applied here, on the local variable, rather than further down in the constructor call, because the local is now used twice: once as the `data_dir` field and once as the argument to `_signing_secret`, and the key file must land in the same expanded directory as everything else it sits beside.

```python
    return Settings(
        openrouter_api_key=_text("OPENROUTER_API_KEY"),
        openrouter_model=_text("OPENROUTER_MODEL", "google/gemini-2.5-flash"),
        ...
```

`config.py:168-188` is the constructor call: one field, one environment variable name, one default, per line. Nothing clever, and that is the point — it is the table you read when someone asks what a variable does.

Two lines break the pattern and are worth a glance. `config.py:177` is `signing_secret=_signing_secret(data_dir)`, the only field on this list whose value comes out of a function rather than straight off an environment variable, for the reasons set out above. And `config.py:187` maps the field `upload_max_mb` to the variable `MAX_FILE_SIZE_MB` — the one place in the file where the two names differ, so grepping for the field name will not find the variable.

Notice that the defaults are written twice: once as the dataclass field default and once as the second argument to `_text`/`_number`/`_flag`. They agree today, with the single deliberate exception of `signing_secret`, whose field default is empty precisely so that it cannot agree with anything and cannot be used. That duplication is the cost of having the dataclass be independently constructible with sensible values (which the tests rely on) while still having each default visible on the line that reads the variable.

---

## `backend/celery_app.py`

Fifty-five lines. It builds the Celery application object and provides `broker_available()`, which is the function that decides the topology of the entire system. The tasks themselves live in `backend/tasks.py` and belong to another document; the only link you need here is `include=["backend.tasks"]` on line 19, and the fact that `tasks.py` attaches a beat schedule to this same `celery_app` object at the bottom of that file.

```python
"""Celery application: workers that run jobs outside the API process."""

from __future__ import annotations

import logging

from celery import Celery

from backend.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
```

`celery_app.py:1-13`. Boring except for the last line: `get_settings()` is called at module import time. That is safe and deliberate. It is safe because `get_settings` loads the `.env` files itself, so importing this module in isolation — which is what `celery -A backend.celery_app worker` does — still gets fully-loaded configuration. It is deliberate because the values are needed at line 17 to construct the Celery object, which must exist at import time for the `@celery_app.task` decorators in `tasks.py` to bind to it.

```python
celery_app = Celery(
    "beeprepared",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or None,
    include=["backend.tasks"],
)
```

`celery_app.py:15-20`. Four arguments, three of which carry a decision.

`"beeprepared"` is the app name, which becomes the default prefix for task names. The tasks here override it explicitly anyway (`@celery_app.task(name="beeprepared.run_job")`), so the name is mostly cosmetic — but it is what shows up in worker logs and in the Flower UI if you ever attach one.

`broker=settings.redis_url or "memory://"` is the line that makes the no-Redis install possible. Constructing `Celery(broker=None)` or `Celery(broker="")` is fine until anything touches the connection, at which point kombu cannot pick a transport and raises. `"memory://"` is kombu's in-memory transport: it constructs cleanly and needs nothing external. This matters because `backend/services/dispatcher.py:29` does `from backend.celery_app import broker_available` — the dispatcher imports this module unconditionally, in every process, including the single-process install with no Redis anywhere. If the module could not be imported without a broker, that import would have to be wrapped in a try/except and the whole "one process is a complete install" story would get much uglier. As written, the module always imports and `broker_available()` is a plain function you call and get a boolean from.

`backend=settings.redis_url or None` sets Celery's *result* backend — the store where a task's return value goes so a caller can fetch it later. `None` means results are discarded. That is correct for this system, and it is worth being able to say why: job state does not live in Celery, it lives in SQLite. The `jobs` table carries `pending`/`running`/`completed`/`failed`, the attempt count, and the error message, and everything that wants to know about a job reads that table. Celery's result backend would be a second, weaker copy of the same information with a TTL on it. Using the database as the single source of truth is also what makes the two dispatch modes interchangeable — the local worker pool has no result backend at all and nothing notices.

`include=["backend.tasks"]` tells a worker which modules to import at startup so the `@task` decorators run and the tasks register themselves. Without it, `celery -A backend.celery_app worker` boots with an empty task registry, every `run_job.delay(...)` from the API succeeds (the API only needs the name to publish a message), and the worker rejects each message with `NotRegistered`. The symptom is jobs that sit in `pending` forever with no error anywhere, which is a genuinely nasty thing to debug — the API says it dispatched, the broker says it delivered, and nothing happened.

```python
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
```

`celery_app.py:22-25`. JSON only, in both directions, and `accept_content` refuses anything else on the way in. Celery historically defaulted to pickle, and a pickle payload from a broker is arbitrary code execution — anyone who can write to the Redis queue owns the worker process. Pinning to JSON closes that. The practical cost is that task arguments must be JSON-serialisable, which is why `run_job` takes a `job_id: str` rather than a job object: the message carries an identifier and the worker re-reads the row from the database. That happens to be the right design anyway, because the row may have changed between enqueue and execution.

```python
    timezone="UTC",
    enable_utc=True,
```

`celery_app.py:26-27`. Everything Celery timestamps is UTC. Uninteresting on its own, but it agrees with the rest of the system — `services/events.py:38` stamps every event with `datetime.now(timezone.utc)` — so nothing in the pipeline ever has to guess which zone a timestamp is in.

```python
    worker_prefetch_multiplier=1,
```

`celery_app.py:28`. This is the most consequential single line in the config block. Celery's default is 4: each worker process reserves four messages from the broker at a time and holds them locally while it works through them. That default assumes short tasks. Here a task is a lecture ingest or an artifact generation, which takes minutes. With the default, one worker grabs four jobs, starts the first, and sits on the other three while every other worker in the fleet is idle — the queue looks busy and your throughput is one job at a time. Setting it to 1 means a worker reserves exactly the job it is about to run, so the next job goes to whichever worker is actually free. For long tasks this is the difference between using your workers and not.

```python
    task_acks_late=True,
    task_reject_on_worker_lost=True,
```

`celery_app.py:29-30`. By default Celery acknowledges a message as soon as it is *received*, which means if the worker dies mid-task the broker has already forgotten the message and the work is silently lost. `task_acks_late=True` moves the acknowledgement to after the task returns, so a worker that dies leaves the message unacknowledged and the broker redelivers it to someone else.

`task_reject_on_worker_lost=True` covers the harder case: acks-late alone still loses the message if the worker *process* is killed outright — SIGKILL, an OOM kill — because there is no chance to run any cleanup. This flag tells Celery to requeue in that case too.

The obvious follow-up question is what stops redelivery from running the same job twice. The answer is not in Celery: it is that the worker's first action is `database.claim_job(job_id)` (`job_runner.py:160`), which is a conditional update inside a write transaction that only succeeds if the row is still claimable. A redelivered message whose job already completed finds nothing to claim and returns `False` immediately (`job_runner.py:161-163`). At-least-once delivery from the broker plus an atomic claim in the database gives you effectively-once execution.

```python
    task_time_limit=settings.job_timeout_seconds + 60,
    task_soft_time_limit=settings.job_timeout_seconds,
```

`celery_app.py:31-32`. Two limits, sixty seconds apart, and the gap is the point.

The soft limit fires first, at exactly `job_timeout_seconds`, by raising `SoftTimeLimitExceeded` *inside* the running task. That is a normal Python exception, so the task's own error handling runs: the failure gets recorded against the job row, the `job.failed` event gets published, and the flow node the job belongs to gets told it failed instead of hanging. The hard limit fires sixty seconds later and kills the worker child process outright, no cleanup, no exception. It is the backstop for a task that has wedged so badly it cannot even process the soft exception — a C extension in a tight loop, a syscall that will not return. Without the gap the process would be killed before it could record anything, and the job row would sit in `running` until the reaper found it half an hour later.

There is a third fence at the same value: `job_runner.py:135-137` wraps `handler.run(job)` in `asyncio.wait_for(..., timeout=get_settings().job_timeout_seconds)`. That one is the innermost and the only one that exists in local mode, where Celery is not running at all. So the same number enforces the same deadline in both topologies.

```python
    task_max_retries=0,
```

`celery_app.py:33`. Celery does not retry. This is not "retries are off", it is "retries happen somewhere else". Retry policy lives in the database: `job_runner.py:175` classifies the failure as transient or not, `database.fail_job(..., retryable=...)` either puts the row back to `pending` or marks it `failed`, and `job_max_attempts` bounds the loop. Having Celery retry *as well* would multiply the two — three Celery attempts times three database attempts is nine model calls for one job, and nine times the bill. One retry authority, in the layer that can actually tell a rate-limit from a malformed prompt.

```python
    broker_connection_retry_on_startup=True,
```

`celery_app.py:34`. Celery 5.x changed the default so that a worker which cannot reach the broker at startup exits instead of retrying, and it emits a deprecation warning if you do not state your preference. `True` restores the retry behaviour, which is what you want under docker-compose or any orchestrator that does not guarantee Redis is accepting connections before the worker container starts. Without it, a worker that loses the race just dies and you get a restart loop.

```python
    result_expires=3600,
)
```

`celery_app.py:35-36`. A one-hour TTL on result keys, so Redis does not accumulate them forever. Largely moot here since the backend is often `None`, but it costs nothing and it is the right value if someone does turn the result backend on.

### `broker_available`

```python
def broker_available() -> bool:
    """
    Whether the broker is configured and answering.

    Checked before enqueuing so work is never dropped into a queue that has no
    worker draining it.
    """
    if not settings.has_redis or not settings.celery_enabled:
        return False
```

`celery_app.py:39-47`. `celery_app.py:46` is the two-part gate. No Redis URL, or the kill switch off, and the answer is `False` without touching the network. This is the cheap path and it is the one every default install takes.

```python
    try:
        with celery_app.connection_for_write() as connection:
            connection.ensure_connection(max_retries=1, timeout=2)
        return True
```

`celery_app.py:49-52`. The actual probe.

`connection_for_write()` rather than `connection()` or `connection_for_read()`: kombu distinguishes the producer connection from the consumer connection, and they can in principle point at different brokers. Since the only thing this process does with the broker is *publish* — `run_job.delay(...)` in `dispatcher.py:50` — testing the write connection is testing the connection that will actually be used. Using it as a context manager means the connection is closed on the way out, so this probe leaks nothing even when it succeeds.

`ensure_connection(max_retries=1, timeout=2)` is the line that matters. The default `ensure_connection` retries forever with exponential backoff, which is correct behaviour for a worker that has nothing better to do than wait for its broker. It is disastrous here, because this runs on the startup path — `main.py:71` calls `dispatch_mode()`, which calls this — and a Redis host that is resolving but not accepting connections would hang the API's startup indefinitely with no log line explaining why. Bounding it to one retry and two seconds means the worst case is a two-second pause at boot and then a clean fall back to local mode.

```python
    except Exception as error:
        logger.warning("Celery broker unreachable (%s)", error)
        return False
```

`celery_app.py:53-55`. A deliberately broad except. Kombu and redis-py raise a wide family here — `ConnectionRefusedError`, `socket.timeout`, `kombu.exceptions.OperationalError`, DNS resolution failures, `redis.AuthenticationError` if the password is wrong — and enumerating them would be a list you have to maintain against two libraries' internals. The response to every one of them is identical: this broker is not usable, run locally instead. The warning is logged at `warning` rather than `error` because falling back to local mode is a supported configuration, not a fault.

The result is used by `services/dispatcher.py:18-33`, which caches it behind a double-checked lock and stores it in a module global. So the two-second probe happens exactly once per process, at startup, not once per request.

Worth knowing, and a good thing to raise before an interviewer does: this is a point-in-time check whose answer is cached for the life of the process. If Redis is up at boot and dies an hour later, the process still believes it is in Celery mode. What actually happens then is that `dispatcher.enqueue` (`dispatcher.py:47-54`) catches the publish failure, logs it, and returns `"deferred"` — the job row is already committed, so the work is queued in the database and simply not dispatched. The `drain_queue` beat task in `tasks.py` re-dispatches anything pending every two minutes. So the work is not lost, but recovery depends on a Celery worker being alive to run beat, which is exactly the thing that just broke. `dispatcher.reset()` exists to clear the cached mode, and it is currently called only from tests.

---

## `backend/main.py`

The FastAPI application. It is short for what it does, because everything it wires together is built elsewhere and it only has to assemble in the right order.

```python
"""FastAPI application assembly."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

`main.py:1-13`. Standard-library imports, then `main.py:13`, which is the odd one.

Every project import in this codebase is absolute — `from backend.core.config import ...` — which requires the *repo root* to be on `sys.path` so that `backend` resolves as a package. When you run `uvicorn backend.main:app` from the repo root, that is already true because the working directory is on the path. When you run `python backend/main.py` directly, Python puts `backend/` on the path, not the root, and every `from backend...` import fails immediately. This line computes the repo root from `__file__` and appends it, so both invocations work.

Note the position: it has to run *before* the project imports on lines 20-27, which is why the import block is split in two and why a linter will flag module-level imports after code here (E402). That is a conscious trade — the file is entry-point-shaped, so it gets entry-point liberties.

```python
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes import artifacts, chat, files, flows, jobs, projects, ws
from backend.core.config import PUBLISHED_SECRETS, Settings, get_settings
from backend.llm.factory import get_provider
from backend.models.artifacts import GENERATED_TYPES, SOURCE_TYPES
from backend.services import events
from backend.services.database import get_database
from backend.services.dispatcher import LOCAL, dispatch_mode
from backend.services.files import get_file_store
```

`main.py:15-27`. Framework imports, then project imports spanning every layer — `api`, `core`, `llm`, `models`, `services`. That looks like a violation of the one-way rule until you notice the direction: `main.py` imports *downward* from every layer and is imported *by* nothing. It sits above `api` in the ordering, so it is allowed to see everything. The rule it must not break is the reverse, and nothing here imports `main`.

Line 21 imports three names rather than one: `PUBLISHED_SECRETS` and `Settings` alongside `get_settings`. Both of the extra two are there for the startup guard on line 41 — the set it checks against, and the type it takes as a parameter so the guard can be called on a `Settings` built by hand rather than only on the process-wide one.

```python
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
```

`main.py:29-33`. Logging configured at import, so it is in place before anything can log. `basicConfig` is a no-op if the root logger already has handlers, so this does not fight a host that configured logging first. `%(levelname)-7s` is left-padded to seven characters, which is the width of `WARNING`, so the columns line up and you can scan a log by eye.

`main.py:30-31` is the part that came from experience. `httpx` logs an INFO line for every single request. The pipeline makes dozens of model calls per ingest, and with those at INFO your own progress logs — the ones that tell you which stage of the pipeline you are in — are buried under HTTP noise. `asyncio` at INFO emits selector chatter. All four go to WARNING, so you still see it when something is actually wrong.

```python
SLOW_REQUEST_MS = 1000
REQUEST_ID_HEADER = "X-Request-ID"

settings = get_settings()
```

`main.py:35-38`. Two constants, named rather than inlined so the threshold has a single place to change, and the header name is shared between the middleware that sets it (line 125), the CORS config that exposes it (line 108), and the error handler that reads it (line 152).

`main.py:38` calls `get_settings()` at import time. It has to: `add_middleware` at line 101 needs the origin list, and Starlette raises `RuntimeError` if you add middleware after the app has started, so it cannot wait for the lifespan handler.

### `require_unforgeable_links`

```python
def require_unforgeable_links(settings: Settings) -> None:
    """
    Refuse to serve with a signing key that anyone can read out of the repository.

    Every property the signed-link scheme relies on is worth nothing if the key
    is public: a stranger with no session could mint a valid, unexpired link for
    any object in the store. `get_settings` mints a private key when none is
    configured, so this should never fire; it is the enforcement point that says
    so out loud, and it still catches a `Settings` assembled by hand.
    """
    if not settings.signing_secret or settings.signing_secret in PUBLISHED_SECRETS:
        raise RuntimeError(
            "SIGNING_SECRET is unset or still one of the defaults published in this "
            "repository. Download links signed with it can be forged for any stored "
            "object. Set SIGNING_SECRET to a private random value and restart."
        )
```

`main.py:41-56`. Sixteen lines and one condition, and the reason it exists is the interesting part.

The condition itself is small: empty, or a member of `PUBLISHED_SECRETS`, and the process refuses to serve. `config.py:_signing_secret` already guarantees neither can be true for a settings object built by `get_settings`, so on the normal path this function does nothing at all and can never fire. That is not an argument against having it. It is an argument for what kind of thing it is.

It is an *enforcement point*, and it is written as one for three reasons.

The first is that it states the invariant somewhere a reader will find it. The rule "download links are only unforgeable while the key is private" is otherwise spread across `config.py`, `services/files.py` and `api/routes/files.py`, and none of those files is the obvious place to look for it. Here it is a named function on the startup path with a docstring that says the whole thing in four sentences.

The second is that the guarantee in `config.py` is a property of one code path, not of the type. `Settings` is an ordinary frozen dataclass and anyone can construct one directly — the tests do exactly that (`test_api.py:665-671` uses `dataclasses.replace` to build a `Settings` with a chosen secret). Taking `settings: Settings` as a parameter rather than calling `get_settings()` internally is what makes that possible, and it is why the guard is testable at all: `test_api.py:673-678` parameterises over the empty string and both published values and asserts a `RuntimeError` from each, and `:680` asserts a private value passes.

The third is that a `RuntimeError` at startup is the right failure. It happens before the socket is listening, so there is no window in which the API is serving forgeable links; the message names the environment variable, says what the consequence is, and says what to do about it; and it fails the whole process rather than degrading, which is correct here because there is no safe reduced mode — either the links can be forged or they cannot.

**The thing to volunteer.** This does not verify that the key is *good*, only that it is not one of the two the repository published. `SIGNING_SECRET=a` passes. Rejecting weak keys generally would mean inventing an entropy policy, and the honest position is that the published values are the realistic failure — nobody accidentally sets `a`, whereas everybody accidentally leaves `change-me-in-production`.

### The lifespan handler

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Resolve every dependency once, then start workers if nothing else will."""
    require_unforgeable_links(get_settings())
```

`main.py:59-62`. This is FastAPI's modern startup/shutdown mechanism, replacing the deprecated `@app.on_event("startup")` and `@app.on_event("shutdown")` pair. The reason it is better is visible in this function: startup and shutdown share a scope, so `pool` on line 79 is an ordinary local variable that the shutdown half can see. With the old decorators you would need a module-level global for that, and globals across two functions is exactly how you end up trying to stop a pool that was never started.

`main.py:62` is the first statement in the body, and the position is the point. It runs before the event bus is built, before the database is opened, before the file store creates its root and before any worker exists. Nothing has been started that would need unwinding, and — more importantly — no request can have arrived, because the ASGI server does not begin serving until the lifespan startup half completes. A check placed after the singletons were resolved would still be correct, but it would mean the process had already created directories and opened connections on behalf of a configuration it was about to reject.

```python
    bus = events.get_event_bus()
    if isinstance(bus, events.InProcessEventBus):
        bus.bind_loop(asyncio.get_running_loop())
```

`main.py:64-66`. The subtlest three lines in the file, and a good thing to be able to explain unprompted.

`get_event_bus()` returns a `RedisEventBus` if Redis is reachable and an `InProcessEventBus` otherwise (`events.py:179-187`). The in-process one delivers events by putting them onto `asyncio.Queue` objects, one per subscribed WebSocket (`events.py:102`). An `asyncio.Queue` belongs to exactly one event loop and is not thread-safe.

The problem is that publishers are not always on that loop. The pipeline offloads blocking work — ffmpeg, PDF parsing, document rendering — to worker threads, and those threads publish progress events. Calling `queue.put_nowait` from another thread does not raise; it appears to work. What it does not do is wake the coroutine waiting on `queue.get()`, because the waiter's callback needs to be scheduled on the queue's own loop and there is nobody to schedule it. The observable symptom is a job that completes perfectly in the logs while the browser's progress bar sits frozen at whatever percentage it reached before the first background-thread event.

`bind_loop` records the loop, and `publish` (`events.py:81-99`) then checks: if the caller is already on that loop, deliver directly; otherwise hop across with `loop.call_soon_threadsafe`, which is the supported way to schedule work onto a loop from another thread. Binding happens here, at startup, because this is the first moment a running loop exists and it is before any request can arrive.

The `isinstance` guard is there because `RedisEventBus` has no loop-owned queues and nothing to bind — the alternative would be a no-op `bind_loop` on the base class, which would hide the fact that the two implementations have genuinely different threading models.

```python
    database = get_database()
    store = get_file_store()
    provider = get_provider()
    mode = dispatch_mode()
```

`main.py:68-71`. Four singletons resolved eagerly. Each of these is lazily constructed on first use anywhere in the system, so none of these calls is strictly necessary — but doing them here rather than on the first request buys two things.

Failures land at startup, loudly, instead of arriving as a 500 on the user's first click. `get_database()` creates the data directory, opens SQLite and applies the schema (`database.py:130-139`); `get_file_store()` creates the files root and loads the signing key (`files.py:33-38`). If the data directory is not writable, you find out when the process boots.

And the cost is paid once, up front. `dispatch_mode()` on line 71 is the one with a real cost — it is what triggers `broker_available()` and its two-second connection probe. Doing that during startup means the first user request does not wait for it.

The order is not arbitrary. All four must be resolved before line 80 reads `mode`, and the bus must be bound before workers exist that could publish to it. Note also what comes before all of them: the signing-key check on line 62. `get_file_store()` on line 69 is the call that reads `signing_secret` into the store, so refusing a published key first means the store is never constructed with one.

```python
    logger.info(
        "BeePrepared starting\n  database : %s\n  files    : %s\n  events   : %s\n"
        "  jobs     : %s\n  model    : %s",
        database.path, store.root, bus.driver, mode, provider.name,
    )
```

`main.py:73-77`. The startup banner. It prints the five things that answer almost every "why is it behaving like that" question: where the data actually is, whether events are going through memory or Redis, whether jobs run here or in Celery, and whether you are talking to a real model or the offline fallback.

This is deliberately the *same* five values that `/health` returns at lines 164-175. That pairing is the useful bit: when something is misbehaving you can compare what the process logged at boot with what it reports now, and if they differ you have learned something specific.

Note the `%s` placeholders rather than an f-string. Standard logging practice — the formatting only happens if the record is actually emitted.

```python
    pool = None
    if mode == LOCAL:
        from backend.services.job_runner import WorkerPool

        pool = WorkerPool()
        await pool.start()
```

`main.py:79-84`. The single-process branch.

`pool = None` first so the `finally` block on line 88 has something defined to check regardless of which branch ran.

The import on line 81 is inside the `if`, which is deliberate and worth explaining. Importing `job_runner` pulls in `IngestHandler`, `GenerateHandler` and `RefineHandler` (`job_runner.py:14-17`), and those pull in the entire pipeline — the media processing, the document parsers, the prompt templates. In Celery mode the API process never executes a handler; the workers do. Keeping the import lazy means the API's import graph and memory footprint stay small in the deployment where it is only an HTTP front end, and — more usefully — a broken import inside a handler cannot take down an API that was never going to run that handler.

`WorkerPool()` reads `worker_concurrency` and `stale_job_seconds` from settings and opens the database handle (`job_runner.py:257-264`). `await pool.start()` creates `concurrency` worker tasks that poll the queue with backoff, plus one reaper task (`job_runner.py:266-277`). The reaper is there because a process killed mid-job leaves its row in `running` forever, and the flow node waiting on that job would spin with no error ever arriving.

```python
    try:
        yield
    finally:
        if pool:
            await pool.stop()
        logger.info("BeePrepared stopped")
```

`main.py:86-91`. `yield` is where the application actually serves requests; everything before it is startup and everything after is shutdown.

The `try`/`finally` rather than plain statements after the `yield`: if the ASGI server cancels the lifespan task during a hard shutdown, the `yield` raises `CancelledError`, and without the `finally` the pool would never be stopped and its tasks would be torn down by process exit instead of unwinding cleanly. `pool.stop()` (`job_runner.py:279-286`) sets the stop event, cancels every task, and gathers them with `return_exceptions=True` so one worker misbehaving on cancellation does not prevent the others from being awaited.

Worth knowing what is *not* torn down here: the database connections, the file store, the LLM provider's `httpx` client, and the Redis client inside `RedisEventBus`. Those are process-lifetime singletons and the process is exiting, so nothing leaks in practice — but an interviewer may ask about the unclosed `httpx` client, and the honest answer is that it produces a warning under `-W error` and nothing worse, and closing it would mean adding a shutdown protocol to the provider interface for no operational benefit.

### Application object

```python
app = FastAPI(
    title="BeePrepared API",
    description="Turns lecture material into study artifacts through a graph pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)
```

`main.py:94-99`. Title, description and version feed the generated OpenAPI document and the Swagger page at `/docs`. `version` is reused at line 169, so `/health` reports the same string the docs page shows. `lifespan=lifespan` wires in the handler above.

### CORS

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)
```

`main.py:101-109`. This block has history and is very likely to be asked about.

Start with the one-sentence framing, because it is the thing people get wrong: CORS is enforced by the *browser*, not by the server. The server's job is only to send back headers saying which origins are permitted; the browser then decides whether to let the JavaScript that made the call see the response. A curl request ignores all of it. So "CORS is broken" always means "the browser refused a response the server did in fact send".

**The bug that was here.** The original configuration was `allow_origins=["*"]` together with `allow_credentials=True`. The Fetch specification forbids that combination: a response may not carry `Access-Control-Allow-Origin: *` and `Access-Control-Allow-Credentials: true` at the same time, because the wildcard is exactly the case where sending someone's cookies to an arbitrary origin would be a disaster. You can see it happen in Starlette's implementation — `starlette/middleware/cors.py` builds `simple_headers` with a literal `"*"` when `allow_all_origins` is set, and adds `Access-Control-Allow-Credentials: true` alongside it, and only replaces the wildcard with the real origin if the request happened to carry a `Cookie` header. Every browser rejects that response. The net effect was that there was no working CORS at all: the frontend only ever worked when served from the same origin, and any genuine cross-origin call failed with an opaque network error rather than anything that pointed at the cause. It is a bad failure mode precisely because the configuration *looks* maximally permissive.

**The fix.** Name the origins. With `allow_all_origins` false, Starlette takes the other branch — `is_allowed_origin(origin)` is checked and the response mirrors back the *specific* requesting origin plus `Vary: Origin`. That is legal with credentials, and it is also simply more correct: an API that accepts credentials should know who it accepts them from.

`allow_origins=settings.cors_origins` takes the list from configuration (`CORS_ORIGINS`, default `["http://localhost:3000"]`), so a deployment adds its production domain without a code change.

`allow_origin_regex` is a development convenience that is checked as an alternative to the list — `is_allowed_origin` returns true if *either* the regex full-matches or the origin is in the list. It matches `http` or `https`, `localhost` or `127.0.0.1`, and any port or none. Two real annoyances motivated it. The Next dev server silently moves to 3001 when 3000 is taken, and a hard-coded 3000 in the list then rejects it. And `http://localhost:3000` and `http://127.0.0.1:3000` are *different origins* to a browser even though they are the same machine, so a teammate who typed the IP got rejected by an allow-list containing the hostname. Note it is matched with `fullmatch`, so it cannot be prefix-tricked by something like `http://localhost.evil.com`.

`allow_credentials=True` is what lets the browser attach cookies and `Authorization` headers to cross-origin requests, and is the constraint that made the wildcard illegal.

`allow_methods` is an explicit list rather than `["*"]`. Starlette's default is `("GET",)` alone, so this is not optional — `PATCH` is required by `PATCH /api/projects/{id}` (`api/routes/projects.py:68`), and `DELETE` by the delete route. `OPTIONS` is listed for the preflight itself.

`allow_headers=["*"]` mirrors back whatever the browser asks for in `Access-Control-Request-Headers`. This is needed because `Content-Type: application/json` is not on the CORS safelist — the safelisted content types are the form ones — so every JSON POST from the app is a non-simple request that triggers a preflight and must have `Content-Type` explicitly allowed.

`expose_headers=[REQUEST_ID_HEADER]` is the pair to the trace middleware below. By default JavaScript can read only a handful of response headers (`Content-Type`, `Cache-Control` and a few others); everything else is hidden even though it arrived. Without this line the frontend could not read `X-Request-ID` off a failed response, and the entire point of stamping requests with an id is that a user can read it off the screen and quote it.

**Middleware ordering.** Starlette's `add_middleware` does `self.user_middleware.insert(0, ...)` (`starlette/applications.py:126`), and the stack is then built with index 0 outermost. So the **last** middleware added is the **outermost**. CORS is added at line 101 and `trace_request` at line 112, which gives, from outside in:

```
ServerErrorMiddleware  ->  trace_request  ->  CORSMiddleware  ->  ExceptionMiddleware  ->  router
```

Two consequences follow, and both are the kind of thing an interviewer probes.

`CORSMiddleware` answers `OPTIONS` preflights itself and never forwards them to the router. Since `trace_request` is *outside* it, preflights still get an `X-Request-ID` and still get timed — which is what you want, because a preflight that is slow or being rejected is exactly the thing you need to see in the log.

And the `@app.exception_handler(Exception)` handler is special-cased by Starlette (`starlette/applications.py:79-83`): the keys `Exception` and `500` are pulled out and given to `ServerErrorMiddleware`, which is the outermost layer of all — *outside* CORS. So a 500 produced by that handler has no `Access-Control-Allow-Origin` header, and a browser will surface it as a CORS/network failure rather than a readable 500. The 422 from the validation handler does not have this problem, because non-500 exception handlers live in `ExceptionMiddleware`, which is inside CORS.

### Request tracing

```python
@app.middleware("http")
async def trace_request(request: Request, call_next):
    """Tag each request with an id and log the slow ones."""
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
    started = time.perf_counter()
```

`main.py:112-116`. `@app.middleware("http")` is sugar for `add_middleware(BaseHTTPMiddleware, dispatch=trace_request)`.

Line 115: reuse the client's `X-Request-ID` if it sent one, otherwise mint a new one. Reusing it is what lets a frontend log line and a backend log line be joined — the frontend generates an id, sends it, and both sides log the same string. `uuid.uuid4().hex[:12]` is 48 bits of randomness, which is far more than enough to disambiguate within one log file, and short enough that a user can read it off a screen and type it into a bug report. A full 32-character UUID would be correct and unusable for that.

Line 116 uses `time.perf_counter()`, not `time.time()`. `perf_counter` is monotonic: it cannot go backwards or jump when NTP corrects the clock or a DST boundary passes. Measuring a duration with wall-clock time occasionally produces negative durations, and this is the standard way to avoid that.

```python
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("[%s] %s %s failed", request_id, request.method, request.url.path)
        raise
```

`main.py:118-122`. `call_next` runs the rest of the stack. If it raises, log the traceback *with the request id attached* — this is the only place in the codebase where the generated id and the traceback appear together — and then re-raise. Re-raising is mandatory: swallowing it here would return `None` as a response and break the ASGI contract, and the job of turning it into a 500 belongs to `ServerErrorMiddleware` above.

```python
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers[REQUEST_ID_HEADER] = request_id

    if elapsed_ms > SLOW_REQUEST_MS or response.status_code >= 500:
        logger.warning("[%s] %s %s -> %d (%.0fms)", request_id, request.method,
                       request.url.path, response.status_code, elapsed_ms)

    return response
```

`main.py:124-131`. Duration in milliseconds, then stamp the id onto the response so the client can read it back (which is why it is in `expose_headers`).

Lines 127-129 are a deliberate logging policy: log only the interesting requests. Emitting an INFO line per request sounds harmless until you remember what the logs are actually for here — watching a pipeline run through its stages. A canvas run with a dozen nodes generates a stream of polling requests from the frontend, and those would bury the stage-by-stage output that tells you what the pipeline is doing. So the rule is: a request gets a line if it took more than a second or if it failed with a 5xx, and otherwise it is silent. `%.0fms` rounds to whole milliseconds because sub-millisecond precision on an HTTP request is noise.

Worth knowing, and a genuinely good thing to have noticed yourself: on the exception path, lines 124-125 never execute, so a 500 response carries **no** `X-Request-ID` header. The error body does contain a `request_id` (line 156), but that handler reads the id from the *request* header and falls back to `"-"`, so it can only report an id the client supplied. When the client supplied none, the log has the generated id and the response body has `"-"`, and there is no way to join them. It is a real gap in the tracing story; the fix would be stashing the id on `request.state` so the exception handler can read it.

Worth knowing, second: `@app.middleware("http")` uses `BaseHTTPMiddleware`, which wraps the downstream response in an anyio memory stream. That is fine for normal responses but is the known reason people avoid it in front of long-lived streaming endpoints. The WebSocket route is unaffected — `BaseHTTPMiddleware` checks the ASGI scope type and passes anything that is not `"http"` straight through, so `/ws/projects/{project_id}` never enters this function. That also means WebSocket connections are not traced and are not subject to CORS at all, since browsers do not apply CORS to WebSockets (the equivalent control is the `Origin` header, checked by the server if it chooses to).

### Error handlers

```python
@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, error: RequestValidationError):
    """Return field-level problems the frontend can display."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed",
            "problems": [
                {"field": ".".join(str(part) for part in item["loc"][1:]), "message": item["msg"]}
                for item in error.errors()
            ],
        },
    )
```

`main.py:134-146`. `RequestValidationError` is what FastAPI raises when Pydantic rejects a request body, query parameter or path parameter. FastAPI's default response is `{"detail": [{"loc": [...], "msg": ..., "type": ..., "input": ..., "url": ...}]}` — accurate, verbose, and shaped for a machine. This reshapes it into something a frontend can render directly next to a form field: a human sentence in `detail` and a flat list of `{field, message}` pairs in `problems`.

Line 142 is the interesting expression. `item["loc"]` is a tuple whose first element is the *location kind* — `"body"`, `"query"` or `"path"` — followed by the actual path to the field. `[1:]` drops the kind, since the frontend already knows it posted a body. `str(part)` is required because list indices arrive as integers and `"".join` refuses anything that is not a string. The result is `"nodes.0.id"` instead of `("body", "nodes", 0, "id")`, which is a string a frontend can match against a field name.

Because this is a non-500 handler it runs inside `ExceptionMiddleware`, which is *inside* `CORSMiddleware`, so the 422 does carry CORS headers and the browser will let the frontend read it. That is the whole reason the reshaping is worth doing.

```python
@app.exception_handler(Exception)
async def on_unhandled_error(request: Request, error: Exception):
    """Keep stack traces in the logs, not in responses."""
    request_id = request.headers.get(REQUEST_ID_HEADER, "-")
    logger.exception("[%s] Unhandled error on %s", request_id, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )
```

`main.py:149-157`. The catch-all.

Line 152 reads the id from the request headers with `"-"` as the fallback. Line 153 uses `logger.exception`, which is `logger.error` plus the current traceback — it works because we are inside exception handling, so `sys.exc_info()` is populated.

Lines 154-157 are the security decision, and it is the one to lead with if asked. The response contains no exception text at all. Exception strings from this codebase routinely contain the absolute SQLite path, a filesystem path under the storage root, or the raw error body from OpenRouter — which is to say, internal layout and occasionally fragments of upstream responses. Those belong to the operator, in the log, not to whoever made the request. The caller gets a stable message and an id they can quote, which is enough to get support and nothing more.

Two mechanical notes. As covered above, Starlette routes this handler to `ServerErrorMiddleware`, so the response is generated outside the CORS layer and lacks CORS headers. And `ServerErrorMiddleware` re-raises the exception after sending the response (`starlette/middleware/errors.py:186`) so that the ASGI server can log it and the test client can be configured to surface it — which is why an unhandled error still appears in uvicorn's own output as well as yours.

### Routers

```python
for router in (projects, jobs, artifacts, flows, files, chat, ws):
    app.include_router(router.router)
```

`main.py:160-161`. Seven route modules mounted in a loop. No prefixes here: each router declares its own (`projects.py:22` is `/api/projects`, `jobs.py:26` is `/api/jobs`, `files.py:12` is `/api/files`, `chat.py:23` is `/api/chat`, `artifacts.py:17` is `/api`, `flows.py:18` is `/api/projects`, and `ws.py:18` has none). A router owning its own URL space means you can read one file and know where it lives, rather than cross-referencing this loop.

The order is not purely cosmetic: FastAPI matches routes in registration order, first match wins. `projects` and `flows` both mount under `/api/projects`, and `projects` is registered first. Today they do not collide — `projects` owns `""`, `"/{project_id}"`, `"/{project_id}/artifacts"` and `"/{project_id}/upload"`, while `flows` owns `"/{project_id}/flow/validate"`, `"/{project_id}/flow/run"` and the two `"/{project_id}/flow/runs"` paths — but if a future flow route ever shadowed a project route, this ordering would decide the winner silently. Worth knowing that the risk exists.

`ws.router` carries no prefix and declares a single WebSocket endpoint at `/ws/projects/{project_id}` (`ws.py:27`), which is the channel the canvas subscribes to for live node progress.

### `/health`

```python
@app.get("/health", tags=["meta"])
def health():
    """Liveness, plus what this instance resolved its dependencies to."""
    return {
        "status": "healthy",
        "version": app.version,
        "database": str(get_database().path),
        "files": str(get_file_store().root),
        "events": events.get_event_bus().driver,
        "jobs": dispatch_mode(),
        "model": get_provider().name,
    }
```

`main.py:164-175`. Note `def`, not `async def`. A synchronous route function is run by FastAPI in a threadpool, so a blocking call inside it cannot stall the event loop. Here every call is a cached-singleton lookup and would be fine either way, but sync-by-default for anything that touches sync code is the right habit.

The five resolved values are the same ones printed in the startup banner at line 73, which is the point. `str()` around the paths because `Path` is not JSON-serialisable.

**What this proves.** The process is up, the module imported without error, an ASGI worker is accepting connections, and these five singletons already exist — they were built during lifespan, and each `get_*()` here returns the cached instance rather than constructing anything.

**What it does not prove**, which is the more important half. It issues no query, no ping, and no model call. It does not prove SQLite is writable *now* — the file could have been deleted or the disk filled since boot. It does not prove Redis is still reachable; `"events": "redis"` means the bus was constructed successfully at startup and `"jobs": "celery"` means the broker answered a probe at startup, neither of which says anything about the last hour. It does not prove the OpenRouter key is valid — `get_provider()` only checks that a key string is non-empty (`llm/factory.py:21`), so a revoked key still reports `"model": "google/gemini-2.5-flash"`. And most importantly it does not prove a worker is alive and draining the queue. In Celery mode you can have a perfectly healthy `/health` and zero workers, and jobs will pile up in `pending` indefinitely.

So this is a **liveness** probe with configuration reporting attached, not a **readiness** probe. If you wanted readiness you would need a `SELECT 1` against the database, a broker ping, and a check on queue depth or worker heartbeat. Say that before you are asked — knowing the limits of your own health check reads much better than defending it.

`backend/tests/test_api.py:17-21` asserts exactly this shape, including that `model` is `"offline"` under the test fixture's empty API key.

### `/api/capabilities`

```python
@app.get("/api/capabilities", tags=["meta"])
def capabilities():
    """What this deployment can produce. The canvas builds its palette from this."""
    provider = get_provider()
    return {
        "artifact_types": sorted(GENERATED_TYPES),
        "source_types": sorted(SOURCE_TYPES),
```

`main.py:178-184`. The reason this endpoint exists rather than a hard-coded list in the frontend is stated in the docstring: the canvas builds its node palette from this response, so it is structurally impossible for the UI to offer a node type the backend cannot produce. A hard-coded frontend list drifts the moment someone adds or removes an artifact type, and the failure is a user dragging a node onto the canvas, wiring it up, pressing Run and getting a 400.

`GENERATED_TYPES` is `frozenset(ARTIFACT_MODELS)` (`models/artifacts.py:148`) — derived from the registry of Pydantic artifact models rather than written out separately. Add a new artifact model to that registry and it appears in the palette with no other edit anywhere. `SOURCE_TYPES` (`models/artifacts.py:150`) is the fixed set `{youtube, audio, video, pdf, pptx, md}`. Both are wrapped in `sorted()` because a frozenset has no defined iteration order, and a palette whose buttons reshuffle between page loads looks broken.

```python
        "features": {
            "flows": True,
            "refine": True,
            "assistant": True,
            "realtime": True,
            "transcription": provider.supports_audio,
            "offline_model": provider.name == "offline",
        },
    }
```

`main.py:185-193`. The first four are compile-time truths — those features are in the build — so the flag is a contract the frontend can gate on rather than a runtime check. They exist so the frontend never has to detect a feature by probing an endpoint and interpreting a 404.

The last two are the useful ones. `transcription` reflects whether the active provider can handle audio; the offline provider cannot, so with no API key the UI can grey out audio and video upload instead of accepting a lecture recording and returning nothing. `offline_model` lets the UI say plainly that no key is configured and output will be much duller. That single boolean is the most valuable field in this response during a demo, because "I forgot the API key" and "the model is producing bad output" are otherwise indistinguishable from the front end.

### Entry point

```python
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
```

`main.py:196-199`. `uvicorn` is imported inside the block rather than at the top because it is only needed on this path — importing the app as a module (which is what `uvicorn backend.main:app` and the test client both do) should not pull in the server.

This exists so `python backend/main.py` works, and it is the reason `sys.path.append` on line 13 is there. It is not the recommended way to run the app — `uvicorn backend.main:app --reload` from the repo root gives you reload and proper worker configuration — but having the file be directly runnable removes one step from a first-time setup, which is the same instinct behind every default in `config.py`.

---

## How `REDIS_URL` and `CELERY_ENABLED` switch the topology

Pulling the thread end to end, since this is the design claim the project is built on and it is spread across four files.

The system has two shapes. **Three processes:** a FastAPI API that accepts work and streams progress, one or more Celery workers that do the work, and Redis carrying both the job queue and the pub/sub event stream between them. **One process:** `uvicorn backend.main:app`, which runs its own worker pool and its own in-memory event bus and needs nothing else installed.

Nothing in the code branches on a "mode" setting you choose. The mode is *derived*, in one place, from whether a broker answers.

Reading configuration, `config.py:178-179` produces `redis_url` (default empty) and `celery_enabled` (default `True`).

Deciding, `celery_app.py:46-52`. `broker_available()` returns `False` immediately if there is no URL or the kill switch is off, and otherwise opens a write connection with a two-second, one-retry bound and returns whether it succeeded. `dispatcher.py:18-33` calls that once, under a double-checked lock, and caches the answer in a module global as either `"celery"` or `"local"`.

Acting on it, in three separate places that each ask the same question:

*Jobs.* `dispatcher.enqueue` (`dispatcher.py:44-54`) is a no-op in local mode, because the in-process pool is already polling the `jobs` table and will pick the row up on its next tick. In Celery mode it publishes `run_job.delay(job_id)`. Either way the job **row is committed to SQLite before the message is sent**, which is what makes a broker outage a delay rather than a loss — an enqueue failure returns `"deferred"` and the row simply waits.

*Workers.* `main.py:79-84`. In local mode the API starts a `WorkerPool` inside itself. In Celery mode it starts nothing and the separately-launched workers drain the queue.

*Events.* `events.py:179-187`, reached from `main.py:64`. With Redis, a `RedisEventBus` publishing to `beeprepared:project:{id}` so a worker in another process can push progress to a WebSocket held by the API. Without it, an `InProcessEventBus` over asyncio queues, bound to the API's loop at `main.py:66` so that background threads can publish safely.

Two properties fall out of this that are worth stating explicitly, because they are what make the design defensible rather than merely clever.

The fallback is automatic in the right direction only. If `REDIS_URL` is set but Redis is down at startup, the system does not fail — it logs a warning and runs single-process. It never does the reverse, because there is nothing to fall back *to*.

And every mechanism that matters is identical in both modes. The same `JobExecutor` runs the job (`tasks.py:41-44` calls `JobExecutor().run_job`; `job_runner.py:293` calls `self._executor.run_next()`). The same claim-in-a-transaction prevents double execution. The same timeout applies. The same reaper requeues stranded rows — as a beat task in Celery mode, as an asyncio task in local mode. That is why "it works on my laptop with no Redis" and "it works in production with three processes" are the same claim about the same code, and it is the answer to the obvious interview question of how you know the single-process path is not a toy.
