# 11 — The API layer

This is the outermost layer of the backend. Everything a browser can reach comes through
one of these nine files. It is also where five of the six security holes lived, and where
the sixth — a full-response SSRF through the YouTube ingest field — was let in, so if the
interview spends time anywhere, it will probably spend it here.

The layering rule for the whole backend is one-directional:

```
api  ->  handlers  ->  services / pipeline  ->  llm / models
```

Nothing lower ever imports anything higher. The API imports handlers and services; a
handler never imports a route; a service never imports a handler. The practical
consequence is that a route module is allowed to know about HTTP status codes and nothing
below it is. If you find yourself wanting to say "the handler returns a 403", that is a
sign the rule has been broken. It has not been broken here.

This layer used to be one file. `main.py` was 1,060 lines and contained every endpoint,
every request model and the identity function. It was split into `api/deps.py`,
`api/schemas.py` and seven route modules. `main.py` is now 199 lines and does almost
nothing but assemble the app: middleware, exception handlers, a startup guard on the
link-signing key, and a loop at `main.py:160` that includes each router.

Read the files in this order. `deps.py` first, because every route depends on it.

---

## 1. `backend/api/deps.py`

87 lines. Three things live here: who the caller is, how to get a database handle, and the
ownership checks. Every route in the system calls at least one of these.

### The imports

```python
"""Request dependencies: identity, database access, and ownership checks."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Header, HTTPException

from backend.services.database import Database, get_database
```

`deps.py:1-9`. Boring. `from __future__ import annotations` at line 3 makes every type
annotation a string at runtime rather than an evaluated expression, which is what lets the
file mention `Database` in a signature without paying an import cost per call. It appears
at the top of every file in this backend for consistency.

Note what is imported from FastAPI at line 7: only `Header` and `HTTPException`. This
module raises HTTP errors but does not define routes. That is deliberate — the ownership
rules are shared by HTTP routes and by the WebSocket handler, and the WebSocket handler
cannot use `Depends`.

### The single user id

```python
LOCAL_USER_ID = "local-user"
```

`deps.py:11`. One constant, referenced from `resolve_user` below and from the test fixtures
(`backend/tests/conftest.py:88`) so that a project created by a fixture is owned by the same
user the API will resolve.

### `resolve_user` — the auth bypass, and what stands there now

```python
def resolve_user(authorization: Optional[str]) -> str:
    """
    Identify the caller.

    This deployment serves a single local workspace, so there is no identity
    provider and every caller is that workspace's owner. Ownership is still
    recorded on each project and checked on every read, which is what keeps the
    queries correct and leaves one seam to replace if accounts are ever added.
    """
    return LOCAL_USER_ID
```

`deps.py:14-23`. This is the function that used to be the bug.

What it used to do: it inspected the `Authorization` header and, if the header string
contained the substring `mock-token` anywhere in it, it returned a fixed development user
id. That check ran in every deployment, not behind a debug flag and not behind an
environment variable. So the sentence "any request whose Authorization header contains the
text `mock-token` is authenticated as user X" was true in production as much as it was
true on a laptop. Anyone who had read the repository, or guessed, was that user.

What it does now: it ignores the header entirely and returns `LOCAL_USER_ID`.

That is worth being precise about when you explain it, because it is easy to overclaim.
This is not authentication. It does not verify anything. What it does is stop pretending.
Before, the code looked like it was checking a credential and was in fact checking nothing
in a way that a reader could miss. Now it is a function with a docstring that says, in
plain terms, that there is no identity provider and every caller is the same person. A
reviewer reading this file cannot form a false impression of the security posture, and
there is exactly one function to replace when accounts arrive.

**Worth knowing.** The `authorization` parameter is now unused. A linter would flag it.
It is kept because the signature is the seam: `get_current_user` below and the WebSocket
handler in `ws.py` both pass a header value in, and the day a real token is verified, the
change is inside this function body and nowhere else. If the parameter were removed, both
call sites would have to change too.

**The honest limitation to volunteer.** Because `resolve_user` returns the same id for
every caller, the four cross-tenant holes below — 1, 2, 3 and 5 — are not exploitable today.
There is only one user, so "another user's artifact" is a thing that can exist in the
database (the tests create such rows directly) but not a thing a second HTTP client can
create. The ownership model is real in the queries and vacuous in practice until an identity
provider exists. Say this yourself before you are asked. It is a much stronger position than
being caught claiming the fixes close an active attack.

Be equally precise about what that argument does *not* cover, because it is easy to overstate
in the other direction. Holes 4 and 6 are not ownership bugs. The arbitrary file read and the
SSRF both worked from a single-user install, against the caller's own project, and needed no
second user at all. "There is only one user" defuses the cross-tenant holes and defuses
nothing else.

### `get_current_user`

```python
def get_current_user(authorization: Optional[str] = Header(None)) -> str:
    """The authenticated caller's id."""
    return resolve_user(authorization)
```

`deps.py:26-28`. This is the FastAPI-facing wrapper. `Header(None)` tells FastAPI to pull
the `Authorization` request header and pass it in, defaulting to `None` when absent. Routes
write `user_id: str = Depends(get_current_user)` and get a string.

The reason there are two functions rather than one is that `Depends` only works inside the
HTTP request cycle. The WebSocket route at `ws.py:42` calls `resolve_user` directly, because
it has to authenticate before accepting the socket and there is no dependency injection at
that point.

### `get_db`

```python
def get_db() -> Database:
    """The shared database handle."""
    return get_database()
```

`deps.py:31-33`. A one-line indirection over the module-level singleton in
`backend/services/database.py:560`. It exists so routes can declare
`database: Database = Depends(get_db)`, which in turn means a test can override the
dependency if it wants to. In practice the tests do not override it; they reset the
singleton instead (`conftest.py:66-76`). The indirection is cheap and keeps the routes free
of direct singleton access.

### `require_project` — hole 2, the NULL owner

```python
def require_project(
    project_id: str,
    user_id: str,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """Load a project and assert the caller owns it."""
    database = database or get_database()
    project = database.get_project(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return project
```

`deps.py:36-51`. This is the single most-called function in the layer. Almost every route
starts with it.

Line 42 is a small convenience: the `database` argument is optional so that callers which
already have a handle can pass it, and callers which do not (the WebSocket route) get the
singleton. It avoids two versions of the function.

Line 43 loads the row. Lines 45-46 turn a missing project into a 404.

**Line 48 is the fix for hole 2.** It used to read, in effect:

```python
owner = project.get("user_id")
if owner and owner != user_id:
    raise HTTPException(403, ...)
```

Read that carefully. `if owner and ...` short-circuits when `owner` is falsy. A project row
whose `user_id` column is `NULL` comes back from SQLite as Python `None`, `None` is falsy,
so the whole condition was `False` and the function returned the project. A project with no
owner passed every caller's ownership check. It was readable by anyone, and every route
that gated on `require_project` — read, update, delete, artifacts, jobs, flows, chat,
WebSocket — inherited that.

What made it a real inconsistency rather than a theoretical one is that `list_projects`
disagreed. That endpoint (`projects.py:36`) filters with `("user_id", f"eq.{user_id}")`,
which compiles to `WHERE user_id = ?`. In SQL, `NULL = 'local-user'` is not true, so an
unowned project never appeared in a listing. Read said yes and list said no about the same
row. That is the shape of bug that survives a long time, because the UI never shows you the
row so you never think to test it.

The current line is a plain inequality: `project.get("user_id") != user_id`. `None` is not
equal to `"local-user"`, so an unowned project now raises 403 for everybody, which matches
what the listing already believed. The check is "the owner must be exactly this caller",
not "the owner must not be somebody else".

Where do unowned projects come from at all? The schema at
`backend/services/database.py:39` declares `user_id TEXT` with no `NOT NULL` constraint, so
any insert that omits the column produces one. The test at `test_api.py:566-577` creates one
deliberately and asserts both the 403 and the absence from the listing.

**Worth knowing.** A foreign project returns 403, not 404. That confirms to the caller that
the id exists, which is a small enumeration oracle. The alternative — returning 404 for
anything you do not own — hides existence but makes debugging harder and makes "you have
been removed from this project" indistinguishable from "this project was deleted". At this
scale, with opaque UUIDs, the trade is fine. It is the kind of thing an interviewer may
probe, and the right answer is that it was a choice, not an oversight.

### `require_artifact`

```python
def require_artifact(
    artifact_id: str,
    user_id: str,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """Load an artifact and assert the caller owns the project it belongs to."""
    database = database or get_database()
    artifact = database.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    require_project(artifact["project_id"], user_id, database)
    return artifact
```

`deps.py:54-67`. Artifacts have no owner column of their own. They belong to a project and
the project has the owner. So the check is one hop: load the artifact, then delegate to
`require_project` on its parent. Line 66 discards the returned project — it is called purely
for the exception it may raise.

This is why the NULL-owner fix mattered twice over. An artifact in an unowned project was
readable through `GET /api/artifacts/{id}` for the same reason the project was. The test at
`test_api.py:578-584` covers exactly that path.

### `require_project_artifact` — the function that closes holes 1 and 5

```python
def require_project_artifact(
    artifact_id: str,
    project_id: str,
    user_id: str,
    database: Optional[Database] = None,
) -> Dict[str, Any]:
    """
    Load an artifact the caller owns and assert it sits in the named project.

    Provenance edges are filed under a single project, so an edge to a parent
    living elsewhere would render as a dangling link on the canvas.
    """
    artifact = require_artifact(artifact_id, user_id, database)

    if str(artifact["project_id"]) != str(project_id):
        raise HTTPException(status_code=400, detail="Artifact belongs to a different project")

    return artifact
```

`deps.py:70-87`. This is the strictest of the three and the one the job and flow routes use.

It asks two questions. First, through `require_artifact` at line 82: do you own the project
this artifact lives in? That is the security question, and it produces 404 or 403. Second,
at line 84: is that project the same project you are writing into? That is a data-integrity
question, and it produces 400.

The second question is not about security. Both projects belong to you in the case it
catches. It exists because of the provenance model: when a generate job finishes it writes
a row into `artifact_edges` linking parent to child, and that row carries a single
`project_id`. If the parent lived in project A and the child in project B, the edge would be
filed under one of them and the canvas of the other would render a link to a node it cannot
see. The `str()` on both sides is defensive: ids come back from SQLite as text and arrive
from JSON as text, but a caller sending an integer id would otherwise compare unequal for
the wrong reason.

Returning 400 rather than 403 for the cross-project case is the honest code: nothing was
denied on grounds of permission, the request was simply incoherent.

---

## 2. `backend/api/schemas.py`

228 lines of Pydantic models. This file is the boundary where untrusted JSON stops being
untrusted. Two of the holes are closed here — and hole 4, which used to be closed only
halfway, is now closed completely — and a third, the SSRF, is deliberately *not* closed
here, which is the more interesting fact and has its own section below.

### Header

```python
from backend.models.artifacts import GENERATED_TYPES, SOURCE_TYPES

JOB_TYPES = frozenset({"ingest", "generate", "refine"})
```

`schemas.py:9-11`. `GENERATED_TYPES` is the set of the eight artifact types the system can
produce, derived at `backend/models/artifacts.py:148` from the keys of the `ARTIFACT_MODELS`
registry. `SOURCE_TYPES` at `models/artifacts.py:150` is the six input kinds. Deriving the
validation set from the registry rather than writing a second list means adding a ninth
artifact type cannot leave the API rejecting it.

`JOB_TYPES` at line 11 is local because there is no job registry to derive it from; the
three names are also the three keys of `REQUEST_MODELS` in `jobs.py:28`.

### Project models

```python
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
```

`schemas.py:14-16`. `min_length=1` rejects the empty string, which is otherwise a valid
`str` and produces a project with a blank name in the sidebar. The maxima are there so a
caller cannot write a megabyte into a name column.

```python
class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    canvas_state: Optional[Dict[str, Any]] = None
```

`schemas.py:19-22`. Every field optional, because PATCH is partial. Note line 22:
`canvas_state` is `Dict[str, Any]`, which is to say it is not validated at all beyond being
a JSON object.

**The honest limitation to volunteer.** `PATCH /api/projects/{id}` accepts and stores the
canvas verbatim. Nobody checks that the artifact ids inside its source nodes point at
artifacts in this project. A canvas can be saved naming an artifact the caller does not own.
The consequence is not a security hole — the flow routes re-check at run time, which is hole
5 below — but it is a usability defect: a bad id surfaces as a 403 when you press Run,
possibly days after you saved it, rather than as a validation error at save time. Validating
seeds on save is the obvious improvement and it has not been done.

```python
class ProjectResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    user_id: Optional[str] = None
    canvas_state: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

`schemas.py:25-32`. The response shape. It matters mostly as a projection: `create_project`
at `projects.py:56` builds it field by field from the database row, so a column added to the
table does not silently start appearing in API responses.

### `IngestRequest` — hole 4, the filesystem read, and the half that used to stay open

```python
class IngestRequest(BaseModel):
    """
    Where an ingest job is to get its source.

    The two references are different kinds of thing and never both: `source_ref`
    is a URL the pipeline fetches, and `staged_key` names an upload already
    sitting in the file store, which is where the upload endpoint puts one.
    """

    source_type: str
    source_ref: Optional[str] = None
    staged_key: Optional[str] = None
    original_name: str = "Untitled"
```

`schemas.py:35-47`. Read that field list against the one it replaced, because the difference
between them *is* the fix:

```python
    source_type: str
    source_ref: str
    original_name: str = "Untitled"
```

There used to be one reference field and it meant two different things depending on
`source_type`. For an upload it was the filesystem path of the temp file the API had just
buffered. For YouTube it was the video URL. One field, two meanings, and only one of the two
meanings was ever constrained. That overloading is what made hole 4 possible, and it is why
half of hole 4 survived the fix that was supposed to close it.

Now there are two fields and each means exactly one thing. `source_ref` is a URL the
pipeline will fetch. `staged_key` is a key in the file store, minted by the upload endpoint,
naming bytes that are already sitting on the shared data volume. Neither field can carry a
path on the server's disk: a path is not an http(s) URL, and it is not a storage key either,
because `UploadStaging` accepts only the exact three-segment shape it writes. There is no
longer a field to put `/etc/passwd` in.

```python
    @field_validator("source_type")
    @classmethod
    def known_source(cls, value: str) -> str:
        if value not in SOURCE_TYPES:
            raise ValueError(f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}")
        return value
```

`schemas.py:49-54`. Unchanged. The type must be one of the six known ones, and the error
message lists them, so the frontend can show something useful rather than "invalid".

```python
    @model_validator(mode="after")
    def exactly_one_reference(self) -> "IngestRequest":
        """
        A job that names both says nothing about which one it means.

        One that names neither has nothing to read, and would be accepted here
        only to fail in a worker minutes later.
        """
        if bool(self.source_ref) == bool(self.staged_key):
            raise ValueError(
                "an ingest job names exactly one of source_ref, a URL to fetch, and "
                "staged_key, an upload waiting in the file store"
            )
        return self
```

`schemas.py:56-69`. New. Splitting one field into two creates a state the old model could not
express: both set, or neither. `bool(a) == bool(b)` is true in exactly those two cases and
false in the two legitimate ones, which is why one comparison covers both.

Both-set is the interesting half. A job carrying a `staged_key` *and* a `source_ref` would
leave whichever branch of the handler ran first deciding what the source was, and the answer
would depend on the order of two `if` statements rather than on anything the caller was told.
Neither-set is the cheap half: it would be accepted here and then fail in a worker some
minutes later, which is a worse error in a worse place.

```python
    @model_validator(mode="after")
    def only_youtube_is_named_by_a_url(self) -> "IngestRequest":
        """
        Keep the downloader on the network and everything else in the store.

        Given a bare path yt-dlp will happily read a local file, which would turn
        a YouTube ingest into an arbitrary file read. This is a cheap early
        rejection, not the guard: it says nothing about where the URL points, and
        an http(s) URL naming an internal address is an SSRF. `YouTubeUrlGuard`
        in `backend/pipeline/ingestion.py` authorises the host, immediately
        before the call that fetches it.

        No other source type may name a `source_ref` at all. It used to be a
        filesystem path for those, which made any ingest job a read of any file
        the server could open; an upload is named by the key it was staged under
        instead, and that key is checked against the project the job belongs to.
        """
        if self.source_type == "youtube":
            if not (self.source_ref or "").startswith(("http://", "https://")):
                raise ValueError("source_ref must be an http(s) URL for a youtube source")
        elif self.source_ref:
            raise ValueError(
                f"a {self.source_type} source is named by the staged_key of an upload, "
                "not by a source_ref"
            )
        return self
```

`schemas.py:71-96`. **This is hole 4**, both halves of it, and the docstring it carries is
the more important half of the story — see the SSRF section immediately below.

What was wrong, and it was wrong in two places. A job with `source_type: "youtube"` reaches
`IngestHandler._store` (`backend/handlers/ingest_handler.py:195-215`), which calls
`self._ingestion.store_youtube(payload.source_ref, project_id)`, which at
`backend/pipeline/ingestion.py:198` calls `downloader.extract_info(url, download=True)`.
yt-dlp does not require a URL. Given a filesystem path it treats it as a local media file
and reads it. So a request naming `source_type: "youtube"` and `source_ref: "/etc/passwd"`
was an arbitrary local file read, and the extracted content would then be run through the
pipeline and stored as an artifact the caller could read back.

The second place is the one that stayed open. Lines 88-90 are the old check, and the old
check is all there was: it constrained `youtube` and said nothing about `pdf`, `audio`,
`video`, `pptx` or `md`. Those five went down the *upload* branch of `_store`, which read the
path directly rather than handing it to yt-dlp, and read it just as happily. An ingest job
posted to `POST /api/jobs` with `source_type: "md"` and `source_ref: "/etc/passwd"` was an
arbitrary local file read with no downloader involved at all, and the resulting artifact was
downloadable. That is what line 91's `elif` closes: **no source type except youtube may name
a `source_ref` at all.**

Why the fix is a `model_validator` and not a `field_validator`. A field validator sees one
field at a time. The rule here is a relationship between two fields — the constraint on
`source_ref` depends on the value of `source_type`. `mode="after"` means it runs once every
field has been parsed and coerced, so `self.source_type` and `self.source_ref` are both
populated.

Note `(self.source_ref or "")` at line 89. `source_ref` is optional now, so it can be `None`,
and `None.startswith` is an `AttributeError` rather than a validation failure — a 500 where a
400 belongs. Coercing to the empty string first means a YouTube job with no reference fails
the same way a YouTube job with a bad reference does.

Where the check runs matters. It is on the Pydantic model, and the model is constructed in
`create_job` at `jobs.py:53` inside a `try`, so a violation becomes a 400 before any row is
written. The tests at `test_api.py:650-664` and `test_api.py:666-690` assert the 400 *and*
assert that no job row was created — the second of those is parametrised over
`sorted(SOURCE_TYPES - {"youtube"})`, so it is five tests, one per non-YouTube type, and a
seventh source type added later gets covered without anyone editing the test. `test_api.py:692`
covers the job that names nothing at all, and `test_api.py:723` asserts a real YouTube URL
still validates, which is the part people forget — a guard that also breaks the legitimate
case is not a fix.

**And the check is made twice, on purpose.** `IngestHandler._staged_upload_path`
(`ingest_handler.py:174-193`) refuses a non-YouTube job that carries no `staged_key`, and
`UploadStaging._require_staged_by` (`uploads.py:79-92`) refuses a key that is not the shape
this project's upload endpoint writes. The schema is the boundary check and the handler is
the operation check, which is the same rule the SSRF section below states: validate at the
boundary, authorise at the operation. A job row can be written by a route that forgets, or
replayed from the queue, or constructed in a test; the handler is the one place every one of
those converges.

**What this cost, and it is worth naming rather than hiding.** The old workspace page
(`frontend/app/workspace/page.tsx:448`) lets a developer type a local path into a free-text
box and posts it as `source_ref` at
`frontend/app/workspace/hooks/useJobOrchestrator.ts:117`. That was the development
convenience the hole existed for, and for the five non-YouTube types it now gets a 400. That
page is the hackathon-era workspace; the real path is `/upload`, which posts multipart to the
upload endpoint. Losing the convenience is the right trade — an arbitrary read of the
server's disk, reachable by anyone who can reach the API, is not something to keep because a
debug page was built on it — but the honest version of this story includes the fact that
something did break.

### The SSRF, and why the guard is not in this file

This is the best security item in the project and the one to spend time on. It is worth
telling in the order it happened, because the point of it is not the vulnerability, it is
what the earlier fix got wrong.

**The earlier fix was incomplete, and it was incomplete in a specific way.** The validator
above constrains the *scheme*. It says the reference must start with `http://` or
`https://`. It says nothing whatsoever about the **host**. That closed the local-file read
and left the field pointing at the entire network the server can reach.

**Why an http(s) URL is dangerous at all here.** `source_type: "youtube"` is a label the
caller chose; it is not a constraint on where the fetch goes. yt-dlp does not restrict
itself to sites it has an extractor for. Anything it does not recognise goes to its
*generic* extractor, which issues the request and, when the response is not media, downloads
the body verbatim. The ingest pipeline then does what it always does with a downloaded
source: stores the bytes in the caller's project, extracts text from them, distils that text
into a knowledge core, and commits the result as an artifact the caller owns and can read
back through the ordinary artifact endpoints. So the field was not merely a request-forgery
primitive where you infer things from timing. It was a **full-response** SSRF with a
built-in exfiltration channel, because the response body came back to you as study material.

**The exploit, end to end.** One request, to an endpoint that requires nothing but a project
you own:

```
POST /api/jobs
{
  "project_id": "<a project you own>",
  "type": "ingest",
  "payload": {
    "source_type": "youtube",
    "source_ref": "http://169.254.169.254/latest/meta-data/iam/security-credentials/admin",
    "original_name": "lecture"
  }
}
```

That address is the cloud instance metadata endpoint — link-local, unroutable from outside
the host, and on an unhardened instance it hands out role credentials to anything on the box
that asks. It was proven against a stand-in for it rather than against a real one. The
result was a 202, then a completed ingest job, then a new artifact in the project, and the
artifact's summary **contained the response body verbatim, credential-shaped strings and
all**. The pipeline did not know it was reading a secret; it read text, summarised it, and
filed it. Reading it back needed nothing more than `GET /api/artifacts/{id}`.

**The failed fetches were useful too, which is the part people miss.** `GET /api/jobs/{id}`
returns `error_message` on a failed job (`schemas.py:163`), and the three outcomes are
distinguishable: a connection refused fails fast with one message, a filtered port hangs
until the job timeout, and anything that answers succeeds and produces an artifact. Refused,
timed out and answered are three different observable states, which is precisely the
definition of a working port scanner — one that runs from inside the network boundary,
against `localhost` and every private range the host can route to, driven entirely through a
public API by a caller with no special privileges.

**The fix, and where it lives.** `YouTubeUrlGuard` and `HostResolver` in
`backend/pipeline/ingestion.py:53-155`, called from `store_youtube` at `ingestion.py:184` —
the first statement in the function, before the temp directory is made and before the yt-dlp
downloader is constructed at all. That file has its own document and the guard is
walked through there. Two sentences of what it does, so the story is complete: the host must
equal an allowed YouTube name or be a proper subdomain of one, which is a suffix match and
never a substring match, because a substring test accepts `youtube.com.evil.tld`; and every
address the host resolves to is then checked against private, loopback, link-local,
multicast, reserved and unspecified ranges, with one disallowed answer among several being
enough to refuse, because an allowed *name* can still be pointed inward by whoever controls
its DNS.

**What matters for this document is the layering question: why is the guard not here?**

The schema is the wrong place for it, and the reason is the fifth-hole lesson repeating.
Hole 5 was a fix applied at `POST /api/jobs` while `/flow/run` reached the same handler
through another door. This is the same shape. `IngestRequest` is a model that one route
happens to construct; it is not the thing that makes the network call. Something else can
reach `store_youtube` without going through it — and something already had, because the
upload route used to hand-write its own job payload and never touched `IngestRequest` at
all, which is the third fix in this batch and is documented under `projects.py` below. A
host allow-list that lives on the request model is a guard that protects one door.

The guard belongs at the layer that makes the dangerous call, because that is the only place
where the set of callers is closed. `store_youtube` is the single function that hands a URL
to yt-dlp. A check on its first line covers the HTTP route, the flow engine, a Celery worker
replaying a queued job, a future CLI, and a test — every one of them, now and later, without
anyone having to remember. The rule to state plainly: **validate at the boundary, authorise
at the operation.** The schema's job is to reject obvious rubbish cheaply and give the
client a useful error; the guard's job is to decide whether this specific request may be
made, and it has to sit next to the thing that would make it.

**So why keep the check here at all, if it is not the guard?** Three reasons, and the
docstring now says the first two explicitly so a future reader cannot mistake it for the
protection. It is cheap: a scheme test on a string, run at parse time, rejecting the whole
job before a row is written rather than after a worker has picked it up. It produces a
better error: a 400 naming the field, which the frontend can show next to the input, rather
than a job that fails asynchronously and surfaces as a red node on the canvas. And it still
closes hole 4 — the bare filesystem path — at the earliest possible moment.

The change to this file when the guard landed was therefore two things: nothing at all to the
logic, and a docstring that says out loud what the check is *not*. That is deliberate. The
dangerous version of this code is not the one without the check; it is the one where a reader
sees a validator on a URL field and concludes the URL has been validated. The `elif` branch
underneath it came later, with the staged-key change, and it is a different kind of thing: not
a cheap early rejection but the removal of a capability, because after it there is no source
type left whose reference is a path.

Tests. The API-layer half is `test_api.py:650` and `:723` as above. The guard's own tests are
`TestYouTubeIngestGuard` at `test_api.py:786-935`, and the two worth being able to name are
`test_the_downloader_never_sees_a_refused_url` at `:861`, which replaces `yt_dlp.YoutubeDL`
with something that raises if it is ever constructed and so proves the guard runs *before*
the fetch rather than after it, and `test_a_genuine_youtube_url_passes` at `:857`, which is
the "did not break the feature" half.

### `GenerateRequest`

```python
class GenerateRequest(BaseModel):
    target_type: str
    source_artifact_ids: List[str] = Field(default_factory=list)
    source_artifact_id: Optional[str] = None
    instructions: Optional[str] = Field(None, max_length=4000)
```

`schemas.py:99-103`. Two source fields. `source_artifact_ids` is the real one; the singular
`source_artifact_id` at line 102 is a shorthand that older frontend code sends —
`useJobOrchestrator.ts:139` still uses it. Rather than break that caller, the model accepts
both and normalises.

```python
    @field_validator("target_type")
    @classmethod
    def known_target(cls, value: str) -> str:
        if value not in GENERATED_TYPES:
            raise ValueError(f"target_type must be one of: {', '.join(sorted(GENERATED_TYPES))}")
        return value
```

`schemas.py:105-110`. The same pattern as `known_source`. `sorted()` in the message so the
list is stable and not in whatever order the frozenset iterates. The test at
`test_api.py:218` asserts the message text reaches the client, because a 400 saying
"validation failed" would have been useless to the frontend.

```python
    @model_validator(mode="after")
    def at_least_one_source(self) -> "GenerateRequest":
        if not self.sources():
            raise ValueError("source_artifact_ids must name at least one artifact")
        return self

    def sources(self) -> List[str]:
        """Every source id, accepting the single-source shorthand."""
        return self.source_artifact_ids or ([self.source_artifact_id] if self.source_artifact_id else [])
```

`schemas.py:112-120`. Line 113 is a cross-field rule again: neither field is individually
required, but at least one must produce an id. Without it a generate job with no sources
would be queued and fail deep in the handler at `generate_handler.py:52`.

`sources()` at line 118 is the normalisation, and it is important for the security story: it
is the single definition of "which artifacts will this job read". `jobs.py:145` calls it to
decide what to ownership-check, `jobs.py:155` calls it to decide what to store, and
`_find_in_flight_duplicate` calls it at `jobs.py:175` to decide what counts as identical
work. One function, three uses, so the check and the storage cannot drift apart. If the
ownership check read `source_artifact_ids` directly and the handler read `sources()`, the
singular shorthand would have been an unchecked path.

The precedence is plural-first: if both are sent, the list wins and the singular is ignored.

### `RefineRequest`

```python
class RefineRequest(BaseModel):
    source_artifact_id: str
    instructions: str = Field(min_length=1, max_length=4000)
    target_type: Optional[str] = None
```

`schemas.py:123-126`. One source, required. `instructions` is required and non-empty, because
a refine with no instruction is a regenerate and should go through the generate path.
`target_type` is optional: omitted, the handler produces the same type as the source.

Lines 128-133 validate `target_type` when present, with `value is not None` guarding the
membership test so that `None` passes through.

### `JobRequest`

```python
class JobRequest(BaseModel):
    project_id: str
    type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
```

`schemas.py:136-139`. The envelope. Note `payload` is an unvalidated dict here — deliberately.
The payload's real shape depends on `type`, and Pydantic discriminated unions for three
variants would be more machinery than the two lines in `create_job` that do it explicitly
(`jobs.py:52-55`). The envelope validates that `type` is one of the three known job kinds at
lines 141-146; the route then picks the matching model out of `REQUEST_MODELS` and parses
the payload against it.

### `JobAccepted` and `JobStatus`

```python
class JobAccepted(BaseModel):
    job_id: str
    status: str = "pending"
    dispatch: str = "local"
    reused: bool = False
```

`schemas.py:149-153`. What a 202 returns. `dispatch` tells the client how the work was
handed off — `"local"`, `"celery"`, `"deferred"` or `"reused"` — which is what makes the
Celery-or-in-process decision visible rather than magic. `reused` at line 153 is the
idempotency signal: `true` means no new job was created and the id refers to one already in
flight. The frontend needs that to avoid double-counting a generation.

`JobStatus` at lines 156-167 is the read shape, including `attempts` and the three
timestamps. Every field except the first four is optional, because a pending job has no
`started_at` and no result. `error_message` at line 163 is the field that made a failed
SSRF probe informative, as described in the SSRF section above — it is the right field to
expose for debugging a real ingest failure, and it was also the readout channel for a port
scan while the host was unconstrained.

`payload` at line 161 is the other field on this model that hands stored data straight back
to the caller, and it is worth knowing that it is a disclosure surface at all. An ingest
job's payload used to carry the absolute path of the temp file the API had buffered, so
`GET /api/jobs/{id}` told anyone who asked where this server keeps things and under what
name. It now carries a `staged_key`, which is scoped to the project and means nothing
outside the store. `test_api.py:97` is the test for that, and it checks it through the HTTP
endpoint rather than through the row, because the endpoint is the thing that discloses.

### `ArtifactUpdate` — hole 3, first half

```python
class ArtifactUpdate(BaseModel):
    content: Optional[Dict[str, Any]] = None
```

`schemas.py:170-171`. One field. This is the model side of hole 3, and on its own it does not
close anything — `Dict[str, Any]` still accepts a `binary` key with a `storage_path` inside
it. The actual fix is in the route, at `artifacts.py:78-80`, and is explained there. What
this model does contribute is that `content` is the *only* thing a caller can send. Type,
project, provenance and timestamps are not client-writable at all, because they are not on
the model.

### `DownloadLink`, `FlowRequest`, and the flow response models

```python
class DownloadLink(BaseModel):
    download_url: str
    format: str
    mime_type: str
    filename: str
```

`schemas.py:174-178`. The download endpoint returns a description of a link rather than the
bytes. Explained under `artifacts.py`.

```python
class FlowRequest(BaseModel):
    """
    The graph to compile.

    Nodes and edges are optional; when omitted the project's saved canvas is
    used instead.
    """

    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
```

`schemas.py:181-190`. Both optional and both defaulting to `None` rather than to an empty
list, and that distinction carries meaning: `None` means "I did not send a graph, use the
saved one", whereas `[]` means "I am sending you an empty graph", which is an error. The
route distinguishes them at `flows.py:28` with `if request.nodes is not None`. If the default
were `[]` the two cases would be indistinguishable and running with no body would always
compile an empty canvas.

The node dicts themselves are `Dict[str, Any]` because they are React Flow nodes and the
compiler, not Pydantic, understands their shape.

`FlowStepView` (193-197), `FlowPlanResponse` (200-204) and `FlowRunResponse` (207-215) are
plain response shapes. `FlowPlanResponse` is the interesting one: it carries `valid: bool`
and an optional `error`, so a graph that will not compile comes back as a 200 with
`valid: false`. That is because an incomplete canvas is a normal editing state, not a client
error — you are mid-drag, one generator has no input yet, and the UI should show a hint, not
an exception.

### `ChatRequest` and `ChatResponse`

```python
class ChatRequest(BaseModel):
    project_id: str
    message: str = Field(min_length=1, max_length=4000)
    artifact_id: Optional[str] = Field(None, description="The artifact in view, if any")


class ChatResponse(BaseModel):
    reply: str
    action: str = "answer"
    job_id: Optional[str] = None
    target_type: Optional[str] = None
```

`schemas.py:218-228`. `artifact_id` is optional because the assistant can be used with
nothing open. `action` defaults to `"answer"`, which is the safe default: if anything goes
wrong the response says "I answered", not "I queued a regeneration". `job_id` is present
only on the refine branch, and the frontend uses its presence to decide whether to start
watching for a new artifact.

---

## 3. `backend/api/routes/projects.py`

236 lines. CRUD plus the file upload endpoint.

### Header

```python
router = APIRouter(prefix="/api/projects", tags=["projects"])

EMPTY_CANVAS = {"viewport": {"x": 0, "y": 0, "zoom": 1}, "nodes": [], "edges": []}
UPLOAD_CHUNK_BYTES = 1024 * 1024
UPLOADABLE_SOURCE_TYPES = SOURCE_TYPES - {"youtube"}
```

`projects.py:23-27`. The prefix means every path below is relative. `EMPTY_CANVAS` at line 25
is the initial canvas written on project creation — a viewport at the origin at zoom 1 and no
nodes. Writing it at creation rather than leaving the column NULL means the frontend never
has to handle "no canvas yet" as a distinct case.

`UPLOAD_CHUNK_BYTES` is 1 MB, the read size for streaming uploads.

`UPLOADABLE_SOURCE_TYPES` at line 27 is new and is one of the three fixes in this batch. It
is `SOURCE_TYPES` minus `youtube`, written as a set difference rather than as a second
literal list so that a source type added to `models/artifacts.py` becomes uploadable
automatically and nobody has to remember to update two places. The reason it exists is under
`upload_source` below.

### `list_projects`

```python
@router.get("")
def list_projects(
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Every project the caller owns, most recently updated first."""
    return database.select("projects", [("user_id", f"eq.{user_id}")], order="updated_at.desc")
```

`projects.py:30-36`. The filter tuples are PostgREST-style — `("user_id", "eq.local-user")` —
and `Database._where` at `services/database.py:513` translates them into parameterised SQL.
The `eq.` prefix is stripped and the remainder becomes a bound parameter, so this is not
string interpolation into SQL despite how the f-string looks.

This is the query that disagreed with `require_project` before hole 2 was fixed: `WHERE
user_id = 'local-user'` never matches a NULL, so an unowned project was invisible here while
being readable there.

**Worth knowing.** This returns raw row dicts, not `ProjectResponse`. `create_project` below
projects through the response model. The inconsistency is real; the listing leaks whatever
columns the table has. Today those are the same seven fields, so nothing leaks, but it is a
divergence someone could point at.

### `create_project`

```python
@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(...)
    rows = database.insert("projects", {
        "name": request.name,
        "description": request.description,
        "user_id": user_id,
        "canvas_state": EMPTY_CANVAS,
    })
    if not rows:
        raise HTTPException(status_code=500, detail="Project creation returned no row")

    logger.info("Created project %s", rows[0]["id"])
    return ProjectResponse(**{field: rows[0].get(field) for field in ProjectResponse.model_fields})
```

`projects.py:39-56`. 201 because a resource is created. Line 49 is where ownership is
established: the caller's resolved id is written into the row, which is the thing every
later check compares against.

Lines 52-53 handle an insert that returns nothing. `Database.insert` re-selects the row it
just wrote (`database.py:244`), so an empty list means the write did not land. It should be
impossible; it is a 500 rather than an `IndexError` so that the failure is a clean error
response and a log line rather than a stack trace escaping into the generic handler.

Line 56 is the projection mentioned earlier. `ProjectResponse.model_fields` is the declared
field names, and each is looked up with `.get`, so a column present in the row but absent
from the model is dropped, and a field in the model absent from the row becomes `None`
instead of raising.

### `get_project`, `update_project`, `delete_project`

```python
@router.get("/{project_id}")
def get_project(...)
    return require_project(project_id, user_id, database)
```

`projects.py:59-66`. One line. The 404 and the 403 both come out of `require_project`. This
is the endpoint that said yes to an unowned project before hole 2 was closed.

```python
@router.patch("/{project_id}")
def update_project(...)
    require_project(project_id, user_id, database)

    changes = request.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")

    rows = database.update("projects", [("id", f"eq.{project_id}")], changes)
    if not rows:
        raise HTTPException(status_code=500, detail="Update returned no row")
    return rows[0]
```

`projects.py:69-86`. Ownership first at line 77, then the change set.

`exclude_none=True` at line 79 is what makes PATCH partial: fields the client did not send
are `None` on the model and are dropped, so they are not written. The consequence, worth
knowing, is that you cannot clear a description by sending `null` — it is indistinguishable
from not sending the field. Clearing requires sending `""`.

Lines 80-81 reject an empty change set with a 400 rather than performing a no-op update.
That is not pedantry: `Database.update` at `database.py:250-251` stamps `updated_at` on every
`projects` write, so an empty PATCH would bump the modification time and reorder the sidebar
for no reason. The test at `test_api.py:52` covers it.

Line 83 filters by id only. It does not re-assert ownership in the WHERE clause, because line
77 already proved it and both statements run on the same connection in the same request.

This is the endpoint that stores `canvas_state` without validating the artifact ids inside
it — the limitation described under `ProjectUpdate` above.

```python
@router.delete("/{project_id}")
def delete_project(...)
    require_project(project_id, user_id, database)
    database.delete("projects", [("id", f"eq.{project_id}")])

    logger.info("Deleted project %s", project_id)
    return {"status": "deleted", "id": project_id}
```

`projects.py:89-100`. Ownership, delete, log, respond. The docstring says artifacts, edges and
jobs cascade, which is a schema property (`ON DELETE CASCADE` in `database.py`) rather than
something this route does. Returning 200 with a body rather than 204 keeps every endpoint's
response parseable as JSON, which the frontend's fetch wrapper assumes.

### `list_artifacts`

```python
@router.get("/{project_id}/artifacts")
def list_artifacts(...)
    require_project(project_id, user_id, database)
    return {
        "artifacts": database.select(
            "artifacts", [("project_id", f"eq.{project_id}")], order="created_at.asc"
        ),
        "edges": database.select("artifact_edges", [("project_id", f"eq.{project_id}")]),
    }
```

`projects.py:103-116`. Nodes and edges in one response, because the canvas needs both to
render and two round trips would let it paint nodes before it knows how they connect.
Artifacts are ordered oldest-first so the graph reads in the order it was built.

### `upload_source`

```python
@router.post("/{project_id}/upload", status_code=202)
async def upload_source(
    project_id: str,
    file: UploadFile = File(...),
    source_type: str = Form(...),
    ...
```

`projects.py:119-126`. `async def` because reading an upload is I/O-bound and the function
awaits chunk reads. 202 rather than 201, because the response is a queued job, not a finished
artifact.

The docstring is worth reading, because it now carries the reason for the gate below *and*
the reason the staging moved:

```python
    """
    Accept a file and queue it for ingestion.

    The upload streams to disk rather than being read into memory, so a large
    lecture recording does not become an equally large resident process, and it
    is staged in the file store rather than in this process's temp directory:
    the job may be run by a Celery worker in another container, and the data
    volume the store sits on is the only thing that container shares with this
    one.

    A `youtube` source is fetched from a URL by the ingest pipeline and is not
    something anybody uploads, so it is refused before a byte is read. Accepting
    one queued a job that named a file on this server and then handed that file
    to the downloader.
    """
```

`projects.py:127-141`.

```python
    require_project(project_id, user_id, database)

    if source_type not in UPLOADABLE_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of: {', '.join(sorted(UPLOADABLE_SOURCE_TYPES))}",
        )
```

`projects.py:142-148`. Ownership, then the source type check — and **the set it checks
against is the fix.**

What was wrong. The line used to read `if source_type not in SOURCE_TYPES`, and
`SOURCE_TYPES` contains `"youtube"`. So `source_type=youtube` on a multipart upload passed
validation. The route then hand-wrote its job payload as a dictionary literal with
`"source_ref": temp_path`, and that job went to `IngestHandler._store`
(`ingest_handler.py:195-215`), which branches on the source type and takes the *download*
branch for `youtube` — handing a path on this server's filesystem to `store_youtube` as
though it were a URL.

It is worth being precise about severity, because overclaiming here would be caught. It is
not a privilege escalation: the file at that path is the caller's own upload, which they had
just supplied. What it is, is a route that accepted a request it should have rejected and
then produced a nonsensical failure deep in a worker, and — more to the point — **a second
door into `store_youtube` that did not go through `IngestRequest` at all**. That is exactly
the property that makes a schema-level URL guard insufficient, and it is why the SSRF guard
had to live next to the fetch. This fix and the SSRF fix are really one observation seen from
two sides: the model was not the chokepoint anybody thought it was.

The fix is `UPLOADABLE_SOURCE_TYPES` from the header: `SOURCE_TYPES - {"youtube"}`. An upload
is a file; `youtube` is the one source type whose reference is a URL rather than a file, so
it is the one type an upload can never legitimately declare. Deriving the set by subtraction
means the two lists cannot drift.

The error message is built from the same set it checked, so the client is told what is
actually allowed rather than being told a list that includes the thing just refused. The test
at `test_api.py:916` asserts the 400, asserts no job row was written, and — the assertion
worth noticing — asserts that the string `"youtube"` does **not** appear in the detail, which
is what pins the message to the narrower set.

Note the ordering: ownership is checked before the file is read, and the source type is
checked before it too. That matters — a caller with no access to the project should not be
able to make the server buffer 200 MB to disk before being told no, and neither should a
caller who named a type that was never going to be accepted.

```python
    staging = UploadStaging()
    staged = await _stage_upload(staging, file, project_id)

    try:
        rows = database.insert("jobs", {
            "project_id": project_id,
            "type": "ingest",
            "status": "pending",
            "payload": _ingest_payload(source_type, staged.key, file.filename),
        })
        if not rows:
            raise HTTPException(status_code=500, detail="Could not queue the ingest job")
    except Exception:
        staging.discard(staged.key, project_id)
        raise
```

`projects.py:150-164`. Lines 150-151 stream the upload onto the shared data volume (see
`_stage_upload` below) and come back with a `StagedUpload` — a key and a byte count, not a
path. Line 158 used to be an inline dictionary literal spelling out `source_type`,
`source_ref` and `original_name` by hand; it is now a call to `_ingest_payload`, which builds
the payload through `IngestRequest`. That change is explained in its own subsection below,
because it is the structural half of the fix rather than the gate.

**What the payload carries is the interesting part, and it changed.** It used to be
`"source_ref": temp_path` — an absolute path in this process's temp directory. That was safe
in the sense that the client never chose it; the server wrote it. It was not safe in two
other senses, and both of them are why this code looks the way it does now.

The first is that it did not work. Under `docker-compose.celery.yml` the API and the workers
are separate containers, and separate containers have separate `/tmp`. The path the API wrote
named nothing at all in the worker, so every single upload failed there with

```
Job dbbd5329-... (ingest) failed: No readable file at /tmp/tmplvqcq44o.md.
```

Upload was completely broken in the distributed configuration — the configuration the whole
architecture story is about — and it worked in the single-container configuration only
because there the worker pool runs inside the API process and shares its temp directory by
accident. The bug had been there the entire life of the project and no test caught it,
because every test ran in one process. It was found the first time anybody built the images
and ran the distributed shape for real.

The second is that `GET /api/jobs/{id}` hands the payload straight back to the caller
(`schemas.py:161`), so the absolute path of a file on the server was a response body. That is
disclosure, not access, but it is the sort of disclosure that tells an attacker the temp
directory, the naming scheme and the fact that the file is still there.

A storage key fixes both at once. It resolves to the same bytes in every process that can
reach the data volume — which under the Celery overlay is the API container and both worker
containers, because `docker-compose.celery.yml` mounts `beedata:/data` into all of them — and
it means nothing outside the store, so quoting it back to the caller discloses nothing.
`test_api.py:97` asserts exactly that, through the HTTP endpoint rather than the row.

The `try/except` at 153-164 exists because a staged upload is now an orphan if the job row
cannot be written. Without the `discard` at line 163, every failed insert would leave a file
on the data volume that nothing would ever clean up — releasing it is otherwise the ingest
handler's job (`ingest_handler.py:245-262`) and the ingest handler only runs if the row
exists. `raise` with no argument re-raises the original exception, so the error the client
sees is the real one.

Note that the `except` also catches a rejection from `_ingest_payload`: if the shared model
refuses the payload for any reason, the staged copy is released on the way out rather than
being left behind. Putting the payload construction inside the `try` rather than before it is
what buys that, and it is why the call sits on line 158 instead of a line or two higher.

```python
    job_id = rows[0]["id"]
    publish(project_id, JOB_CREATED, {"job_id": job_id, "type": "ingest", "filename": file.filename})

    return {
        "job_id": job_id,
        "filename": file.filename,
        "size_bytes": staged.size_bytes,
        "dispatch": enqueue(job_id),
    }
```

`projects.py:166-174`. `publish` puts a `job.created` event on the bus so any open WebSocket
for this project renders the new job immediately, without the client having to refetch.

`size_bytes` at line 172 comes off the `StagedUpload` rather than off a counter in the route,
which means the number the client is told is the size of the object that is actually in the
store — `UploadStaging.stage` reads it back with `size_of` after the copy — rather than the
number of bytes the route thought it wrote.

`enqueue(job_id)` at line 173 happens **after** the row is committed. That ordering is the
whole reliability story for job dispatch, and it is stated in `dispatcher.py:41-42`: the row
is the source of truth, the enqueue is a notification. In Celery mode a broker failure leaves
the job pending and a later sweep picks it up; in local mode the enqueue is a no-op because
the worker pool is already polling for pending rows. If the order were reversed, a worker
could receive a job id for a row that does not exist yet.

### `_ingest_payload` — sharing the model instead of duplicating the rules

```python
def _ingest_payload(source_type: str, staged_key: str, filename: Optional[str]) -> Dict[str, Any]:
    """
    Build the job payload through the model the other ingest door already uses.

    Hand-writing the dictionary here is what let this route contradict
    `IngestRequest`: the rules about what a source may be lived in that model,
    and an upload never went through it. Sharing the model makes the invariant
    structural rather than something two routes have to remember separately.

    The dump drops what is unset, so the stored payload names the staged key and
    nothing else. `GET /api/jobs` hands that payload back to the caller, and a
    payload that also carried a filesystem path would be disclosing one.
    """
    try:
        request = IngestRequest(
            source_type=source_type,
            staged_key=staged_key,
            original_name=filename or "Untitled",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Invalid ingest payload: {error}") from error

    return request.model_dump(exclude_none=True)
```

`projects.py:177-199`. Twenty-three lines that produce the dictionary the literal used to
produce, minus the field that was the problem. The value is mostly in *how* it produces it.

Three things changed here with the staging move. The second parameter is a `staged_key`
rather than a `source_ref`, so this route can no longer put a path into a job payload even
by accident. The model is constructed with `staged_key=`, which means it goes through
`exactly_one_reference` and `only_youtube_is_named_by_a_url` like any other ingest request —
this route now satisfies the same two rules the JSON door does, rather than being trusted
because it is server-side. And the dump is `exclude_none=True`, which is what keeps
`"source_ref": null` out of the stored payload; the field exists on the model, it is simply
never set on this path, and a payload that carried the key `source_ref` at all would make a
reader of `GET /api/jobs` wonder what used to be in it.

**The problem this solves.** There are two ways to create an ingest job: `POST /api/jobs`,
which parses its payload through `IngestRequest` (`jobs.py:53`), and this upload route, which
did not. Every rule about what a source may be lived on that model — the known-type check,
the YouTube-must-be-a-URL check — and one of the two doors walked straight past all of it.
That is not a hypothetical: it is the mechanism by which the `source_type=youtube` upload got
through, because the model would have been the natural place to notice the contradiction and
the model was never asked.

The earlier document said of this route that it "duplicates `IngestRequest.known_source`
because a multipart form field cannot be validated by the same Pydantic model that validates
a JSON body", and called the duplication "real but small". That reasoning was wrong in a way
worth understanding, because it is a common wrong reasoning. It is true that FastAPI cannot
bind a multipart form to a body model automatically. It does not follow that the model cannot
be used — you can construct it by hand, which is all this function does. What the earlier
version actually had was two independent implementations of the same rule, and the argument
that they "cannot disagree about the allowed set" only held for the one rule they happened to
share. They disagreed about everything else on the model, which is where the bug was.

**Why it is a 400 and not a 500.** `source_type` comes from a form field, so a bad value is a
client error. Pydantic's `ValidationError` is a subclass of `ValueError`, so the narrow
`except ValueError` catches model rejections without also swallowing programming errors like
a `TypeError` from a wrong argument name — those would be genuine 500s and should stay
uncaught. The error text is interpolated into the detail so the client learns which rule it
broke, and `from error` keeps the chain for the log.

**`model_dump()` rather than assembling a dict.** The stored payload is whatever the model
says the payload is. If a field is added to `IngestRequest` tomorrow, it appears in the
upload path's payload without an edit here. That is the invariant the docstring calls
"structural": the two doors cannot drift, because there is only one definition of the shape.
`staged_key` is the proof of it — the field was added to the model and this route picked it
up by passing it, with no second definition of the payload shape to keep in step.

**Worth knowing.** The gate on line 144 and this function overlap — a `youtube` upload is
refused before it ever reaches here. That is not redundancy for its own sake. The gate exists
to produce a good, specific error at the boundary before a 200 MB file is buffered to disk;
the model exists so that every rule is enforced regardless of which door was used. Belt and
braces is the right posture here precisely because the failure being guarded against is "a
second door forgot a rule", and one more door is always possible.

### `_stage_upload` — the function that used to be `_buffer_upload`

```python
async def _stage_upload(
    staging: UploadStaging,
    file: UploadFile,
    project_id: str,
) -> StagedUpload:
    """
    Stream an upload onto the shared data volume, enforcing the limit as it goes.

    The bytes go through a temporary file so the request never holds the whole
    upload in memory, and that file belongs to this process alone: it is copied
    into the store, which every process that could run the ingest job can read,
    and dropped when the block closes, on the way out of a rejection as much as
    on success.
    """
    limit = get_settings().upload_max_mb * 1024 * 1024
    written = 0

    with tempfile.NamedTemporaryFile(suffix=Path(file.filename or "").suffix) as buffered:
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"File exceeds the {get_settings().upload_max_mb} MB limit",
                )
            buffered.write(chunk)
```

`projects.py:202-227`. The point of this function is unchanged and is still the first thing to
say about it: a 200 MB lecture recording never exists in memory. `await file.read(1 MB)` in a
loop, write each chunk to disk, and the process holds one megabyte at a time regardless of
file size.

**What changed is `delete=`, and it is a one-word diff carrying the whole fix.** It used to be
`tempfile.NamedTemporaryFile(delete=False, ...)`, and the comment underneath it in the old
version of this document explained why: "the file must survive the `with` block, because its
path is handed to a background job that may run in a different process". That sentence
contains its own refutation. If the job may run in a different process, a path is exactly the
wrong thing to hand it, because a path is only meaningful inside one filesystem namespace.
Under the Celery overlay the worker is a different *container*, its `/tmp` is its own, and the
path resolved to nothing.

So `delete=True` — the default — is back, and the temp file is now what it always should have
been: a private buffer belonging to this request, existing so that the request does not have
to hold the upload in memory, and gone when the block closes. The copy that outlives the
request goes into the file store instead, on the volume every process shares.

Three `os.unlink` calls disappeared with it. The old version unlinked on the oversize path, on
the empty path, and in the caller's `except`; the `with` block now does all three, because
closing it deletes the file however control leaves. `os` is no longer imported by this module
at all, which is the small, checkable sign that the route stopped doing filesystem
bookkeeping.

`Path(file.filename or "").suffix` at line 219 preserves the original extension, because the
extraction pipeline dispatches on it. It replaced `os.path.splitext(...)[1]`, which is the
same thing said less directly.

Line 222 checks the limit **as it goes**, not after. Checking `Content-Length` up front would
trust a header; checking after the write would mean the disk is already full. Checking the
running total means the write is abandoned the moment it crosses the line, and the raise no
longer needs to clean up after itself. 413 is the correct status. The test at
`test_api.py:141` sets the limit to 1 MB and posts 2 MB.

The same `upload_max_mb` setting also caps a YouTube download, as `max_filesize` on the
yt-dlp options (`pipeline/ingestion.py:193`), so both ways into the file store are bounded by
one number rather than one of them being unbounded. `test_api.py:886` asserts that the
configured megabytes reach the downloader's options.

```python
        if written == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty")

        buffered.flush()
        staged = staging.stage(buffered.name, project_id, file.filename)

    logger.info("Staged %s (%d bytes) as %s", file.filename, written, staged.key)
    return staged
```

`projects.py:229-236`. An empty upload is a 400 rather than a job that fails ten seconds later
with "no text extracted". Failing at the boundary is cheaper for the user and cheaper for the
worker pool.

`buffered.flush()` at line 232 is not decoration. `NamedTemporaryFile` is buffered, so the
last chunk may still be in Python's buffer rather than on disk, and `stage` copies by path
using `shutil.copyfile` — it does not go through this file object. Without the flush the
stored object can be short by up to one buffer, silently, on exactly the uploads whose length
does not land on a buffer boundary.

Note where line 233 sits: **inside** the `with`. The copy into the store has to happen while
the temp file still exists, and the temp file now stops existing at the end of the block. That
is the ordering the whole function is arranged around — buffer, flush, copy, and only then let
the buffer go.

### The staging module: `backend/services/uploads.py`

This is not an API file, so it has no section of its own in this document, but it has exactly
two callers — the upload route above and `IngestHandler` — and the route cannot be understood
without it. 92 lines.

```python
class UploadStaging:
    """
    Holds an accepted upload in the file store until its ingest job reads it.

    The process that accepts an upload and the process that runs the ingest are
    the same one only while the worker pool lives inside the API. Dispatch the
    job to Celery and they are separate containers whose one shared surface is
    the data volume the file store sits on, so an upload staged in the API's
    temp directory names a file the worker cannot open and a job that can never
    run. Staging goes through the store instead, and what the job carries is a
    storage key, which resolves to the same bytes in every one of those
    processes.

    A key is also safe to hand back to a caller and to accept from one: it names
    a slot inside one project's staging folder rather than a location on the
    server's filesystem, and every lookup is checked against the project asking.
    """

    FOLDER = "staged"

    def __init__(self, store: Optional[FileStore] = None) -> None:
        self._store = store or get_file_store()
```

`uploads.py:28-49`. The class docstring is the bug report, and its second paragraph is the
security argument. Everything else in the module follows from those two.

The two callers are worth naming, because they are the two ends of the same object's life.
The route calls `stage`, and `discard` if the job row cannot be written. The handler calls
`path_for` when it starts and `discard` when it has succeeded. Nothing else in the codebase
touches staging at all.

The constructor is the same dependency-inversion shape every collaborator in this backend
uses: take the store as an argument, fall back to the module singleton. Production passes
nothing; a test passes a `FileStore` rooted in `tmp_path`.

```python
    def stage(self, source_path: str, project_id: str, filename: Optional[str] = None) -> StagedUpload:
        """Take a received upload into the store under a key naming its project."""
        key = f"{project_id}/{self.FOLDER}/{uuid.uuid4()}{Path(filename or '').suffix}"
        self._store.put(source_path, key)
        return StagedUpload(key=key, size_bytes=self._store.size_of(key))
```

`uploads.py:51-55`. Three segments, always: the project id, the literal `staged`, and a fresh
uuid carrying the original extension. The project id is first because that is what makes the
key checkable later — the folder a key names is the evidence of who staged it, so the check in
`_require_staged_by` needs no database lookup to do its job. The uuid is what stops two
uploads of `lecture.md` into one project from overwriting each other. The extension is kept
because the extraction pipeline dispatches on it.

`size_bytes` is read back out of the store with `size_of` rather than being passed in, so the
number the route returns to the client describes the object that actually exists.

```python
    def path_for(self, key: str, project_id: str) -> Path:
        self._require_staged_by(key, project_id)
        if not self._store.exists(key):
            raise StagingError(
                f"No staged upload at {key}. A staged upload is released once its ingest "
                "succeeds, so a job that already finished cannot be run again; upload again."
            )
        return self._store.open_path(key)

    def discard(self, key: str, project_id: str) -> None:
        """Release a staged upload once something durable has been made of it."""
        self._require_staged_by(key, project_id)
        self._store.delete(key)
        logger.info("Released the staged upload %s", key)
```

`uploads.py:57-77`. Two lookups, and **both of them start with the same check.** That is the
point of the class: there is no way to reach a staged file without going past
`_require_staged_by`, because the two methods that touch the store both call it on their first
line.

The absent-file message on lines 67-70 is worth its length. It is the error an operator will
actually meet, and the reason is not obvious: the slot is released the moment its ingest
succeeds, so re-running a job that already finished finds nothing there. A bare "object not
found" would send someone looking for a storage bug.

`exists` and `delete` on `FileStore` had no callers anywhere in the codebase before this
module existed. They were written when the store was, and nothing used them; these two methods
are the first thing that ever did.

```python
    @classmethod
    def _require_staged_by(cls, key: str, project_id: str) -> None:
        """
        Refuse a key that is not one this project staged.

        The key travels in the job payload, so wherever a caller can queue a job
        it is a caller-supplied string. Only the exact shape `stage` writes is
        accepted, which is what keeps a job from reading, or deleting, an
        export, another project's source, or anything reached by climbing out of
        the folder.
        """
        parts = PurePosixPath(key).parts
        if len(parts) != 3 or parts[:2] != (project_id, cls.FOLDER) or ".." in parts:
            raise StagingError(f"'{key}' is not an upload staged by project {project_id}")
```

`uploads.py:79-92`. Fourteen lines, and this is the security half of the module.

**Why it exists at all**, which is the part to be able to say: the key is stored in the job
payload, and a job payload is a caller-supplied dictionary at `POST /api/jobs`. So the moment
an upload is named by a key rather than a path, the key becomes a value an attacker chooses,
exactly like `source_ref` was. Replacing one caller-controlled string with another and
declaring the problem solved would have been the same mistake in a new coat.

The check is an allow-list on *shape*, not a deny-list on content. Three segments exactly, the
first being the project the job belongs to, the second being the literal `staged`. Everything
else fails: `{other_project}/staged/x` fails on the first segment,
`{project}/sources/lecture.md` fails on the second, `{project}/staged/a/b` fails on the count,
and `/etc/passwd` — whose `parts` are `('/', 'etc', 'passwd')`, so it passes the count —
fails on the first two. The `".." in parts` test is belt and braces —
`FileStore.resolve` already refuses to leave the store root — but the two guards protect
different things, and the one closer to the operation is the one that knows a staging slot
from an export.

The two positive consequences worth naming: a job can never read another project's staged
upload, and `discard` can never delete anything that is not a staging slot. The second matters
more than it looks. Leaking a staged file costs disk; deleting a stored source costs the
project an artifact it can never get back, and `discard` is the only `delete` call anywhere in
the ingest path.

`test_seams.py:410` is the test for that shape check — it puts a real source in the store,
tries to `discard` it both by its own key and through `{project}/staged/../sources/lecture.md`,
and asserts the source is still there afterwards. `test_seams.py:376` is the cross-project
half.

---

## 4. `backend/api/routes/jobs.py`

191 lines. This is the busiest module and the one hole 1 lived in.

### Header

```python
REQUEST_MODELS: Dict[str, type[BaseModel]] = {
    "ingest": IngestRequest,
    "generate": GenerateRequest,
    "refine": RefineRequest,
}

IN_FLIGHT = ("pending", "running")
DEDUPLICATION_WINDOW = 50
```

`jobs.py:28-35`. `REQUEST_MODELS` maps the job type to the model that validates its payload.
It is a dict rather than an if-chain so that adding a job type is a one-line change and the
route body does not grow.

`IN_FLIGHT` at line 34 is the two statuses that count as "already doing this work". It is
where the idempotency fix lives; see `_find_in_flight_duplicate` below.

`DEDUPLICATION_WINDOW` bounds how far back the duplicate search looks.

### `create_job` — hole 1

```python
@router.post("", response_model=JobAccepted, status_code=202)
def create_job(
    request: JobRequest,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
) -> JobAccepted:
    """
    Queue a job.

    The row is written before dispatch, so a broker outage delays the work
    rather than losing it.
    """
    require_project(request.project_id, user_id, database)
```

`jobs.py:38-50`. Line 50 checks the caller owns the project the job will write into. **That
check alone was the entire authorisation on this endpoint, and that was hole 1.**

```python
    try:
        payload = REQUEST_MODELS[request.type](**request.payload)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Invalid {request.type} payload: {error}") from error
```

`jobs.py:52-55`. The payload is parsed against the model for its type. `request.type` was
already constrained to the three known values by `JobRequest.known_type`, so the dict lookup
cannot `KeyError`.

The broad `except Exception` is deliberate: Pydantic raises `ValidationError`, but a payload
that is not a dict raises `TypeError`, and both should be a 400 rather than a 500. The error
text is interpolated into the detail, which is how the YouTube message
("source_ref must be an http(s) URL for a youtube source") and the target-type message reach
the client. `from error` preserves the chain for the logs.

This is where hole 4's validator runs.

```python
    for artifact_id in _source_ids(payload):
        require_project_artifact(artifact_id, request.project_id, user_id, database)
```

**`jobs.py:57-58`. This is the fix for hole 1.**

What was wrong. The endpoint checked that you owned `request.project_id` and stopped there.
The payload of a generate or refine job names source artifact ids, and nothing checked them.
The handlers do not check either — `generate_handler.py:49` takes `payload.source_artifact_ids`
and resolves them, and `refine_handler.py:58` calls `self._database.get_artifact(...)` directly.
Neither has a user id to check against; handlers run in a worker with no request context, which
is exactly why the check has to happen at the API boundary.

So the attack was: create a project of your own, then `POST /api/jobs` with
`project_id` set to your project and `source_artifact_ids` set to an artifact id belonging to
someone else. The job passed authorisation, the handler read the foreign artifact, flattened it
into text, generated from it, and wrote the result as a new artifact **in your project**, which
you could then read through the ordinary artifact endpoints. It was a content exfiltration
primitive with a laundering step built in.

The fix is two lines and one helper. `_source_ids` returns every artifact the job will read;
each is passed through `require_project_artifact`, which asserts you own it *and* that it lives
in the project you are writing into.

Note the position of these lines. They run after payload validation — you cannot check ids you
have not parsed — and before the duplicate search and before the insert. An unauthorised source
produces 403 (or 404 for a nonexistent id) with no row written at all. The three tests at
`test_api.py:444`, `:457` and `:497` each assert the status code *and* that
`database.select("jobs", ...)` is empty afterwards, because "refused but queued anyway" would be
a subtler version of the same bug.

`require_project_artifact` and not `require_artifact`, because the cross-project rule matters
here too: even between two projects you own, generating in project B from a source in project A
would produce an edge filed in one project pointing at a node in the other.

```python
    if isinstance(payload, GenerateRequest):
        duplicate = _find_in_flight_duplicate(database, request.project_id, payload)
        if duplicate:
            logger.info("Reusing in-flight job %s", duplicate["id"])
            return JobAccepted(
                job_id=duplicate["id"], status=duplicate["status"], dispatch="reused", reused=True
            )
```

`jobs.py:60-66`. Idempotency, only for generates. Ingests are never deduplicated because two
uploads of the same file are two different files as far as the API knows, and refines are never
deduplicated because they always carry instructions and different instructions are different work.

If a duplicate is found the existing job's id is returned with `dispatch="reused"` and
`reused=True`, so the client can tell the difference between "I made you a job" and "you already
have this one".

```python
    stored = _normalise(payload)
    rows = database.insert("jobs", {
        "project_id": request.project_id,
        "type": request.type,
        "status": "pending",
        "payload": stored,
    })
    if not rows:
        raise HTTPException(status_code=500, detail="Could not create the job")

    job_id = rows[0]["id"]
    logger.info("Queued %s job %s", request.type, job_id)
    publish(request.project_id, JOB_CREATED, {"job_id": job_id, "type": request.type})

    return JobAccepted(job_id=job_id, dispatch=enqueue(job_id))
```

`jobs.py:68-82`. Status `pending` is what the worker pool polls for. Publish the created event,
then enqueue — again, row committed before dispatch.

### `list_jobs`

```python
@router.get("")
def list_jobs(
    project_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    ...
    if project_id:
        require_project(project_id, user_id, database)
        return database.select(
            "jobs", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=limit
        )

    projects = database.select("projects", [("user_id", f"eq.{user_id}")], columns="id")
    if not projects:
        return []

    ids = ",".join(project["id"] for project in projects)
    return database.select("jobs", [("project_id", f"in.({ids})")], order="created_at.desc", limit=limit)
```

`jobs.py:85-104`. Two modes. With a `project_id`, check ownership and filter. Without one, list
across everything the caller owns.

`Query(20, ge=1, le=100)` at line 88 bounds the page size in the framework rather than in the
body, so an out-of-range value is a 422 before the function runs.

The cross-project branch cannot filter by user id directly, because the `jobs` table has no
owner column — ownership lives on `projects`. So lines 99-104 resolve the caller's project ids
first and then use an `IN` filter. `Database._where` at `database.py:527-533` splits the
`in.(...)` expression on commas and binds each value separately, so this is still parameterised.
Line 100's early return matters: an empty `in.()` would otherwise produce `1 = 0` (handled at
`database.py:530`) — correct, but a pointless query.

**Worth knowing.** Two round trips and an unbounded `IN` list. With a few dozen projects it is
nothing. With thousands it would want a join. It is the sort of thing to name yourself as "I know
this is O(projects) and it is fine at this scale" rather than have it pointed out.

### `get_job` and `cancel_job`

```python
@router.get("/{job_id}", response_model=JobStatus)
def get_job(...)
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    require_project(job["project_id"], user_id, database)
    return JobStatus(**{field: job.get(field) for field in JobStatus.model_fields})
```

`jobs.py:107-119`. Load first, then authorise via the job's project. Same one-hop pattern as
`require_artifact`. The projection at line 119 is the same defensive pattern as
`create_project` — build the response field by field from the declared model fields.

The test at `test_api.py:294` creates a job in a foreign project and asserts 403.

```python
@router.post("/{job_id}/cancel")
def cancel_job(...)
    job = database.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")

    require_project(job["project_id"], user_id, database)

    if not database.cancel_job(job_id):
        raise HTTPException(status_code=409, detail=f"Job is already {job['status']}")

    publish(job["project_id"], JOB_CANCELLED, {"job_id": job_id})
    return {"status": "cancelled", "id": job_id}
```

`jobs.py:122-139`. `Database.cancel_job` (`database.py:374`) returns a boolean: it only
transitions a job that has not finished. Line 135 turns `False` into a 409 Conflict, which is the
right code — the request was well-formed and the caller was authorised, but the resource is in a
state that does not permit it. The test at `test_api.py:301` cancels a completed job and asserts
409.

The message reports `job['status']` from the row read at line 129, so under a race it could name
a status one transition stale. Harmless.

### `_source_ids`

```python
def _source_ids(payload: BaseModel) -> List[str]:
    """Every artifact this job will read, so ownership can be checked before it is queued."""
    if isinstance(payload, GenerateRequest):
        return payload.sources()
    if isinstance(payload, RefineRequest):
        return [payload.source_artifact_id]
    return []
```

`jobs.py:142-148`. The other half of the hole 1 fix. It answers one question — what will this job
read — for each job type. Generate delegates to `sources()`, which is the same method the storage
path uses, so the checked set and the stored set are the same set by construction. Refine has
exactly one source. Ingest reads a file, not an artifact, so the answer is the empty list and the
loop in `create_job` does nothing.

The `return []` at line 148 is the piece to be careful about if a fourth job type is ever added.
A new type that reads artifacts and is not added here would be unchecked. That is the maintenance
hazard of a default-permissive fallback; the alternative — raising on an unknown type — would be
stricter, at the cost of an extra branch.

### `_normalise`

```python
def _normalise(payload: BaseModel) -> Dict[str, Any]:
    """Store generate payloads in their multi-source form, whichever was sent."""
    if isinstance(payload, GenerateRequest):
        stored = payload.model_dump(exclude_none=True, exclude={"source_artifact_id"})
        stored["source_artifact_ids"] = payload.sources()
        return stored
    return payload.model_dump(exclude_none=True)
```

`jobs.py:151-157`. The singular shorthand is a wire-format convenience and must not reach
storage, or every consumer — the handler, the deduplicator, the flow engine — would have to
understand both forms. So the singular field is excluded at line 154 and the canonical plural
list is written at line 155. One shape in the database.

### `_find_in_flight_duplicate` — the idempotency fix

```python
def _find_in_flight_duplicate(
    database: Database,
    project_id: str,
    payload: GenerateRequest,
) -> Optional[Dict[str, Any]]:
    """
    Find a running job that already does exactly this work.

    Only in-flight jobs count. Returning a completed one would make regenerate
    hand back the old artifact, and a steered request is never a duplicate
    because different instructions are different work.
    """
```

`jobs.py:160-171`. The docstring states both rules. Here is what went wrong.

The original version searched all recent generate jobs regardless of status, including
`completed`. The intent was reasonable — do not regenerate what already exists. The effect was
that the "Regenerate" button appeared broken. The user looks at a quiz, decides it is not what
they wanted, presses Regenerate, and the API finds the completed job that produced the quiz they
are looking at, matches it, and returns its id. The frontend follows the id, finds the job
already complete, and displays its artifact — which is the same quiz. Nothing appears to happen.
No error, no spinner that ends badly, just a button that does nothing. That is a worse failure
mode than a slow regeneration, because there is nothing to report.

```python
    if payload.instructions:
        return None
```

`jobs.py:172-173`. The second rule, and the cheaper one, so it comes first. Any request carrying
instructions is steered, and two differently-steered requests over the same source are different
work. Rather than compare instruction strings, the code declines to deduplicate at all when
instructions are present. The test at `test_api.py:281` sends "harder" and then "easier" over the
same source and asserts two distinct job ids.

```python
    wanted = sorted(payload.sources())
    candidates = database.select(
        "jobs",
        [("project_id", f"eq.{project_id}"), ("type", "eq.generate"),
         ("status", f"in.({','.join(IN_FLIGHT)})")],
        order="created_at.desc",
        limit=DEDUPLICATION_WINDOW,
    )
```

`jobs.py:175-182`. `sorted` at line 175 makes source order irrelevant: generating from [A, B] is
the same work as generating from [B, A]. The filter at line 179 is where `IN_FLIGHT` does its
job — `status IN ('pending', 'running')`, so a completed, failed or cancelled job can never
match. Newest first, capped at 50.

```python
    for job in candidates:
        stored = job.get("payload") or {}
        if stored.get("target_type") != payload.target_type or stored.get("instructions"):
            continue
        if sorted(str(value) for value in stored.get("source_artifact_ids") or []) == wanted:
            return job

    return None
```

`jobs.py:184-191`. Three conditions for a match: same target type, the stored job also has no
instructions, and the same set of sources. Line 186 checks the stored side for instructions as
well as the incoming side, so a steered job in flight is never handed back to an unsteered
request. The `str(value)` on line 188 guards against a stored id being a non-string.

This reads the payload column in Python rather than querying on it, because the payload is a JSON
blob in SQLite and there is no index into it. Fifty rows scanned in Python is not a problem.

**Worth knowing.** This is read-then-write with no lock. Two identical requests arriving at the
same moment can both find nothing and both insert. There is no unique constraint to catch it. The
consequence is a duplicated generation, which costs a model call and produces a second artifact —
wasteful, not harmful. Deduplication here is a best-effort optimisation against a user
double-clicking, not a correctness guarantee, and saying so is better than claiming it is
airtight.

---

## 5. `backend/api/routes/artifacts.py`

147 lines. Reading artifacts, editing them, tracing lineage, downloading exports, and the vault.

### Header

```python
router = APIRouter(prefix="/api", tags=["artifacts"])

VAULT_LIMIT = 200
```

`artifacts.py:17-19`. The prefix is `/api`, not `/api/artifacts`, because `/api/vault` also lives
in this file and is not under the artifacts path. Each route below therefore writes its own full
path.

### `get_artifact`

```python
@router.get("/artifacts/{artifact_id}")
def get_artifact(...)
    return require_artifact(artifact_id, user_id, database)
```

`artifacts.py:22-29`. One line. All the behaviour is in the dependency: 404 if it does not exist,
403 if you do not own the project it lives in, otherwise the row.

### `get_lineage`

```python
@router.get("/artifacts/{artifact_id}/lineage")
def get_lineage(...)
    """
    What this artifact came from and what was built on it.

    Both sides are lists: with multi-input generation an artifact genuinely has
    several parents.
    """
    artifact = require_artifact(artifact_id, user_id, database)

    parent_edges = database.get_parent_edges(artifact_id)
    child_edges = database.get_child_edges(artifact_id)

    return {
        "artifact": artifact,
        "parents": database.get_artifacts([edge["parent_artifact_id"] for edge in parent_edges]),
        "children": database.get_artifacts([edge["child_artifact_id"] for edge in child_edges]),
    }
```

`artifacts.py:32-53`. The provenance view. The docstring's point is the design decision: parents
is a list, not a single value, because a generate job accepts several sources
(`GenerateRequest.source_artifact_ids`) and each produces an edge. A schema with a single
`parent_id` column would have forced multi-input generation to lie about where its output came
from.

Two edge queries, then one batched fetch per side via `Database.get_artifacts`
(`database.py:439`), which builds a single `IN` query rather than looping. Three queries total
regardless of how many parents there are.

**Worth knowing.** The artifacts returned by the two `get_artifacts` calls are not re-checked for
ownership. They do not need to be: an edge is filed within a single project
(`require_project_artifact` is what enforces that at job-creation time), so anything reachable
through an edge from an artifact you own is in the same project you own. The invariant that makes
this safe is enforced at `deps.py:84`. That is a good thing to be able to say out loud, because
"why is there no check here" is a natural question.

### `update_artifact` — hole 3

```python
@router.patch("/artifacts/{artifact_id}")
def update_artifact(...)
    """
    Save user edits.

    Content is merged rather than replaced, so a client sending only `data` does
    not discard the attached export metadata. The export block itself is written
    by the renderer and kept out of the client's reach: it names a storage key,
    and a caller that could rewrite it could point a download at any stored file.
    """
    artifact = require_artifact(artifact_id, user_id, database)

    if updates.content is None:
        raise HTTPException(status_code=400, detail="No content supplied")
```

`artifacts.py:56-74`. Ownership, then reject an empty PATCH the same way `update_project` does.

```python
    existing = artifact.get("content") or {}
    merged = {**existing, **updates.content, "edited_by_user": True}
    merged.pop("binary", None)
    if "binary" in existing:
        merged["binary"] = existing["binary"]
```

**`artifacts.py:76-80`. This is hole 3.**

What was wrong. Line 77 alone was the whole function. The client's `content` was merged over the
stored content and written back. `content` is a free-form JSON object, and one of its keys is
`binary` — the export block that the renderer writes when it produces a PDF or a PPTX. That block
looks like:

```json
{"storage_path": "<project-id>/exports/<uuid>.pdf", "format": "pdf", "mime_type": "application/pdf"}
```

`storage_path` is a key into the file store. `download_artifact` below reads it at
`artifacts.py:105` and passes it to `store.signed_url`, which produces an HMAC-signed URL for that
key. The signature is generated server-side over whatever key it is given; it does not verify that
the key has anything to do with the artifact.

So a caller could PATCH their own artifact with a `content.binary.storage_path` naming any key in
the store — another project's export, another user's uploaded source — then call
`/download` and receive a validly signed link to it. The server would sign the capability itself.
Ownership of the artifact being edited was never in question; the artifact was the caller's own.
The bug was that a client-writable field was load-bearing for authorisation.

The fix is lines 78-80. After the merge, `binary` is unconditionally removed from the result, and
then the *stored* `binary` is put back if there was one. The net effect:

- If the artifact already had an export, it keeps exactly the export it had. A client-supplied
  `binary` is discarded.
- If the artifact had no export, it still has none. A client cannot attach one.

`binary` becomes renderer-owned. There is no request through this API that can write it.

`merged.pop("binary", None)` with the `None` default rather than a membership test first, because
the key may legitimately be absent from both sides.

`"edited_by_user": True` at line 77 is written unconditionally, and it is not decorative — the
regeneration paths read it to decide whether overwriting an artifact would destroy manual work.

Two tests cover this, and they cover both directions. `test_api.py:601` creates an artifact with a
real export plus a second file in the store, PATCHes with `binary.storage_path` pointing at the
second file, and asserts three things: the response still names the original key, the stored row
still names the original key, and — the one that actually matters — following the download link
returns the original bytes. `test_api.py:632` covers the attach case: an artifact with no export,
a PATCH that tries to add one, and an assertion that `binary` is absent from the response and that
`/download` still 404s.

**Worth knowing, and an interviewer may well find this.** The merge at line 77 is shallow.
`{**existing, **updates.content}` replaces whole top-level keys. A client sending
`{"content": {"data": {"title": "x"}}}` replaces the entire `data` object, dropping every other
field inside it. That is fine for the intended caller, which sends the complete edited `data`, but
it is not what "merge" usually implies, and a partial `data` update silently loses content.

**Worth knowing, second.** Only `binary` is protected. Every other top-level key in `content` is
still client-writable, including `kind` and `core`. Writing a fake `core` into an artifact would
corrupt the knowledge core that downstream generation reads from. That is a data-integrity
weakness within your own project, not a cross-tenant one, and it is not currently guarded. The
principled version of this endpoint would accept only `content.data` and nothing else. The
implemented version blocks the one key that carries a capability.

```python
    rows = database.update("artifacts", [("id", f"eq.{artifact_id}")], {"content": merged})
    if not rows:
        raise HTTPException(status_code=500, detail="Update returned no row")

    logger.info("Artifact %s edited", artifact_id)
    return rows[0]
```

`artifacts.py:82-87`. Only the `content` column is in the update dict, so type, project and
provenance cannot be touched by this endpoint regardless of what was sent.

### `download_artifact`

```python
@router.get("/artifacts/{artifact_id}/download", response_model=DownloadLink)
def download_artifact(
    artifact_id: str,
    inline: bool = Query(False, description="Preview in the browser instead of downloading"),
    ...
    store: FileStore = Depends(get_file_store),
) -> DownloadLink:
    """A time-limited link to the artifact's exported file."""
    artifact = require_artifact(artifact_id, user_id, database)
```

`artifacts.py:90-99`. `inline` at line 93 selects `Content-Disposition: inline` instead of
`attachment`, which is the difference between previewing a PDF in an iframe and downloading it.

```python
    export = (artifact.get("content") or {}).get("binary")
    if not export:
        raise HTTPException(status_code=404, detail="This artifact has no exported file")

    key = export.get("storage_path")
    if not key:
        raise HTTPException(status_code=500, detail="Export metadata is missing its storage key")
```

`artifacts.py:101-107`. Line 101 is the read of the block hole 3 protected. Line 103 is a 404 —
the artifact exists, the file does not, which is the case for a notes artifact that was never
rendered. Line 107 is a 500 and correctly so: a `binary` block with no `storage_path` means the
renderer wrote something malformed, which is a server bug, not a client one.

```python
    file_format = export.get("format", "bin")
    filename = f"{artifact.get('type', 'artifact')}_{str(artifact_id)[:8]}.{file_format}"

    try:
        url = store.signed_url(key, filename=filename, inline=inline)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return DownloadLink(
        download_url=url,
        format=file_format,
        mime_type=export.get("mime_type", "application/octet-stream"),
        filename=filename,
    )
```

`artifacts.py:109-122`. The filename is constructed rather than stored — the artifact type plus
eight characters of its id plus the format, so a downloaded file is `quiz_a1b2c3d4.pdf` and not a
raw UUID. Truncating to eight characters is a readability trade; collisions in a downloads folder
are possible and unimportant.

`store.signed_url` raises `StorageError` if the key escapes the store root
(`files.py:82-83`), which becomes a 404 rather than a 500 because there is no sense telling the
caller the difference.

The endpoint returns a *description of a link*, not the bytes. That is the design decision worth
explaining: the actual serving is a separate unauthenticated route (`files.py`) whose credential is
the signature. Streaming bytes through this endpoint would work, but then a PDF preview in an
iframe or an image in an `<img>` tag would be impossible, because neither can attach an
`Authorization` header.

### `list_vault`

```python
@router.get("/vault")
def list_vault(
    limit: int = Query(VAULT_LIMIT, ge=1, le=1000),
    ...
    projects = database.select("projects", [("user_id", f"eq.{user_id}")], columns="id,name")
    if not projects:
        return {"files": []}

    names = {project["id"]: project.get("name") for project in projects}
    artifacts = database.select(
        "artifacts",
        [("project_id", f"in.({','.join(names.keys())})")],
        order="created_at.desc",
        limit=limit,
    )

    for artifact in artifacts:
        artifact["project_name"] = names.get(artifact["project_id"])

    return {"files": artifacts}
```

`artifacts.py:125-147`. Everything the caller owns across every project, newest first. Same
two-step shape as the cross-project branch of `list_jobs`: resolve owned project ids, then filter
artifacts by them. This is the only place ownership is enforced for this endpoint, and it is
enforced by construction — the query cannot return an artifact from a project not in the list.

Line 136 keeps the project names so line 145 can decorate each artifact with `project_name`. The
alternative would be a join; this is a dict lookup per row in Python, and it means the frontend can
render "Quiz — Distributed Systems" without a second request.

---

## 6. `backend/api/routes/files.py`

47 lines, and the shortest module in the layer. The file store itself is documented separately;
this is only the route surface.

```python
router = APIRouter(prefix="/api/files", tags=["files"])

CACHE_SECONDS = 300
```

`files.py:12-14`.

```python
@router.get("/{key:path}")
def serve_file(
    key: str,
    expires: int = Query(description="Unix timestamp after which the link is dead"),
    signature: str = Query(description="HMAC over the key and expiry"),
    disposition: str = Query("attachment", pattern="^(attachment|inline)$"),
    filename: str = Query("download"),
    store: FileStore = Depends(get_file_store),
) -> FileResponse:
```

`files.py:17-25`. Four things to notice.

`{key:path}` at line 17 is a FastAPI path converter that allows slashes, because storage keys look
like `<project-id>/exports/<uuid>.pdf` and a normal path parameter would stop at the first slash.

`expires` and `signature` at lines 20-21 have no default, which makes them required query
parameters — a request without them is a 422 before the body runs.

`disposition` at line 22 is constrained by a regular expression to exactly `attachment` or
`inline`. That is not cosmetic. The value is interpolated into a response header at line 44. Without
the pattern, a caller could put a newline and a second header into it. This is header injection
defence expressed as a validator.

`filename` has a harmless default and is escaped at line 44 by `quote()`, for the same reason.

```python
    """
    Serve a stored object.

    The signature is the credential: these links go to image tags, iframes and
    download managers that cannot send a bearer token, and they expire.
    """
    if not store.verify(key, expires, signature):
        raise HTTPException(status_code=403, detail="This link is invalid or has expired")
```

`files.py:26-33`. **There is no user check on this route, and that is deliberate.** The docstring
says why. `FileStore.verify` at `files.py:113-117` does two things: rejects an expired link, and
compares the HMAC using `hmac.compare_digest`, which is constant-time so the comparison does not leak
information through timing.

The signature is computed over `f"{key}:{expiry}"` (`files.py:111`), both values together. That
matters: signing them separately, or signing only the key, would let a holder extend a link by
editing the `expires` parameter. Because they are signed as one string, changing either invalidates
the signature.

The test at `test_api.py:1002` tampers with the signature and asserts 403.

**And the thing this whole scheme rests on, which is worth raising here unprompted.** Every
property above — the expiry inside the signature, the constant-time comparison, the confined
key — is worth nothing if the HMAC key is a value published in the repository, because then a
stranger with no session can compute a valid signature for any object in the store. It used
to be: `signing_secret` defaulted to a literal in `backend/core/config.py`, and
`.env.example` and `docker-compose.yml` shipped a second one. That is closed now — the
default is gone, a private key is minted and persisted per installation, and
`require_unforgeable_links` at `main.py:41-56` refuses to start on either published value.
The full account is in document 01; the reason to mention it here is that this route is where
the consequence would have landed.

```python
    try:
        path = store.open_path(key)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return FileResponse(
        path,
        media_type=store.content_type(key),
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": f"private, max-age={CACHE_SECONDS}",
        },
    )
```

`files.py:35-47`. `open_path` resolves the key against the store root and refuses anything that
escapes it (`files.py:75-84`), so a signed link to `../../etc/passwd` would fail here even if
someone had somehow obtained a signature for it. `test_api.py:1012` covers the traversal case at the
store level.

`filename*=UTF-8''...` is the RFC 5987 encoded form, which is how you put a non-ASCII filename in a
`Content-Disposition` header. `Cache-Control: private` keeps intermediary caches out of it;
`max-age=300` is well inside the one-hour link lifetime, so a cached response can never outlive its
credential by much.

**The trade to be able to state.** Anyone holding a link can fetch the file for up to an hour, with
no account and no session, including after the artifact has been deleted. That is inherent to signed
URLs and it is the price of being able to render a PDF in an iframe. The mitigations are the short
expiry and the fact that keys are not guessable.

---

## 7. `backend/api/routes/flows.py`

146 lines. This is the best of the ownership stories, because the code here was not wrong — the fix
elsewhere was incomplete. It is the first of the two holes with that shape; the SSRF under
`schemas.py` is the second, and telling them as a pair is stronger than telling either alone.

### Header

```python
router = APIRouter(prefix="/api/projects", tags=["flows"])
```

`flows.py:18`. Note the prefix collides deliberately with `projects.py`. Flow endpoints are nested
under a project (`/api/projects/{id}/flow/run`) but live in their own module, because they are a
different concern. FastAPI merges routers with the same prefix without complaint.

### `_graph` — the second and third doors

```python
def _graph(project: Dict[str, Any], request: FlowRequest) -> Tuple[List[dict], List[dict]]:
    """
    The graph to compile: whatever the client sent, else the saved canvas.

    Autosave is debounced, so the canvas on screen is routinely ahead of what is
    stored and running the stale copy would ignore the last node connected.
    """
    if request.nodes is not None:
        return request.nodes, request.edges or []

    canvas = project.get("canvas_state") or {}
    return canvas.get("nodes") or [], canvas.get("edges") or []
```

`flows.py:21-32`. Two sources of graph, and both are caller-written.

Line 28 tests `is not None`, not truthiness. An explicitly-sent empty node list is a different thing
from an omitted one, as discussed under `FlowRequest`. An omitted `nodes` with a present `edges` is
nonsense and is handled by falling through to the saved canvas entirely.

The docstring explains why the request body wins. Canvas autosave is debounced on the frontend, so
at any given moment the saved `canvas_state` may be several seconds behind what the user sees. If Run
always used the stored copy, the most common bug report would be "I connected a node and pressed Run
and it ignored it".

The security-relevant point: the saved canvas is not more trustworthy than the request body. It got
into the database through `PATCH /api/projects/{id}`, which stores it without validation. Both
branches of this function return client-written data.

### `_require_owned_seeds` — hole 5

```python
def _require_owned_seeds(
    plan: FlowPlan,
    project_id: str,
    user_id: str,
    database: Database,
) -> None:
    """
    Assert every artifact the canvas seeds the run with sits in this project.

    The nodes are client-supplied, so a seed id is a request to read a stored
    artifact. Handlers resolve those ids without an ownership check, which makes
    this the last point where naming somebody else's artifact can be refused.
    The whole request fails rather than the offending node being dropped: a flow
    that quietly ran without one of its inputs is worse than one that refused.
    """
    for node_id, artifact_id in plan.seed_artifacts.items():
        try:
            require_project_artifact(artifact_id, project_id, user_id, database)
        except HTTPException as error:
            raise HTTPException(
                status_code=error.status_code,
                detail=f"Node '{node_id}': {error.detail}",
            ) from error
```

`flows.py:35-58`. **This is hole 5, and it is the story worth telling properly.**

The sequence of events. Hole 1 was found and fixed: `create_job` now checks its source artifact
ids. A test was written for it. Then the right question was asked — *does anything else reach the
same handler by another route?* — and the answer was yes.

Trace it. A canvas node of type `artifactNode` carries `data.artifact.id`. `FlowCompiler._classify`
at `services/flow/plan.py:155-158` calls `_artifact_id(node)`, which lifts that value straight out
of the node dict, and files it in `seeds`. `FlowCompiler.compile` returns
`FlowPlan(steps=..., seed_artifacts=seeds)` at `plan.py:139`. `FlowEngine.start` at
`services/flow/engine.py:84-85` writes each seed into the run's `node_states` as
`{"status": "ready", "artifact_id": artifact_id}`. `FlowEngine._schedule` then reads those states at
`engine.py:132` to build the source list for each ready step, and `_queue_job` at `engine.py:255-273`
inserts a `generate` job row whose payload contains `source_artifact_ids: sources` — **inserted
directly into the jobs table, not through `POST /api/jobs`.**

So every check added to `create_job` was bypassed. The flow route was a second front door into
exactly the same handler with exactly the same primitive: name a foreign artifact id, get its
content generated into your own project.

It was confirmed exploitable before being fixed. `POST /api/projects/{mine}/flow/run` with a canvas
whose source node named an artifact in a project owned by `someone-else` returned 202, and the
queued job row visibly contained the foreign id in its payload.

And there was a third door. Running with an empty body falls through `_graph` to the saved canvas,
and the saved canvas is equally caller-written because `PATCH /api/projects/{id}` stores it
unvalidated. Fixing only the request-body path would have left "save the canvas first, then run with
no body" working.

The fix is this function, called from both flow entry points.

Line 50 iterates `plan.seed_artifacts`, which is a mapping of node id to artifact id. Iterating the
compiled plan rather than the raw nodes is the right choice: the compiler is the thing that decides
which nodes count as seeds, so checking its output means the check covers exactly what will actually
be read, including any node shape the compiler recognises now or later. Checking the raw node list
would require duplicating `_is_source` and `_artifact_id`, and the duplicate would drift.

Line 52 reuses `require_project_artifact` — the same function that closes hole 1. One rule, one
implementation, two entry points.

Lines 53-57 catch the `HTTPException` and re-raise it with the node id prefixed onto the detail,
preserving the original status code. Without that, the client gets "Access denied" with no way to
know which of forty nodes caused it. The test at `test_api.py:540` asserts `"s1"` appears in the
detail.

The docstring's last sentence is the design decision: the whole request fails rather than the
offending node being skipped. Dropping the node would leave a flow that ran, reported success, and
quietly produced output from fewer inputs than the user connected. A refusal is legible; a silently
degraded result is not.

Three tests cover the three doors. `test_api.py:524` is the request body. `test_api.py:544` saves a
poisoned canvas and runs with an empty body. `test_api.py:556` covers validate, which compiles the
same graph and must not report a foreign-seeded flow as runnable. Each of the first two asserts that
no `jobs` row and no `flow_runs` row was created.

### `validate_flow`

```python
@router.post("/{project_id}/flow/validate", response_model=FlowPlanResponse)
def validate_flow(...)
    """Compile the graph and report the plan, or why it will not run."""
    project = require_project(project_id, user_id, database)
    nodes, edges = _graph(project, request)

    try:
        plan = FlowCompiler().compile(nodes, edges)
    except FlowValidationError as error:
        return FlowPlanResponse(valid=False, error=str(error))

    _require_owned_seeds(plan, project_id, user_id, database)

    return FlowPlanResponse(
        valid=True,
        waves=len(plan.waves),
        steps=[
            FlowStepView(
                node_id=step.node_id,
                target_type=step.target_type,
                parents=step.parents,
                depth=step.depth,
            )
            for step in plan.steps
        ],
    )
```

`flows.py:60-90`. A dry run. It compiles and reports, and creates nothing — the test at
`test_api.py:325` asserts the jobs table is still empty afterwards.

Note the asymmetry in how the two failure kinds are reported. A compile failure at lines 73-74 is a
**200 with `valid: false`**. A foreign seed at line 76 is a **403 exception**. That is intentional
and worth being able to defend: a graph that does not compile is a normal state of a canvas being
edited — you have dragged in a generator and not connected it yet, and the UI should show a hint
next to the node. An artifact id you are not allowed to read is not an editing state; it is a
refused request, and it belongs in the status code.

The order also matters: seeds are checked after compilation, because `seed_artifacts` does not exist
until the graph compiles. A malformed graph never reaches the ownership check, which is fine — a
graph that cannot run cannot read anything.

`FlowStepView` is built field by field rather than by dumping the dataclass, so `instructions` —
which is on `FlowStep` — is not echoed back.

### `run_flow`

```python
@router.post("/{project_id}/flow/run", response_model=FlowRunResponse, status_code=202)
def run_flow(...)
    """Start a flow run and dispatch its first wave."""
    project = require_project(project_id, user_id, database)
    nodes, edges = _graph(project, request)

    try:
        plan = FlowCompiler().compile(nodes, edges)
    except FlowValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    _require_owned_seeds(plan, project_id, user_id, database)
    run = FlowEngine(database).start(project_id, nodes, edges, dispatch=enqueue)

    logger.info("Flow run %s started", run["id"])
    return FlowRunResponse(**{field: run.get(field) for field in FlowRunResponse.model_fields})
```

`flows.py:93-113`. Same first four steps as validate, then execution.

Here a compile failure **is** an error — 422, at line 107 — because running an uncompilable graph is
a client mistake, not an editing state. The test at `test_api.py:354` posts an empty graph and
asserts 422.

Line 109 is the security check, standing immediately in front of line 110, which is the only line in
the module that writes anything.

`dispatch=enqueue` at line 110 injects the dispatcher rather than letting the engine import it. That
keeps `FlowEngine` testable without a broker — `test_flow_engine.py` passes a recording function
instead.

**Worth knowing.** The graph is compiled twice: once here at line 105, and again inside
`FlowEngine.start` at `engine.py:78`. That is not a bug — the route needs a plan in order to check
the seeds before anything is written, and the engine's contract is "nodes and edges in, run row out"
rather than "pre-compiled plan in". Compilation is a topological sort over at most 100 nodes
(`plan.py:15`) with no I/O, so the cost is negligible, and the inputs are identical so the two plans
cannot differ. But it is exactly the kind of thing an interviewer notices, and the answer is that
the alternative — passing the plan in — would let a caller of the engine supply a plan that had
never been validated.

The response returns the run's `node_states`, which is what the test at `test_api.py:343` inspects
to prove wave semantics: with a source feeding two generators and one of those feeding a third, `g1`
and `g2` are `running` and `g3` is still `pending`.

### `list_flow_runs` and `get_flow_run`

```python
@router.get("/{project_id}/flow/runs")
def list_flow_runs(...)
    require_project(project_id, user_id, database)
    return FlowEngine(database).list_for_project(project_id)
```

`flows.py:116-124`. Ownership then delegate. Capped at 10 inside the engine
(`engine.py:247`).

```python
@router.get("/{project_id}/flow/runs/{flow_run_id}", response_model=FlowRunResponse)
def get_flow_run(...)
    """
    The current state of a flow run.

    Live updates arrive over the WebSocket; this lets a reconnecting client
    resynchronise without replaying the event stream.
    """
    require_project(project_id, user_id, database)

    run = FlowEngine(database).get(flow_run_id)
    if not run or run["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Flow run not found")

    return FlowRunResponse(**{field: run.get(field) for field in FlowRunResponse.model_fields})
```

`flows.py:127-146`. Line 143 does the ownership work in an interesting way: rather than a second
`require_project` on the run's own project, it asserts the run belongs to the project in the URL —
whose ownership was already proved at line 140. A run in someone else's project produces the same
404 as a run that does not exist, which here is the better answer, because the caller has no
legitimate reason to distinguish the two.

The docstring explains why a polling endpoint exists alongside a live socket: reconnection. A client
that slept through part of a run cannot replay events it missed, so it reads the current state
instead. This is the same reasoning behind the snapshot frame in `ws.py`.

---

## 8. `backend/api/routes/chat.py`

204 lines. The assistant. It does one interesting thing: it decides whether a message is a request
to change the artifact or a question about it, and only the first queues a job.

### Header and prompt

```python
router = APIRouter(prefix="/api/chat", tags=["assistant"])

ARTIFACT_CONTEXT_LIMIT = 6_000
SUMMARY_CONTEXT_LIMIT = 2_000
HISTORY_LIMIT = 50
```

`chat.py:23-27`. Two character budgets and a page size. The limits exist because the context is
assembled by string slicing and an unbounded artifact would blow the model's context window and the
request cost.

```python
CLASSIFIER_PROMPT = """
You are the assistant inside a study-material generator. The user is looking at
an artifact and has sent you a message.

Choose one action:

- "refine" when they want the artifact changed, regenerated or made different:
  "make it harder", "add more examples", "focus on chapter 3", "too easy",
  "shorter please". Restate their request as a clear directive in instructions,
  and set target_type to the artifact type to produce.
- "answer" when they are asking a question and the artifact should not change:
  "what does this mean?", "why is B correct?", "explain X".

When it is genuinely ambiguous, choose "answer" and ask what they want changed.
Regenerating something the user did not ask you to regenerate is worse than one
extra question.

Always fill reply. For a refine, confirm briefly what you are about to change.
For an answer, give the answer, grounded in the material below, and say so when
the material does not cover it.
"""
```

`chat.py:29-49`. This is the classifier, and it is a prompt rather than a keyword matcher because
the distinction is genuinely semantic. "Is this quiz too easy?" is a question. "This quiz is too
easy" is a refine. No rule over word lists gets that right.

The three design points in the prompt, in order of importance:

Line 42-44 sets the tie-break: when it is ambiguous, answer. That is the asymmetry-of-cost argument
made explicit to the model. A wrong "answer" costs the user one extra sentence of clarification. A
wrong "refine" spends a model call, overwrites what they were reading, and — if they had edited it —
may destroy work. Bias toward the cheap mistake.

Lines 35-38 give the model concrete examples of each class rather than abstract definitions,
because short imperative phrases are what people actually type and they are the ambiguous cases.

Lines 46-48 require `reply` on both branches, so a refine confirms what it is about to do rather
than silently starting.

### `Intent`

```python
class Intent(BaseModel):
    """How the assistant read the user's message."""

    action: str = Field(description="'refine' to change the artifact, 'answer' to reply")
    target_type: Optional[str] = Field(None, description="Artifact type to produce when refining")
    instructions: Optional[str] = Field(None, description="The change, restated as a directive")
    reply: str = Field(description="What to say back to the user")
```

`chat.py:52-58`. The structured output schema. It is passed to `provider.complete_as`
(`llm/base.py:33`), which validates the model's response against it, so the code below is working
with a parsed object rather than parsing prose.

The `description` on each field is not documentation for humans — it is part of the schema sent to
the model and is how the model knows what to put in each slot. That is why they are written as
instructions.

**Worth knowing.** `action` is a plain `str`, not a `Literal["refine", "answer"]`. A `Literal` would
have the schema enforce the two values and reject anything else. As written, a model returning
`"REFINE"` or `"clarify"` would validate, and then fail the `!= "refine"` test at line 121 and fall
into the answer branch. That is a safe failure, so the loose type is survivable — but a `Literal`
would be strictly better and it is a fair thing to concede.

### `AssistantContext`

```python
class AssistantContext:
    """Assembles what the model needs to see to answer or revise."""

    def __init__(self, database: Database, flattener: Optional[ArtifactFlattener] = None) -> None:
        self._database = database
        self._flattener = flattener or ArtifactFlattener()

    def build(self, project_id: str, artifact: Optional[Dict[str, Any]], message: str) -> str:
        return (
            f"{self._project(project_id)}\n\n"
            f"--- ARTIFACT IN VIEW ---\n{self._artifact(artifact)}\n\n"
            f"--- USER MESSAGE ---\n{message}"
        )
```

`chat.py:61-73`. A small class rather than a function because it holds two collaborators. The
flattener is injectable for testing.

`build` produces three labelled sections: what the project is about, what is on screen, and what the
user said. The delimiters are there so the model can tell where the user's text starts, which also
means a user message containing the word "ARTIFACT" cannot be confused for a section header.

```python
    def _project(self, project_id: str) -> str:
        cores = self._database.select(
            "artifacts",
            [("project_id", f"eq.{project_id}"), ("type", "eq.knowledge_core")],
            order="created_at.desc",
            limit=1,
        )
        if not cores:
            return "This project has no source material yet."

        core = (cores[0].get("content") or {}).get("core") or {}
        concepts = ", ".join(concept.get("name", "") for concept in (core.get("concepts") or [])[:12])
        return (
            f"Project material: {core.get('title', 'Untitled')}\n"
            f"Summary: {(core.get('summary') or '')[:SUMMARY_CONTEXT_LIMIT]}\n"
            f"Key concepts: {concepts}"
        )
```

`chat.py:75-91`. The project side of the context is the most recent knowledge core, reduced to a
title, a truncated summary and up to twelve concept names. Not the whole core — that would be tens
of thousands of characters, most of it irrelevant to answering "why is B correct?". The concept list
gives the model the vocabulary of the material, which is usually enough to ground an answer or to
notice that the material does not cover the question.

Line 83's fallback matters: a project with no ingested source still gets a coherent context line
rather than an empty string, so the model knows why it has nothing to work with.

```python
    def _artifact(self, artifact: Optional[Dict[str, Any]]) -> str:
        if not artifact:
            return "No artifact is open."

        body = self._flattener.flatten(artifact) or ""
        return f"Type: {artifact.get('type')}\nContent:\n{body[:ARTIFACT_CONTEXT_LIMIT]}"
```

`chat.py:93-98`. `ArtifactFlattener.flatten` (`handlers/sources.py:29`) renders any artifact type
back into plain text — a quiz becomes questions and answers, a mindmap becomes an indented outline.
Reusing it here rather than writing a second renderer means the assistant sees the artifact the same
way the generation pipeline does when chaining.

`or ""` handles a type the flattener has no renderer for, which returns `None`.

### `send_message` — the two branches

```python
@router.post("", response_model=ChatResponse)
async def send_message(
    request: ChatRequest,
    user_id: str = Depends(get_current_user),
    database: Database = Depends(get_db),
    provider: LLMProvider = Depends(get_provider),
) -> ChatResponse:
    """Answer a message, or queue a refinement of the artifact in view."""
    require_project(request.project_id, user_id, database)
    artifact = (
        require_project_artifact(request.artifact_id, request.project_id, user_id, database)
        if request.artifact_id
        else None
    )
```

`chat.py:101-114`. `async def` because the model call is awaited. The provider is injected as a
dependency so tests get the offline provider.

Lines 109-114 are the authorisation, and note that line 111 uses `require_project_artifact`, the
strict version. The artifact in view must be one the caller owns *and* must be in the project named
in the request. That is the same check as holes 1 and 5, applied here because this endpoint also
ends up inserting a job whose `source_artifact_id` is that artifact.

```python
    _record(database, request, "user", request.message, {})

    context = AssistantContext(database).build(request.project_id, artifact, request.message)
    intent = await _classify(provider, context)
```

`chat.py:116-119`. The user's message is written to the transcript **before** classification. If the
model call fails or the process dies, the conversation history still contains what the user said. A
transcript missing the user's turn but containing the assistant's reply is worse than one missing
the reply.

```python
    if intent.action != "refine":
        return _reply(database, request, ChatResponse(reply=intent.reply, action="answer"))
```

`chat.py:121-122`. **The answer branch.** Note the test is `!= "refine"`, not `== "answer"`. Anything
the model returns that is not exactly `"refine"` — including a hallucinated third value, or an empty
string — falls here. Default-to-safe, which is the same asymmetry the prompt states.

This branch queues nothing, writes no job, and returns the model's reply with `action="answer"` and
`job_id=None`. The frontend renders it as a chat message and does nothing else. This path was
verified end to end, including a question that could plausibly have been read as a refine being
correctly classified as an answer.

```python
    if artifact is None:
        return _reply(database, request, ChatResponse(
            reply="Open an artifact and I can revise it for you.", action="answer",
        ))
```

`chat.py:124-127`. First guard on the refine branch. The model may decide the user wants a change
even when nothing is open — "make it harder" with no artifact in view. There is nothing to refine, so
this degrades to an answer with a human explanation rather than a 400. The user asked a reasonable
thing in an unreasonable state; telling them what to do next is more useful than an error.

```python
    target_type = intent.target_type if intent.target_type in GENERATED_TYPES else artifact.get("type")
    if target_type not in GENERATED_TYPES:
        return _reply(database, request, ChatResponse(
            reply=f"I cannot regenerate a '{artifact.get('type')}' artifact.", action="answer",
        ))
```

`chat.py:129-133`. Two steps.

Line 129 validates the model's `target_type` against the real registry and falls back to the type of
the artifact in view if it is not valid. So a model that returns `"horoscope"`, or nothing at all,
produces "regenerate the thing they are looking at", which is almost always what was meant.

Line 130 then checks the fallback itself. Not every artifact type is generatable — a
`knowledge_core` is produced by ingestion, not by a generator, and `GENERATED_TYPES` does not contain
it. So a user looking at the knowledge core who asks for it to be shortened gets
"I cannot regenerate a 'knowledge_core' artifact" rather than a job that fails in a worker.

Both guards degrade to `action="answer"`, so the frontend never sees a refine response without a job
id.

```python
    job_id = database.insert("jobs", {
        "project_id": request.project_id,
        "type": "refine",
        "status": "pending",
        "payload": {
            "source_artifact_id": request.artifact_id,
            "instructions": intent.instructions or request.message,
            "target_type": target_type,
        },
    })[0]["id"]

    publish(request.project_id, JOB_CREATED, {"job_id": job_id, "type": "refine"})
    enqueue(job_id)
    logger.info("Assistant queued refine job %s", job_id)

    return _reply(database, request, ChatResponse(
        reply=intent.reply, action="refine", job_id=job_id, target_type=target_type,
    ))
```

`chat.py:135-152`. **The refine branch**, and the only place in this module that writes a job.

The payload is built here rather than by calling `create_job`. That is a deliberate shortcut and it
is worth knowing what it skips: the `REQUEST_MODELS` validation, the in-flight deduplication, and the
`_source_ids` ownership loop. Skipping the first two is fine — the payload is constructed from
already-validated values, and a refine is never deduplicated anyway. Skipping the third is only fine
because line 111 already ran `require_project_artifact` on `request.artifact_id`, which is the exact
same check on the exact same id. If that line were ever removed, this insert would become a fourth
door onto hole 1.

Line 141's `intent.instructions or request.message` falls back to the user's raw text if the model
did not restate it, so a refine never goes out with empty instructions.

`publish` then `enqueue` at 146-147, again after the row is committed.

**Worth knowing.** `database.insert(...)[0]["id"]` at line 135 indexes without checking for an empty
list. Every other route in this layer guards that with `if not rows: raise HTTPException(500, ...)`.
Here an insert that returned nothing would raise `IndexError` and be caught by the generic handler in
`main.py:149`, producing a 500 with a request id — the same status the guard would produce, but
through an unhandled exception rather than a deliberate one. It is an inconsistency, not a
vulnerability, and it is better to name it yourself.

### `get_history`

```python
@router.get("/{project_id}/history")
def get_history(...)
    require_project(project_id, user_id, database)
    messages = database.select(
        "chat_messages", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=limit
    )
    return list(reversed(messages))
```

`chat.py:155-167`. Ownership, then the last `limit` messages. The query orders newest-first because
that is how you take the most recent N; the result is reversed in Python at line 167 so the client
receives them oldest-first, which is how a transcript reads. Doing it the other way — oldest-first
with a limit — would return the *first* fifty messages of the conversation, which is the opposite of
what is wanted.

### `_classify`

```python
async def _classify(provider: LLMProvider, context: str) -> Intent:
    try:
        return await provider.complete_as(CLASSIFIER_PROMPT, Intent, context=context)
    except Exception as error:
        logger.warning("Assistant classification failed: %s", error)
        return Intent(
            action="answer",
            reply=(
                "I could not reach the model just now. Try again shortly, or tell me "
                "exactly what to change and I will regenerate the artifact."
            ),
        )
```

`chat.py:170-181`. The only place the model is called, and it cannot raise.

`complete_as` returns a validated `Intent` or raises — a network failure, a timeout, a rate limit, or
a response that does not fit the schema. All of them land here. Rather than propagating a 500, the
function synthesises an `Intent` with `action="answer"` and an honest message.

The fallback action is `"answer"` for the same reason as everything else on this path: a
classification failure must never result in a regeneration. The user gets a chat message explaining
the situation and a suggestion for what to do, and their artifact is untouched.

### `_reply` and `_record`

```python
def _reply(database: Database, request: ChatRequest, response: ChatResponse) -> ChatResponse:
    _record(database, request, "assistant", response.reply,
            {"action": response.action, "job_id": response.job_id})
    publish(request.project_id, CHAT_MESSAGE, response.model_dump())
    return response
```

`chat.py:184-188`. Every return path in `send_message` goes through this — there are five of them —
so there is no branch that can reply without recording the reply and publishing it. The metadata
carries the action and job id, so replaying the transcript later shows which turns queued work.

The publish is what lets a second browser tab on the same project see the conversation update live.

```python
def _record(
    database: Database,
    request: ChatRequest,
    role: str,
    content: str,
    metadata: Dict[str, Any],
) -> None:
    database.insert("chat_messages", {
        "project_id": request.project_id,
        "artifact_id": request.artifact_id,
        "role": role,
        "content": content,
        "metadata": metadata,
    })
```

`chat.py:191-204`. One insert. `artifact_id` is stored on the message so the transcript records what
was on screen at the time, which is what makes an old "make it harder" interpretable months later.

---

## 9. `backend/api/routes/ws.py`

149 lines. One WebSocket endpoint, and it replaced a lot of HTTP.

### Why it exists

Before this, the frontend polled. `useJobOrchestrator` started a generate job per artifact type and
then polled `GET /api/jobs/{id}` for each one until it finished. A single ingest fanning out to five
generators meant five concurrent polling loops, each waking on a timer, each producing a request that
almost always said "still running". Progress within a job — "cleaning text", 50 per cent — could not
be represented at all, because polling only sees status transitions. And flow runs made it worse: a
canvas with twenty nodes is twenty things to watch.

The socket inverts it. One connection per project, and the server pushes whatever happens. The
frontend's `ProjectSocket` (`frontend/lib/realtime.ts`) reconnects with exponential backoff and gives
up on the two fatal close codes defined below.

### Header

```python
router = APIRouter(tags=["realtime"])

HEARTBEAT_SECONDS = 25
SNAPSHOT_JOBS = 20
SNAPSHOT_FLOW_RUNS = 3
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
```

`ws.py:18-24`. No prefix, because the path is `/ws/...` and not under `/api`.

`HEARTBEAT_SECONDS = 25` is chosen to sit under the common 30-second and 60-second idle timeouts in
proxies and load balancers. A silent WebSocket is indistinguishable from a dead one to an
intermediary, and it will be closed.

The close codes are in the 4000-4999 range, which the WebSocket specification reserves for
application use. They mirror the HTTP codes deliberately — 4401 for unauthenticated, 4403 for
forbidden — so the frontend can treat them as fatal and stop retrying, which
`realtime.ts:50` does with `FATAL_CLOSE_CODES`. Retrying a 403 forever would be a busy loop.

### The handshake and authentication

```python
@router.websocket("/ws/projects/{project_id}")
async def project_events(
    websocket: WebSocket,
    project_id: str,
    token: Optional[str] = Query(None),
) -> None:
    """
    Stream events for one project.

    The token arrives as a query parameter because browsers cannot set headers
    on a WebSocket handshake, and it is checked before the socket is accepted.
    """
    database = get_database()

    try:
        user_id = resolve_user(f"Bearer {token}" if token else None)
        require_project(project_id, user_id, database)
    except HTTPException as error:
        code = CLOSE_FORBIDDEN if error.status_code == 403 else CLOSE_UNAUTHORIZED
        await websocket.close(code=code, reason=str(error.detail))
        return
```

`ws.py:27-47`. Three things here.

The token is a **query parameter**, and the docstring says why: the browser `WebSocket` constructor
takes a URL and a subprotocol list and nothing else. There is no way to set an `Authorization` header
on the handshake. The options are a query parameter, a cookie, or abusing the subprotocol field. A
query parameter is the conventional choice, and its cost is that the token appears in access logs.
Given that the token is currently a fixed string, that cost is zero today; it would matter with real
tokens.

Line 42 reconstructs a `Bearer ...` header string so `resolve_user` receives the same shape it
receives from `get_current_user`. That value is discarded inside `resolve_user`, but keeping the
call shape identical means the day the function verifies a real token, both entry points work
without further change. This is the seam mentioned in `deps.py`.

`get_database()` is called directly at line 39 rather than through `Depends`, because dependency
injection is not available on this handler.

Lines 44-47 are the important part: the check happens **before `websocket.accept()`**. An
unauthorised client never gets an open socket — it gets the handshake closed with a code. Accepting
first and closing after would mean an attacker could hold open sockets against the server for as long
as it took to check.

The mapping at line 45 turns a 403 into 4403 and anything else — in practice the 404 from
`require_project` — into 4401. The test at `test_api.py:412` connects to a foreign project and
asserts close code 4403.

### The three tasks

```python
    await websocket.accept()
    logger.info("WebSocket open for project %s", project_id)

    await _send_snapshot(websocket, database, project_id)

    tasks = [
        asyncio.create_task(_forward_events(websocket, project_id), name="ws-events"),
        asyncio.create_task(_heartbeat(websocket, project_id), name="ws-heartbeat"),
        asyncio.create_task(_read_client(websocket, database, project_id), name="ws-reader"),
    ]

    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        logger.info("WebSocket closed for project %s", project_id)
```

`ws.py:49-65`. Accept, snapshot, then three concurrent tasks.

The snapshot at line 52 goes out **before** any of them start, so a client that connects in the
middle of a run renders the current state immediately rather than showing an empty page until the
next event happens. Without it, joining a project whose jobs all completed an hour ago would show
nothing at all.

The three tasks are: forward bus events out, send a heartbeat every 25 seconds, and read frames in.

`asyncio.wait(..., return_when=FIRST_COMPLETED)` at line 61 is the whole lifecycle. The three tasks
are all long-running; if any one of them returns, the connection is over. In practice it is the
reader that returns first, when the client disconnects. The `finally` at 62-65 cancels the other two
unconditionally. Without that cancellation, a disconnected client would leave a heartbeat task
sleeping forever and an event subscription registered on the bus, and every reconnect would add
another pair — a slow leak that shows up as memory growth over a long session.

Cancelling the event task is what triggers the `finally` block in
`InProcessEventBus.subscribe` (`events.py:112-117`), which discards the queue and removes the project
key when it was the last subscriber. That is the cleanup that matters.

The socket is not explicitly closed here; Starlette closes it when the handler returns.

### `_forward_events`

```python
async def _forward_events(websocket: WebSocket, project_id: str) -> None:
    """Push bus events to the client until it goes away."""
    try:
        async for event in get_event_bus().subscribe(project_id):
            if websocket.client_state != WebSocketState.CONNECTED:
                return
            await websocket.send_json(event)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.debug("Event stream for %s ended: %s", project_id, error)
```

`ws.py:68-78`. `subscribe` is an async generator that yields events for one project. In-process it
is an `asyncio.Queue`; with Redis configured it is a pub/sub subscription
(`events.py:148`). The route does not know or care which — that is `build_bus`'s decision at
`events.py:179`.

Line 72 checks the connection state before each send. Without it a send on a closing socket raises,
which works but produces noise.

Lines 75-76 re-raise `CancelledError` explicitly. This is a real asyncio idiom and worth
understanding: `CancelledError` inherits from `BaseException` in Python 3.8+, so a bare
`except Exception` would not catch it — but the explicit clause is here to document the intent and to
guard against the ordering being changed later. Swallowing a cancellation would mean `task.cancel()`
in the handler's `finally` did not actually stop the task.

Line 77 logs at debug, not warning. An event stream ending because a client closed its laptop is the
normal case, not an incident.

**Worth knowing.** There is a race between the snapshot at `ws.py:52` and the subscription here. The
snapshot reads the database, then the task is created, then the task runs and registers with the bus.
An event published in that window is delivered to nobody and is not in the snapshot either. The
window is small — one event loop turn — and the mitigation is the `resync` message below, which lets
a client ask for a fresh snapshot at any time. Subscribing first and snapshotting second would close
the race at the cost of possibly delivering an event the client then sees again in the snapshot,
which would need deduplication by id. The current choice trades a rare miss for simplicity.

### `_heartbeat`

```python
async def _heartbeat(websocket: WebSocket, project_id: str) -> None:
    """Keep the connection alive through idle proxies."""
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await websocket.send_json(make_event("ping", project_id))
    except asyncio.CancelledError:
        raise
    except Exception:
        return
```

`ws.py:81-90`. A `ping` event every 25 seconds. It is an application-level frame using the same
envelope as every other event (`make_event` at `events.py:33`), not a WebSocket protocol ping, so the
client sees it as an ordinary message and can ignore it by type. Using the protocol-level ping would
be more correct but is not exposed by the browser `WebSocket` API, so a client could not observe it.

The loop condition is checked before the sleep, so a socket that has already closed does not wait 25
seconds before noticing.

### `_read_client`

```python
async def _read_client(websocket: WebSocket, database: Database, project_id: str) -> None:
    """
    Consume inbound frames.

    Reading is what makes a dropped connection detectable, and it lets a client
    ask for a fresh snapshot after waking from sleep.

    A disconnect returns rather than raising: nothing retrieves this task's
    result, so raising the ordinary end of a connection would leave asyncio
    logging an unretrieved exception for every socket that closes.
    """
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "resync":
                await _send_snapshot(websocket, database, project_id)
    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        return
    except Exception as error:
        logger.debug("Client stream for %s ended: %s", project_id, error)
```

`ws.py:93-114`. Two jobs, both explained in the docstring.

The first is disconnect detection. In Starlette, a WebSocket close arrives as a message on the
receive channel. If nothing is reading, `receive_json` is never called, the close is never observed,
and the handler sits in `asyncio.wait` while the other two tasks keep trying to send to a socket that
is gone. So a reader must exist even if the protocol were entirely server-to-client.

The second is `resync` at line 108, which is the client's escape hatch after a laptop wakes from
sleep or a background tab is throttled. Rather than reconnecting, the client asks for the current
state.

The `except WebSocketDisconnect: return` at lines 111-112 has a specific history. Starlette raises
`WebSocketDisconnect` when the client goes away, which is the ordinary end of every connection.
Nothing ever calls `.result()` on these tasks — `asyncio.wait` returns the task objects and the
handler ignores them — so when the task finishes with an exception, asyncio's default handler
eventually reports "Task exception was never retrieved" with a traceback. Every closed socket
produced one. The logs filled with tracebacks describing the most normal event in the system.
Returning instead of raising makes the task complete cleanly, which is what tells `asyncio.wait` the
connection is over without also producing noise.

### `_send_snapshot` and `_snapshot`

```python
async def _send_snapshot(websocket: WebSocket, database: Database, project_id: str) -> None:
    """Send current state so a client joining mid-run renders correctly."""
    try:
        await websocket.send_json(make_event("snapshot", project_id, _snapshot(database, project_id)))
    except Exception as error:
        logger.debug("Could not send a snapshot for %s: %s", project_id, error)
```

`ws.py:117-122`. Wrapped in a try because a client can disconnect between accept and first send, and
that should not take the handler down.

```python
def _snapshot(database: Database, project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    jobs = database.select(
        "jobs", [("project_id", f"eq.{project_id}")], order="created_at.desc", limit=SNAPSHOT_JOBS
    )
    runs = database.select(
        "flow_runs", [("project_id", f"eq.{project_id}")],
        order="created_at.desc", limit=SNAPSHOT_FLOW_RUNS,
    )

    return {
        "jobs": [
            {
                "id": job["id"],
                "type": job["type"],
                "status": job["status"],
                "result": job.get("result"),
                "error_message": job.get("error_message"),
            }
            for job in jobs
        ],
        "flow_runs": [
            {"id": run["id"], "status": run["status"], "node_states": run.get("node_states")}
            for run in runs
        ],
    }
```

`ws.py:125-149`. Two bounded queries and an explicit projection of each row.

The projection is the point. `job["payload"]` is not included, and neither is anything else the
client does not need. A job payload can be large and contains source ids and instructions; sending
twenty of them on every connect and every resync would make the snapshot heavy for no benefit. The
same reasoning applies to flow runs, where `plan` is omitted and only `node_states` — the thing that
drives the canvas rendering — is sent.

The limits (20 jobs, 3 flow runs) bound the frame size. A project with a thousand historical jobs
still sends a small snapshot.

Note this function is synchronous and performs database reads inside an async handler, which blocks
the event loop for the duration. Two indexed SQLite selects against a local file are microseconds, so
it is not worth the machinery of a thread pool — but it is a real property of the code and an
interviewer familiar with asyncio may ask about it.

---

## 10. `backend/api/routes/__init__.py`

```python
"""HTTP and WebSocket route modules, one per resource."""
```

One line. It exists to make `backend.api.routes` a package so that `main.py:20` can write
`from backend.api.routes import artifacts, chat, files, flows, jobs, projects, ws`. Nothing is
re-exported here on purpose: `main.py` imports the modules and reads `.router` off each in the loop
at `main.py:160`, so adding a route module is a two-word change in one place.

`backend/api/__init__.py` is the same, with the docstring "The HTTP and WebSocket surface."

---

## The six holes, and the line that closes each

Under pressure, this is the section to find. Each entry is the hole, the exact line, and the test.

**1. `create_job` never checked its source artifacts.**
A caller who owned project B could queue a generate or refine job naming artifact ids from project A,
and the handler would read them and write their content into B. Ownership of the destination was
checked; ownership of the sources was not, and handlers have no user id to check with.

- Fix: `backend/api/routes/jobs.py:57-58` — the loop calling `require_project_artifact` on every id
  returned by `_source_ids`.
- Supporting: `jobs.py:142-148` (`_source_ids`) and `backend/api/deps.py:70-87`.
- Tests: `backend/tests/test_api.py:444` (generate), `:457` (refine), `:469` (a project of the caller's
  own), `:497` (nonexistent id). Each
  asserts no job row was written.

**2. A NULL owner satisfied every ownership check.**
The check was `if owner and owner != user_id`, and `None` is falsy, so an unowned project short-
circuited to allowed. Read returned it; `list_projects` did not, because `WHERE user_id = ?` never
matches NULL.

- Fix: `backend/api/deps.py:48` — `if project.get("user_id") != user_id`.
- Tests: `test_api.py:566` (project), `:578` (its artifacts).

**3. `update_artifact` merged client content wholesale.**
A caller could PATCH `content.binary.storage_path` to any key in the file store, then call
`/download` and have the server sign a link to it. The download endpoint reads that field at
`artifacts.py:105` and signs whatever key it finds.

- Fix: `backend/api/routes/artifacts.py:78-80` — `merged.pop("binary", None)` followed by restoring
  the stored `binary` if there was one. The export block is renderer-owned and unreachable from the
  API.
- Tests: `test_api.py:601` (cannot repoint an existing export; follows the link and checks the
  bytes), `:632` (cannot attach one where there was none).

**4. An ingest source carrying a filesystem path was an arbitrary file read.**
Two halves, and they were closed a long way apart. The YouTube half: `source_type: "youtube"`
routes to `yt_dlp.extract_info` at `backend/pipeline/ingestion.py:198`, which reads local files
given a path. The other half, which survived the first fix: `pdf`, `audio`, `video`, `pptx` and `md`
went down the upload branch of `IngestHandler._store`, which read the named path directly — no
downloader involved, the same arbitrary read, and no check on it at all.

- Fix, YouTube half: `backend/api/schemas.py:88-90` — the scheme test inside
  `only_youtube_is_named_by_a_url`, requiring an `http://` or `https://` prefix.
- Fix, the other half: `backend/api/schemas.py:91-95` — the `elif`, which refuses a `source_ref`
  on any non-YouTube source type outright. Those types are named by `staged_key` now, a storage key
  the upload endpoint minted, and `UploadStaging._require_staged_by` (`uploads.py:79-92`) accepts
  only the three-segment shape it writes. There is no field left that can hold a path.
- Second line of defence: `IngestHandler._staged_upload_path` (`ingest_handler.py:174-193`) refuses
  a non-YouTube job with no `staged_key`, at the point of use rather than at the door.
- Tests: `test_api.py:650` (a YouTube path is refused, no job written), `test_api.py:666`
  (parametrised over `sorted(SOURCE_TYPES - {"youtube"})`, so all five other types), `:692` (a job
  naming neither), `:723` (a real YouTube URL still validates), and `test_seams.py:394` (the handler
  refuses one even if a row somehow exists).
- Still incomplete on the scheme alone: it constrains the scheme and not the host, which is hole 6.
- What it cost: the hackathon workspace page posted a typed local path as `source_ref` for every
  source type, and for the five non-YouTube ones that now gets a 400. The real upload path is
  `/upload`, which is multipart. The convenience was the reason the hole stayed open; it was not a
  good enough reason.

**5. `/flow/run` reached the same handler through a different door.**
Canvas nodes arrive in the request body, `FlowCompiler` lifts artifact ids out of them into
`plan.seed_artifacts` (`services/flow/plan.py:158`), and `FlowEngine` writes them straight into a
generate job's `source_artifact_ids` (`services/flow/engine.py:227-238`) without ever passing through
`POST /api/jobs`. Confirmed exploitable: a 202, with the foreign id visible in the queued job's
payload. The saved canvas was a third door, because `PATCH /api/projects/{id}` stores it unvalidated
and running with an empty body falls back to it.

- Fix: `backend/api/routes/flows.py:35-58` (`_require_owned_seeds`), called at `flows.py:76`
  (validate) and `flows.py:109` (run) — immediately before `FlowEngine.start` at `flows.py:110`.
- Tests: `test_api.py:524` (request body), `:544` (saved canvas), `:556` (validate).

This is the one to tell as a story rather than a fact, because it is about process. Hole 1 was fixed
and tested. Then the question was asked — does anything else reach that handler by another route? —
and the answer was yes, twice. The lesson is that fixing the endpoint is not the same as fixing the
capability, and the way to find the difference is to trace from the dangerous operation backwards to
every caller, not forwards from the endpoint you happened to be looking at.

**6. A `youtube` ingest could fetch any URL the server could reach, and hand you the response.**
The scheme check in `schemas.py` constrained `http`/`https` and said nothing about the host. yt-dlp
gives an unrecognised URL to its generic extractor, which downloads the response body verbatim when
it is not media, and the pipeline stored that body in the caller's project, extracted text from it,
distilled it into a knowledge core and committed it as a readable artifact. Proven end to end
against a stand-in for the cloud instance-metadata endpoint at `169.254.169.254`: one
`POST /api/jobs`, and the resulting artifact's summary contained the response body verbatim,
credential-shaped strings included. Failed fetches were useful too — `GET /api/jobs/{id}` returns
`error_message`, and refused, timed out and answered are three distinguishable outcomes, which is a
working internal port scanner driven through a public API.

- Fix: `backend/pipeline/ingestion.py:53-155` (`HostResolver` and `YouTubeUrlGuard`), called from
  `store_youtube` at `ingestion.py:184` — the first statement in the function, before yt-dlp is
  constructed. Suffix-matched host allow-list, then every resolved address checked against the
  non-public ranges, one bad answer being enough to refuse.
- API-layer half: `backend/api/schemas.py:71-96` keeps its scheme check as a cheap early rejection,
  and its docstring now says explicitly that it is **not** the host guard.
- Tests: `test_api.py:786-935` (`TestYouTubeIngestGuard`), notably `:861`, which proves the guard
  runs before yt-dlp is constructed rather than after it has already fetched, and `:857`, which
  proves a genuine YouTube URL still works.

Tell this one alongside hole 5, because it is the same lesson a second time and that is what makes
it worth telling. Hole 5 was a fix at one door while another door reached the same code. Hole 6 is a
fix at one *layer* while the layer below it was what actually made the call. The rule that came out
of both: validate at the boundary for a cheap, legible rejection, but **authorise at the operation**,
because the operation is the only place where the set of callers is closed.

**Also: the auth bypass.** `resolve_user` used to accept any header containing `mock-token` as a
fixed user, in every deployment, not behind a flag. It now ignores the header and returns
`LOCAL_USER_ID` — `backend/api/deps.py:14-23`. That is not authentication; it is an honest statement
that there is none, in one function, which is the seam to replace.

**Also: the upload route contradicted the ingest model.** `POST /api/projects/{id}/upload` checked
`source_type not in SOURCE_TYPES`, and `SOURCE_TYPES` contains `"youtube"`, so a multipart upload
declaring `source_type=youtube` queued a job whose `source_ref` was a filesystem path and whose
handler took the download branch with it. Two fixes: `UPLOADABLE_SOURCE_TYPES` at
`backend/api/routes/projects.py:27` with the gate at `projects.py:144-148`, and `_ingest_payload` at
`projects.py:177-199`, which builds the payload through `IngestRequest` so the two ingest doors
share one definition instead of duplicating it. Test: `test_api.py:916`, which asserts the 400, that
no job row was written, and that `"youtube"` no longer appears in the list of allowed types.

**Also: upload was broken in the distributed configuration, which is not a security hole but is the
worst bug in this list.** The route staged the upload in the operating system temp directory and put
that absolute path into the job payload. Under `docker-compose.celery.yml` the API and the workers
are separate containers with separate `/tmp`, so the worker could not open the file and *every*
upload failed with `No readable file at /tmp/tmplvqcq44o.md`. It worked in the single-container
shape only because there the worker pool runs inside the API process. Fixed by staging into the file
store, which sits on the `beedata` volume mounted into every container: `backend/services/uploads.py`
(`UploadStaging`), called from `_stage_upload` at `projects.py:202-236` and read back by
`IngestHandler._staged_upload_path` at `ingest_handler.py:174-193`. The payload carries a storage key
now, which also means `GET /api/jobs/{id}` stopped disclosing a server path. Tests:
`test_seams.py:432-518` (`TestCrossProcessIngest`), which destroys and replaces the accepting
process's temp directory, drops the module singletons, builds the handler only afterwards and then
runs the job through `JobExecutor().run_job` — the same entry point `tasks.py:44` uses — and
`test_api.py:97`, which asserts the payload discloses no host path through the HTTP endpoint.

**Also: the link-signing key was published in this repository.** `signing_secret` defaulted to
`beeprepared-dev-secret` in `backend/core/config.py`, and `.env.example` and `docker-compose.yml`
shipped `change-me-in-production`. The signed-link scheme in `files.py` is otherwise sound, and all
of it is worth nothing against a known key: anyone could mint a valid link for any object in the
store with no session. Fixed in `backend/core/config.py` (no default, `PUBLISHED_SECRETS`, and a
minted-and-persisted `LocalSigningSecret`) and enforced by `require_unforgeable_links` at
`backend/main.py:41-56`, called first in lifespan. Tests: `test_api.py:957`, `:963`, `:968`. Walked
through in document 01; it belongs in this list because `api/routes/files.py` is where it would have
been exploited.

---

## What is still open, in your own words

Volunteer these. They are stronger said than extracted.

**Nobody is authenticated.** `resolve_user` returns the same id for every caller, so the four
cross-tenant holes — 1, 2, 3 and 5 — are not exploitable across users today, because there is only
one user. The ownership model is real in the queries and in the tests, and vacuous in practice until
an identity provider exists. What the fixes bought is that the day a real `resolve_user` lands, the
rest of the layer is already correct; the alternative would have been shipping four holes that all
become live on the same commit.

Be careful to scope that claim correctly, because it does not cover everything. The SSRF was not an
ownership bug and did not need a second user: it reached the network the server sits on, from a
single-user install, through a caller's own project. The same was true of the published signing key,
which needed no session at all, and of the arbitrary file read in hole 4 while it was open. "There is
only one user" defuses the cross-tenant holes and defuses nothing else, and saying so is the
difference between an honest summary and a convenient one.

**Ingest no longer accepts a path — this used to be the largest open item and it is closed.** It is
listed here because the previous version of this document said, at some length, that it was the first
thing to close before any multi-user deployment, and anyone who read that deserves the correction
rather than a silent deletion. `POST /api/jobs` with `type: "ingest"` and a non-YouTube
`source_type` used to accept an arbitrary `source_ref`, which `IngestHandler._store` then read,
extracted and committed as a downloadable artifact. Two changes closed it. `IngestRequest` now
refuses a `source_ref` on any source type but `youtube` (`schemas.py:91-95`), and an upload is named
by the `staged_key` it was staged under instead — a storage key whose shape and whose owning project
are both checked (`uploads.py:79-92`). `IngestHandler._staged_upload_path`
(`ingest_handler.py:174-193`) refuses it a second time at the point of use, because a job row can be
written by a route that forgets or replayed from the queue. Five parametrised tests at
`test_api.py:666` cover every non-YouTube source type.

What is genuinely left of that item is the YouTube door, and it is the next paragraph.

**The SSRF guard is a host allow-list, not a full SSRF defence.** `YouTubeUrlGuard` resolves the
hostname and checks the addresses, then yt-dlp resolves it again and connects. Between those two
resolutions there is a window, which is the classic DNS-rebinding shape: a name that answers with a
public address when the guard asks and a private one when the fetch happens. Closing it properly
means pinning the connection to the address that was checked, which needs a custom socket factory
underneath yt-dlp rather than a check in front of it. The same applies to redirects: `check` runs
once, on the URL the caller supplied, and yt-dlp follows any redirect itself without re-entering the
guard. What makes both acceptable in practice is that the host must be a YouTube domain to get past
the allow-list at all, so an attacker needs control of DNS for a `youtube.com` subdomain or a
redirect out of YouTube's own infrastructure — a much higher bar than pointing a field at an IP
address, which was the actual bug. Name this yourself. It is the natural follow-up question, and
having the answer ready is worth more than the guard being perfect.

**A job that exhausts its attempts leaves its staged upload behind.** Releasing the staged copy used
to be in a `finally`, which meant a *retryable* ingest failure deleted the only copy of what the
caller had uploaded, so the retry the runner queued failed for a second and unrelated reason and a
transient failure became permanent. Releasing now happens on the success path only
(`ingest_handler.py:245-262`), and the cost of that is one file per permanently-failed ingest sitting
in `{project}/staged/` with nothing referencing it. That is the cheaper of the two, but it is
unbounded, and the fix is a sweep for staging slots older than the job timeout, or a release when
`fail_job` records a terminal failure rather than a retryable one.

There is a narrower window in the same place, worth knowing about if someone reads the ordering
closely. The release happens inside `handler.run`, and `JobExecutor.execute` calls `commit_bundle`
*after* that (`job_runner.py:135-138`). So a failure between the release and the commit — in
practice, a failing `commit_bundle` — leaves a job that will be retried with nothing staged to read.
It is narrow because a commit failure classifies permanent, so it is usually not retried at all, and
because the durable source copy is already in the store by then. It is still the honest answer to
"is the retry hole completely closed", and the answer is "for every failure in the pipeline, yes;
for a failure in the commit, no".

**`PATCH /projects/{id}` does not validate the canvas.** `canvas_state` is stored verbatim, so a
canvas can be saved naming an artifact that does not exist or that the caller cannot read. It is not
a security hole — `_require_owned_seeds` catches it at run time — but it means a bad id surfaces as a
403 when the user presses Run rather than as a validation error when they saved. Validating seeds on
save is the obvious improvement.

**Deduplication is best-effort.** `_find_in_flight_duplicate` is read-then-write with no lock and no
unique constraint, so two simultaneous identical requests can both insert. The cost is a wasted model
call, not a correctness failure.

**The artifact PATCH protects one key.** Only `content.binary` is renderer-owned. Every other
top-level key, including `core`, is still client-writable, which is a data-integrity weakness inside
your own project. Accepting only `content.data` would be the principled version.
