# 12 — The test suite

Files covered:

- `backend/tests/conftest.py` (114 lines, 0 tests, 5 fixtures)
- `backend/tests/test_api.py` (977 lines, 59 test functions, 72 cases)
- `backend/tests/test_pipeline.py` (758 lines, 38 test functions, 59 cases)
- `backend/tests/test_flow_engine.py` (297 lines, 21 tests)
- `backend/tests/test_seams.py` (631 lines, 20 tests)

172 tests. Run them with:

```
backend/venv/bin/python -m pytest -q -p no:warnings
```

The last recorded run: `172 passed in 1.40s`.

The gap between "test functions" and "cases" is parametrisation. `pytest -q`
counts cases, so 172 is the number you will see; when this document says a test
"has four parameters" it means one function that pytest reports as four.

---

## 1. The mutation-testing pass, and what it found

This is the most interesting thing in this document, so it comes first.

The suite used to have 108 tests. All of them passed, and a good number of them
were written as regression tests for bugs that had actually happened. The
question that is worth asking about a suite like that — and that an interviewer
may well ask — is: *how do you know those tests would still fail if you broke
the thing again?*

The honest way to find out is to break the thing again on purpose. So a sandbox
copy of the repository was made, and roughly forty-five single-behaviour
mutations were applied to it one at a time. Each mutation changed exactly one
thing — a comparison flipped, a constant widened, a guard deleted, a return
value hard-coded — and then the whole suite was run against it and the list of
tests that failed was recorded. A mutation that nothing catches is called a
*surviving* mutation, and every surviving mutation is a piece of behaviour the
suite claims to protect and does not.

Twenty-one mutations survived. All twenty-one are now killed, and closing them
took the suite from 108 tests to 172.

Say it in that order if you are asked. "I mutation-tested my own test suite" is
a strong sentence, and the result was genuinely humbling in places, which is the
part worth being frank about.

### The headline result: 8 of 10 regression tests held, 2 did not

There were ten tests in the suite written specifically to pin a bug that had
been found and fixed. Eight of them did their job. Two did not, and one of those
two was for the worst bug in the project.

**What held, and how well.**

The flow-concurrency regression test is the real thing. Reverting the
transaction boundary in `FlowEngine.on_job_finished` and running that one test
twenty times failed twenty times out of twenty, nineteen of them with exactly
`assert 9 == 2`. The concurrency is genuine rather than simulated: eight real OS
threads, a `threading.Barrier(8)` so that none of them moves until all eight
have arrived, and every thread observes the downstream step as `pending` before
any writer commits. It also carries a second, independent assertion on the
number of rows in the `jobs` table, which pins the *side effect* rather than the
observer — a dispatch counter can be fooled, a row count cannot.

One thing to be unambiguous about, because it is the tab you will want open:
**that test lives in `backend/tests/test_pipeline.py`, not in
`test_flow_engine.py`.** It is
`TestFlowConcurrency::test_concurrent_completions_queue_the_next_step_once` at
`test_pipeline.py:630`. `test_flow_engine.py` holds the single-threaded sibling,
`test_advance_is_idempotent` at `test_flow_engine.py:273`, which is a much
weaker test and now says so in its own docstring.

The five security regression tests all held. The best-designed group in the
whole suite is the flow-seeding cluster, because it tests all three doors into
the same handler — `POST /flow/run` with a body, `POST /flow/run` with no body
so the saved canvas is used, and `POST /flow/validate` — rather than only the
door that was reported. A fix that guarded the request body instead of the
compiled plan would pass one of those three and fail the other two. That is what
testing a fix for *completeness* looks like.

**What did not hold.**

*The locale bug had no test at all.* Setting
`PASS_THROUGH_MARKERS = ("do not summarize",)` in `backend/llm/offline.py:24` —
which is literally the original bug, a British spelling in the prompt and an
American one in the recogniser — survived with all 108 tests passing. So did
making `OfflineProvider._wants_the_source_back()` return `False`
unconditionally. Either mutation means the offline provider stops handing a
cleaning prompt its own text back and instead derives a synthetic study document
from it, so a whole lecture transcript is replaced by text nobody ever said, and
the knowledge core and every artifact under it are built on that.

The root cause of the miss is worth stating plainly, because it is a design
lesson rather than an oversight. **No test ever ran a real ingest.** Every
ingest test injected a `StubCleaner` whose `clean()` was `return text`, and the
API upload test stopped at HTTP 202 without ever executing the queued job. So
`backend/pipeline/cleaning.py` sat at 50% coverage with `_repair` never entered
even once. The whole class of failure this belongs to — *a stage returning
plausible-but-wrong output instead of raising* — had no detector anywhere in the
suite. Everything was pinned against exceptions and status codes; nothing was
pinned against silence.

That class is now covered by `TestTranscriptRepairKeepsTheSource` and
`TestCleaning` in `test_pipeline.py`, described in section 5.

*Idempotency had no negative test.* Mutating `IN_FLIGHT` in
`backend/api/routes/jobs.py:34` from `("pending", "running")` to
`("pending", "running", "completed")` survived. That mutation **is** the
original bug: with `completed` in the set, pressing Regenerate hands back the
job of the artifact you already have, nothing runs, and the canvas never
changes. The old test only proved that two identical in-flight requests were
merged; nothing proved that a *finished* one was not. The negative case is now
`test_a_completed_job_is_never_handed_back_to_a_later_request` at
`test_api.py:251`.

### The other things the pass found, all now closed

**A test that was green by scheduling luck.**
`test_identical_in_flight_requests_are_deduplicated` passed for the wrong
reason. The `client` fixture runs `main.lifespan`, and because dispatch mode is
`local` that lifespan starts a real `WorkerPool` which drains the queue in the
background *during the test*. The test only passed because the idle backoff in
`WorkerPool._worker` starts at 0.5 seconds, so the worker was usually asleep
between the two POSTs. Dropping the backoff to 1 ms made it fail three times out
of three. The fix was not to the test's assertions but to its preconditions:
there is now an `idle_client` fixture (`test_api.py:19`) that monkeypatches
`WorkerPool.start` to a no-op, so the first job is pending because nothing *can*
claim it rather than because nothing happened to.

**The `exam` artifact type was untested.** Seven of the eight generated types
were parametrised; `exam` was not. It is the most complex path in the system —
an `ExamSpec` contract generated first, then three question batches generated
concurrently under `asyncio.gather`, then merged, renumbered and typeset to PDF.
It is now the eighth parameter of
`test_every_artifact_type_generates_and_commits`, and it has a dedicated test
for the export as well.

**Event-bus project isolation was untested.** Making `InProcessEventBus._deliver`
broadcast every project's events to every subscriber survived the whole suite,
because every event test had exactly one project in it. That is the leak that
looks like nothing at all in a single-project test and hands one workspace's job
progress, artifact names and chat replies to another. Now covered by
`TestEventBusIsolation` in `test_seams.py`.

**A batch of individually-surviving guards.** Each of these was one mutation,
each survived, each now has a test:

- `require_project_artifact`'s cross-project 400 (`backend/api/deps.py:84`)
- `GenerateRequest.at_least_one_source` (`backend/api/schemas.py:79`)
- `IngestRequest.known_source` reached through the schema rather than the upload
  route (`backend/api/schemas.py:42`)
- `FlowCompiler`'s `MAX_NODES` limit (`backend/services/flow/plan.py:109`)
- `reap_stale_jobs`'s out-of-attempts branch
  (`backend/services/database.py:416`)
- `update_artifact`'s documented merge-not-replace behaviour
  (`backend/api/routes/artifacts.py:77`)

**Several tests asserted too little for their names.** This is the humbling
part, and it is worth being able to list without flinching:

- `test_capabilities_lists_every_artifact_type` checked two of the eight types.
- `test_upload_queues_an_ingest_job` survived the endpoint queueing an *empty*
  `source_ref`, because it only looked at the status code and the presence of a
  job id.
- `test_create_and_read_a_generate_job` survived the endpoint always reporting
  `"pending"` regardless of the row.
- The WebSocket snapshot test survived `flow_runs` being emptied out of the
  snapshot entirely.
- `test_a_youtube_url_still_validates` was a tautology: it asserted that the
  URL it had just passed in came back out.

All five now assert what their names claim. The last one is still partly
tautological and is discussed honestly in section 4.

### One nuance to get right if you are asked

In the `is_transient` parametrisation, the UUID case
`"429e4567-e89b-12d3-a456-426614174000"` — the one the original bug is named
after — is the **weakest** of the three parameters, not the strongest.

The current regex is:

```python
TRANSIENT_STATUS = re.compile(r"\b(?:http|status|code)\s*[:=]?\s*(408|409|425|429|500|502|503|504)\b")
```

Remove the `(?:http|status|code)` label group, which is the obvious mutation,
and you are left with `\b(408|...|429|...)\b`. That still does **not** match
inside `429e4567`, because `\b` after `429` requires a non-word character and
the next character is `e`. So the UUID parameter survives that mutation. It only
dies under a true-substring mutation — a regex with no word boundaries at all,
or a plain `"429" in message`.

The two parameters doing the real work are the ones with the status code sitting
in ordinary prose: `"Source artifacts not found: 502"` and
`"artifact 504 has no content"`. Both of those match `\b502\b` and `\b504\b`
once the label group is gone, so both die under the label mutation. Verified
directly rather than reasoned about.

This is a good thing to volunteer, because it shows the difference between a
test that names the bug and a test that catches it.

### One mislabelled test, now corrected

`test_advance_is_idempotent` in `test_flow_engine.py` had a docstring claiming
it covered duplicate completions. It does not. It calls `advance` twice
**sequentially** on one thread, and it passes perfectly well against an engine
with no transaction around the read-then-write. It pins only the
`status != "pending"` guard at `backend/services/flow/engine.py:137`. The
docstring now says exactly that, and points at the concurrent test in
`test_pipeline.py` by name.

Keeping both is right. One is a logic property, the other is a concurrency
property, and passing the first does not imply the second — which is precisely
why the old engine passed one and failed the other.

---

## 2. How the suite is built, and why it finishes in under two seconds

The thing an interviewer is most likely to ask about this suite is why it is so
fast, because a suite that exercises a whole upload-to-artifact pipeline in
about a second normally means one of two things: either it is full of mocks and
tests nothing, or the system was designed so that the slow parts are pluggable.
This one is the second. The answer you want to have ready is short: **the tests
run the real code against fake edges.**

There are four "edges" the backend touches, and every one of them is turned off
by configuration rather than by patching:

**The language model.** `backend/llm/factory.py:19` picks a provider:

```python
def build_provider() -> LLMProvider:
    """Return OpenRouter when a key is configured, otherwise the offline provider."""
    if not get_settings().has_llm_key:
        return OfflineProvider()
```

`conftest.py:58` sets `OPENROUTER_API_KEY` to the empty string, so
`has_llm_key` is false and every test gets `OfflineProvider`. That class
(`backend/llm/offline.py`) is not a mock. It implements the same abstract base
class as the real provider, `LLMProvider` in `backend/llm/base.py:17`, and it
produces real, schema-valid artifacts by doing word-frequency analysis on the
source text. It is slow-model-shaped but it runs in microseconds because it is
just regular expressions and dictionary counting.

This is the Liskov substitution point, and it is worth saying out loud in those
words. `OfflineProvider` and `OpenRouterProvider` are substitutable everywhere
`LLMProvider` is expected. Nothing in `ArtifactGenerator`, `KnowledgeExtractor`,
`CoreMerger` or any handler knows which one it has. The proof that the
substitution really holds is that the entire suite — including all eight
artifact types generating end to end and committing to a database — runs against
the offline one and passes.

> **Worth knowing, and new.** The real provider is no longer completely
> untouched. `TestProviderFailureClassification` in `test_pipeline.py:160`
> constructs a genuine `OpenRouterProvider` and drives its retry loop against a
> patched `httpx.AsyncClient.post`. No network is involved, but the class itself
> now runs. See section 5.

**Redis.** `conftest.py:59` sets `REDIS_URL` to empty.
`backend/services/events.py:184` then builds an `InProcessEventBus` instead of a
`RedisEventBus`, so the WebSocket tests get a real event bus with real asyncio
queues and no network.

**Celery.** `conftest.py:57` sets `CELERY_ENABLED=false`. `broker_available()`
in `backend/celery_app.py:39` short-circuits at line 46 on
`if not settings.has_redis or not settings.celery_enabled: return False` — it
does not even attempt a connection, so there is no two-second timeout waiting
for a broker that is not there. Dispatch mode resolves to `"local"`.

**The database and the filesystem.** `conftest.py:54` points `BEE_DATA_DIR` at
pytest's `tmp_path`, which is a fresh directory per test. The database is
SQLite; `Database.__init__` (`backend/services/database.py:130`) creates the
file and runs the schema. Creating an empty SQLite file and executing about
sixty lines of DDL costs roughly a millisecond.

Two more reasons for the speed that are worth knowing:

- Only part of `test_api.py` builds the FastAPI application. The other three
  files talk to the services and handlers directly, and several classes inside
  `test_api.py` — `TestYouTubeIngestGuard`, `TestStartupGuard`, the schema-level
  YouTube tests — take no client either. Roughly 127 of the 172 cases never
  start an app, never open a socket and never run the lifespan.
- Nothing in the suite sleeps waiting for work. The concurrency tests use
  `threading.Barrier` to make threads collide and then `join`, which returns as
  soon as the work is done. `test_pipeline.py:69` runs jobs synchronously with
  `asyncio.run(...)` instead of handing them to a worker and polling. The only
  sleeps anywhere are two 50 ms `asyncio.sleep` calls in
  `TestEventBusIsolation`, which exist to prove a *negative* — that an event has
  not been delivered — and there is no way to prove that except by waiting.

`pytest.ini` at the repo root sets `asyncio_mode = auto`, which is why async
test functions work. `test_seams.py` still marks them `@pytest.mark.asyncio`
explicitly; that is redundant but harmless.

### One thing that surprises people

When `test_api.py` uses the `client` fixture, the FastAPI lifespan actually
runs, and because dispatch mode is `local`, that lifespan starts a real
`WorkerPool` with two workers (`backend/main.py:83`, `WORKER_CONCURRENCY=2` from
`conftest.py:56`). You can see it in the logs:

```
INFO backend.services.dispatcher: Job dispatch: local
INFO backend.services.job_runner: Worker pool started (concurrency=2)
```

So during API tests there genuinely are background workers polling the queue.

**This used to be described here as harmless, and it was not.** The reason it
usually looks harmless is the idle backoff in `WorkerPool._worker`
(`backend/services/job_runner.py:288`, constants at lines 253-254): a worker
that finds nothing sleeps 0.5 seconds and then backs off by a factor of 1.5 up
to a 5-second ceiling. A test body that finishes in a few milliseconds normally
lands inside that first sleep, so a job it posted is still `pending` when it
asserts.

That is a race, not a guarantee. The mutation pass found it by shortening the
backoff, at which point
`test_identical_in_flight_requests_are_deduplicated` failed three times out of
three. The fix is the `idle_client` fixture at `test_api.py:19`:

```python
@pytest.fixture
def idle_client(monkeypatch):
    async def start_nothing(pool) -> None:
        return None

    monkeypatch.setattr(job_runner.WorkerPool, "start", start_nothing)

    with TestClient(app) as test_client:
        yield test_client
```

The lifespan still runs — the event bus is still bound, the database and file
store are still resolved — but `WorkerPool.start` does nothing, so no worker
ever claims anything. Three tests use it: the two deduplication tests
(`test_api.py:225` and `test_api.py:251`) and
`test_create_and_read_a_generate_job` (`test_api.py:155`), plus
`test_upload_queues_an_ingest_job` (`test_api.py:90`), which additionally needs
the staged upload file to still exist when it reads it. Four in total.

The docstring on the fixture is the sentence to remember: turning the pool off
"makes the precondition a fact rather than a question of scheduling."

---

## 3. `conftest.py` — isolation

114 lines. There is no test in this file. Everything here exists so that the
172 tests cannot see each other.

Note that the `idle_client` fixture described above is *not* here — it lives in
`test_api.py`, because only that file needs it.

### The path fix, lines 11-13

```python
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

`conftest.py` lives at `backend/tests/`, so `parents[2]` is the repository root.
Adding it to `sys.path` is what makes `from backend.services.database import ...`
resolve when pytest is invoked from anywhere. Without it, the imports in every
test file fail at collection time.

### `SAMPLE_CORE`, lines 15-42

A hand-written `KnowledgeCore` about distributed systems: a title, a summary,
three concepts, one section, one note block, one definition, one example, one
key fact.

It is worth understanding why this is a full, valid core rather than a stub with
two fields. `KnowledgeCore` (`backend/pipeline/knowledge.py:74`) requires all
eight collections, and `KnowledgeCoreValidator`
(`backend/handlers/ingest_handler.py:30`) additionally requires `title`,
`summary`, `concepts` and `key_facts` to be non-empty and rejects any LaTeX or
dollar signs anywhere in the text (`FORBIDDEN_MARKUP` at
`ingest_handler.py:23`). So `SAMPLE_CORE` has to be a genuinely legal core, or
the ingest tests in `test_seams.py` would fail on validation rather than on what
they are actually testing.

The content also matters. The offline provider derives everything from the
words in the core, so a core with real prose about quorums and consensus
produces quizzes and notes with real-looking content, and the length floors in
`GeneratorSpec.validate` are satisfied. A core saying "lorem ipsum" would fail
the 200-character notes minimum.

`SAMPLE_CORE` is imported by name from three places: the `knowledge_core`
fixture below, the `core` fixture in `test_seams.py:54`, and
`TestSecurity.foreign_artifact` in `test_api.py:431` (which also uses it inline
at `test_api.py:476`).

### `isolated_environment`, lines 45-63

```python
@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("BEE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SIGNING_SECRET", "test-secret")
    ...
    _reset_singletons()
    yield
    _reset_singletons()
```

`autouse=True` means it runs for every test in the suite whether the test asks
for it or not. It does two jobs.

First, it sets six environment variables. `BEE_DATA_DIR` gives each test its own
directory under `tmp_path`, which is where both the SQLite file and the file
store live. `SIGNING_SECRET` makes the HMAC key deterministic, which matters
because the signed-URL tests compare a signature produced in one place against a
verification done in another. The other four variables are the ones described
above that turn off OpenRouter, Redis and Celery, and cap worker concurrency at
two.

> **New, and worth knowing.** `"test-secret"` is not one of the values in
> `PUBLISHED_SECRETS` (`backend/core/config.py:19`), which is why the startup
> guard added in `backend/main.py:41` does not refuse to boot during the API
> tests. If somebody changed this line to `"change-me-in-production"` every test
> that uses the `client` fixture would fail at lifespan with a `RuntimeError`.
> That coupling is deliberate and is itself tested, at `test_api.py:918`.

Second, and more important, it resets every cached singleton **both before and
after** each test. That is the part to explain if asked.

### `_reset_singletons`, lines 66-76

```python
def _reset_singletons() -> None:
    get_settings.cache_clear()
    factory.reset_provider()
    database.reset_database()
    files.reset_file_store()
    events.reset_event_bus()
    dispatcher.reset()
```

Six process-wide caches, each of which exists for a good production reason and
each of which would leak between tests if it were not cleared:

- `get_settings` is decorated `@lru_cache(maxsize=1)`
  (`backend/core/config.py:159`). Settings are read from the environment once
  per process. Without `cache_clear()`, the `monkeypatch.setenv` calls above
  would have no effect after the first test, because the cached `Settings`
  object would still hold the old values.
- `factory.reset_provider()` drops the module-level `_provider`. Otherwise a
  test that configured a key would leave a real `OpenRouterProvider` behind for
  every later test. This matters more than it used to:
  `test_pipeline.py:175` and `test_pipeline.py:124` both set
  `OPENROUTER_API_KEY` to a real-looking value mid-test.
- `database.reset_database()` drops the module-level `Database` handle, which is
  bound to a specific file path. Without this, test two would keep writing into
  test one's `tmp_path` — which still exists on disk, so it would not even
  error; the tests would just see each other's rows.
- `files.reset_file_store()` does the same for the `FileStore`, which caches its
  root directory and its signing secret.
- `events.reset_event_bus()` matters because `InProcessEventBus` holds a
  reference to the asyncio event loop it was bound to (`bind_loop`, called from
  the lifespan at `backend/main.py:66`). A bus still bound to a closed loop from
  a previous test would try `call_soon_threadsafe` on a dead loop.
- `dispatcher.reset()` clears the memoised `_mode`, which is decided once per
  process in `dispatch_mode()`.

The reset runs after the test as well as before. That is deliberate: several
tests change settings mid-body — `test_api.py:139`, `test_api.py:847`,
`test_pipeline.py:503` and `test_pipeline.py:540` all call
`get_settings.cache_clear()` by hand after a `setenv` — and none of them must
leave that change visible to the next test even though the next test's `setenv`
will also reset it. Resetting on both sides means neither the order of the
fixtures nor the order of the tests can matter.

**How this fixture would fail.** Delete `get_settings.cache_clear()` and a
handful of tests break immediately, but the interesting failure is subtler:
delete `database.reset_database()` and the suite still mostly passes, because
most tests only look at rows they created themselves. It would start failing on
tests that assert a table is *empty*, and there are now nine of those — every
security test that ends
`assert database.select("jobs", [...]) == []`. That is the kind of failure that
looks like flakiness and is actually leakage.

### `database`, lines 79-83

```python
@pytest.fixture
def database():
    from backend.services.database import get_database
    return get_database()
```

Returns the real `Database`, pointed at this test's `tmp_path` by the autouse
fixture. Note the import is inside the function, not at module scope. That is
not stylistic: it must happen *after* `isolated_environment` has set
`BEE_DATA_DIR` and cleared the settings cache, otherwise `get_database()` would
build a handle against the developer's real `.storage` directory.

### `project`, lines 86-94

```python
return database.insert("projects", {
    "name": "Test Project",
    "description": "fixture",
    "user_id": LOCAL_USER_ID,
})[0]
```

A project owned by `LOCAL_USER_ID` — the constant from `backend/api/deps.py:11`,
which is what `resolve_user` returns for every caller in this deployment. Using
the same constant the API uses is what makes the ownership checks pass for this
project and fail for the deliberately foreign ones created in the security
tests.

### `knowledge_core`, lines 97-104

```python
return database.insert("artifacts", {
    "project_id": project["id"],
    "type": "knowledge_core",
    "content": {"kind": "core", "core": SAMPLE_CORE},
})[0]
```

The artifact row that ingest would have produced. The `{"kind": "core", "core": ...}`
shape is exactly what `IngestHandler._bundle` writes
(`backend/handlers/ingest_handler.py:235`) and exactly what
`SourceResolver.to_core` reads (`backend/handlers/sources.py:157`). Having the
fixture write the same shape is what lets the generation tests start from a real
core without running ingest, while still going through the real resolver.

### `client`, lines 107-114

```python
with TestClient(app) as test_client:
    yield test_client
```

The `with` block is the important part. Using `TestClient` as a context manager
is what makes Starlette run the application lifespan, which is what checks the
signing secret, resolves the database, the file store, the provider and the
dispatch mode, binds the event bus to the running loop, and starts the worker
pool. Without the `with`, `events.bind_loop` would never be called and the
WebSocket test at `test_api.py:393` — which publishes from the test thread and
expects the frame to arrive on the socket — would hang.

Use `client` when you want the whole application. Use `idle_client` when the
test asserts something about a row that a background worker could change
underneath it.

---

## 4. `test_api.py` — the HTTP and WebSocket surface

977 lines, 59 test functions, 72 cases, ten classes. Most of it goes through the
real FastAPI app with the real routers, dependencies and Pydantic schemas; two
of the newer classes are unit tests of guards that sit behind the app, placed
here because that is where the rest of their story is.

A helper at the top, lines 13-16:

```python
def create_project(client, name="API Project") -> dict:
    response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()
```

The `assert` inside a helper is a deliberate choice: if project creation breaks,
every test that uses it fails with a clear message at line 15 instead of with a
confusing `KeyError: 'id'` twenty lines later.

The `idle_client` fixture at lines 19-40 is described in section 2.

### `TestMeta` (line 43)

**`test_health_reports_what_it_is_wired_to`** — `test_api.py:44`. Hits `/health`
and asserts `status == "healthy"`, `model == "offline"` and `jobs == "local"`.
The middle assertion proves the provider selection in `factory.build_provider`
really did fall back to offline when the key was blank. If someone hard-coded
`OpenRouterProvider()` into the factory, this test fails with
`"openrouter" != "offline"`.

The third assertion used to read `jobs in {"local", "celery"}`, which could only
fail on a third, unexpected string. It is now an equality, and the docstring
says why that is legitimate: "Every fixture forces `CELERY_ENABLED=false`, so
there is one right answer." Weakening `broker_available()` so that it tries a
connection, or making `dispatch_mode()` default to `celery`, now fails here.

**`test_capabilities_lists_every_artifact_type`** — `test_api.py:51`. This is
one of the tests the mutation pass caught asserting less than its name. It now
reads:

```python
assert set(body["artifact_types"]) == set(GENERATED_TYPES)
assert set(body["source_types"]) == set(SOURCE_TYPES)
assert body["features"]["flows"] is True
```

Set equality against the constants themselves, imported at the top of the file
from `backend.models.artifacts`. The endpoint (`backend/main.py:179`) builds its
lists from `GENERATED_TYPES` and `SOURCE_TYPES`, which are derived from
`ARTIFACT_MODELS` at `backend/models/artifacts.py:137` and the literal frozenset
at line 150. So removing *any* model from that dictionary now fails here — which
is the frontend's contract, because the canvas builds its node palette from this
response. The docstring puts the stake plainly: "a short list is a missing
feature."

The old version asserted only that `"mindmap"` and `"cheatsheet"` were present.
Removing `quiz` or `slides` would have gone unnoticed here.

### `TestProjects` (line 59)

**`test_create_read_update_delete`** — `test_api.py:60`. One test walking the
full lifecycle: create, read back the name, PATCH with a new name and a canvas
state, assert the canvas round-tripped (`canvas_state.viewport.zoom == 1.5`),
delete, then confirm the read is now a 404. The canvas assertion is the one with
teeth — `canvas_state` is stored as a JSON string in SQLite and encoded and
decoded by `Database._encode`/`_decode` (`backend/services/database.py:479` and
`:496`). If a nested float were lost in that round trip, this test catches it.
The final 404 proves the delete actually removed the row rather than returning
200 and doing nothing.

**`test_empty_update_is_rejected`** — `test_api.py:75`. `PATCH` with `{}` must
be a 400. `ProjectUpdate` has all-optional fields, so an empty body validates
fine at the schema level; the guard is explicit at
`backend/api/routes/projects.py:79` (`if not changes: raise HTTPException(400)`).
Delete that guard and the route would issue an `UPDATE` with no assignments,
which `Database.update` handles by returning the unchanged row — so the caller
would get a 200 for a no-op. This test pins the 400.

**`test_another_users_project_is_not_visible`** — `test_api.py:79`. Inserts a
project with `user_id: "someone-else"` directly through the database, bypassing
the API, then asserts a GET on it is 403 *and* that its id is absent from
`GET /api/projects`. Two different mechanisms are being checked. The 403 comes
from `require_project` (`backend/api/deps.py:48`), which compares owner to
caller. The absence from the listing comes from the `WHERE user_id = ?` filter
at `backend/api/routes/projects.py:35`. The docstring says why both are here:
"Ownership is enforced on read, not only on write." A codebase that only
filtered the list would pass half of this test.

**`test_missing_project_is_a_404_not_a_500`** — `test_api.py:85`. A well-formed
but non-existent UUID must be 404. This pins the ordering inside
`require_project`: the `if not project: 404` check at `deps.py:45` has to come
*before* the `project.get("user_id") != user_id` comparison at line 48, because
`None.get` would raise an `AttributeError` and the global exception handler at
`backend/main.py:149` would turn it into a 500.

### `TestUploads` (line 89)

**`test_upload_queues_an_ingest_job`** — `test_api.py:90`. Rewritten. This was
one of the tests that asserted too little: the old version checked only for a
202 and the presence of a `job_id`, and survived the endpoint queueing a job
with an **empty** `source_ref`, which would have made every upload fail later in
the worker with no clue where the damage was done.

It now takes `idle_client` and reads the row back:

```python
job = database.get_job(response.json()["job_id"])
assert job["type"] == "ingest"
assert job["status"] == "pending"
assert job["payload"]["source_type"] == "md"
assert job["payload"]["original_name"] == "lecture.md"

staged = Path(job["payload"]["source_ref"])
assert staged.read_bytes() == uploaded
staged.unlink()
```

The last three lines are the ones with teeth. `source_ref` is followed to the
staged file on disk and the bytes are compared against what was posted. That
pins the whole buffered-upload path in `_buffer_upload`
(`backend/api/routes/projects.py:192`): chunked read, temp file, and the path of
that temp file written into the job payload.

It needs `idle_client` for two reasons, both in the docstring. A live worker
could claim the job and change its status out from under the
`status == "pending"` assertion, and — worse — the ingest handler's last act is
to delete the staged file, so the file this test reads might not be there. With
no workers running, "Nothing runs that handler here, so the staged copy it would
have deleted is this test's to remove", which is what the final `unlink()` is
for.

**`test_unknown_source_type_is_rejected`** — `test_api.py:121`. `source_type:
"executable"` must be a 400. The guard is at
`backend/api/routes/projects.py:139`, checking against
`UPLOADABLE_SOURCE_TYPES`, which is `SOURCE_TYPES` minus `"youtube"`
(`projects.py:26`). Note this check happens *before* `_buffer_upload` is called,
so a rejected upload never touches the disk.

**`test_empty_upload_is_rejected`** — `test_api.py:130`. A zero-byte file must be
400.

**`test_oversized_upload_is_rejected`** — `test_api.py:139`. Sets
`MAX_FILE_SIZE_MB=1`, clears the settings cache by hand, then posts 2 MB and
expects 413. The reason it has to clear the cache mid-test is the `lru_cache` on
`get_settings`; the settings snapshot was already built when the app started.
The meaningful thing this pins is that the limit is enforced *while streaming*
(`written > limit` inside the read loop at `projects.py:207`), not after the
whole file has landed. If someone moved the check to after the loop, a 10 GB
upload would be fully written to disk before being rejected. This test would
still pass — it only checks the status code — so be honest about that if asked.

> **Worth knowing.** This test proves the limit is enforced. It does not prove
> it is enforced incrementally. The complementary cap on the *download* side is
> asserted properly, at `test_api.py:847`.

### `TestJobs` (line 154)

**`test_create_and_read_a_generate_job`** — `test_api.py:155`. Also rewritten.
The old version checked the 202 and the job's type, and survived the endpoint
hard-coding `"pending"` as the status of every job it was asked about. It now
takes `idle_client` and asserts on the whole round trip:

```python
assert body["id"] == job_id
assert body["project_id"] == project["id"]
assert body["type"] == "generate"
assert body["status"] == "pending"
assert body["payload"] == payload

database.claim_job(job_id)
assert idle_client.get(f"/api/jobs/{job_id}").json()["status"] == "running"
```

The last two lines are the fix for the surviving mutation. The test claims the
job directly through the database — which is what a worker does — and reads the
endpoint again. A hard-coded `"pending"` now fails on the second read. The
docstring names the consumer: "The browser polls this endpoint to decide whether
a node is still spinning."

**`test_a_generate_request_naming_no_source_is_refused`** — `test_api.py:184`.
New. Posts a generate payload with a `target_type` and no sources at all, and
expects a 400 containing `"at least one artifact"`, plus no job row. The guard
is the model validator `GenerateRequest.at_least_one_source` at
`backend/api/schemas.py:79`. Deleting it survived the old suite entirely: the
job would queue, the worker would call `SourceResolver.resolve([])`, and the
generator would be handed no material. The docstring is the one-liner:
"Generation reads from the graph, so a request naming nothing is not work."

**`test_an_unknown_ingest_source_type_is_refused`** — `test_api.py:194`. New,
and a nice illustration of two doors onto one rule. `POST /api/jobs` builds an
`IngestRequest` from the raw payload and never inspects the source type itself,
so the only thing between a made-up type and a queued job is the field validator
`IngestRequest.known_source` at `backend/api/schemas.py:42`. The upload route
has its own separate check, tested at `test_api.py:121`. Deleting the schema
validator survived, because the only test that exercised source types went
through the upload route. Asserts a 400 with `"source_type must be one of"` and
no job row.

**`test_invalid_target_type_is_a_400_with_a_useful_message`** — `test_api.py:216`.
`target_type: "horoscope"` must be a 400 whose detail contains
`"target_type must be one of"`. The validator lives on the schema
(`backend/api/schemas.py:71`) and raises a `ValueError`, which the route catches
at `backend/api/routes/jobs.py:55` and re-raises as a 400 with the message
embedded. Asserting on the message text matters: FastAPI's default for a schema
failure is a 422 with a nested error structure the frontend does not render, so
the explicit catch is what turns it into something a user can read.

**`test_identical_in_flight_requests_are_deduplicated`** — `test_api.py:225`.
Posts the same payload twice and asserts the second response has `reused: True`,
the *same* job id, and — new — that the project holds exactly one job row. This
pins `_find_in_flight_duplicate` (`backend/api/routes/jobs.py:160`), which is
what stops a double-clicked "Generate" button from spending two lots of tokens.
Break the source-set comparison at `jobs.py:188` and the second request creates
a new job, so both the id assertion and the count assertion fail.

The test now takes `idle_client` and asserts its own precondition explicitly:

```python
first = idle_client.post("/api/jobs", json=payload).json()
assert database.get_job(first["job_id"])["status"] == "pending"
```

That middle line is the whole story of section 1's "green by scheduling luck".
Without it, and with a live worker pool, the first job could finish between the
two posts and the second request would legitimately not be a duplicate. The test
would then fail for a reason that has nothing to do with deduplication. The
docstring says it: the first job "is pending because nothing can claim it, not
because nothing happened to."

**`test_a_completed_job_is_never_handed_back_to_a_later_request`** —
`test_api.py:251`. New, and the negative case that was missing. Inserts a
`completed` generate job with a given payload, then posts the identical payload
and asserts three things: the response is a 202 with `reused: False`, the job id
is different from the finished one, and the project now holds two job rows.

Widening `IN_FLIGHT` at `backend/api/routes/jobs.py:34` to include `"completed"`
— which is the original bug — fails all three. The docstring records the
user-visible symptom rather than the mechanism, which is the right way round:
"Counting finished jobs as duplicates made the button look broken: the API
answered with the previous artifact's job, nothing ran, and the canvas never
changed."

Read this one and `test_identical_in_flight_requests_are_deduplicated` as a
pair. One says "merge concurrent duplicates", the other says "and only
concurrent ones". Neither is sufficient alone; a system that merged nothing
would pass the second, and a system that merged everything would pass the first.

**`test_steered_requests_are_never_deduplicated`** — `test_api.py:279`. Same
source, same target, different `instructions` ("harder" versus "easier"). These
must be two different jobs. The guard is the early return at
`backend/api/routes/jobs.py:172` (`if payload.instructions: return None`). If
someone "improved" the dedup key by ignoring instructions, a user asking for an
easier quiz would silently be handed the harder one that was already running.
This test is the reason that cannot happen. It is the third leg of the same
stool.

**`test_a_job_in_another_users_project_is_hidden`** — `test_api.py:292`. A job in
a foreign project must be 403 on read. The route looks the job up first, then
calls `require_project` on the job's project id
(`backend/api/routes/jobs.py:118`). Remove that line and any job id would be
readable by anyone who guessed it.

**`test_cancelling_a_finished_job_conflicts`** — `test_api.py:299`. Cancelling a
`completed` job must be 409, not 200 and not 500. `Database.cancel_job`
(`backend/services/database.py:374`) returns `False` for terminal statuses and
the route turns that into a 409 at `jobs.py:136`. The distinction matters to the
frontend, which uses the status code to decide whether to remove the cancel
button or show an error.

### `TestFlows` (line 306)

The shared `graph` helper at lines 307-321 builds one canvas used by several
tests: a source node `s1` holding the knowledge core, three generator nodes, and
edges `s1→g1`, `s1→g2`, `g2→g3`. Two waves: `g1` and `g2` can start immediately,
`g3` has to wait for `g2`.

**`test_validate_returns_the_plan_without_running_anything`** — `test_api.py:323`.
Asserts `valid: True`, three steps, two waves, and — the important line —
`database.select("jobs", ...) == []`. Validate must be a pure compile. If
somebody wired `validate_flow` to `FlowEngine.start` instead of
`FlowCompiler().compile`, the first three assertions would still pass and only
the empty-jobs assertion would catch it.

**`test_validate_explains_why_a_bad_graph_will_not_run`** — `test_api.py:333`.
Adds `g3→g2` on top of the existing `g2→g3`, creating a cycle, and asserts
`valid: False` with `"cycle"` in the error. Note the status code is still 200 —
validate answers the question "will this run?", and "no" is a successful answer.
The 4xx path is the *run* endpoint's job, which is the next test but one.

**`test_run_dispatches_the_first_wave_only`** — `test_api.py:341`. Posts the same
graph to `/flow/run`, expects 202, and then checks the node states: `g1` and
`g2` are `running`, `g3` is `pending`, with the assertion message "g3 depends on
g2 and must wait". This is the wave scheduling visible from the outside. If
`FlowEngine._schedule` dropped its `_inputs_ready` check
(`backend/services/flow/engine.py:139`), `g3` would be dispatched immediately
with no source artifacts and the test fails on the third assertion.

**`test_run_rejects_an_invalid_graph_with_422`** — `test_api.py:352`. An empty
graph (`{"nodes": [], "edges": []}`) must be 422. Careful reading of the route:
`nodes` is `[]`, not `None`, so `_graph` (`backend/api/routes/flows.py:21`)
returns the empty list rather than falling back to the saved canvas, the
compiler raises `FlowValidationError`, and `run_flow` converts it to a 422 at
`backend/api/routes/flows.py:107`.

**`test_run_falls_back_to_the_saved_canvas`** — `test_api.py:356`. Writes a
canvas into `projects.canvas_state`, then posts `{}` — no nodes, no edges. The
run must use the stored canvas, and the response must have four node states
(three generators plus the seed node). This pins the `if request.nodes is not
None` branch in `_graph` (`flows.py:28`). It is also the setup that the security
test at `test_api.py:542` reuses, for a different reason.

### `TestWebSocket` (line 366)

**`test_snapshot_is_sent_on_connect`** — `test_api.py:367`. Strengthened. It
inserts a `running` job **and** a `running` flow run, connects, and asserts the
first frame is a `snapshot` containing both:

```python
assert [entry["id"] for entry in frame["data"]["jobs"]] == [job["id"]]
assert [entry["id"] for entry in frame["data"]["flow_runs"]] == [flow_run["id"]]
assert frame["data"]["flow_runs"][0]["node_states"] == {"g1": {"status": "running"}}
```

The old version asserted only on the jobs list, and survived `flow_runs` being
emptied out of `_snapshot` entirely. The docstring explains what that costs: "A
client that reconnects gets no replay of the events it missed, so a flow left
out of the snapshot renders as a canvas with nothing running on it while the run
is still going."

The third assertion goes one level deeper and checks `node_states` came through
intact, because a snapshot that lists the run but not which nodes are live is
almost as useless as no snapshot. The snapshot is built in `_snapshot`
(`backend/api/routes/ws.py:125`) and sent before the forwarding tasks start
(`ws.py:55-57`), which is the ordering this test also pins: if the snapshot were
sent after subscribing, a live event could arrive first and the client would
apply an update to state it had not yet received.

**`test_events_reach_a_connected_client`** — `test_api.py:393`. Connects, drains
the snapshot, then calls `publish(...)` directly from the test thread and
expects the frame to arrive on the socket. This is the cross-thread hop in
`InProcessEventBus.publish` (`backend/services/events.py:81`): the test thread
is not the loop thread, so delivery goes through `loop.call_soon_threadsafe`.
That path exists because in production the publisher is a worker thread, not the
request handler. If someone simplified `publish` to call `_deliver`
(`events.py:119`) directly, this test would hang and then fail on the socket
read.

**`test_resync_returns_a_fresh_snapshot`** — `test_api.py:404`. Sends
`{"type": "resync"}` and expects another snapshot. This pins `_read_client`
(`backend/api/routes/ws.py:93`), which exists both to let a laptop waking from
sleep re-sync and to make a dropped connection detectable at all.

**`test_a_foreign_project_socket_is_refused`** — `test_api.py:410`. Connecting to
another user's project must raise `WebSocketDisconnect` with code **4403**. The
specific code matters: `ws.py:43-49` maps a 403 from `require_project` to
`CLOSE_FORBIDDEN = 4403` (`ws.py:24`) and anything else to
`CLOSE_UNAUTHORIZED = 4401`, and the frontend uses the code to decide whether to
retry. A retry loop against a project you will never be allowed to see is a hot
loop. Note also that the check at `ws.py:43` happens *before*
`websocket.accept()` at line 49, which is the correct order — accepting and then
closing leaks a handshake.

> **Worth knowing.** The `?token=mock-token` in all four WebSocket tests is
> decorative. `resolve_user` (`backend/api/deps.py:14`) ignores its argument
> entirely and returns `LOCAL_USER_ID`. This deployment has no identity
> provider; every caller is the single local workspace owner. Say that plainly
> if asked — the design point is that ownership is still *recorded* and
> *checked* on every read, so adding real authentication means replacing one
> function rather than auditing every route. The 4401 branch is consequently
> never exercised by any test.

### `TestSecurity` (line 420)

This class is the record of five holes that were open and are now closed. The
class docstring at lines 421-428 names all five, and each has at least one test.
It is worth being able to state the general principle before walking through
them: **anything that arrives in a request body is caller-controlled, including
ids that look like internal plumbing.**

All five of these regression tests survived the mutation pass — reverting any of
the five fixes fails the corresponding test. That is the part to say if asked
whether the security tests are real.

The helper at lines 430-440:

```python
@staticmethod
def foreign_artifact(database, artifact_type="knowledge_core"):
    foreign = database.insert("projects", {"name": "Theirs", "user_id": "someone-else"})[0]
    return database.insert("artifacts", {...})[0]
```

It writes straight to the database rather than through the API, because the API
would not let the test caller create a project owned by somebody else. This is
the standard way to set up an ownership test: build the state you could not
reach legitimately, then prove the API refuses to reach it.

#### Hole 1 — source-artifact ownership on `create_job`

**`test_a_generate_source_from_another_users_project_is_refused`** —
`test_api.py:442`. Posts a normal generate job to a project the caller *does*
own, but names a `source_artifact_id` belonging to a project owned by
`"someone-else"`. Asserts 403 **and** that no job row was created.

The docstring is the one-line summary of the whole hole: "Owning the destination
is not permission to read the source." The fix is the loop at
`backend/api/routes/jobs.py:57`:

```python
for artifact_id in _source_ids(payload):
    require_project_artifact(artifact_id, request.project_id, user_id, database)
```

Without it, the job would be queued, a worker would pick it up,
`SourceResolver.resolve` would happily fetch the row by id — the resolver has no
notion of ownership, and deliberately so, because it runs inside a worker with
no request context — and the generated artifact would be committed into the
caller's own project. That is a complete read of somebody else's material.

The second assertion, `database.select("jobs", ...) == []`, is what makes this a
real test rather than a status-code test. A version of the fix that queued the
job and then rejected it would still return 403 and would still leak, because
the worker would already have the row.

**`test_a_refine_source_from_another_users_project_is_refused`** —
`test_api.py:455`. The same attack through the refine door. It exists because
`_source_ids` (`backend/api/routes/jobs.py:142`) has to handle three payload
shapes: `GenerateRequest.sources()`, `RefineRequest.source_artifact_id`, and
ingest (which reads no artifacts, so an empty list). A fix that only covered
generate would pass the previous test and fail this one. Note the foreign
artifact here is of type `"notes"` rather than a core, because refine operates
on generated artifacts.

**`test_a_source_in_another_project_of_the_callers_own_is_refused`** —
`test_api.py:467`. New. This one is the third branch of
`require_project_artifact`, and it is subtler than the other two because nothing
is stolen: the caller owns *both* projects.

The setup inserts a second project owned by `LOCAL_USER_ID`, puts a knowledge
core in it, and then posts a generate job in the *first* project naming that
core. The expected answer is a **400**, not a 403, with `"different project"` in
the detail, and no job row.

Deleting the project-membership check at `backend/api/deps.py:84` survived the
old suite, because every previous test aimed at an artifact the caller did not
own, and `require_artifact` catches those a step earlier. The reason it is worth
a check at all is in the docstring: "Provenance edges are filed under a single
project, so a job in one project reading a parent that lives in another would
commit an edge pointing at an artifact this canvas cannot show." A dangling
lineage arrow, not a leak — but a permanently broken graph.

Note that the three status codes here form a deliberate ladder: 404 when the
artifact does not exist, 403 when it exists and is not yours, 400 when it is
yours but is in the wrong place. Each is answered by a different line of
`deps.py` (64, 49, 85).

**`test_a_source_that_does_not_exist_is_refused_before_the_job_is_queued`** —
`test_api.py:495`. Names an all-zeros UUID and expects **404**, again with no
job row. The docstring explains the value: "An unreadable source is a bad
request, not a job that fails later." Without the check, this request would be
accepted with a 202, the user would watch a spinner, and a minute later a job
would fail with a message about missing sources.

#### Hole 5 — the `/flow/run` door into the same place

These three are the newest of the original five, and the class docstring calls
the flow route "another door" into hole 1. This is the one to lead with if you
get to pick, because it shows a fix being tested for *completeness* rather than
just for the one path that was reported.

The `seeded_graph` helper at lines 511-520 builds the minimal canvas: one source
node naming an artifact by id, one generator node, one edge.

**`test_a_flow_seeded_with_another_users_artifact_is_refused`** —
`test_api.py:522`. Posts that canvas, with a stolen artifact id in the source
node, to `/api/projects/{mine}/flow/run`. It asserts four things:

```python
assert response.status_code == 403, response.text
assert "s1" in response.json()["detail"]
assert database.select("jobs", [("project_id", f"eq.{project['id']}")]) == []
assert database.select("flow_runs", [("project_id", f"eq.{project['id']}")]) == []
```

The chain the docstring describes is worth being able to recite: nodes come from
the request body, `FlowCompiler._classify` lifts each source node's
`data.artifact.id` into `plan.seed_artifacts`
(`backend/services/flow/plan.py:141`), `FlowEngine.start` copies those ids into
`states[...]["artifact_id"]` (`engine.py:84`), `_input_artifacts`
(`engine.py:283`) collects them, and `_queue_job` writes them straight into a
generate job's `source_artifact_ids` (`engine.py:262`). At no point does
anything check who owns them. So a caller who could not name a foreign artifact
in a job payload could name it in a canvas node and reach exactly the same code.

The fix is `_require_owned_seeds` at `backend/api/routes/flows.py:35`, called
after compilation and before `FlowEngine(database).start(...)`. Two design
choices in it are pinned by the assertions:

- It re-raises with the node id in the detail (`flows.py:56`), which is why
  `"s1" in response.json()["detail"]` is asserted. The canvas needs to highlight
  the offending node.
- It fails the whole request rather than dropping the bad node. The docstring
  says why: "a flow that quietly ran without one of its inputs is worse than one
  that refused."

The `flow_runs` assertion is the strict one. It proves the refusal happens
before `FlowEngine.start` writes its row, not after.

**`test_a_saved_canvas_cannot_smuggle_a_foreign_seed_into_a_run`** —
`test_api.py:542`. The same stolen id, but written into `projects.canvas_state`
first and then run with an empty body so the fallback path is used. The
docstring is the reason it exists: "Running with no body uses the stored canvas,
which is equally caller-written." A canvas is saved by a `PATCH /api/projects`
call from the browser, so it is request data that has merely been round-tripped
through the database. A fix that validated `request.nodes` instead of validating
`plan.seed_artifacts` would pass the previous test and fail this one. Because
`_require_owned_seeds` operates on the compiled plan, both doors land on it.

**`test_validating_a_foreign_seed_is_refused_the_same_way`** — `test_api.py:554`.
The third door: `/flow/validate`. It expects 403, not a `valid: false` response.
The docstring: "Validate compiles the same graph, so it must not report the flow
as runnable." This one is subtle and is a good thing to be able to explain.
Validate does not run anything, so it does not directly leak an artifact — but
if it reported `valid: true`, it would confirm to the caller that the artifact
exists and is usable, which is an oracle. And a UI that trusted validate would
present a Run button for a flow that cannot run. So the check goes in both
routes.

#### Hole 3 — NULL-owner project reads

**`test_a_project_with_no_owner_belongs_to_nobody`** — `test_api.py:564`.
Inserts a project with `user_id: None` — the column is nullable
(`backend/services/database.py:39`) — then asserts that a GET on it is 403 and
that it is absent from the listing.

The docstring records the shape of the bug precisely: "Read said yes while list
said no, because the listing filters on the caller's id and a NULL never matches
it." The listing was always correct, because SQL `WHERE user_id = 'local-user'`
never matches NULL. The read path was the broken one — the check was presumably
written to skip the comparison when the owner was falsy, which is a natural way
to write "unowned projects are public" and a terrible default. The current form
at `backend/api/deps.py:48` is a plain inequality:

```python
if project.get("user_id") != user_id:
    raise HTTPException(status_code=403, detail="Access denied")
```

`None != "local-user"` is true, so the request is refused. Change it to
`if project.get("user_id") and project["user_id"] != user_id` and this test
fails on line 573.

The reason NULL owners exist at all is migration history: rows created before
ownership was recorded, or by a script that omitted the field. A test that
inserts one directly is the honest way to cover that.

**`test_an_unowned_projects_artifacts_are_not_readable`** — `test_api.py:576`.
The same orphan project, but reaching for an artifact inside it. Asserts 403.
This covers `require_artifact` (`backend/api/deps.py:54`), which finds the
artifact and then delegates to `require_project` on its project id at line 66.
The delegation is the whole point: ownership is a property of the project and
every artifact check must go through the project check, so a single fix in
`require_project` closes both.

#### Hole 4 — `update_artifact` rewriting `content.binary.storage_path`

The helper `exported_artifact` at lines 584-597 sets up the scenario: two files
in the store, and an artifact whose `content.binary.storage_path` points at the
first one.

**`test_an_edit_cannot_repoint_an_export_at_another_file`** — `test_api.py:599`.
PATCHes the artifact with a body that supplies both a new `data.title` and a
`binary` block pointing at the *other* file. It asserts:

```python
assert response.status_code == 200, response.text
assert response.json()["content"]["binary"]["storage_path"] == mine
assert response.json()["content"]["data"]["title"] == "Edited"
```

then re-reads the row from the database to confirm the response was not merely
cosmetic, then follows the download link and asserts the bytes are
`b"the real export"`.

Three things are being pinned at once, and this is the test to walk through
slowly:

1. **The request succeeds.** It is a 200, not a 400. The user's legitimate edit
   to `data.title` is applied. Rejecting the whole request would be a worse
   design, because clients routinely send back the whole content object they
   were given, `binary` included, without intending anything by it.
2. **The `binary` block is ignored.** The mechanism is four lines at
   `backend/api/routes/artifacts.py:77`:

   ```python
   merged = {**existing, **updates.content, "edited_by_user": True}
   merged.pop("binary", None)
   if "binary" in existing:
       merged["binary"] = existing["binary"]
   ```

   Merge everything, then unconditionally discard whatever `binary` came out of
   that merge, then restore the stored one if there was one. The order is what
   makes it safe: popping after merging means the caller's value can never
   survive, whatever key ordering the merge produced.
3. **The consequence is real.** The final two lines of the test follow the
   actual download and check the bytes, because the reason this matters is
   `download_artifact` (`backend/api/routes/artifacts.py:91`): it reads
   `export.get("storage_path")` at line 105 and hands it to
   `store.signed_url(key, ...)` at line 113. The signature is computed over
   whatever key it is given. So a caller who could write `storage_path` could
   have the server mint a valid, signed link to any file in the store. The
   docstring puts it exactly: "The export block names a storage key, so writing
   it is writing a capability."

**`test_an_edit_cannot_attach_an_export_where_there_was_none`** —
`test_api.py:630`. The complementary case. A notes artifact with no `binary` at
all; the caller sends one. Asserts 200, that `"binary" not in
response.json()["content"]`, and that the download endpoint now returns 404.

This is the case the naive fix misses. If you wrote the guard as "if the caller
sent a `binary`, replace it with the stored one", an artifact with no stored one
would keep the caller's. The `merged.pop` runs unconditionally, which is why
this passes. Without the `pop`, the first assertion fails and the caller has
attached a download link to a file they were never given.

#### Hole 2 — a `youtube` source carrying a filesystem path

**`test_a_youtube_source_pointing_at_the_filesystem_is_refused`** —
`test_api.py:648`. Posts an ingest job with `source_type: "youtube"` and
`source_ref: "/etc/passwd"`. Asserts 400, that the detail contains
`"http(s) URL"`, and that no job row was created.

The docstring is the explanation: "Given a bare path yt-dlp reads the local
file, so the path never reaches it." That is genuinely how `yt-dlp` behaves —
it accepts local paths as inputs. So an ingest job with a `youtube` source type
and a path would have the downloader read the file, the extraction pipeline
transcribe or parse it, and the knowledge core end up containing its contents,
readable in the caller's own project. Arbitrary file read, dressed as a feature.

The guard is a Pydantic model validator at `backend/api/schemas.py:47`:

```python
if self.source_type == "youtube" and not self.source_ref.startswith(("http://", "https://")):
    raise ValueError("source_ref must be an http(s) URL for a youtube source")
```

Putting it on the schema rather than in the route means it applies wherever an
`IngestRequest` is constructed. The route catches the `ValueError` and returns a
400 with the message (`backend/api/routes/jobs.py:55`), which is why the test
can assert on the text.

**`test_a_youtube_ref_that_is_not_an_http_url_is_refused`** — `test_api.py:670`,
four parameters. New, and the generalisation of the test above. It constructs
`IngestRequest` directly and expects a `ValidationError` for each of
`"file:///etc/passwd"`, `"//evil.com/lecture"`, `"ftp://evil.com/lecture.mp4"`
and `"../../etc/passwd"`.

The docstring is the reasoning: "A scheme yt-dlp does not fetch over the network
it reads locally, and a relative path is a local read with the leading slash
filed off." The absolute path in the previous test is one shape of the bug; a
guard written as `if source_ref.startswith("/")` would pass that test and fail
all four of these.

**`test_a_youtube_url_still_validates`** — `test_api.py:684`. Constructs an
`IngestRequest` with a real YouTube URL and asserts it survives. The docstring:
"The guard rejects those without also rejecting the legitimate case."

> **Worth knowing, and still true.** The assertion itself —
> `request.source_ref == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"` — is
> tautological, since the test passed that exact string in. The real assertion
> is implicit: that constructing the model does not raise. If the validator were
> tightened to, say, require a `youtube.com/watch` path, the constructor would
> raise and the test would error out before reaching the assert line. So it does
> its job, but the meaningful failure is an exception, not an assertion failure.
> It matters more now than it did, because there are five negative cases either
> side of it and a "reject everything" mutation has to fail *somewhere*.

### `TestArtifactEditing` (line 697)

**`test_an_edit_merges_into_the_stored_content_rather_than_replacing_it`** —
`test_api.py:698`. New. A single test, and the one that closes the surviving
mutation on `update_artifact`.

The `binary` guard tested above is one half of that route's contract; this is
the other half, which was documented in the route's own docstring
(`backend/api/routes/artifacts.py:66`) and pinned by nothing. Changing the merge
at line 77 from `{**existing, **updates.content, ...}` to
`{**updates.content, ...}` — a replace rather than a merge — survived the whole
old suite.

The test inserts a quiz artifact whose content carries four fields the editor
never shows: `kind`, `target_type`, `instructions` and `refined_from`. It then
PATCHes with only `data`, and asserts all four survived, that `data.title`
changed, that `edited_by_user` is now `True`, and that the database row matches
the response exactly.

The docstring is the sentence to remember: "The editor sends the field it
changed, not the whole record... A replacing write loses the lot on the first
keystroke saved." Losing `refined_from` means losing a revision's link to its
parent; losing `instructions` means an artifact that claims to be unsteered when
it was not.

### `TestYouTubeIngestGuard` (line 747)

New class, ten test functions, eighteen cases. This is the largest single
addition to `test_api.py` and it covers a guard that lives in the pipeline
rather than in a route.

The class docstring states the vulnerability rather than the fix, which is the
right way round:

> `source_type: "youtube"` only ever named the field. yt-dlp handed anything it
> did not recognise to its generic extractor, downloaded the response whatever
> it was, and the pipeline stored it, read text out of it and committed it as an
> artifact the caller owns and can read back: a full-response SSRF reaching
> cloud instance metadata, localhost and this API's own routes.

Note the phrase "full-response": this is not a blind SSRF where you infer
something from timing. The response body is parsed into a knowledge core and
handed back to the caller through the normal artifact-reading endpoints.

`StubResolver` at lines 737-744 is a two-line fake DNS resolver, and the `guard`
helper at lines 759-763 builds a `YouTubeUrlGuard` with it. That is the
injection seam that makes this class fast and offline: `YouTubeUrlGuard.__init__`
(`backend/pipeline/ingestion.py:100`) takes an optional `resolver`, and the real
one calls `socket.getaddrinfo`. Passing no answers at all leaves the real
resolver in place, which is fine for the tests that never get as far as
resolution.

**`test_an_internal_address_is_refused`** — `test_api.py:769`, two parameters:
`http://169.254.169.254/latest/meta-data/iam/security-credentials/admin` and
`http://[fd00::1]/admin`. The docstring calls the first one "the proof: the
address the exploit reached for is not a YouTube host." That address is the AWS
and GCP instance-metadata endpoint, and the path is the one that returns IAM
credentials. The second is a private IPv6 address in bracket notation, which is
there because the host parsing has to handle it.

**`test_a_loopback_url_is_refused`** — `test_api.py:780`, two parameters:
`http://localhost:8000/api/projects` and `http://127.0.0.1/latest/meta-data/`.
The first is this API talking to itself, which is the case people forget.

Both of the above are refused by the host check at
`backend/pipeline/ingestion.py:107`, not by the address check — `localhost` is
not a YouTube host, so it never gets as far as resolving.

**`test_a_host_that_only_looks_like_youtube_is_refused`** — `test_api.py:792`,
four parameters, matching on `"not a YouTube host"`. The docstring is five
words: "A suffix match, never a substring one." The four cases are
`https://youtube.com.evil.tld/watch?v=1`, `https://notyoutube.com/watch?v=1`,
`https://evil.tld/youtube.com` and `https://youtu.be.evil.tld/1`. Each of them
defeats a different naive implementation:

- `youtube.com.evil.tld` defeats `"youtube.com" in host`.
- `notyoutube.com` defeats `host.endswith("youtube.com")`.
- `evil.tld/youtube.com` defeats `"youtube.com" in url`.
- `youtu.be.evil.tld` is the same trick against the short domain.

The real check is at `ingestion.py:107` against `ALLOWED_HOSTS`
(`ingestion.py:89`) and requires equality or a proper subdomain.

**`test_a_youtube_host_resolving_inward_is_refused`** — `test_api.py:799`.
Passes a genuine `https://www.youtube.com/watch?v=...` URL but a stub resolver
that answers `10.0.0.5`, and expects `"not on the public internet"`. The
docstring: "An allowed name is not an allowed destination." This is DNS
rebinding, stated as a property rather than as an exploit: a name you allow can
point wherever its owner — or an attacker with a DNS record — says it does.

**`test_one_internal_answer_among_several_is_enough_to_refuse`** —
`test_api.py:806`. The resolver answers with two addresses, `142.250.72.14`
(a real, public Google address) and `127.0.0.1`. The guard must refuse. This is
the `for` loop at `ingestion.py:113` needing to check *every* answer rather than
the first one, which is the mutation that a single-address test would not catch.

**`test_a_genuine_youtube_url_passes`** — `test_api.py:818`, four parameters:
`www.youtube.com`, bare `youtube.com`, `youtu.be` and `music.youtube.com`, all
with a public stub answer. Asserts `check(url) is None`. The docstring: "The
guard closes the hole without closing the feature." Without this the whole class
would be satisfied by a guard that refused everything.

**`test_the_downloader_never_sees_a_refused_url`** — `test_api.py:822`. The
ordering test, and the cleverest one in the class. It monkeypatches
`ingestion.yt_dlp.YoutubeDL` to a function that raises `AssertionError("yt-dlp
was handed a URL the guard refused")`, then calls
`IngestionService().store_youtube` with the metadata URL and expects
`UnsafeSourceError`.

If the guard ran after the downloader was constructed, the `AssertionError`
would surface instead of the `UnsafeSourceError` and the test fails with a
message that says exactly what went wrong. The docstring: "The guard runs before
yt-dlp is constructed, not after it has fetched." A check that happens after the
request has already gone out is not a check.

**`test_a_refusal_is_a_permanent_failure`** — `test_api.py:837`. Takes the
`UnsafeSourceError` the guard raises and asserts `is_transient(...) is False`.
This is a cross-module test and a good one to point at: a refusal that
classified as transient would be retried up to `JOB_MAX_ATTEMPTS` times, so the
server would make the forbidden request three times instead of once, and the
logs would fill with it. It couples the guard to the retry classifier
(`backend/services/job_runner.py:57`) so that neither can be changed in
isolation.

**`test_a_download_is_capped_at_the_upload_limit`** — `test_api.py:847`. Sets
`MAX_FILE_SIZE_MB=7`, substitutes a `CapturingDownloader` that records the
options dictionary it was constructed with and then raises, and asserts
`options["max_filesize"] == 7 * 1024 * 1024`.

The docstring is the point: "The upload cap covers both ways into the file
store, not just one." An upload is capped while streaming (tested at
`test_api.py:139`); a YouTube fetch is a second door into the same store and had
no cap at all, so `yt-dlp` would write whatever the far end sent. Note that this
test asserts the option is *passed*, not that it is *enforced* — enforcement is
`yt-dlp`'s business. That is a reasonable boundary, and worth saying out loud
rather than overclaiming.

**`test_an_upload_declaring_a_youtube_source_is_refused`** — `test_api.py:877`.
The last door. Posts a Markdown file to the upload endpoint with
`source_type: "youtube"` and expects a 400 with no job row. It also asserts
`"youtube" not in response.json()["detail"]`, which reads oddly until you see
why: the error lists the *acceptable* types, and `youtube` must not be among
them.

The docstring records the original hole in full: "The route checked membership
of `SOURCE_TYPES`, which contains 'youtube', then wrote the payload by hand: the
job it queued named a path in this server's temp directory as a URL to
download." Two fixes closed it, and both are visible in the route.
`UPLOADABLE_SOURCE_TYPES` at `backend/api/routes/projects.py:26` is
`SOURCE_TYPES - {"youtube"}`, and `_ingest_payload` at `projects.py:171` now
builds the payload through `IngestRequest` rather than by hand — so the same
model that guards `POST /api/jobs` guards this route too. That docstring is
worth reading in the code: "Sharing the model makes the invariant structural
rather than something two routes have to remember separately."

### `TestStartupGuard` (line 898)

New class, three test functions, five cases. The subject is what the API refuses
to boot with.

The class docstring states the problem: a download link is unforgeable only
while its HMAC key is private, and this repository publishes two candidate keys
— the old default in `config.py` and `change-me-in-production` in `.env.example`
and `docker-compose.yml`. With either in place, anybody who has read the project
on GitHub can mint a valid link for any object in the store with no session at
all.

The `settings_with` helper at lines 909-915 uses `dataclasses.replace` to build
a `Settings` object with one field changed. `Settings` is a frozen dataclass
(`backend/core/config.py:114`), so this is the supported way to do it, and it
means the tests never touch the environment or the cache.

**`test_a_published_signing_secret_refuses_to_boot`** — `test_api.py:918`, three
parameters: `""`, `"beeprepared-dev-secret"` and `"change-me-in-production"`.
Each must make `require_unforgeable_links` (`backend/main.py:41`) raise a
`RuntimeError` matching `"SIGNING_SECRET"`. The empty string is in the list
because an unset key is as forgeable as a published one — the HMAC still
computes, it is just computed over a key everyone knows.

**`test_a_private_signing_secret_boots`** — `test_api.py:924`. The negative
control: a private value returns `None`. Without it the guard could be
`raise RuntimeError` unconditionally.

**`test_a_published_default_is_replaced_by_a_minted_one`** — `test_api.py:929`.
The most interesting of the three, because it pins a design decision rather than
a check.

Refusing `change-me-in-production` outright would break `docker compose up` on a
fresh clone, which is the documented way to start the stack. So `get_settings`
does not refuse it — it *replaces* it. `_signing_secret` at
`backend/core/config.py:94` treats a published value as equivalent to no value
and falls through to `LocalSigningSecret.read_or_create()` (`config.py:68`),
which mints 32 random bytes and persists them next to the data they protect.

The test sets `SIGNING_SECRET=change-me-in-production` and `BEE_DATA_DIR` to a
fresh directory, clears the cache, and asserts:

```python
minted = get_settings().signing_secret
assert minted and minted not in PUBLISHED_SECRETS

get_settings.cache_clear()
assert get_settings().signing_secret == minted
```

The second half is the part that matters and is easy to miss. Clearing the cache
and reading again simulates a process restart. The key must be the *same*,
because otherwise every download link outstanding at the moment of a restart
would stop verifying. That is what the file on disk is for, and `_create` at
`config.py:78` opens it with `O_EXCL` so that two processes starting at once
cannot each install a different key.

Read this class together with `conftest.py:55`. The suite sets
`SIGNING_SECRET=test-secret`, which is private as far as the guard is concerned,
which is why every `client` fixture boots.

### `TestFileServing` (line 951)

**`test_a_signed_link_serves_the_file`** — `test_api.py:952`. Writes bytes into
the store, mints a signed URL, and fetches it through the client. This is the
full loop: `FileStore.signed_url` (`backend/services/files.py:93`) produces a
relative path with `expires` and `signature` query parameters, and `serve_file`
(`backend/api/routes/files.py:18`) verifies them before returning a
`FileResponse`. It proves the signature produced by the store is the one the
route accepts — which only works because both sides read the same
`SIGNING_SECRET`, which is why `conftest.py:55` pins it.

**`test_a_tampered_signature_is_refused`** — `test_api.py:963`. Corrupts the
signature by prefixing an `x` and expects 403. The verification uses
`hmac.compare_digest` (`backend/services/files.py:117`), which is
constant-time. This test would pass against a plain `==` comparison too, so it
is pinning the refusal, not the timing safety.

**`test_path_traversal_is_refused`** — `test_api.py:973`. Calls
`put_bytes(b"pwn", "../../etc/passwd")` and expects `StorageError`. The guard is
`FileStore.resolve` (`backend/services/files.py:75`), which resolves the path
and checks `is_relative_to(self.root)` at line 82. Every read and write goes
through `resolve`, which is why one check covers the whole class. The same guard
is tested from the other side at `test_seams.py:428`; here it is being checked
at the store's write entry point, there at its resolve entry point.

---

## 5. `test_pipeline.py` — the pipeline end to end

758 lines, 38 test functions, 59 cases, ten classes. This file runs handlers,
the job runner and the database for real, with only the model swapped out by
configuration. If someone asks "what does your test suite actually prove?", this
is the file to point at.

It grew the most in the rewrite: four entirely new classes, and it is where the
two failed regression tests from section 1 are now covered.

### The helpers at the top

```python
def queue(database, project_id, job_type, payload) -> JobModel:
    """Insert a job and claim it, the way a worker would."""
    row = database.insert("jobs", {...})[0]
    return database.claim_job(row["id"])
```

`test_pipeline.py:61`. Note it *claims* the job, which sets status to `running`,
stamps `started_at`, and increments `attempts`. That last part matters for the
retry test later, which relies on the claimed job already having one attempt on
it.

```python
def run(database, project_id, job_type, payload) -> tuple[bool, JobModel]:
    job = queue(database, project_id, job_type, payload)
    return asyncio.run(JobExecutor(database).execute(job)), job
```

`test_pipeline.py:69`. Runs the executor synchronously and returns
`(committed, job)`. This is what makes the file fast and deterministic — there
is no worker pool involved and no waiting.

```python
def run_threads(target, *, count: int) -> None:
    threads = [threading.Thread(target=target) for _ in range(count)]
    ...
    assert not any(thread.is_alive() for thread in threads), "a thread did not finish"
```

`test_pipeline.py:75`. Real OS threads, joined with a 30-second timeout, and an
assertion that none is still alive. That last assertion is the deadlock
detector: if the write lock in `Database._transaction` were mis-nested, the
threads would block forever and this would fail with a clear message instead of
hanging the suite.

Five more module-level helpers were added with the new classes:

- `notes_then_quiz(artifact_id)` at line 85 returns the `(nodes, edges)` of a
  three-node canvas, shared by the three flow-concurrency tests.
- `record_flow_events(monkeypatch)` at line 100 patches `publish` inside
  `backend.services.flow.engine` and returns the list it appends to. Note it
  patches the name *as imported into the engine module*, which is the only place
  that matters.
- `study_guide_payload(body)` at line 113 builds a complete, schema-valid study
  guide with a caller-chosen body, used by the JSON-parsing tests.
- `exhausted_failure(monkeypatch, transport_error)` at line 124 drives the real
  `OpenRouterProvider._send` against an `httpx.AsyncClient.post` that always
  raises, and hands back whatever `LLMError` came out.
- `lecture_transcript(paragraphs=40)` at line 46 builds a transcript long enough
  to be chunked, with one distinctive sentence repeated throughout. Its
  docstring explains the repetition: the repair pass splits at four thousand
  characters, so "exactly one copy per boundary can be cut in half, and the rest
  prove whether the pass returned the lecture or something it invented."

Four module constants carry the test data: `FENCED_BODY` (line 27), `PDF_TEXT`
(29), `TRANSCRIPT_TEXT` (37), `LECTURE_SENTENCE` (39) and `OFFLINE_MARKER` (43).

### `TestResponseParsing` (line 142)

New. Two tests on `backend/llm/schema.py`, which is the code that turns a
model's text answer into a Pydantic object.

**`test_a_code_fence_inside_the_document_survives`** — `test_pipeline.py:143`.
The docstring names the bug: "The fence pattern used to match inside the body
and return its contents."

`_FENCED_JSON` at `backend/llm/schema.py:12` is
`re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)`, and it exists because
models routinely wrap JSON in a Markdown fence. The problem is that a study
guide's *body* is Markdown, and Markdown contains code fences. So a perfectly
good response whose body happened to include a Python snippet could have the
fence pattern match inside the payload and hand back the snippet as though it
were the whole JSON document.

The test builds a study guide whose body is `FENCED_BODY` — prose, a
```` ```python ```` block, more prose — serialises the whole thing as plain JSON
with no outer fence, parses it, and asserts `guide.body == FENCED_BODY` and the
title survived. If `extract_json` reaches for a fence in text that is already
valid JSON, this fails.

**`test_a_fenced_response_is_still_unwrapped`** — `test_pipeline.py:152`. The
other half. The same payload wrapped in ```` ```json ... ``` ```` must still be
unwrapped, checked twice: once at the `extract_json` level by comparing the
parsed dictionary, once at the `parse_as` level by comparing the body.

Together these say: strip the fence when it is a wrapper, never when it is
content. A fix for one direction that broke the other would fail here.

### `TestProviderFailureClassification` (line 160)

New. Three test functions, five cases, and the only place in the suite that
constructs a real `OpenRouterProvider`. No network is involved — the transport
is patched — but the retry loop, the wrapping and the error classification all
run for real.

**`test_an_exhausted_network_failure_stays_transient`** — `test_pipeline.py:166`,
three parameters: `httpx.ConnectTimeout("")`, `httpx.ReadTimeout("")` and
`httpx.ConnectError("[Errno 61] Connection refused")`.

The docstring is the bug in one line: "Wrapping used to discard the type, and
these carry no message to match on." Look at the two halves of `is_transient`
(`backend/services/job_runner.py:57`). The first is
`isinstance(error, TRANSIENT_EXCEPTIONS)`, which covers `httpx.TimeoutException`
and friends. The second is a string search. When `_send` exhausts its retries it
raises `LLMError(...)`, which is not in `TRANSIENT_EXCEPTIONS`, so the type
check no longer helps — and `httpx.ConnectTimeout("")` stringifies to the empty
string, so there is nothing for the phrase list to find either. A network
failure that had already been retried three times inside the provider would then
be classified as permanent and the job would die.

The fix is at `backend/llm/openrouter.py:202`: the final `LLMError` message is
built with `self._describe(last_error)`, which puts the exception's class name
into the text. The helper `exhausted_failure` sets `LLM_MAX_RETRIES=1` so the
loop finishes immediately.

**`test_an_exhausted_failure_names_the_fault_it_gave_up_on`** —
`test_pipeline.py:170`. Asserts `"ConnectTimeout" in str(failure)` directly.
This is the mechanism the previous test relies on, stated on its own, so that a
failure tells you *which* of the two things broke.

**`test_a_malformed_payload_is_still_permanent`** — `test_pipeline.py:175`. The
control, and the important one. It patches `_send` to return
`"Sure! Here is your study guide."` — a real model's most common failure mode —
lets `complete_as` fail to parse it, and asserts the resulting `LLMError` is
**not** transient. The docstring: "Rescuing network faults must not make every
provider failure retryable." Without this, a fix for the previous test that
simply made every `LLMError` transient would pass, and every malformed response
would be retried three times at full token cost.

### `TestCleaning` (line 208)

New. Four test functions, nine cases, and the first half of the answer to the
worst bug in the project.

The class docstring says what was wrong: "A document is not a transcript, and
used to be cleaned as though it were. The transcript rules delete every
parenthesised and bracketed span, so a maths or computer-science PDF lost the
notation it is made of, silently, before the knowledge core and every artifact
under it were built on it."

Look at `TRANSCRIPT_NOISE` at `backend/pipeline/cleaning.py:27`. Four patterns:
timestamps, shouted speaker labels, everything in parentheses, everything in
square brackets. On speech those remove `12:34`, `SPEAKER:`, `(laughs)` and
`[inaudible]`. On a document they remove `f(x)`, `[0,1]`, `O(n log n)`,
`[Knuth 1998]`, `NOTE:` and `3:14`.

**`test_a_document_keeps_mathematical_and_bracketed_notation`** —
`test_pipeline.py:217`. Runs `TextCleaner().clean(PDF_TEXT)` and loops over six
pieces of notation asserting each survives, with the message `f"cleaning ate
{notation}"`. `PDF_TEXT` (line 29) was written to contain one instance of every
pattern that would be destroyed.

**`test_page_markers_survive_a_document_clean`** — `test_pipeline.py:223`.
Asserts the cleaned text still starts with `--- Page 1 ---\n` and still contains
`\n--- Page 2 ---\n`. The docstring: "The reader inserts them deliberately: they
are structure, not noise." This one also pins the newline handling — the
document path uses `LINE_PADDING` and `BLANK_LINES` (`cleaning.py:113`, `115`)
rather than `WHITESPACE`, so line breaks survive. Collapsing all whitespace, as
the transcript path does at `cleaning.py:134`, would run the page markers into
the prose and the assertion on the leading marker would fail.

**`test_a_transcript_still_loses_asides_labels_and_timestamps`** —
`test_pipeline.py:230`. The negative control, and the reason this is a
separation of paths rather than a weakening of the rules. It runs
`clean_transcript(TRANSCRIPT_TEXT, use_model=False)` and asserts six things are
*gone* — including both `"(laughs)"` and the bare word `"laughs"`, so a fix that
merely stripped the brackets would fail — and one thing survives: `"any two
quorums intersect"`. Note `use_model=False`, which skips the repair pass; this
test is about the regexes only.

**`test_only_transcribed_sources_reach_the_transcript_rules`** —
`test_pipeline.py:245`, six parameters. The routing test. `RecordingCleaner`
(line 193) implements both entry points and records which was called, and the
test drives `IngestHandler(cleaner=cleaner)._clean(PDF_TEXT, source_type)` for
each of `audio`, `video`, `youtube`, `pdf`, `pptx` and `md`, asserting the path
taken. The docstring: "Every source type used to get them, documents included."

The guard is three lines at `backend/handlers/ingest_handler.py:203`:

```python
if source_type in TRANSCRIBED_SOURCE_TYPES:
    return await self._cleaner.clean_transcript(text)
return await self._cleaner.clean(text)
```

`TRANSCRIBED_SOURCE_TYPES` is at `cleaning.py:17`. Note which way round the
default falls: anything unknown is treated as a *document*, which is the
conservative direction, so a source type added later cannot silently start
destroying notation. That is also why `TextCleaner.clean` holds the plain name
and the destructive path has to be asked for by name — its own docstring at
`cleaning.py:69` says so.

### `TestTranscriptRepairKeepsTheSource` (line 254)

New. Three tests, and the second half of the worst-bug story. Read the class
docstring aloud if you get the chance; it is the best paragraph in the test
suite:

> The cleaning pass edits the transcript; it must never author a new one. This
> is the project's worst bug and its whole class. The offline provider hands a
> prompt its own input back only when it recognises the prompt as an edit, the
> cleaning prompt says "summarise", and the recogniser only knew "summarize", so
> a whole lecture was replaced by a synthetic study document. Nothing raised:
> the knowledge core and every artifact under it were built on text nobody had
> ever said.

A single letter. British spelling in `REPAIR_PROMPT`
(`backend/pipeline/cleaning.py:19`), American spelling in
`PASS_THROUGH_MARKERS` (`backend/llm/offline.py:24`). The current marker list
carries both spellings plus three other phrases from the same prompt, which is
belt and braces.

**`test_the_repair_prompt_is_recognised_as_an_edit_by_the_offline_provider`** —
`test_pipeline.py:266`. One line:

```python
assert OfflineProvider._wants_the_source_back(REPAIR_PROMPT) is True
```

Its docstring calls this "the cheap half: the prompt and the recogniser pinned
to each other. Neither can be reworded on its own after this, which is the
failure that has no other symptom." Rewriting the prompt in a different register
— which is a completely ordinary thing to do — silently breaks the pipeline, and
this is the test that stops it.

**`test_a_repaired_transcript_still_contains_the_lecture`** —
`test_pipeline.py:278`. The real one. The real `TextCleaner`, the real
`OfflineProvider`, and a real chunked transcript:

```python
cleaned = asyncio.run(TextCleaner(OfflineProvider()).clean_transcript(transcript))

assert LECTURE_SENTENCE in cleaned
assert OFFLINE_MARKER not in cleaned
assert cleaned.count(LECTURE_SENTENCE) >= transcript.count(LECTURE_SENTENCE) - 3
assert len(cleaned) > len(transcript) * 0.9
```

Four assertions, each catching a different shape of the same failure:

1. The distinctive sentence is still there at all.
2. `OFFLINE_MARKER` — `"Generated by the BeePrepared offline provider"`, which
   the provider appends to anything it *derives* (`offline.py:316`) — is not.
   This is the direct detector: if the marker is present, the text is synthetic.
3. Almost all the copies are still there, not just one. The tolerance of 3 is
   the chunk boundaries: `_chunks` (`cleaning.py:169`) splits every 4,000
   characters with no regard for sentence boundaries, so a copy straddling a
   boundary can legitimately be cut in half.
4. The output is at least 90% of the input's length. A summary would be a
   fraction of it.

Notice what makes this test possible at all: it reads the *output*, not the
recogniser. The docstring says why — "Only the output can tell the difference
between a repair and a replacement." A test that asserted `complete` was called
would pass against a provider that returned a summary.

**`test_the_ingest_handler_sends_a_transcript_down_that_same_path`** —
`test_pipeline.py:296`. The door the bug actually came through. It builds a real
`IngestHandler` with a real `TextCleaner(OfflineProvider())` and calls
`_clean(lecture_transcript(), "audio")`, asserting the same first two things.
The previous test proves the cleaner is safe; this proves ingest reaches it.
Both are needed: the routing could be right and the cleaner wrong, or the other
way round.

Between them, `TestCleaning` and this class close the coverage gap named in
section 1. `backend/pipeline/cleaning.py` is now at 96% with `_repair` genuinely
executed.

### `TestGeneration` (line 308)

**`test_every_artifact_type_generates_and_commits`** — parametrised at
`test_pipeline.py:309`, body at line 313. **Eight** parameters now: quiz,
flashcards, notes, slides, study_guide, cheatsheet, mindmap and — new — exam.
Each asserts the job committed, that exactly one artifact of that type now
exists in the project, that its `content["data"]` is non-empty, and that the job
row ends `completed` with `result["artifact_type"]` set.

This is the broadest test in the suite. It runs the real `GenerateHandler`, the
real `SourceResolver`, the real `ArtifactGenerator` with its per-type
`GeneratorSpec` and validation, the real `ExportService`, and the real
`Database.commit_bundle`. Only the model is offline.

`exam` was the missing one, and it was the worst one to be missing, because it
is the only type that does not go down the ordinary
`complete_as(prompt, schema)` path. `ArtifactGenerator._exam`
(`backend/services/generators.py:242`) generates an `ExamSpec` first, then runs
three question batches concurrently under `asyncio.gather`, merges them,
enforces a floor, renumbers every question and typesets the result.

How it fails: add a type to `ARTIFACT_MODELS` without adding a `GeneratorSpec`
and the parametrised case for it raises `Unknown artifact type`. Break the
offline provider's builder for one type and only that case fails. Break
`commit_bundle` and all eight fail.

**`test_an_exam_commits_its_rendered_booklet_alongside_the_questions`** —
`test_pipeline.py:329`. New, and the one that goes past "it committed".

```python
questions = exam["content"]["data"]["questions"]
assert len(questions) > max(count for _, count, _ in EXAM_BATCHES), "one batch is not an exam"
assert [question["id"] for question in questions] == [
    f"Q-{number}" for number in range(1, len(questions) + 1)
], "batches are renumbered once they are merged"

export = exam["content"]["binary"]
assert export["format"] in {"pdf", "tex"}
assert export["mime_type"] == MIME_TYPES[export["format"]]
assert get_file_store().size_of(export["storage_path"]) == export["size_bytes"] > 0
```

Four separate claims, and each is worth understanding.

The first compares the question count against the *largest single batch* in
`EXAM_BATCHES` (`generators.py:207`, which is
`(("MCQ", 15, 3), ("Short Answer", 5, 5), ("Problem Set", 3, 10))`). A count of
15 or fewer means at least one batch was dropped. Writing it against the
constant rather than against a literal means the test follows the configuration.

The second pins the renumbering at `generators.py:283`. Each batch numbers its
own questions from 1, so a merge that forgot to renumber would produce an exam
with three question 1s. The assertion message says it: "batches are renumbered
once they are merged."

The last three pin the export. The docstring explains why they have to exist
separately from the previous test: "A failed export is logged rather than
raised, so the job completing says nothing about whether a booklet came out."
`ExportService.export` swallows every exception at
`backend/services/exports/__init__.py:84` and returns `None`, which is the right
call for a convenience file but means a completely broken renderer produces a
green suite. So this test looks at the stored export, checks the declared MIME
type matches the format via the `MIME_TYPES` table, and — the strongest line —
asks the file store how big the file actually is and compares it to the recorded
`size_bytes`, then asserts both are above zero.

The `format in {"pdf", "tex"}` allowance is honest rather than lazy: the PDF
comes out of `pdflatex`, which may not be installed, in which case
`ExamPdfRenderer` falls back to storing the LaTeX source. Both are real
outcomes, so both are accepted.

**`test_multi_input_records_one_edge_per_source`** — `test_pipeline.py:364`.
Creates two extra knowledge cores, runs a notes job with all three as sources,
and asserts the resulting artifact has exactly three parent edges whose ids
match the three sources. The docstring: "Provenance survives fan-in."

This exercises the merge path — three cores means `GenerateHandler.build_context`
(`backend/handlers/generate_handler.py:76`) calls `CoreMerger.merge` — and then
the edge construction at `generate_handler.py:134`, which builds one
`EdgePayload` per source id. If someone collapsed that to a single "primary
source" edge, the lineage view in the UI would show one parent for a node the
user wired three inputs into, and this test fails on the sorted comparison at
line 387.

**`test_duplicate_sources_collapse_to_one_edge`** — `test_pipeline.py:389`. Calls
`GenerateHandler()._unique([id, id])` directly and asserts it returns one id.
The implementation is `list(dict.fromkeys(...))`
(`generate_handler.py:166`), which deduplicates *and* preserves order — order
matters because the sources are concatenated into the prompt in the order the
user wired them.

> **Worth knowing.** This is a direct unit test of a private static method, not
> of the behaviour. If `run()` stopped calling `_unique`, the `artifact_edges`
> table's `UNIQUE (parent, child, relationship)` constraint
> (`backend/services/database.py:76`) plus `INSERT OR IGNORE` in `commit_bundle`
> (`database.py:325`) would still prevent a duplicate row — so the visible
> behaviour would be unchanged and this test would still pass. It pins the
> helper, not the wiring.

**`test_chaining_reads_the_chained_artifact_not_its_ancestor`** —
`test_pipeline.py:393`. Generates notes from the core, then asks
`SourceResolver.resolve([notes_id], "quiz")` for the core it would use, and
asserts the first 80 characters of the notes body appear in that core's summary.

This is one of the more interesting tests in the suite because the naive
implementation is wrong in a way nobody would notice. When you wire notes into a
quiz node on the canvas, the notes artifact has a `derived_from` edge back to
the knowledge core. The easy implementation walks that edge and generates the
quiz from the core — producing a perfectly good quiz that has nothing to do with
the notes the user actually wired in. `SourceResolver.to_core`
(`backend/handlers/sources.py:152`) tries three things in order: the artifact's
own core if it is a `knowledge_core` (line 157), then `ArtifactFlattener.flatten`
to render a generated artifact back to text and wrap it as a synthetic core
(lines 160-164), and only then the parent edge (line 166). This test pins the
second branch beating the third.

**`test_unknown_target_type_fails_the_job`** — `test_pipeline.py:408`. A
`horoscope` target must not commit and must leave the job `failed`. This is the
handler-level guard at `backend/handlers/generate_handler.py:53`, which is a
second line of defence behind the schema validator tested at `test_api.py:216`.
Both exist because a job can be created by the flow engine, which does not go
through `GenerateRequest`.

**`test_missing_source_fails_with_a_clear_message`** — `test_pipeline.py:415`.
A random UUID as the source. Asserts the job did not commit, that its status is
`failed`, and that `"not found"` appears in the error message.

**This is the test that used to flake.** See section 7; the mechanism is worth
understanding because it is a good story.

**`test_generation_is_steerable`** — `test_pipeline.py:425`. Passes
`instructions: "focus only on quorums"` and asserts the stored artifact records
`content["instructions"]`. The persistence happens at
`generate_handler.py:117`. Storing the instructions is what lets the UI show
"generated with: focus only on quorums" next to an artifact, and it is also what
the deduplication logic reads when deciding whether two requests are the same
work. The counterpart test that the instructions actually reach the prompt is
`test_seams.py:88`.

### `TestRefinement` (line 439)

**`test_refine_appends_a_version_linked_to_the_original`** —
`test_pipeline.py:440`. Generates a quiz, refines it, and then asserts there are
now **two** quizzes with the message "refinement should append, not overwrite",
that the new one records `content["refined_from"] == original_id`, and that a
parent edge points from the original to the revision.

The design decision being pinned is stated in the handler docstring
(`backend/handlers/refine_handler.py:30`): refinement appends rather than edits
in place, so every revision stays visible and nothing already exported changes
underneath the user. If somebody changed `RefineHandler` to update the existing
row, the count assertion at line 456 fails.

**`test_refine_without_instructions_is_rejected`** — `test_pipeline.py:462`.
Instructions of `"   "` — whitespace only. The job must fail with
`"instructions is required"` in its error message. The guard strips before
checking (`backend/handlers/refine_handler.py:54`), which is why whitespace does
not slip past a plain truthiness test. Refinement with no instruction is
meaningless: it would burn tokens regenerating the same artifact.

### `TestRetryPolicy` (line 476)

Four test functions, eleven cases, over `is_transient`
(`backend/services/job_runner.py:57`) and the requeue path. This classifier
decides whether a failed job goes back on the queue or dies, so getting it wrong
is expensive in both directions: too eager and you retry a malformed payload
three times, spending tokens each time; too conservative and a rate limit kills
a job the user is waiting for.

**`test_transient_failures_retry`** — parametrised at `test_pipeline.py:477`,
four cases: `"HTTP 429: rate limit exceeded"`, `"Read timed out"`, `"503 Service
Unavailable"`, `"upstream is overloaded"`. Each must classify as transient. They
cover both mechanisms in the string half of the classifier — the labelled-status
regex at `job_runner.py:54` and the phrase list at line 44. Note that `"503
Service Unavailable"` matches on the *phrase* `"service unavailable"`, not on
the digits, because `503` there has no `http`/`status`/`code` label in front of
it. That is a good detail to have noticed, and it is the same observation that
makes the UUID parameter below weaker than it looks.

**`test_permanent_failures_do_not_retry`** — parametrised at
`test_pipeline.py:486`, three cases: `"target_type is required"`, `"Source
artifacts not found: abc"`, `"Expected at least 5 questions, got 2"`. These are
three real permanent-failure messages the system produces — a bad payload, a
missing source, and a generation-contract violation. Each will fail identically
on retry, so retrying is pure waste.

**`test_status_digits_inside_identifiers_do_not_trigger_a_retry`** —
`test_pipeline.py:494`, body at 499. This is the regression test for the
flakiness. Three parametrised identifiers, each embedded in a "not found"
message:

```python
@pytest.mark.parametrize("identifier", [
    "429e4567-e89b-12d3-a456-426614174000",
    "Source artifacts not found: 502",
    "artifact 504 has no content",
])
def test_status_digits_inside_identifiers_do_not_trigger_a_retry(self, identifier):
    """A bare three-digit match would retry anything containing those digits."""
    assert not is_transient(ValueError(f"Source artifacts not found: {identifier}"))
```

The first case is the actual bug: a UUID that happens to start with `429`. The
classifier now requires the digits to be *labelled* as a status:

```python
TRANSIENT_STATUS = re.compile(r"\b(?:http|status|code)\s*[:=]?\s*(408|409|425|429|500|502|503|504)\b")
```

**Be precise about which parameter does what.** This is the nuance from section
1, and the old version of this document got it wrong.

Removing the `(?:http|status|code)` prefix group leaves `\b(408|...)\b`. Against
`"...not found: 429e4567-e89b-..."` that still does **not** match, because the
`\b` after `429` requires a non-word character and the next character is `e`. So
the UUID parameter — the one the bug is named after — survives the obvious
mutation. It only dies if the pattern loses its word boundaries entirely, or
becomes a plain substring test.

The two parameters that catch the label mutation are the prose ones:
`"Source artifacts not found: 502"` and `"artifact 504 has no content"`. In both
the number is a standalone word, so `\b502\b` and `\b504\b` match once the
labels are gone, and both go transient and both fail.

Keep all three. The UUID is the one you can tell the story about; the other two
are the ones doing the work.

**`test_a_transient_failure_requeues_until_attempts_run_out`** —
`test_pipeline.py:503`. Sets `JOB_MAX_ATTEMPTS=2` and clears the settings cache,
then queues a job (which claims it, so `attempts` is 1), fails it retryably and
asserts `fail_job` returns `"pending"`, re-claims it (`attempts` becomes 2),
fails it again and asserts the return is `"failed"`.

This pins the accounting in `Database.fail_job`
(`backend/services/database.py:341`): the requeue condition is `retryable and
attempts < max_attempts`, and the attempt counter is incremented by `claim_job`,
not by `fail_job`. Getting that backwards by one gives you either infinite
retries or none. The test asserts on the *return value* of `fail_job` as well as
the stored status, because the return value is what
`JobExecutor._record_failure` branches on at `backend/services/job_runner.py:189`
when deciding whether to publish a `job.failed` event and whether to re-dispatch.

### `TestQueue` (line 517)

Eight tests on the job queue. The queue is SQLite, and everything here is about
making SQLite behave correctly under several workers.

**`test_a_job_is_claimed_exactly_once`** — `test_pipeline.py:518`. One pending
job, two `claim_job()` calls. The first returns it; the second returns `None`.
The docstring says the stakes: "Without an atomic claim, two workers run the
same job." That means two OpenRouter bills and two artifacts for one user
action.

**`test_stale_running_jobs_return_to_the_queue`** — `test_pipeline.py:529`.
Claims a job, confirms it is `running`, then calls
`reap_stale_jobs(older_than_seconds=-1)`. The negative value is a trick: the
cutoff is computed as `now - older_than_seconds`, so `-1` makes it one second in
the *future*, which means every running job counts as stale. The assertion is
that the reaper returns that job's id and the row is back to `pending`. Without
the reaper, a worker killed mid-job leaves the row `running` forever and the
canvas node spins with no error — which is exactly the kind of bug that is
invisible in development and permanent in production.

**`test_a_stale_job_with_no_attempts_left_is_failed_rather_than_requeued`** —
`test_pipeline.py:540`. New, and the reaper's other branch — the one that stops
the loop. Sets `JOB_MAX_ATTEMPTS=1`, claims a job (so it has used its one
attempt), reaps it, and asserts three things: the reaper still reports the id,
the row is now `failed` rather than `pending` with `"no attempts left"` in its
error message, and a subsequent `claim_job()` finds nothing.

Deleting that branch at `backend/services/database.py:416` survived the old
suite, because the only reaper test used the default attempt limit and never got
near it. The docstring spells out what the surviving mutation costs: "A job that
dies the same way every time would otherwise be requeued forever: the reaper
hands it back, the next worker dies on it, and the node spins with no error for
as long as the process lives." That is a livelock that consumes a worker slot
permanently and produces no error anywhere.

The third assertion is the strongest. Checking the status says the row was
written; checking that `claim_job()` returns `None` says the job is genuinely
off the queue.

**`test_a_committed_job_cannot_commit_twice`** — `test_pipeline.py:567`. Runs a
job successfully, then calls `commit_bundle` again with a fresh bundle and
expects `ValueError` matching `"already completed"`. The guard is inside
`commit_bundle` (`backend/services/database.py:301`), in the same transaction as
the writes. This is what stops a job that was reclaimed by the reaper — and is
therefore running twice — from writing its artifacts twice.

**`test_cancelling_takes_a_job_off_the_queue`** — `test_pipeline.py:576`. Cancel
returns `True`, a subsequent `claim_job()` finds nothing, and a second cancel
returns `False`. The boolean is what the route turns into a 409
(`test_api.py:299` covers that side).

**`test_racing_workers_partition_the_queue`** — `test_pipeline.py:585`. 24 jobs,
six real threads released simultaneously by a `threading.Barrier(6)`, each
draining until `claim_job()` returns `None`. The assertion is
`sorted(claimed) == sorted(queued)` — every job claimed, exactly once,
collectively.

This is the strongest test of `BEGIN IMMEDIATE` in the codebase. `claim_job`
(`backend/services/database.py:276`) does a read (find a pending row) and then a
write (mark it running), and those two must be atomic with respect to other
workers. `Database._transaction` (`database.py:154`) takes a process-level
`RLock` and then issues `BEGIN IMMEDIATE` at line 176, which acquires SQLite's
write lock up front rather than lazily on the first write. Change that to a
plain `BEGIN` and two threads can both read the same pending row before either
writes; the assertion then fails because the claimed list has a duplicate and is
longer than the queued list.

**`test_a_late_failure_cannot_undo_a_committed_result`** — `test_pipeline.py:608`.
Runs a job to completion, then calls `fail_job` on it and asserts the return is
`"completed"` and the status is unchanged. The docstring names the scenario: "A
job reclaimed by the reaper runs twice; the loser must not erase the winner."
The guard is the terminal-status check inside `fail_job`
(`backend/services/database.py:341`), which returns the existing status rather
than overwriting.

**`test_a_late_failure_cannot_undo_a_cancellation`** — `test_pipeline.py:618`.
The same protection for a cancelled job. This one is the user-visible case: you
cancel a job, the handler notices a few seconds later and reports a failure, and
without the guard the UI would flip from "cancelled" to "failed" and you would
think something went wrong.

### `TestFlowConcurrency` (line 629) — the headline regression test

Three tests now. The first is the one to open on screen.

#### `test_concurrent_completions_queue_the_next_step_once` — `test_pipeline.py:630`

**Say the file name out loud when you navigate to this.** It is in
`test_pipeline.py`, not in `test_flow_engine.py`. The flow-engine file holds the
single-threaded sibling, which is a different and much weaker test.

The setup, lines 632-648. A three-node canvas — source `s1` holding the
knowledge core, generator `g1` producing notes, generator `g2` producing a quiz
— wired `s1→g1→g2`. That is two waves: `g1` can start immediately, `g2` has to
wait for `g1`. `engine.start(...)` compiles it, writes the `flow_runs` row, and
dispatches the first wave, appending `g1`'s job id to `dispatched`. Then the run
id is fetched back.

The concurrency, lines 650-660:

```python
ready = threading.Barrier(8)
failures: list[BaseException] = []

def notify() -> None:
    try:
        ready.wait()
        engine.on_job_finished(run_id, "g1", artifact_id="notes-1", dispatch=dispatched.append)
    except BaseException as error:
        failures.append(error)

run_threads(notify, count=8)
```

Eight real threads. Each one blocks on `ready.wait()`; `threading.Barrier(8)`
releases all eight only when the eighth arrives, so they enter
`on_job_finished` as close to simultaneously as the operating system allows.
Each reports the *same* node, `g1`, as finished with the *same* artifact,
`notes-1`.

This is the real production scenario, not a contrived one. `_notify_flow`
(`backend/services/job_runner.py:223`) is called by the job executor on both the
success and failure paths, workers can run in several processes, and the reaper
can requeue a job that is actually still alive — so the same node genuinely can
be reported finished more than once.

The assertions, lines 662-665:

```python
assert not failures
assert len(dispatched) == 2
assert len(database.select("jobs", [("project_id", f"eq.{project['id']}")])) == 2
assert engine.get(run_id)["node_states"]["g2"]["status"] == "running"
```

**Why 2 and not 1.** This is the question you will be asked, and the answer is
simple once you see it: `dispatched` counts every dispatch in the whole test,
not just the ones caused by the eight threads. One dispatch came from
`engine.start` when it queued `g1`. One more should come from the eight
completions collectively, when they unblock `g2`. Two nodes in the plan, two
jobs, two dispatches. The number 2 is "one job per generator node", which is the
correct total for this canvas regardless of how many notifications arrive.
Asserting 1 would be asserting that starting the flow did nothing.

The job-row count is the same claim checked against the database rather than
against a Python list, which matters because a dispatch that did not write a row
would be harmless while a row that was written without a dispatch would be an
orphan. Both are 2. This second assertion is what makes the test durable: it
pins the side effect rather than the observer, so a fix that suppressed the
dispatch callback without fixing the double-insert would still fail.

**How it fails against the old engine: `9 != 2`.** Before the fix, `advance` was
not idempotent. Each of the eight threads read `node_states`, saw `g2` as
`pending` with its parent satisfied, and queued a job for it — because the read
of the state, the insert of the job row, and the write-back marking `g2` as
`running` were three separate operations with no transaction around them. Eight
threads, eight extra dispatches, plus the one from `start`, equals nine. Nine
job rows too, which means the same quiz generated nine times: nine model calls,
nine artifacts, nine sets of edges.

Reverting the fix and running this test twenty times failed twenty out of
twenty, nineteen of them with exactly `assert 9 == 2`. The twentieth failed with
a different count, which is what a genuine race looks like.

The fix is the transaction boundary in `FlowEngine.on_job_finished`
(`backend/services/flow/engine.py:207`):

```python
with self._database.transaction():
    run = self.get(flow_run_id)
    ...
    self._database.update("flow_runs", [("id", f"eq.{flow_run_id}")], {"node_states": states})
    queued = self._schedule(flow_run_id, outbox)

outbox.flush()
self._hand_off(queued, dispatch)
```

The read of `node_states`, the write back marking `g1` complete, and the
scheduling that follows all happen inside one `BEGIN IMMEDIATE`. Because
`Database._transaction` also holds a process-level lock, the eight threads
serialise. The first one through marks `g1` complete, sees `g2` pending, queues
it, and writes `g2` as `running`. The other seven then read the state *after*
that write, see `g2` is `running` rather than `pending`, and the guard at
`engine.py:137` skips it:

```python
if states.get(step.node_id, {}).get("status") != "pending":
    continue
```

Two more things in that code are worth being able to point at:

- `_hand_off` (`engine.py:178`) is called **outside** the `with` block. Its
  docstring says why: "Tell the workers about jobs only once their rows are
  committed." If dispatch happened inside the transaction, a Celery worker could
  claim the job id and look for the row before the transaction committed, and
  find nothing.
- `on_job_finished` needs the transaction for a second reason beyond
  idempotence, described at `engine.py:197`: two parents of a fan-in step
  finishing at once would each read the same `node_states`, each write back
  their own completion, and the second write would erase the first. The step
  below them would then wait forever on a parent the row no longer remembers.
  `test_flow_engine.py:190` covers the fan-in behaviour single-threaded; this
  test covers the concurrency.

The `assert not failures` line matters too. Because the threads catch
`BaseException` and stash it, an exception inside `on_job_finished` — a SQLite
"cannot start a transaction within a transaction", say — would otherwise be
swallowed by the thread and the test would pass with the wrong counts.
Collecting and asserting is what makes that visible.

#### The two new siblings

The `outbox.flush()` line above is not decoration, and it has its own pair of
tests. `EventOutbox` (`backend/services/flow/engine.py:27`) holds every flow
event in a list until the transaction that produced it has committed, then
publishes them in order. Its docstring gives two reasons: publishing from inside
an open transaction "announces a node the database has not stored yet", and on
the Redis bus delivery is a blocking network round trip that would be made while
holding the write lock.

**`test_a_rolled_back_completion_publishes_nothing`** — `test_pipeline.py:667`.
Starts a flow, installs the event recorder, then monkeypatches
`FlowEngine._schedule` to raise, so the transaction in `on_job_finished` rolls
back after the node state has been written but before the commit. Asserts two
things:

```python
assert published == []
assert engine.get(run_id)["node_states"]["g1"]["status"] == "running"
```

Nothing was published, and the node state is untouched — still `running`, not
`completed`. The docstring: "The browser must never be shown a finished node the
transaction threw away." Without the outbox, the `flow.node` event for `g1`
would have gone out before the rollback, so the canvas would show a green node
for work the database has no record of, and no later event would ever correct
it.

Note that this test also incidentally proves the rollback itself works, which is
the subject of `TestTransactions` below.

**`test_a_finished_run_publishes_its_events_in_order`** — `test_pipeline.py:689`.
The complement, and the one that stops the fix from being "publish nothing".
Runs a whole two-step flow to completion and asserts the exact sequence:

```python
[
    ("flow.started", None, None),
    ("flow.node", "g1", "running"),
    ("flow.node", "g1", "completed"),
    ("flow.node", "g2", "running"),
    ("flow.node", "g2", "completed"),
    ("flow.completed", None, None),
]
```

plus the payload of the final event: `{"flow_run_id": run_id, "completed": 2,
"failed": 0, "skipped": 0}`.

The docstring: "Holding events back until the commit must not reorder or drop
any of them." Six events, in the order a browser needs them to render a run
progressing. Two details are worth noticing. `flow.started` is published
directly rather than through the outbox (`engine.py:95`), because it precedes
any transaction — and it still lands first. And `g1` is reported `completed`
before `g2` is reported `running`, which is the ordering the canvas depends on
to animate an edge lighting up.

The tally in the last event comes from `_save` (`engine.py:302`), which only
writes a result once every step is in a terminal state.

### `TestTransactions` (line 740)

New. One test, and it is about the connection rather than about any feature.

`RefusesTheFirstCommit` at line 718 wraps a real `sqlite3.Connection` and makes
its first `COMMIT` raise `sqlite3.OperationalError("disk I/O error")`.
Everything else is delegated through `__getattr__`, which the class docstring
explains: "everything else is the real connection, so `in_transaction` still
reports what SQLite actually thinks." That is the whole trick — the assertion
has to come from SQLite, not from bookkeeping the test controls.

**`test_a_failed_commit_leaves_the_connection_usable`** — `test_pipeline.py:741`.
Installs the wrapper as this thread's connection, does an insert that therefore
fails, and then asserts:

```python
assert not flaky.in_transaction, "the failed commit stranded the connection"
```

then does a *second* insert, reads the row back, and asserts
`not flaky.in_transaction` again with the message "the later write joined a
transaction that never ends."

The behaviour being pinned is two lines of `Database._transaction`
(`backend/services/database.py:154`) that are easy to get wrong and whose
docstring explains both:

- The `COMMIT` is inside the `try`, not after it. A commit can fail on its own —
  full disk, I/O error, busy timeout — and if it were outside the `try` the
  `except` would never run and the transaction would stay open behind it.
- The `except` catches `BaseException`, not `Exception`, so a `CancelledError`
  cannot escape with the transaction still open.

Why this matters is the nesting rule at `database.py:172`: if a connection is
already `in_transaction`, `_transaction` yields it rather than issuing a second
`BEGIN`, because SQLite rejects nested `BEGIN`s. A stranded transaction
therefore does not error — it silently swallows every subsequent write on that
thread into a transaction that will never commit. The second half of this test
is what catches that, and it is the reason the test does two inserts rather than
one.

---

## 6. `test_flow_engine.py` — compilation and scheduling

297 lines, 21 tests. Split cleanly into two halves: `TestCompile` and
`TestValidation` are pure functions on graphs with no database at all;
`TestScheduling` drives the engine against a real database.

Three helpers at the top build React Flow node dictionaries — `source_node`
(line 10), `generator_node` (line 18) and `edge` (line 26). They produce exactly
the shape the frontend sends, which is why these tests are meaningful: the
compiler's job is to make sense of client JSON.

### `TestCompile` (line 30)

**`test_linear_chain_is_ordered_by_depth`** — `test_flow_engine.py:31`. `s1→g1→g2`.
Asserts `g1.depth < g2.depth` and `g2.parents == ["g1"]`. Depth is what the
`waves` property groups on, so getting it wrong means running a step before its
input exists. The depth assignment is `depth[child] = max(depth[child],
depth[node_id] + 1)` at `backend/services/flow/plan.py:219` — the `max` is what
makes a node with several parents sit below the *deepest* one.

**`test_fan_in_gives_a_step_every_parent`** — `test_flow_engine.py:40`. Two
sources into one generator. Both must appear in `parents`. The docstring gives
the user story: "Two lectures into one set of notes: both must reach the
generator." If `parents` kept only one, the notes would be generated from half
the material the user wired in — and the user would never know.

**`test_fan_out_gives_every_child_the_same_parent`** — `test_flow_engine.py:48`.
One quiz feeding flashcards, an exam and a cheat sheet. Asserts three downstream
steps, all with `parents == ["g1"]`, and — the important line —
`len({step.depth for step in downstream}) == 1` with the message "siblings
should run in one wave". Independent work at the same depth must be dispatched
together, because that is the entire performance argument for the DAG: three
generations running concurrently instead of one after another.

**`test_waves_group_independent_work`** — `test_flow_engine.py:65`. `s1→g1`,
`s1→g2`, `g2→g3`. Asserts two waves and that the first is exactly `{g1, g2}`.
This is the `waves` property at `backend/services/flow/plan.py:60` grouping
steps by depth and returning them in depth order.

**`test_duplicate_edges_do_not_duplicate_parents`** — `test_flow_engine.py:79`.
Two identical edges from `s1` to `g1`. Parents must be `["s1"]`, not
`["s1", "s1"]`. React Flow can produce duplicate edges when a user drags the
same connection twice. A duplicated parent would mean the same source appearing
twice in the prompt and two identical provenance edges attempted. The guard is
the `if source in incoming[target]: continue` at `plan.py:176`.

**`test_dangling_edges_from_deleted_nodes_are_ignored`** — `test_flow_engine.py:86`.
Edges referencing a node id `"ghost"` that is not in the node list, in both
directions. They must be skipped rather than raising. The guard is at
`backend/services/flow/plan.py:172`:

```python
if source not in by_id or target not in by_id:
    continue
```

This one is about robustness against a real client bug: React Flow can leave an
edge behind when a node is deleted, and the canvas is autosaved. Raising here
would leave the user with a project that can never be run and no obvious way to
fix it.

**`test_instructions_travel_with_the_node`** — `test_flow_engine.py:93`.
Per-node instructions on the canvas must reach `FlowStep.instructions`, which is
then copied into the job payload by `_queue_job`
(`backend/services/flow/engine.py:269`) and eventually into the prompt. Without
this the "focus on chapter 3" a user typed into a node would be silently
discarded.

### `TestValidation` (line 101)

Seven tests, all asserting that `FlowCompiler.compile` raises
`FlowValidationError` with a specific word in the message. The reason they match
on message text rather than just on the exception type is that these messages go
to the user: the compiler's job is to name the offending node so the canvas can
point at the problem before any work is dispatched.

**`test_cycle_is_rejected`** — `test_flow_engine.py:102`, matching `"cycle"`.
`g1→g2→g1`. Detected structurally: Kahn's algorithm in `_topological_order`
(`backend/services/flow/plan.py:199`) produces a shorter `order` than the
runnable set when a cycle exists, and the difference is reported by name at line
228. An undetected cycle would be an infinite scheduling loop.

**`test_self_loop_is_rejected`** — `test_flow_engine.py:109`, matching
`"itself"`. Caught earlier and separately, in `_adjacency` at `plan.py:175`,
because a self-loop deserves a message about that specific node rather than a
generic cycle report.

**`test_generator_without_input_is_rejected`** — `test_flow_engine.py:116`,
matching `"no input"`. `g2` is on the canvas with nothing wired into it. A
generator with no source has nothing to generate from; `_require_inputs`
(`plan.py:184`) refuses it and names it.

**`test_generator_without_output_type_is_rejected`** — `test_flow_engine.py:123`,
matching `"no output type"`. A generator node whose `data` has only a label and
no `subType`. This is the state a node is in immediately after being dragged
onto the canvas before the user picks what it produces. The message lists the
valid choices (`plan.py:151`).

**`test_canvas_with_no_generators_is_rejected`** — `test_flow_engine.py:130`,
matching `"Nothing to run"`. A canvas with only a source node. Nothing to do.
(`plan.py:117`.)

**`test_empty_canvas_is_rejected`** — `test_flow_engine.py:134`, matching
`"empty"`. No nodes at all. This is the first check in `compile`
(`plan.py:108`), before anything else can trip over an empty dictionary.

**`test_a_canvas_past_the_node_limit_is_rejected`** — `test_flow_engine.py:138`.
New. Builds `MAX_NODES + 1` source nodes and asserts the compile raises with
`f"limited to {MAX_NODES} nodes"` in the message. `MAX_NODES` is 100
(`backend/services/flow/plan.py:15`) and the check is at `plan.py:109`.

Deleting that check survived the old suite, because no test had ever sent a
large canvas. The docstring is the argument for the limit existing at all: "The
canvas is request data, so its size is the caller's to choose. Compilation walks
every node and every edge and the run that follows queues a job per generator,
so an unbounded graph is an unbounded amount of work bought with one request."

Note that the test imports `MAX_NODES` and builds the message from it rather
than hard-coding 100, so raising the limit does not require editing the test.
That is the right call here: the number is a tuning decision, the existence of a
bound is the invariant.

### `TestScheduling` (line 154)

Seven tests, all using the `database`, `project` and `knowledge_core` fixtures,
and all passing a `dispatch` callable that appends to a list — the same seam the
production code uses to hand job ids to `enqueue`.

**`test_only_the_first_wave_is_dispatched_initially`** — `test_flow_engine.py:155`.
`s1→g1→g2`. After `start`, exactly one dispatch, `g1` is `running`, `g2` is
`pending`. The docstring: "A downstream node must not be queued before its input
exists." Dispatching everything at once would give `g2` a generate job with an
empty source list.

**`test_completion_unblocks_the_next_wave_with_the_new_artifact`** —
`test_flow_engine.py:171`. Reports `g1` finished with
`artifact_id="quiz-artifact-1"` and asserts `g2` is now `running` **and** that
its `source_artifact_ids == ["quiz-artifact-1"]`. That second assertion is the
one that matters: it is not enough for the next step to start, it has to start
with the artifact its parent actually produced. That value comes from
`_input_artifacts` (`backend/services/flow/engine.py:283`) reading each parent's
recorded `artifact_id`, and it is what makes chaining work at all.

**`test_fan_in_node_waits_for_every_parent`** — `test_flow_engine.py:190`. A
diamond: `s1` into `g1` and `g2`, both into `g3`. After `g1` finishes, `g3` must
still be `pending`, with the assertion message "one parent is not enough". After
`g2` also finishes, `g3` is `running` with both artifact ids as its sources.
This is `_inputs_ready` (`engine.py:276`) requiring *all* parents to be in
`READY_STATUSES`. If it used `any` instead of `all`, `g3` would run with half
its inputs.

**`test_failure_skips_everything_downstream`** — `test_flow_engine.py:215`.
Reports `g1` failed with `error="model refused"`. Asserts `g1` is `failed`, `g2`
is **`skipped`** — not `pending`, not `failed` — and the run status is `failed`.
The distinction between `skipped` and `pending` is a user-interface decision:
`pending` renders as a spinner, and a node that will never run must not spin
forever. `_skip_downstream` (`engine.py:292`) walks `plan.descendants_of` and
marks the whole subtree.

**`test_a_step_with_no_usable_input_still_reaches_a_terminal_state`** —
`test_flow_engine.py:232`. The awkward case: `g1` finishes *successfully* but
with `artifact_id=None`. Its child `g2` is now unblocked but has nothing to
generate from. Asserts `g2` is `failed`, `g3` is `skipped`, and the run is
`failed`. The docstring: "A parent that finished without an artifact must not
strand the run as running."

This is the branch at `engine.py:143` — inputs ready but `sources` empty, so the
node is failed with the message "This node's inputs produced no artifacts"
rather than being left pending. Without it the run would sit at `running`
forever, with `g2` pending and nothing that could ever move it, and the `_save`
completion check would never fire.

**`test_run_completes_when_every_step_lands`** — `test_flow_engine.py:257`. The
happy path: one generator, it finishes, the run status is `completed` and
`result["completed"] == 1`. This pins the tally in `_save` (`engine.py:302`),
which is only written once every step is in a terminal state and is what the UI
shows when a flow ends.

**`test_advance_is_idempotent`** — `test_flow_engine.py:273`. The single-threaded
version of the headline test, and the one whose docstring was wrong. After
`start` has already dispatched `g1`, calling `advance` twice more must add
nothing:

```python
engine.advance(run_id, dispatch=dispatched.append)
engine.advance(run_id, dispatch=dispatched.append)

assert len(dispatched) == 1
```

The corrected docstring is the honest description of what this proves:

> A second sequential advance finds no pending step and dispatches nothing.
>
> This is the `status != "pending"` guard and only that: the two calls run one
> after the other on one thread, so an engine with no transaction around the
> read-then-write passes it. The concurrent case, where two advances interleave
> inside that window, is
> `TestFlowConcurrency::test_concurrent_completions_queue_the_next_step_once`
> in backend/tests/test_pipeline.py.

That is worth reading closely, because the old docstring claimed this test
covered duplicate completions and it does not. Remove the transaction from
`advance` (`engine.py:118`) and this test still passes. It pins the guard at
`engine.py:137` and nothing else.

Keep both tests, and keep them labelled correctly. The first is a logic
property, the second is a concurrency property, and passing the first does not
imply the second. That is exactly why the old engine passed one and failed the
other — and being able to say that sentence about your own code is worth more
than either test.

---

## 7. The flaky run, and where the classifier is pinned now

For a while the suite failed roughly one run in six, always in
`test_missing_source_fails_with_a_clear_message` — now at `test_pipeline.py:415`:

```python
def test_missing_source_fails_with_a_clear_message(self, database, project):
    committed, job = run(database, project["id"], "generate", {
        "target_type": "quiz", "source_artifact_ids": [str(uuid.uuid4())],
    })
    assert not committed

    failed = database.get_job(job.id)
    assert failed["status"] == "failed"
```

The source id is a **random** UUID, which is the only randomness in the whole
suite, and that is where the non-determinism came from.

The chain: the resolver raises `SourceResolutionError(f"Source artifacts not
found: {', '.join(missing)}")` (`backend/handlers/sources.py:145`), so the
message contains the random UUID. `JobExecutor._record_failure` asks
`is_transient` whether to retry. The old classifier looked for the bare status
digits **anywhere** in the message text — a substring test with no word
boundaries. A UUID like `429e4567-e89b-12d3-a456-426614174000` begins with the
characters `429`, so the message matched, the failure was classified as
transient, and `fail_job` put the job back to `pending` instead of `failed`. The
test's `assert not committed` still passed — a requeued job did not commit — but
the status assertion on the next line failed with `'pending' != 'failed'`.

So the test failed exactly when the random UUID happened to contain one of the
eight status-code digit sequences, which is why it looked like flakiness rather
than a bug.

Two things to be able to say about this:

**The fix.** `TRANSIENT_STATUS` at `backend/services/job_runner.py:54` now
requires the digits to be labelled:

```python
TRANSIENT_STATUS = re.compile(r"\b(?:http|status|code)\s*[:=]?\s*(408|409|425|429|500|502|503|504)\b")
```

The docstring under `is_transient` (`job_runner.py:64`) records the reasoning in
the code itself, so nobody removes the prefix group later thinking it is noise:
"A bare three-digit match would classify any message that happened to contain
those digits, including artifact identifiers, as retryable."

**Yes, it is pinned — but be precise about how.**
`test_status_digits_inside_identifiers_do_not_trigger_a_retry`
(`test_pipeline.py:499`) exists precisely for this, and its first parametrised
case is the literal UUID `429e4567-e89b-12d3-a456-426614174000`. That turns a
probabilistic failure into a deterministic one: revert the classifier to a
substring test and that case fails every single run rather than one in six. That
conversion — from a flaky test to a certain test — is the actual point of the
regression test, and it is a good thing to say if you are asked how you handle
intermittent failures.

What the UUID case does **not** catch is the weaker mutation of dropping only
the `(?:http|status|code)` label group while keeping the word boundaries. As
covered in section 1 and section 5, `\b429\b` does not match inside `429e4567`,
so that parameter survives it. The two prose parameters catch it. Volunteering
that distinction is stronger than claiming the UUID case covers everything,
because it shows you went and checked rather than assuming.

The broader lesson, if you want to state it: the bug was not really in the
regex. It was in classifying a *structured* thing (an HTTP status) by pattern
matching on *unstructured* text (a formatted exception message). The regex
narrows the window; it does not close it. `"code 502"` inside a quoted upstream
message would still match. The properly robust version would carry the status
code on the exception object rather than in its string, and `is_transient`
already does that for real exception types at `job_runner.py:68`
(`isinstance(error, TRANSIENT_EXCEPTIONS)`). The string path is the fallback for
errors that come back as text.

`TestProviderFailureClassification` (`test_pipeline.py:160`) is the other end of
that same argument, and it is worth mentioning in the same breath. It exists
because the *type* information was being thrown away when the provider wrapped
an exhausted retry loop in an `LLMError`, leaving the string path as the only
signal — for exceptions whose string is empty. The fix there was to put the
class name back into the message, which is a patch on the same weakness rather
than a cure for it. Saying that out loud is more convincing than pretending the
classifier is now correct.

---

## 8. `test_seams.py` — the dependency-injection proof

631 lines, 20 tests, eight classes. **This is the file to put on screen.** It
answers "is your dependency injection real, or is it constructor parameters
nobody ever passes?" Every test in it passes a collaborator that does not exist
in production, and the production code runs unchanged.

There is one thing to notice before any of the tests: **there is no
`unittest.mock` anywhere in this file, or in the suite at all.** No patching of
imports, no `Mock()`, no `patch` decorators. Substitution happens by passing an
object into a constructor.

That claim needs one honest qualification, which is new. Three of the newer
classes do use pytest's `monkeypatch`, and it is worth knowing exactly what for:

- `TestProgressAttribution` uses `monkeypatch.setattr` on
  `backend.services.job_runner.publish` and `monkeypatch.setitem` on
  `JobExecutor.HANDLERS`. The first replaces the *event transport*, which has no
  constructor seam because it is a module-level function; the second registers a
  test handler in a dictionary that exists to be registered into.
- `TestRetryDispatch` uses the same `setitem` on `HANDLERS`, and injects its
  dispatcher through the constructor (`JobExecutor(database, dispatch=...)`).

So the accurate sentence is: **every collaborator that a class owns is injected
through its constructor; the two things patched are a module-level function and
a registry.** That is a better answer than an absolute claim, and it survives
someone opening the file and reading it.

If asked why injection matters: patching tests the code you have; injection
tests the code you designed. A test that patched
`backend.services.generators.get_provider` would still pass if the class had a
hard dependency on OpenRouter buried in a method.

### `RecordingProvider`, lines 21-51

```python
class RecordingProvider(LLMProvider):
    """A provider that answers from a script and remembers what it was asked."""

    name = "recording"
    supports_audio = True

    def __init__(self, text: str = "recorded", model: Optional[object] = None) -> None:
        self.text = text
        self.model = model
        self.prompts: List[str] = []
        self.contexts: List[Optional[str]] = []
```

A third implementation of `LLMProvider`, alongside `OfflineProvider` and
`OpenRouterProvider`. It does two things at once: it answers from a script, and
it records what it was asked.

`complete` (line 33) appends the prompt and context to its lists and returns
`self.text`. `complete_as` (line 38) does the same and returns `self.model`, or
raises `LLMError("no scripted model")` if none was scripted. `transcribe`
(line 50) returns the text — it overrides the base class's default, which raises
`LLMError` (`backend/llm/base.py:43`).

The recording half is what makes the test at line 88 possible. Without it you
could only assert on what came out; with it you can assert on what went in,
which is where prompt-construction bugs live.

Note that it subclasses `LLMProvider`, which is an `ABC` with two
`@abstractmethod`s. That is not decoration: if the interface grew a third
abstract method, this class would fail to instantiate and every test in this
file would error. That is the desired behaviour — a widened interface should
break the fakes, because it means the abstraction changed.

Two subclasses appear inline inside tests — `CancellingProvider` at line 143 and
`OneQuestionPerBatch` at line 170 — each overriding `complete_as` with a
per-schema script. Defining them inside the test body keeps the script next to
the assertion it exists for.

### The `core` fixture, lines 54-58

```python
@pytest.fixture
def core() -> KnowledgeCore:
    from backend.tests.conftest import SAMPLE_CORE
    return KnowledgeCore(**SAMPLE_CORE)
```

A real `KnowledgeCore` object rather than a dictionary, because that is what
`ArtifactGenerator.generate` expects and it calls `.model_dump_json()` on it.

### `TestProviderSubstitution` (line 61)

Class docstring: "Any provider can stand in for any other without callers
noticing." This is the Liskov claim, stated and then demonstrated three ways.

**`test_a_generator_accepts_any_provider`** — `test_seams.py:65`. Builds a real
`QuizModel` with six questions, wraps it in a `RecordingProvider`, and runs the
real `ArtifactGenerator` against it:

```python
provider = RecordingProvider(model=quiz)
generated = await ArtifactGenerator(provider).generate("quiz", core)

assert generated is quiz
assert core.title in (provider.contexts[0] or "")
```

Two assertions, two different claims.

`generated is quiz` — identity, not equality. The exact object the fake returned
came back out of `generate` unchanged. That proves the generator did not
re-serialise, re-parse or re-wrap it. If someone added a normalisation pass
inside `generate`, the identity assertion would catch it even though an equality
assertion would not.

`core.title in provider.contexts[0]` proves the knowledge core actually reached
the provider as context. The generator serialises it with
`core.model_dump_json()` at `backend/services/generators.py:232` and passes it
as the `context` argument. If somebody changed that to pass only the summary, or
forgot the context entirely, the recorded context would not contain
"Distributed Systems" and this fails.

**What it would take to break this seam.** Change `ArtifactGenerator.__init__`
from `self._provider = provider or get_provider()`
(`backend/services/generators.py:213`) to `self._provider = get_provider()`. The
constructor parameter would become decorative, the test would run against the
offline provider instead, and `generated is quiz` fails because the offline
provider returns its own quiz. That single line is the seam.

**`test_instructions_reach_the_provider`** — `test_seams.py:88`.

```python
provider = RecordingProvider(text="# Notes\n\n" + "content " * 60)
await ArtifactGenerator(provider).generate("notes", core, "focus on quorums")

assert "focus on quorums" in provider.prompts[0]
assert "take precedence" in provider.prompts[0]
```

This is the recording half of the fake earning its place. It inspects the
**prompt**, which no other test in the suite can do — `test_pipeline.py:425`
checks that instructions are stored on the artifact, but storing them and
sending them are different things, and a user whose steering was persisted but
never sent would get a normal quiz with a label claiming it was steered.

The second assertion is the more interesting one. `ArtifactGenerator._steer`
(`backend/services/generators.py:333`) does not just concatenate:

```python
return (
    f"{prompt}\n"
    "--- USER INSTRUCTIONS (these take precedence over the rules above) ---\n"
    f"{instructions.strip()}\n"
)
```

The instructions go *after* the base prompt, with an explicit statement that
they win. That framing is a real behaviour: a model given "write 10-15
questions" followed by "give me 5 hard ones" with no precedence marker will
often obey the first. Asserting on `"take precedence"` pins the framing, not
just the presence of the text. Note also the `text` given to the fake is 488
characters — deliberately over the 200-character notes floor, so the test fails
on the prompt assertions if they break and not on validation.

**`test_the_offline_provider_satisfies_the_interface`** — `test_seams.py:98`.
Strengthened. It used to loop over four hard-coded type names. It now loops over
the constant:

```python
generator = ArtifactGenerator(OfflineProvider())
for target in sorted(GENERATED_TYPES):
    assert await generator.generate(target, core) is not None, target
```

Every type the API advertises, not a sample of them, and the `, target` on the
assertion means a failure names which one. The docstring gives the reasoning,
and it is a product argument rather than a testing one:

> A missing key is meant to degrade the results and nothing else, so a type the
> offline provider has no fixture for is a type that breaks outright on a
> machine with no model configured.

That is the whole promise of the offline provider. Adding a ninth artifact type
and forgetting to teach the offline provider about it now fails here rather than
on somebody's laptop.

It is also, indirectly, the justification for the whole suite. If the offline
provider did not satisfy the interface, running 172 tests against it would prove
nothing about production.

Two types in that set are worth knowing about specifically. `mindmap` is the
only one with a deeply nested schema (`MindMapRoot` → `MindMapBranch` →
`MindMapLeaf`, `backend/models/artifacts.py:119`), so it proves the offline
provider can satisfy a structured schema rather than only flat ones. `notes`
goes down the other branch of `generate` — no schema, plain `complete`, wrapped
by `_as_notes` (`generators.py:344`). And `exam` goes down the third branch
entirely, `_exam` at `generators.py:242`, which the old four-name list missed.

### `TestGenerationContract` (line 115)

Class docstring: "A generator rejects output that parses but would not help
anyone." A different kind of seam — here the fake is used to inject *bad* output
that a real model would only produce occasionally, which is exactly the case you
cannot test against a real model.

**`test_too_few_questions_is_rejected`** — `test_seams.py:119`. A `QuizModel`
with one question. It is schema-valid — `QuizModel.questions` is just a list, no
minimum — so Pydantic accepts it and the failure has to come from somewhere
else:

```python
with pytest.raises(GenerationError, match="at least 5 questions"):
    await ArtifactGenerator(RecordingProvider(model=thin)).generate("quiz", core)
```

That somewhere is `GeneratorSpec.validate` (`backend/services/generators.py:58`),
driven by `minimum_items=5` in the quiz spec at line 81. The docstring on
`validate` says it: reject artifacts that parse but would not help anyone. A
one-question quiz is not a quiz. Without this check the user gets an artifact
that technically exists and is useless, and no error anywhere.

Getting this from a real model would mean waiting for it to under-deliver.
Injecting it takes one line.

**`test_a_cancelled_exam_batch_is_not_absorbed`** — `test_seams.py:136`. The
most subtle test in the file, and the one worth studying most closely.

```python
class CancellingProvider(RecordingProvider):
    async def complete_as(self, prompt, schema, context=None):
        if schema is ExamSpec:
            return DEFAULT_EXAM_SPEC
        raise asyncio.CancelledError()

with pytest.raises(asyncio.CancelledError):
    await ArtifactGenerator(CancellingProvider()).generate("exam", core)
```

The fake is scripted per-schema: return a valid spec for the first call, then
cancel every question batch. That models a job being torn down mid-generation —
a worker shutting down, or the per-call timeout firing.

Exam generation (`backend/services/generators.py:242`) runs its three question
batches concurrently with `asyncio.gather(..., return_exceptions=True)` and
drops any batch that failed, building the exam from the rest. That is right for
a batch that errored: two good batches beat no exam. It is wrong for
cancellation, because cancellation means the whole job is being killed, and
absorbing it produces a partial exam that looks like a real result.

The check is at `generators.py:266`:

```python
for result in results:
    if isinstance(result, asyncio.CancelledError):
        raise result
```

The comment above it (`generators.py:253-255`) explains the trap, and this is
the part to be able to say: `asyncio.CancelledError` inherits from
`BaseException`, not from `Exception`, since Python 3.8. So `except Exception`
does not catch it and `isinstance(result, Exception)` does not match it. The
code deliberately classifies on `BaseException` at line 272 — `if
isinstance(result, BaseException): continue` — because that is what `gather`
hands back, and an `Exception` check would let a `CancelledError` fall through
to `questions.extend(result)` where it would be treated as a list of questions.

`CoreMerger.merge` (`backend/services/merger.py:101`) has the identical guard
for the identical reason, and so does `TextCleaner._repair`
(`backend/pipeline/cleaning.py:155`), which is a good thing to notice: three
places in the codebase run fan-out under `gather` and all three classify on
`BaseException`.

**How this test fails.** Delete the re-raise loop at `generators.py:266` and the
three cancelled batches are dropped, `questions` is empty, and the code raises
`GenerationError("Expected at least 10 exam questions, got 0")` instead. That is
a different exception type, so `pytest.raises(asyncio.CancelledError)` fails.
The failure message would be readable and the cause obvious.

**`test_an_exam_built_from_too_few_questions_is_rejected`** — `test_seams.py:153`.
New, and the complement to the one above. `OneQuestionPerBatch` returns a
`QuestionBatch` with exactly one question for every batch, so the exam assembles
from three questions and nothing raises along the way. The floor at
`generators.py:277` (`MIN_EXAM_QUESTIONS = 10`, `generators.py:30`) is what
turns that into a `GenerationError`.

The docstring is the important part, and it names the failure mode rather than
the mechanism:

> A batch that fails is dropped, so a thin exam is the quiet failure mode.
> Nothing raises when two of the three batches go missing: the exam is assembled
> from whatever came back and commits as a finished artifact. The floor is what
> turns three questions into an error instead of a final exam somebody sits.

Read the three exam tests as a set, because together they describe a complete
policy for partial results:
`test_a_cancelled_exam_batch_is_not_absorbed` says cancellation is never
partial; this one says a partial result below the floor is an error;
`test_pipeline.py:329` says a result above the floor is renumbered and typeset.
Each of the three would pass against an implementation that got the other two
wrong.

**`test_notes_below_the_length_floor_are_rejected`** — `test_seams.py:188`.

```python
with pytest.raises(GenerationError, match="at least 200 characters"):
    await ArtifactGenerator(RecordingProvider(text="# Too short")).generate("notes", core)
```

The other half of the contract. Notes have no schema — they are Markdown — so
the only quality signal available is length, and `minimum_characters=200` on the
notes spec (`generators.py:129`) is the floor. Eleven characters is not study
notes. Note this goes through the `complete` branch and `_as_notes`
(`generators.py:344`), which builds a `NotesModel` from the text, and *then*
`spec.validate` measures `body`.

Together these four tests describe the whole validation contract: minimum item
counts for structured types, a minimum question count for the assembled exam, a
minimum length for prose, and cancellation is never a partial result.

### `TestHandlerInjection` (line 195)

Class docstring: "Handlers depend on their collaborators, not on how those are
built." One test, and it is the deepest injection in the file.

**`test_a_generate_handler_uses_the_injected_generator`** — `test_seams.py:199`.

```python
handler = GenerateHandler(
    database=database,
    generator=ArtifactGenerator(RecordingProvider(model=quiz)),
)

row = database.insert("jobs", {...})[0]
bundle = await handler.run(JobModel(**{**row, "status": "running"}))

assert bundle.artifacts[0].content["data"]["title"] == "From a fake"
assert len(bundle.edges) == 1
```

Read what is real here and what is not, because that is the point of the test.

**Real:** the database (this test's own SQLite file), the job row, the
`JobModel`, `SourceResolver` — which does a genuine query and turns the stored
`knowledge_core` row into a `KnowledgeCore` — `build_context`, `ExportService`,
and `bundle`, which constructs the `JobBundle` with its artifact and its
provenance edge.

**Fake:** the model, two layers down. `RecordingProvider` is inside
`ArtifactGenerator`, which is inside `GenerateHandler`. Nothing was patched;
`GenerateHandler.__init__` (`backend/handlers/generate_handler.py:33`) takes
five optional collaborators and this test supplies two of them.

The `{**row, "status": "running"}` is a small necessity worth understanding: the
row was inserted with status `pending`, but `JobModel` is what a *claimed* job
looks like, so the test constructs the claimed form directly instead of going
through `claim_job`. That keeps the test focused on the handler.

`bundle.artifacts[0].content["data"]["title"] == "From a fake"` is the whole
proof. That string exists in only one place: the `QuizModel` the test built at
line 204. Its presence in the bundle means the injected generator was the one
that ran. `len(bundle.edges) == 1` confirms the provenance edge was built for
the single source.

**What it would take to break this seam.** In `GenerateHandler.__init__`, change
`self._generator = generator or ArtifactGenerator()` to
`self._generator = ArtifactGenerator()`, and the handler builds its own
generator holding whatever `get_provider()` returns — the offline provider — and
the title assertion fails with `"Quiz: Consensus" != "From a fake"`. The same
applies to `database`: hard-code `get_database()` and the handler would still
work here, because the singleton happens to point at the same file, so that
particular substitution is not proven by this test.

> **Worth knowing.** The injection here is partial by design. `merger` and
> `exporter` are not supplied, so real ones are constructed —
> `ExportService.__init__` (`backend/services/exports/__init__.py:59`) builds an
> `ExamPdfRenderer`, a `SlidesPptxRenderer` and calls `get_file_store()`. For a
> quiz that is harmless, because `ExportService.export` (line 69) returns `None`
> for types with no file form. But it does mean this test would go slower, not
> fail, if PDF rendering became expensive at construction time.

### The ingest stubs, lines 235-289

Four stub classes, all used by `TestStagedUploads`:

- `StubIngestion` (235) returns a `StoredSource` without copying anything into
  the file store. Note it does call `Path(file_path).stat().st_size`, so the
  staged file must genuinely exist — which is the point.
- `StubExtraction` (249) returns fixed text, or raises a configured exception.
  The constructor parameter `error` is what makes the failure test possible.
- `StubCleaner` (267) returns its input, from **both** entry points.
- `StubKnowledge` (284) returns the core it was handed. The real
  `KnowledgeExtractor` calls the model, possibly several times for a long
  document.

`StubCleaner` gained its second method in the rewrite, and its docstring is now
the most useful comment in the file:

> It mirrors both entry points deliberately. A stub that only implements the one
> method its current callers happen to use will keep passing after the real
> class grows a second, and the drift is invisible until a test that needs the
> other method is written.

That is exactly what happened. `TextCleaner` grew `clean_transcript` when the
document/transcript split was made; `StubCleaner` only had `clean`; the ingest
tests kept passing because they all used `md` sources, which take the document
path. A test with an `audio` source would have hit `AttributeError`. Now both
exist, and the routing itself is tested for real over in
`test_pipeline.py:245`.

This is also the stub named in section 1 as the reason the locale bug went
undetected: `async def clean(self, text): return text` means no ingest test ever
ran the real cleaner, so `_repair` was never entered by anything.

### `TestStagedUploads` (line 292)

Three tests about a resource-lifetime property that no other test in the suite
touches.

Four collaborators replaced, and `IngestHandler` takes exactly five constructor
parameters (`backend/handlers/ingest_handler.py:120`). The fifth, `validator`,
is deliberately *not* replaced, so the real `KnowledgeCoreValidator` runs against
`SAMPLE_CORE` in all three tests. That is why `SAMPLE_CORE` has to be a legal
core.

The class docstring, lines 293-298, states the stakes: "Without this every
ingested lecture leaves a full-size duplicate in the system temp directory for
as long as the machine stays up." A two-hour lecture recording is not a small
file.

The `staged` helper at line 300 is the important detail:

```python
@staticmethod
def staged(suffix: str = ".md") -> Path:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
```

It uses `tempfile.NamedTemporaryFile` with `delete=False`, which is *exactly*
what the upload endpoint uses at `backend/api/routes/projects.py:203`. That
matters because the deletion logic identifies its own files by shape, not by a
flag.

**`test_a_successful_ingest_removes_the_staged_upload`** — `test_seams.py:331`.
Stages a file, runs the handler, asserts the bundle reports success and
`not upload.exists()`. The deletion is in a `finally` block at
`ingest_handler.py:166`.

**`test_a_failed_ingest_removes_the_staged_upload`** — `test_seams.py:340`.
Configures `StubExtraction(error=RuntimeError("unreadable"))`, asserts the error
propagates, and asserts the file is gone anyway. This is why the cleanup is in a
`finally` rather than at the end of the happy path. The failure case is the one
that leaks in real systems, because it is the one nobody writes by hand.

Note what is *not* in the `try` block: `self._store(payload, ...)` at
`ingest_handler.py:171` runs before it. Its docstring explains: until it
returns, the staged upload is the only copy there is. Deleting the staged file
before the durable copy exists would lose the user's upload entirely. That
ordering is not directly asserted by any test, which is worth being honest about
— but reading the two tests together with that comment is how you would explain
it.

**`test_a_callers_own_file_is_never_deleted`** — `test_seams.py:350`. The
complement, and the reason the deletion logic is as fussy as it is.

```python
theirs = tmp_path / "my-lecture.md"
theirs.write_text("# Lecture\n\nConsensus is hard.")

await self.handler(core).run(self.job(database, project, str(theirs)))

assert theirs.exists()
```

A file in a directory of the caller's own, with a name of their own. Ingest must
read it and leave it alone. The guard is `_discard_staged_upload`
(`ingest_handler.py:213`), which requires **three** things before unlinking:

```python
path = Path(source_ref)
if not path.name.startswith(tempfile.gettempprefix()):
    return
if path.parent != Path(tempfile.gettempdir()):
    return
if not path.is_file():
    return
```

The file must be named with the temp-file prefix (`tmp` on this platform), must
sit directly in the system temp directory, and must exist. `my-lecture.md` in
pytest's `tmp_path` fails the first two. The docstring is blunt about the
trade-off: "deleting the wrong file here is far worse than leaking one."

Weaken any of the three checks and this test fails. Weaken it to "delete
anything under `/tmp`" and it still passes — because pytest's `tmp_path` is
under `/private/var/folders/...` on macOS, not under the temp directory the
prefix check uses. So be aware the test constrains the guard but does not pin
every branch of it independently.

### `TestEventBusIsolation` (line 360)

New. One test, and it closes one of the more alarming surviving mutations: making
`InProcessEventBus._deliver` (`backend/services/events.py:119`) broadcast every
project's events to every subscriber passed the entire old suite, because every
event test had exactly one project in it.

The class docstring is worth quoting in full, because it explains why a
single-project test can never find this:

> A subscriber is subscribed to one project, not to the bus. Every open canvas
> holds a socket, and the bus is the only thing keeping one workspace's job
> progress, artifact names and chat replies out of another's. Delivery is by
> project id, so widening the lookup leaks everything at once and looks like
> nothing at all in a single-project test.

The helper at lines 370-376:

```python
@staticmethod
async def first_event(bus, project_id: str):
    """Subscribe, hand back the first event delivered, and unsubscribe."""
    async with aclosing(bus.subscribe(project_id)) as stream:
        async for event in stream:
            return event
    return None
```

`contextlib.aclosing` around the async generator is the detail to notice. Return
from inside `async for` leaves the generator suspended, and without `aclosing`
its cleanup — which is what removes the subscriber's queue from the bus — would
run whenever the garbage collector got round to it. In a test that asserts about
who is subscribed, "eventually" is not good enough.

**`test_a_subscriber_never_sees_another_projects_events`** — `test_seams.py:379`.

```python
watcher = asyncio.create_task(self.first_event(bus, "project-a"))
await asyncio.sleep(0.05)

bus.publish("project-b", make_event("job.completed", "project-b", {"job_id": "theirs"}))
await asyncio.sleep(0.05)
assert not watcher.done(), "a subscriber to project-a was handed project-b's event"

bus.publish("project-a", make_event("job.completed", "project-a", {"job_id": "mine"}))
delivered = await asyncio.wait_for(watcher, timeout=5)

assert delivered["project_id"] == "project-a"
assert delivered["data"]["job_id"] == "mine"
```

The structure is worth walking through, because proving a negative in an async
test is fiddly and this does it cleanly.

A task subscribes to `project-a` and parks. The first `sleep(0.05)` lets it
actually reach the `async for` — without it the task might not have subscribed
yet, and the test would pass for the wrong reason. Then an event is published to
`project-b` and another 50 ms passes. `assert not watcher.done()` is the
negative: the watcher is still waiting, so it was not handed the other project's
event. Then the *right* event is published and the watcher completes, and both
its project id and its payload are checked.

The two assertions at the end matter as a pair. Checking only that something
arrived would pass against a bus that delivered `project-b`'s event to
`project-a`'s subscriber late. Checking the payload as well means the event that
arrived is provably the one that was meant for this subscriber.

`assert not watcher.done()` also carries a message — "a subscriber to project-a
was handed project-b's event" — which is the whole bug in one sentence at the
point of failure.

The two 50 ms sleeps are the only sleeps in the suite, and they are the reason
this file takes marginally longer than it used to. That is the honest price of
proving a negative: there is no way to observe that something has *not* been
delivered except to wait a while and look.

`bus.bind_loop(asyncio.get_running_loop())` at line 383 is doing what the
lifespan does in production (`backend/main.py:66`), and is why this test needs
no app.

### `TestFileStoreContract` (line 399)

Class docstring: "Signed links are the credential, so the signature has to be
load-bearing." Four tests, no database, no app — just `FileStore` constructed
directly with an explicit root and secret, which is itself a small injection
seam (`backend/services/files.py:33` takes both as optional parameters and falls
back to settings).

**`test_a_link_survives_a_round_trip`** — `test_seams.py:402`. Stores bytes,
mints a signed URL, pulls `expires` and `signature` back out of the query string
by hand, and asserts `store.verify(key, expires, signature)` is true. Parsing
the URL by string surgery is deliberate — it checks the URL *format*, not just
the signing function. If `signed_url` changed its parameter names or ordering,
the split at line 409 would produce garbage and the test would fail, which is
correct, because `serve_file` (`backend/api/routes/files.py:20-21`) reads those
exact parameter names.

**`test_an_expired_link_is_refused`** — `test_seams.py:414`.

```python
assert not store.verify("k", 0, store.sign("k", 0))
```

The signature is genuinely correct — the test signs it with the same store — and
verification still fails, because the expiry is Unix epoch zero. That isolates
the time check at `backend/services/files.py:115` from the signature check at
line 117. A version that only compared HMACs would pass a signature test and
fail this one.

**`test_a_key_signed_elsewhere_is_refused`** — `test_seams.py:420`. Two stores
with different secrets. A signature from one must not verify in the other, with
a far-future expiry so time is not the reason. This is the property that makes
rotating `SIGNING_SECRET` invalidate every outstanding link — and it is the same
property `TestStartupGuard` in `test_api.py:898` depends on when it insists the
key be private in the first place.

**`test_keys_cannot_escape_the_store_root`** — `test_seams.py:428`.

```python
with pytest.raises(StorageError):
    store.resolve("../../etc/passwd")
```

`resolve` (`files.py:75`) strips leading slashes, joins to the root, calls
`.resolve()` to collapse the `..` segments, and then checks
`is_relative_to(self.root)` at line 82. Doing the check after resolution rather
than by string inspection is what makes it robust — a blocklist of `".."` would
miss symlinks and encoded variants, while path resolution handles both.

Every read and write in `FileStore` goes through `resolve`, which is why this
one test covers `put`, `put_bytes`, `copy_to`, `delete`, `exists`, `size_of` and
`open_path`. `test_api.py:973` checks the same guard from `put_bytes`, and
`backend/api/routes/artifacts.py:105` is where a caller-supplied key would have
reached it — which is the connection between this test and the export-repointing
security test at `test_api.py:599`. Even if the `binary` guard were removed,
`resolve` would still block a key that escaped the root. Defence in depth, and
worth saying so.

### The job-runner fakes, lines 436-509

Five small classes support the last two test classes. They are worth reading as
a group, because each exists to make a specific kind of assertion possible.

- `claimed_job` (436) is the same insert-then-claim helper as
  `test_pipeline.py:61`, duplicated here rather than imported to keep the files
  independent.
- `Rendezvous` (444) is an async barrier: every arrival waits until all of them
  are in. Its docstring explains why it is a separate object rather than a
  counter on the handler — "a handler is copied per job: a counter kept on the
  handler would be copied too, and the runs would never meet." That sentence is
  the whole subject of `TestProgressAttribution` stated sideways.
- `PausingHandler` (464) reports one stage, waits for the rendezvous, then
  reports another. Its docstring: "The wait builds the interleaving rather than
  hoping for it." That is the difference between a concurrency test and a
  concurrency hope.
- `FailingHandler` (483) raises whatever the test hands it.
- `RecordingDispatcher` (493) records both the job id it was given **and the
  status of that row at the moment it was called**. The second list is the
  clever part, and its docstring says why: "a job dispatched before its requeue
  is committed would be claimed by a worker that still sees `running`."

### `TestProgressAttribution` (line 512)

New. Two tests on a bug class that is invisible in any single-job test.

The class docstring names the failure precisely, and it is worth reading twice
because the obvious guess about what goes wrong is not what goes wrong:

> One handler serves every worker, so a reporter must not be attached by
> mutation. A mutated reporter is not a lost event: the job that attached last
> owns the callback, so a job still in flight publishes its progress into
> somebody else's project under somebody else's job id.

Not a dropped event — a *misattributed* one. Progress from job A appearing on
job B's node, in project B's canvas.

The mechanism is `JobExecutor.handler_for`
(`backend/services/job_runner.py:101`), which builds one handler per job type
and reuses it, because construction opens clients. `execute` then attaches a
per-job progress callback at line 129 via `handler.with_progress(...)`, and
`JobHandler.with_progress` (`backend/handlers/base.py:37`) does
`attached = copy.copy(self)` before assigning. Changing that to
`self.progress = reporter` is one character short of the same thing and is
completely wrong.

**`test_concurrent_jobs_report_under_their_own_identity`** — `test_seams.py:543`.
Two projects, one shared `PausingHandler` registered into `JobExecutor.HANDLERS`,
and two jobs executed concurrently under `asyncio.gather`. The `Rendezvous(2)`
guarantees that both jobs are inside `run` with their reporters attached before
either publishes its second stage — which is the exact window in which a mutated
reporter would be overwritten.

The assertion is an exact sorted comparison of four events:

```python
assert self.progress_events(published) == sorted([
    (project["id"], str(here.id), "before the pause"),
    (project["id"], str(here.id), "after the pause"),
    (elsewhere["id"], str(there.id), "before the pause"),
    (elsewhere["id"], str(there.id), "after the pause"),
])
```

Four events, each tagged with the project and job it belongs to. Against a
mutating `with_progress`, both "after the pause" events carry whichever job
attached last, and the comparison fails with a diff that shows exactly that.
`progress_events` (line 532) filters to `JOB_PROGRESS` and sorts, so the test
does not depend on which of the two jobs happens to be scheduled first.

**`test_attaching_a_reporter_leaves_the_shared_handler_alone`** —
`test_seams.py:571`. The unit-level statement of the same rule, and it reads
like a specification:

```python
attached = shared.with_progress(lambda stage, percent: None)

assert attached is not shared
assert "progress" not in vars(shared)
assert executor.handler_for(JobType.GENERATE.value) is shared
```

Three assertions, three distinct claims. The returned handler is a different
object. The shared one has no `progress` in its instance dictionary — note
`vars()`, not `getattr`, because `JobHandler.progress` is a class attribute
(`backend/handlers/base.py:35`) and `getattr` would find it either way. And the
executor still hands back the same shared instance afterwards, so the copy did
not displace it in the cache.

That middle assertion is the one worth pointing at. It is the difference between
"the copy has the reporter" and "the original does not", and only the second is
the property that matters.

### `TestRetryDispatch` (line 585)

New. Two tests, and they close the gap between "the row says pending" and "the
job actually runs again".

The class docstring is the argument:

> A requeued job only runs again if somebody is told it is queued. The local
> pool polls and would find it eventually; Celery workers only ever run what
> they are sent, so without this the retry waits on the periodic drain and,
> without that, forever.

That is why `_redispatch` exists at `backend/services/job_runner.py:205`. The
old suite tested that `fail_job` returned `"pending"` (`test_pipeline.py:503`)
and stopped there, which proves the bookkeeping and nothing about the work.

**`test_a_retryable_failure_is_dispatched_again`** — `test_seams.py:595`.
Registers a `FailingHandler(TimeoutError("upstream timed out"))` — a genuinely
transient error, and one caught by the *type* half of `is_transient` rather than
the string half — injects a `RecordingDispatcher` through
`JobExecutor(database, dispatch=dispatcher)`, and asserts:

```python
assert await JobExecutor(database, dispatch=dispatcher).execute(job) is False

assert database.get_job(job.id)["status"] == "pending"
assert dispatcher.job_ids == [str(job.id)]
assert dispatcher.statuses == ["pending"]
```

Four claims. `execute` returns `False` because nothing committed. The row is
back to `pending`. The dispatcher was called exactly once with that job id. And
— the last line, which is the one worth explaining — the row was already
`pending` **at the moment the dispatcher was called**.

That last assertion pins an ordering that has no other symptom until it bites in
production. `_record_failure` (`job_runner.py:174`) calls `fail_job` first and
only then `_redispatch`. Swap those two lines and a Celery worker could pick the
job up and find a row still marked `running`, which `claim_job` will not claim —
so the dispatch is silently wasted and the job sits until the reaper notices.
`RecordingDispatcher` capturing the status at call time is what makes that
visible; a dispatcher that only recorded ids would pass either way.

**`test_a_permanent_failure_is_not_dispatched_again`** — `test_seams.py:615`.
The control. A `FailingHandler(ValueError("target_type is required"))` — one of
the exact strings in the permanent list at `test_pipeline.py:486` — must leave
the row `failed` and must call the dispatcher **zero** times:

```python
assert database.get_job(job.id)["status"] == "failed"
assert dispatcher.job_ids == []
```

Without this, a fix for the previous test that re-dispatched unconditionally
would pass, and every permanent failure would be retried at full token cost
until the attempt limit ran out. This is the same shape as
`test_a_youtube_url_still_validates` and
`test_a_genuine_youtube_url_passes`: whenever a test asserts that something
happens, there needs to be a sibling asserting when it does not.

---

## 9. What the suite still does not cover

Be able to say this list without being prompted. It is a stronger answer than
claiming broad coverage, and it is a much stronger answer after a mutation pass,
because you can say *how* you know.

### The measurement

Re-measured with `coverage` run over the whole suite. **83% of 3,514 statements,
608 missed.** The earlier figure was 77%, so closing the twenty-one surviving
mutations moved it six points — but the number is not the point and you should
not lead with it. Coverage says a line ran; the mutation pass says a line
*matters*. The two lists below disagree in places, and where they do, the
mutation result is the one to trust.

Coverage is still concentrated rather than even. The parts that are effectively
complete:

| Module | Cover |
| --- | --- |
| `backend/api/deps.py` | 100% |
| `backend/models/artifacts.py` | 100% |
| `backend/services/flow/plan.py` | 99% |
| `backend/services/flow/engine.py` | 98% |
| `backend/api/schemas.py` | 97% |
| `backend/core/config.py`, `backend/pipeline/cleaning.py` | 96% |
| `backend/llm/offline.py` | 95% |
| `backend/services/database.py` | 91% |

And the parts that are not:

| Module | Cover | Why |
| --- | --- | --- |
| `backend/tasks.py` | 0% | Celery task definitions; never imported by a test |
| `backend/pipeline/extraction.py` | 35% | No test reads a real PDF, PPTX or DOCX |
| `backend/api/routes/chat.py` | 47% | Module imports; no route body ever entered |
| `backend/pipeline/media.py` | 54% | No audio or video is ever processed |
| `backend/celery_app.py` | 61% | Only the short-circuit branch runs |
| `backend/handlers/sources.py` | 63% | `ArtifactFlattener` has one type exercised |
| `backend/pipeline/knowledge.py` | 63% | The real extractor is stubbed everywhere |
| `backend/services/merger.py` | 68% | Fan-in merge runs; its failure paths do not |
| `backend/pipeline/ingestion.py` | 70% | The guard is well covered; the download is not |
| `backend/llm/openrouter.py` | 71% | The retry loop runs; transcription and streaming do not |
| `backend/services/events.py` | 74% | `RedisEventBus` is never constructed |

### The specific gaps, in the order worth admitting them

**Celery and Redis are never exercised.** `backend/tasks.py` is at exactly 0% —
it is never imported, because `dispatch_mode()` resolves to `local` in every
test. `RedisEventBus` (`backend/services/events.py:130`) is never constructed.
The cross-process paths — the ones that matter for the "several workers" story
the concurrency tests support — are only tested against threads in one process.
This is the largest single hole and the first thing to volunteer.

Note the shape of it, though: `TestRetryDispatch` in `test_seams.py:585` exists
*because* of Celery, even though no Celery runs. It pins the contract the Celery
path depends on — that a requeued job is dispatched, and dispatched only after
its row is committed — through the injected dispatcher. That is the right way to
test a boundary you cannot stand up in CI, and it is worth saying so rather than
just conceding the gap.

**The chat feature has no tests at all.** `backend/api/routes/chat.py` is 204
lines. Its module body is imported, because `main.py` mounts the router, which
is where the 47% comes from — but neither route body is ever entered:
`POST /api/chat` (lines 109-150) and `GET /api/chat/{project_id}/history`
(163-167) are both untouched. That includes the intent classifier, the artifact
context window and the rebuild path that can queue a generate job.

**The real model provider is only partly exercised.** This used to read "never",
and that is no longer true. `TestProviderFailureClassification`
(`test_pipeline.py:160`) constructs a real `OpenRouterProvider`, drives `_send`
through its retry loop against a patched transport, and drives `complete_as`
against a malformed answer. `backend/llm/openrouter.py` is at 71%.

What remains untested there: audio transcription (`openrouter.py:137-153`), the
successful-response path including the JSON repair in `backend/llm/schema.py`'s
`TruncatedResponse` handling, and the concurrency semaphore. And no test ever
makes a real HTTP request, which is the direct cost of the offline-provider
design: the suite proves the system is correct given a provider that behaves,
and proves little about the provider itself.

**Real extraction never runs.** No test reads an actual PDF, PPTX, DOCX or audio
file. `backend/pipeline/extraction.py` is at 35% and `backend/pipeline/media.py`
at 54%; both are stubbed out in `test_seams.py` and never invoked for real.
`test_api.py:90` creates an ingest job for a Markdown file and reads the staged
bytes back, but nothing runs the extraction on them.

Worth pairing this with the `TestCleaning` story from section 1: the cleaning
stage is now covered because the *outputs* of extraction are what it consumes,
and those could be written by hand as `PDF_TEXT`. The same trick would work for
extraction itself only if you shipped a fixture PDF, which is the obvious next
test to write.

**The renderers are barely asserted.** `ExamPdfRenderer` is at 89% and
`SlidesPptxRenderer` at 95% by line count, but almost all of that comes from
being *run* as a side effect of `test_pipeline.py:313`, not from anything
checking what came out. The one real assertion is
`test_an_exam_commits_its_rendered_booklet_alongside_the_questions`
(`test_pipeline.py:329`), and even that checks the file exists and has a
non-zero size that matches the recorded one — not that the PDF is a readable
exam. Markdown export runs for notes, study_guide and cheatsheet and nothing
checks the file's contents at all. `ExportService.export` swallows all
exceptions by design (`exports/__init__.py:84`), so a subtly broken renderer
would produce a passing suite and unreadable downloads.

**Several read endpoints are untested.** Confirmed by line-level coverage, not
guessed:

| Endpoint | Uncovered lines |
| --- | --- |
| `GET /api/vault` | `artifacts.py:132-147` |
| `GET /api/artifacts/{id}/lineage` | `artifacts.py:44-49` |
| `GET /api/projects/{id}/artifacts` | `projects.py:109-110` |
| `GET /api/jobs` (the list form) | `jobs.py:93-104` |
| `GET /api/projects/{id}/flow/runs` | `flows.py:123-124` |
| `GET /api/projects/{id}/flow/runs/{id}` | `flows.py:140-146` |
| `POST /api/chat`, `GET /api/chat/{id}/history` | `chat.py:109-150, 163-167` |

Every one of those is a read, and every one of them calls `require_project`
before returning anything — which *is* tested, thoroughly, through the endpoints
that do have tests. So the ownership property holds for them by construction.
What is untested is their shape: what they return, in what order, and with what
limit.

`FlowEngine.list_for_project` (`backend/services/flow/engine.py:247`) is a
special case worth knowing, because it is exercised heavily — every scheduling
test calls it to find the run id it just created — while the route that wraps it
is not.

**`KnowledgeCoreValidator` is only exercised on the happy path.** It runs inside
the three staged-upload tests, always against `SAMPLE_CORE`, which is valid. No
test feeds it a core containing `$`, or an empty `key_facts` list, so the two
`raise` statements at `backend/handlers/ingest_handler.py:52` and `:63` never
execute. The markup rejection is unproven, which is a shame because it is a
one-line test to write and the class docstring makes a strong claim: "stray
LaTeX here corrupts every artifact derived from it."

**Authentication does not exist, so it is not tested.** `resolve_user`
(`backend/api/deps.py:14`) returns a constant. Every ownership test in
`TestSecurity` proves that the *ownership comparison* works; none of them proves
that a caller cannot claim to be somebody else, because in this deployment there
is nothing to claim. The `CLOSE_UNAUTHORIZED = 4401` branch in
`backend/api/routes/ws.py:23` is consequently dead code as far as the tests are
concerned.

**`WorkerPool` still has no direct test.** `reap_stale_jobs` is tested directly
at `test_pipeline.py:529` and `:540`, and `JobExecutor` is now well covered by
`TestProgressAttribution` and `TestRetryDispatch`. But the pool's own loop — the
idle backoff at `backend/services/job_runner.py:288`, the reaper's 60-second
timer at line 304, the shutdown path at line 279 — is only exercised
incidentally by whichever API tests happen to use the `client` fixture. The
`idle_client` fixture added in this pass turns the pool *off* for the tests that
cannot tolerate it, which is the right fix for those tests and also an
admission: the pool is a thing the suite works around rather than tests.

**Multi-process SQLite is untested.** The concurrency tests use threads in one
process, which share the `RLock` in `Database` (`database.py:170`). Two separate
processes would rely on SQLite's own locking with the 30-second busy timeout set
at `database.py:149`, and nothing checks that. This is the same gap as the
Celery one seen from the storage side.

**The frontend has no tests.** These 172 are backend only. There is no test
runner configured in `frontend/package.json` and no `*.test.*` file anywhere
outside `node_modules`.

### The honest summary

If you get one sentence for this section, use this one: *the suite covers the
orchestration completely and the edges hardly at all, which is the shape you get
when you design for injectable boundaries — everything inside the boundary is
cheap to test and everything outside it needs the real thing.* Then name the
three largest gaps: Celery, chat, and real file extraction.

And if you are asked what you would write next, the answer is short and specific
rather than aspirational: a fixture PDF through the real extractor, one
`KnowledgeCoreValidator` rejection test, and the six read endpoints. That is
perhaps an afternoon, and it is a better answer than "more integration tests".
