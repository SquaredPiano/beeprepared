# Interview Guide

Everything needed to walk someone through this backend at a glance, and to show
what changed since the last time it was reviewed.

Read once end to end the night before. Read [the cheat sheet](#cheat-sheet) 60
seconds before the call.

### This guide and the walkthrough are different tools

`docs/walkthrough/` is a line-by-line read of every Python file in `backend/` —
thirteen documents, one per package plus an index. **This guide teaches you what
to say. The walkthrough teaches you what the code is.** If an interviewer opens a
file and lands on a line, the walkthrough is the thing that means you can say
what that line does and why it is there. This guide will not save you there.

Read it in this order (from `docs/walkthrough/00-index.md`), not numeric order —
it is sorted by how likely a question is to land there and how hard the answer is
to improvise:

1. `09-flow-engine.md` — the compiler and the scheduler. The headline of the
   project, the hardest part to fake, and where the concurrency bug lives.
2. `03-database.md` — one file, four separate correctness invariants.
3. `10-jobs-and-workers.md` — the transaction boundary, and why it is drawn there.
4. `07-handlers.md` — the contract that shapes everything above it.
5. `05-llm.md` — the subtlest bug, in a file short enough to read on screen.
6. Everything else, in numeric order.

The remaining documents are `01-config-and-startup`, `02-models`, `04-files`,
`06-pipeline`, `08-generation`, `11-api`, `12-tests`.

---

## 1. The opener

When they say "tell me about your project", say this. It is about 90 seconds at
a normal speaking pace.

> BeePrepared turns lecture material into study artifacts, but the part I care
> about is the canvas. You drag nodes onto an infinite canvas — a lecture
> recording, a notes generator, a quiz generator — and you wire them together.
> When you press Run, that graph is not a diagram of what happens. It *is* the
> program. The backend compiles your nodes and edges into a DAG, topologically
> sorts it with Kahn's algorithm, assigns each step a wave depth, and dispatches
> wave by wave, so independent branches run concurrently and a node with three
> inputs waits for all three.
>
> Underneath that, everything derives from one thing I call the knowledge core.
> A source gets ingested once and distilled into a structured representation of
> what the material actually says, and every artifact is generated from that
> core rather than from the raw text. That is why the quiz, the notes and the
> mock exam agree with each other instead of each hallucinating separately.
>
> The thing I would point at architecturally is that handlers never touch the
> database. A handler does the work and returns a `JobBundle`; the job runner
> commits it in one transaction. LLM calls fail often enough that a handler
> throwing halfway through is the common case, not the edge case, and it must
> not be able to leave a half-written knowledge graph behind.
>
> I rewrote the backend since I last showed it to you, and then I went back over
> the rewrite. The two things I'd most want to show you both came out of that
> second pass: a real concurrency bug in my own scheduler — eight simultaneous
> completions were queueing nine jobs where there should have been one — and a
> critical SSRF in my own ingest path, where a field I'd already once fixed
> turned out to be fixed at the wrong layer. Happy to start with either, or
> anywhere else.

Four things that opener is doing deliberately:

1. **Leads with the executable canvas.** Everyone at a hackathon built a prompt
   in a box. Almost nobody built a scheduler.
2. **Names a correctness invariant unprompted** (handlers are pure). That is the
   signal that separates "I wired an API" from "I designed a system".
3. **Closes on two measured bugs**, not on "I refactored things". A number is a
   claim they can test; "cleaner architecture" is not. And "I went back over the
   rewrite" is the sentence a returning candidate needs — it says the growth is
   in the auditing, not just in the volume of code.
4. **Hands them the steering wheel.** It invites the question you most want to
   answer.

If they only want one, offer the SSRF for a security-leaning interviewer and the
scheduler race for a systems-leaning one. Do not try to tell both unprompted;
finish one, then say "there's a second one of a different shape if it's useful".

---

## 2. The demo path

Under three minutes. Rehearse it twice. Have the project already ingested — do
not burn 90 seconds watching a transcription bar.

**Before the call:** `docker compose up`, ingest one lecture, build the 8-node
graph on the canvas, leave the browser on that tab. Have a second tab on
`localhost:8000/health`.

| # | Screen | What to say | Time |
|---|---|---|---|
| 1 | `localhost:8000/health` | "Every deployment tells you what it actually resolved to — which database file, which file store, which event bus, whether jobs are running in Celery or in-process, and which model provider. I got tired of guessing why a machine behaved differently." | 15s |
| 2 | Canvas, `/dashboard/canvas?id=…` | "This is a real graph. One source, fanning out into notes and a quiz, then the quiz fanning out into flashcards, an exam and a cheat sheet." Trace the edges with the cursor. | 20s |
| 3 | Draw an edge from a downstream node back to an upstream one, hit Run | "It refuses before spending a single token, and it names the node. Cycles, self-loops, generators with no input and generators with no output type are all rejected at compile time by `FlowCompiler`." Then delete the bad edge. | 25s |
| 4 | Press Run | "First wave dispatches. Everything downstream stays pending until its inputs actually exist. And the scheduling is transactional — that's where I found my best bug, which I'll show you in the code." | 45s |
| 5 | Open the exam artifact, download the PDF | "Exams typeset to real PDF through LaTeX, decks to PPTX. The download goes through an HMAC-signed link with an expiry, because an `<img>` tag or a download manager can't send a bearer token." | 25s |
| 6 | Assistant panel: "make question 3 harder" | "It classifies intent first — refine versus answer. If I'd asked *why* question 3 was hard, it would have answered instead of regenerating. Regenerating something the user didn't ask you to regenerate is worse than one extra clarifying question." | 30s |
| 7 | Point at the two quiz versions in the library | "Refinement appends. The old artifact is still there, linked, because something already exported must not change underneath you." | 15s |

Total: about 2:55. If you are running long, cut step 7 and say the line over
step 6's result instead.

### If the demo breaks live

Do not apologise and start debugging. Say one sentence and move to code.

- **Model returns an error or the key is dead.** "That is actually the case I
  designed for — let me show you." Stop the stack, blank `OPENROUTER_API_KEY`,
  restart. `/health` now reports `"model": "offline"`, and the entire pipeline
  still runs on `OfflineProvider`, which derives artifacts from the source text
  with frequency analysis. The output is dull; every stage executes. That is
  also what lets `docker compose up` work with an empty `.env`.
- **Anything else.** "Let me show you the tests instead —
  `backend/venv/bin/python -m pytest -q`, 172 tests, no network, no API keys."
  That takes under two seconds and it exercises real handlers, real
  transactions, real threads and real DAG traversal, so it is a legitimate
  substitute for the demo rather than a consolation prize.
- **Frontend is broken.** Fall back to `curl` against
  `POST /api/projects/{id}/flow/validate`, which returns the compiled plan with
  each step's parents and wave depth without running anything. That is the
  clearest possible view of what the compiler does.

---

## 3. What changed since last time

This is the section that matters. Last time the canvas was decorative and the
backend was one file.

Since then the backend was rewritten — and then the rewrite was audited again,
which is where §§3.1–3.7 come from. **For a returning candidate the audit is the
more valuable half.** Anyone can produce more code between interviews. Going back
over code you already shipped, and finding that a fix you were proud of was
applied at the wrong layer, is a different claim.

The three to lead with, in this order: the SSRF (§3.1), the scheduler race
(§3.2), and mutation testing (§3.5). If they want distributed systems rather than
security, swap the first two.

### 3.1 The headline: a critical SSRF in my own ingest path

**Lead with this**, or with §3.2 depending on the room. This is the strongest
new material, because it is the fifth security hole's lesson repeating — and he
is the one who caught the repeat.

The story, in his words:

> The fifth hole I reported last time was that `source_type: "youtube"` with a
> filesystem `source_ref` went straight to `yt_dlp.extract_info`, which reads
> local files as happily as URLs. I fixed it by requiring an `http(s)` scheme,
> wrote a test, and moved on. What I never asked was what the *host* could be.
>
> yt-dlp hands any URL its extractors don't recognise to the generic extractor,
> which fetches it, and when the response isn't media it writes the body out
> verbatim. So `http://169.254.169.254/latest/meta-data/...` passed my validator,
> got fetched by my server, stored under the caller's project, text-extracted,
> distilled into a knowledge core, and committed as an artifact the caller could
> read back. I proved that end to end against a local stand-in for a cloud
> metadata endpoint: the job completed, and the artifact's summary contained the
> response body verbatim, credential-shaped strings included.
>
> A *failed* fetch was useful too. `GET /api/jobs/{id}` returns `error_message`,
> and refused, timed out and succeeded all read differently — so the same field
> was a working internal port scanner. And there was no `max_filesize`, so the
> 200 MB upload cap had never applied to that path at all.
>
> The fix is `YouTubeUrlGuard` and `HostResolver` in `pipeline/ingestion.py`. The
> host must equal an allowed name or be a proper subdomain of one — an exact or
> suffix match, never a substring test, because a substring test accepts
> `youtube.com.evil.tld`. Then I resolve the host and check every answer against
> private, loopback, link-local, multicast, reserved and unspecified ranges, with
> IPv4-mapped IPv6 unwrapped first, and one disallowed answer refuses the whole
> request. Plus a `max_filesize` read from the upload limit, so both ways into
> the file store have the same ceiling.

**The structural point, and the part worth saying out loud:** the guard now lives
in `ingestion.py`, immediately before the call that makes the request — not on
the request schema. The request schema is where the old check lived, and it is
exactly the wrong place, because I had already watched one route reach the same
code by a different door. A check at the layer that makes the dangerous call
cannot be bypassed by finding another way in. That is the structural version of
the fifth hole's fix, and it is the same lesson twice.

**The residual, which he should volunteer before being asked:** the check happens
at resolve time, not at connect time. A DNS rebind — the name resolving to a
public address for my check and an internal one for yt-dlp's socket a moment
later — is not covered, and neither is a redirect from an allowed host to an
internal address. Closing that properly needs a pinned-IP socket or an egress
proxy, and yt-dlp does not expose the connect hook to do it cleanly.

Eighteen tests cover the guard, in `TestYouTubeIngestGuard`: the metadata
address and an IPv6 unique-local one, loopback by name and by literal,
`youtube.com.evil.tld` / `youtu.be.evil.tld` / `notyoutube.com` /
`evil.tld/youtube.com`, an allowed name resolving to `10.0.0.5`, one internal
answer among several, four genuine YouTube URLs that still pass, a test that
yt-dlp is never even *constructed* for a refused URL, one asserting the refusal
classifies as permanent so a blocked fetch is not replayed three times, and one
asserting the download cap is the upload cap.

One more door closed alongside it: the upload route accepted `source_type:
"youtube"` because it checked membership of `SOURCE_TYPES`, then wrote the
payload by hand — so an upload could queue an ingest job naming a path in the
server's own temp directory *as a URL to download*. Uploads now go through
`IngestRequest` and `UPLOADABLE_SOURCE_TYPES`, which is `SOURCE_TYPES` minus
youtube. An upload is a file; it can never be the source type that is a URL.

### 3.2 The scheduler race, found and measured

It is a genuine distributed-systems bug in his own code, diagnosed from first
principles, fixed, and *measured*.

The story, in his words:

> `FlowEngine.advance` was supposed to be idempotent, and I had a test asserting
> it was — but the test called it twice in a row on one thread, which proves
> nothing. What was actually happening: `on_job_finished` did a
> read-modify-write of the entire `node_states` JSON blob outside any
> transaction, then called `advance`, which re-read the row, inserted job rows
> for anything now ready, and only wrote the states back at the very end. So
> there is a long window between "I read this step as pending" and "I marked it
> running".
>
> That window gets hit for two reasons. FastAPI runs sync routes on a threadpool
> while the workers run on the event loop, so two callers genuinely overlap. And
> with fan-in, two parents of the same child finishing at once each read the
> blob and each wrote their own completion back over the other's, so the child
> ended up waiting forever on a parent the row no longer remembered finishing.
>
> The fix is that the read, the job insert and the write-back now happen inside
> one `Database.transaction()`, and dispatch moved to *after* the commit — you
> must not tell a worker about a job row that might still roll back. I measured
> it with eight threads on a barrier all reporting the same step complete: nine
> dispatches and nine job rows before, two after. There's a regression test,
> `TestFlowConcurrency::test_concurrent_completions_queue_the_next_step_once`,
> and it fails 9≠2 against the old engine.

**The numbers to say out loud: 8 concurrent completions → 9 dispatches and 9 job
rows before, 2 after.** Nine, because eight racing threads each thought they were
first, plus the one legitimate dispatch.

Three follow-ups worth having ready:

- *"Why did your old idempotence test not catch it?"* — Because it tested
  sequential idempotence, which is a different property. `advance` twice in a
  row on one thread genuinely was idempotent. Concurrent idempotence needs
  concurrency in the test, which is why the new one uses a `threading.Barrier`
  to make eight threads arrive at the same instant.
- *"Why is dispatch outside the transaction?"* — `_schedule` returns the job ids
  it queued and `_hand_off` dispatches them only once the transaction has
  committed. Telling a worker about a row that is still uncommitted means the
  worker can look it up and not find it.
- *"How does the nested transaction work?"* — `Database._transaction` checks
  `connection.in_transaction` and joins the open transaction rather than issuing
  a second `BEGIN`, which SQLite rejects. That is what lets `on_job_finished`
  wrap `update`, `insert` and `select` calls that each transact on their own.

### 3.3 A second concurrency bug, of a different kind

This is the answer to *"have you found any others?"*, and it is worth having
ready because the honest answer is yes, and it is not a variant of the first one.

> `WorkerPool` builds **one** `JobExecutor` and runs four worker tasks against
> it. `handler_for` caches one handler instance per job type, because
> construction opens clients. And `with_progress` used to do
> `self.progress = reporter` — on that shared instance.
>
> So: worker 0 claims job A in project P1 and sets the reporter. Worker 1 claims
> job B in project P2 and overwrites it. Job A resumes, calls `report`, and its
> progress event publishes to **project P2 under job B's id**. Not a lost event —
> a misattributed one, crossing a project boundary. I reproduced it.
>
> The fix is that `with_progress` returns `copy.copy(self)` with the reporter set
> on the copy. Shallow on purpose: the collaborators opened in `__init__` are
> what make construction expensive and they stay shared, and the reporter is the
> only thing that is genuinely per job.

**Have the answer to "why didn't your tests catch it" ready, because it is the
good part.** Celery mode was unaffected: `tasks.py` builds a fresh executor per
task, so there is no sharing to corrupt. Every test that exercised a handler went
down a path where one executor served one job. The bug only existed in the
in-process worker pool, which is the mode the tests did not model. The lesson is
the same one as the first race: the test exercised a configuration in which the
property held.

Two tests now:
`TestProgressAttribution::test_concurrent_jobs_report_under_their_own_identity`
runs two jobs in two different projects through one shared handler with a
rendezvous holding both mid-report, and asserts each project saw only its own
job's stages. And
`test_attaching_a_reporter_leaves_the_shared_handler_alone` asserts
`"progress" not in vars(shared)` — the shared instance is never written to at
all.

### 3.4 The sequel to the ordering fix, and two more transaction holes

The headline fix in §3.2 moved *dispatch* after the commit. It left `publish`
inside the transaction. That is a smaller hole of the same shape:

> Publishing from inside an open transaction announces a node the database has
> not stored yet. If the commit fails or anything in the block raises, the write
> rolls back and the browser keeps the green node it was already shown — the UI
> says a step ran and the database says it never did. It is also a blocking
> network round trip on the Redis bus while holding the write lock, which stalls
> every other writer for its duration.
>
> The fix is an `EventOutbox`: `record` during the transaction, `flush` after the
> commit. That is the same shape `_hand_off` already used for dispatch, which is
> the point — once dispatch has to wait for the commit, so does anything else
> that tells the outside world something happened.

The test worth pointing at is
`TestFlowConcurrency::test_a_finished_run_publishes_its_events_in_order`, because
**it passes against the pre-fix code**. That is what makes it evidence: it proves
the observable behaviour did not change, only the moment of delivery. The one
that fails against the pre-fix code is
`test_a_rolled_back_completion_publishes_nothing`, which forces `_schedule` to
raise and asserts nothing was published and the node is still `running`.

Two more, both in the same family:

- **`advance` and `on_job_finished` returned a run row read inside the
  uncommitted transaction** straight to the HTTP caller. Both now re-read after
  the block closes. Same rule as dispatch and events: nothing leaves the process
  describing state the database has not committed.
- **`_transaction`'s `COMMIT` was outside the `try`.** A commit can fail on its
  own — a full disk, an I/O error, a busy timeout expiring — and when it did, the
  connection was left in a transaction and every later write on that thread
  failed. Structurally the identical hole to the `BaseException` fix: an exit
  path that skipped the cleanup. `COMMIT` is now inside the `try`, and
  `TestTransactions::test_a_failed_commit_leaves_the_connection_usable` wraps the
  connection so its first `COMMIT` raises `disk I/O error`, then asserts the next
  write succeeds.

The `BaseException` fix is still worth its one sentence: rollback in
`_transaction` is on `BaseException`, not `Exception`, because a `CancelledError`
escaping with `BEGIN IMMEDIATE` still open left the connection unusable for every
later write on that thread.

### 3.5 Mutation testing: how I check my own tests

**This is the best behavioural answer in the document**, and the right response
to "how do you know your tests are good". It is better than any coverage number,
because coverage measures which lines ran and this measures whether anything
would have noticed if they were wrong.

> I copied the repo to a sandbox and applied about 45 mutations, one at a time,
> each breaking exactly one behaviour, and recorded which tests died. I cared
> most about the ten regression tests I'd written for previously-fixed bugs,
> because those are the ones I was relying on. Eight of the ten held. Two did
> not.
>
> The flow-concurrency test is the real thing: reverting the fix failed it 20
> times out of 20, and 19 of those were exactly `assert 9 == 2`.
>
> But the locale bug had **no** test at all. Setting the marker back to the
> American spelling — literally the original bug, the one that silently replaced
> whole lectures — survived with all 108 tests green. And idempotency had no
> negative test: adding `"completed"` back into the in-flight set survived too,
> and that mutation *is* the original bug, the one that made "Regenerate" hand
> back the old artifact.
>
> One test was passing by scheduling luck rather than by being right. The client
> fixture starts a live worker pool in the background, and the deduplication test
> only passed because the idle backoff kept the worker asleep between the two
> requests. At a 1 ms backoff it failed 3 times out of 3. It now uses an
> `idle_client` fixture that starts no workers, so the precondition — the first
> job is still in flight — is a fact rather than a question of timing.
>
> All 21 surviving mutations are killed now. The suite went from 108 tests to
> 172.

**The framing to use, and it is the honest one:** *"I had regression tests that
made me feel covered, and mutation testing showed me two of them proved nothing
at all. A test that passes against the bug it was written for is worse than no
test, because it stops you looking."* That is the same failure as the old
sequential idempotence test in §3.2 — this time he had a method that finds it
instead of noticing by luck.

If they push on cost: it was a scripted sweep against a sandbox copy, and the
suite runs in under two seconds, so 45 mutations is a couple of minutes of
machine time. It is not something he set up as CI; it is something he ran once,
deliberately, on the tests he was most relying on.

### 3.6 Two more silent-corruption bugs

Both are the same shape as the locale bug: plausible output, nothing raised.

**Every source type was getting the transcript cleaning rules.** The rules delete
every parenthesised span, every bracketed span, every `[A-Z]{2,}:` and every
timestamp. That is correct for speech — it removes `(laughs)`, `[inaudible]`,
`SPEAKER:` and `12:34`. Applied to a maths or CS PDF it destroys `f(x)`, `[0,1]`,
`O(n log n)`, bracketed citations, `NOTE:` and `CPU:`, and then collapses the
`--- Page N ---` markers along with every other line break. No exception
anywhere; the material just quietly stopped saying what it said, and every
artifact downstream was built on the wreckage.

> It is split now. `strip_document_noise` does whitespace normalisation and
> removes characters that carry no text at all — form feeds, soft hyphens,
> zero-width spaces — and nothing that can delete a character the author typed.
> `strip_transcript_noise` keeps the destructive rules. `IngestHandler` routes on
> source type: `TRANSCRIBED_SOURCE_TYPES` is audio, video and youtube; everything
> else takes the document path.
>
> The part I'd point at is which one got the plain name. `clean` is the *safe*
> path, and `clean_transcript` is the one you have to ask for by name. A caller
> that does not know which kind of source it is holding must not be able to
> destroy notation by accident — so the dangerous behaviour is the one that needs
> a longer name.

Six parametrised cases assert the routing (`audio`/`video`/`youtube` →
transcript, `pdf`/`pptx`/`md` → document), plus one that a document keeps its
notation and one that page markers survive.

**`extract_json` shredded valid JSON that contained a code fence.** It ran the
fence regex before checking whether the text was already JSON, so a fence living
*inside* a string value matched and the function returned that fence's contents
instead of the document. The live exposure was the study guide, whose schema has
a Markdown body — exactly the field a model will put a code block in. The fix is
one check first: if it already parses, return it untouched.

> The reason my tests could not catch it is worth saying: the offline provider
> never calls `extract_json` at all. It builds its fixtures as objects. So the
> entire suite ran the real handlers against a provider that structurally cannot
> exercise the parser. That is the cost of testing through a substitute — it is
> still the right call, but it means the seam itself needs its own tests, and now
> it has them.

### 3.7 Retry classification was dead for the commonest failures

`is_transient` looked correct and was not.

> The provider wrapped every failure as a plain `LLMError` before it left. So
> `is_transient`'s `isinstance` branch — the one listing `httpx.TimeoutException`,
> `ConnectError`, `ConnectionError` — could never fire, because the type was
> gone by the time it was asked. And there was nothing to string-match either:
> `str(httpx.ConnectTimeout(""))` is the empty string, and a refused connection
> reads `[Errno 61] Connection refused`, which none of my transient phrases
> cover.
>
> I measured it: a wrapped connect timeout classified PERMANENT, a wrapped
> "connection refused" classified PERMANENT, and an HTTP 429 classified
> transient. So the two most common real failures in the system — the upstream
> being slow and the upstream being unreachable — were the two the retry logic
> had stopped covering, while the one case that was already handled by the
> provider's own retry loop was the one that still classified correctly.

The fix is `TransientFailure(LLMError, ConnectionError)`. The base classes are
the payload: `ConnectionError` is already in `TRANSIENT_EXCEPTIONS`, so the
`isinstance` branch fires on type rather than on words. Plus a `_describe` helper
that prefixes the exception's class name to the message, because several httpx
transport errors stringify to nothing and the job's `error_message` column was
otherwise saying only how many attempts had been made.

Three parametrised tests cover `ConnectTimeout`, `ReadTimeout` and a refused
connection surviving the wrap as transient, one asserts the class name reaches
the message, and one asserts a malformed payload is *still* permanent — because
rescuing network faults must not make every provider failure retryable.

**And a retryable failure was requeued but never re-dispatched.** `fail_job` set
the row back to `pending` and nothing told a worker. It worked anyway, which is
why it survived: the local worker pool polls, and the Celery beat schedule sweeps
the queue every 120 seconds. So under Celery a retry waited up to two minutes,
and with the beat schedule removed it waited forever. `_redispatch` now hands the
job back after `fail_job` has committed it — same order as every other dispatch
in the codebase — and logs rather than raises, because it runs inside the handler
for a job that has already failed and `execute` promises not to raise.

### 3.8 The canvas became executable

Before, the "Run" button POSTed to `/run`, an endpoint that did not exist. Each
generator node independently fetched the project's knowledge core, so the edges
you drew changed nothing — the graph was decoration over a set of independent
buttons.

Now `backend/services/flow/plan.py` and `backend/services/flow/engine.py` make
the graph load-bearing:

- `FlowCompiler.compile()` classifies each node as a **source** (already points
  at an artifact) or a **generator** (will produce one), builds adjacency, and
  runs Kahn's algorithm in `_topological_order`. Each step gets a **wave
  depth** — `depth[child] = max(depth[child], depth[node] + 1)` — so a node sits
  one wave below its *deepest* parent and siblings dispatch together.
- Validation happens before dispatch and every message names the offending node:
  cycles (Kahn terminates with nodes left over), self-loops, generators with no
  input (`_require_inputs`), generators with no output type (`_classify`).
- **Fan-in and fan-out are one mechanism seen from two ends.** A node with three
  incoming edges is dispatched with three `source_artifact_ids`, merged by
  `CoreMerger`. A node with three outgoing edges satisfies three downstream
  steps when it completes.
- The engine holds **nothing in memory between calls**. Everything lives in the
  `flow_runs` row, because the job that unblocks a step may finish in a
  different process from the one that started the run.
- A failed step marks its whole downstream subtree `skipped` rather than leaving
  it `pending` forever — including the case where a step's inputs produced no
  artifacts at all, which previously hung the run with no error anywhere.

### 3.9 Security: the API audit

Six holes, found by going back over his own code looking for them — the framing
matters more than the count. The SSRF in §3.1 is a seventh and the most serious;
it is separated out because it is not in `backend/api/` and because it is the
better story.

| Hole | What it gets you | The fix |
|---|---|---|
| **`create_job` never checked the source artifacts.** It checked that you owned the *project* and stopped there. | Queue a generate or refine naming artifact ids from someone else's project. The handler resolves them, reads their content, and writes it into a new artifact in *your* project — a clean cross-tenant read, laundered through the generator. | Every source id now goes through `require_project_artifact` before the row is written: it asserts you own the artifact *and* that it lives in the project you named. `_source_ids` extracts them per request type. |
| **`deps.py` used `if owner and owner != user_id`.** | A project with a NULL `user_id` was readable by anyone, while `list_projects` filtered on `user_id` and hid it. Read said yes, list said no — the two disagreeing is how this kind of hole survives review. | `require_project` is now `if project.get("user_id") != user_id`. Absent ownership is denial, not permission. |
| **`update_artifact` merged client `content` wholesale.** | Rewrite `content.binary.storage_path` to any key in the store, then call `/download` and have the server sign a valid link to it. Escalation through the *export metadata*, not through the file server. | The `binary` block is renderer-owned. `update_artifact` drops whatever the client sent and restores it from the existing row, so the storage key is never client-writable. |
| **`IngestRequest` with `source_type: "youtube"` and a filesystem `source_ref`** went straight to `yt_dlp.extract_info`, which reads local files as happily as URLs. | Arbitrary local file read, dressed as a video download. | A `model_validator` on `IngestRequest` requires `http://` or `https://` for youtube sources. **This fix was incomplete — see [§3.1](#31-the-headline-a-critical-ssrf-in-my-own-ingest-path).** |
| **`/flow/run` reached the same place through a different door.** Fixing `create_job` did not fix this: canvas nodes arrive in the request body, and the compiler reads artifact ids straight out of them into `seed_artifacts`. | Run a flow in your own project seeded with a node naming someone else's artifact, and the engine queues a generate job carrying that id. Confirmed before fixing: `202`, with the foreign id visible in the job payload. The saved canvas was a third door, since `canvas_state` is caller-written through `PATCH`. | `_require_owned_seeds` checks every seed before anything is persisted, so a refused run leaves no `flow_run` and no job. `/flow/validate` refuses identically instead of reporting the graph as valid. |
| **The HMAC signing key was published in this repository** — `beeprepared-dev-secret` as the default in `config.py`, `change-me-in-production` in `.env.example` and `docker-compose.yml`. | Download links are unforgeable only while the key is private. Anyone who had *read the repo* could mint a valid, unexpired link for any object in the store, with no session at all. The signed-link scheme was decorative in every default deployment. | `require_unforgeable_links` refuses to boot on an unset or published key, and `get_settings` mints a private random key and persists it when the configured one is published — so a fresh clone and `docker compose up` still work rather than being broken by the fix. Five tests. |

The line to say if they ask how he found them: *"I went back through the API
looking specifically for places where I'd checked the obvious thing and stopped.
Most of them are that exact shape — I checked the project and forgot the
artifact, I checked the owner and forgot that NULL isn't a match, I validated the
type and forgot the value."*

The fifth one is the better story, because it is about the *fix* being
incomplete rather than the code being wrong: *"I fixed the ownership check on
the jobs endpoint, wrote the test, and then asked whether anything else reaches
the same code by another route. The flow endpoint did — it takes the canvas from
the request body, so the artifact ids are just as caller-controlled. Same hole,
different door. That is the one I would not have found by reading the diff."*

**And then it happened again**, which is the point of §3.1. Same question asked
about a different fix, and the answer was the same shape: I constrained the
scheme and stopped, and the host was the part that mattered. If they ask what he
learned from the audit, that is the answer — not "check ownership twice", but
*"when I fix a thing, ask what else reaches it and what else the value could
be"*.

Worth volunteering alongside all of it: **`resolve_user` returns the same local
user for every caller** — it takes an `Authorization` argument and ignores it —
so today nobody can *be* a second user and the cross-tenant holes are not
remotely exploitable. The ownership model is real in the queries and vacuous in
practice until an identity provider exists. Note that this does *not* apply to
the SSRF or the signing key: those two are exploitable by anyone who can reach
the API, single-user or not. Being able to draw that line is the difference
between "I found bugs" and "I understand my own threat model".

### 3.10 The other defects worth naming

| # | What was broken | Why it mattered | What he did |
|---|---|---|---|
| 1 | **Effective concurrency was 1.** Async handlers called the *synchronous* LLM client, blocking the event loop for the entire model call. | Worker count was decorative. Four workers and one worker performed identically. | Generation is async end to end. The exam's three question batches run under `asyncio.gather` in `ArtifactGenerator._exam`. |
| 2 | **Authentication bypass.** Any request whose `Authorization` header merely *contained* the substring `mock-token` was accepted as a fixed user, in every deployment. | A test convenience that shipped. The one he is least proud of and most willing to talk about. | Removed. `resolve_user` returns one documented local user; ownership is recorded per project and checked on every read, so there is exactly one seam to replace when accounts arrive. |
| 3 | **Structured-output drift.** Pydantic emits nested models as `$defs` + `$ref`. Providers accept that but cannot enforce it strictly, and a model handed a reference-heavy schema stops treating field bounds as binding — one mind map ran a single string field to 100k characters and failed three retries. | Silent, expensive, and it looked like the model "just being bad". It was the schema. | `strict_schema()` in `backend/llm/schema.py` inlines every `$ref`, sets `additionalProperties: false`, marks every object fully-required, and the request sends `strict: true`. Same tree, two-second response. |
| 4 | **Retry classification matched bare status codes** anywhere in the error text. | `"Source artifacts not found: 429e4567-e89b-…"` — the digits are part of a UUID — was retried as transient. Roughly one flaky test run in six, and in production it paid three times for a request that could never succeed. | `TRANSIENT_STATUS` matches a code only where it is *labelled* as one. Named regression test: `TestRetryPolicy::test_status_digits_inside_identifiers_do_not_trigger_a_retry`. |
| 5 | **`RETRYABLE_STATUS` was inert.** Every HTTP error was retried identically. | A 401 from a rejected key burned three full attempts, and the actionable truncation message — "raise `LLM_MAX_OUTPUT_TOKENS`" — never reached the user, because it was retried away and replaced by a generic "failed after 3 attempts". | A `PermanentFailure` class, with `TruncatedResponse` as a subclass. `_checked` raises it for any non-retryable 4xx/5xx and `_send` re-raises it immediately instead of retrying. |
| 6 | **`fail_job` had no terminal guard.** | A job reclaimed by the reaper runs twice. The loser finishing late flipped a `completed` job to `failed`, and the flow engine then skipped a subtree that had already succeeded. | `fail_job` returns the existing terminal status untouched, and `_record_failure` leaves that outcome alone rather than notifying the flow. Two tests: a late failure cannot undo a committed result, or a cancellation. |
| 7 | **Idempotency returned *completed* jobs.** | "Regenerate" silently handed back the old artifact. It looked exactly like a broken button, and the logs said success. | `_find_in_flight_duplicate` deduplicates only `pending` and `running`, and returns `None` immediately for a steered request, because different instructions are different work. |
| 8 | **No stale-job reaper.** A worker killed mid-job left its row `running` forever, and `claim_job` skips running rows. | The node spun indefinitely with no error ever surfacing. The worst failure mode, because it is invisible. | `reap_stale_jobs()` requeues rows stuck past `STALE_JOB_SECONDS`, or fails them if attempts are exhausted. Run by `WorkerPool._reaper` locally and a Celery beat task otherwise. |
| 9 | **Source ids parsed as `uuid.uuid4() if isinstance(x, str) else x` inside a bare `except: pass`.** | A malformed id became a *fresh random* id, which became a lookup for an artifact that had never existed. The error surfaced three layers from its cause. | `as_uuid()` parses and raises, naming the offending value. |
| 10 | **`ALLOWED_GENERATIONS` was checked and the failure branch was `pass`.** | The type map documented a rule it did not enforce. A comment pretending to be a constraint is worse than no constraint. | `ALLOWED_TARGETS`; `_check_transition` raises, listing what *is* allowed. |
| 11 | **CORS was `allow_origins=["*"]` with `allow_credentials=True`.** | Browsers reject that combination outright, so there was effectively no CORS — it only ever worked same-origin. | Explicit origin list from settings, plus an `allow_origin_regex` for localhost. |
| 12 | **Uploads were read whole into memory**; a 600 MB recording became 600 MB resident. | Two concurrent uploads on a small box is an OOM kill, not a slow request. | `_buffer_upload` streams in chunks and enforces the limit *as it goes*. `IngestHandler` deletes the staged file in a `finally` — see [3.11](#311-also-fixed). |
| 13 | **The knowledge-core validator required every collection to be populated.** | A short recording with no worked examples failed ingest, discarding an otherwise usable extraction. Strictness that costs the user their upload is a bug. | `REQUIRED_FIELDS` is now only the fields every generator actually reads. Markup rejection stayed — stray LaTeX in the core corrupts everything derived from it. |

Rows 4 and 5 have a sequel: fixing the *matching* left the classifier correct and
still unreachable for the two commonest failures, which is [§3.7](#37-retry-classification-was-dead-for-the-commonest-failures).
If they ask about retries, tell that pair together — a fix that looked complete,
and the measurement a year later that showed it was not.

### 3.11 Also fixed

A family of bugs with one root cause: **things that were not `Exception`, and
things that should not have been on the event loop.**

- **`asyncio.CancelledError` is a `BaseException`, not an `Exception`.** Under
  `gather(return_exceptions=True)` it comes back as a *value*, so an
  `isinstance(result, Exception)` check misses it. In three places a cancelled
  task was treated as a successful result — most visibly in the text cleaner,
  where a cancelled chunk was `" ".join()`'d into the transcript and raised a
  `TypeError`. Now `cleaning.py` and `knowledge.py` classify on `BaseException`,
  and `generators.py` and `merger.py` re-raise a `CancelledError` rather than
  absorbing it into a partial result, because a cancellation means teardown, not
  a failed batch.
- **ffmpeg, pypdf and a ~150 MB base64 encode all ran on the API's event loop**,
  stalling every other request and every WebSocket for their duration. All three
  are now behind `asyncio.to_thread` (`pipeline/media.py`,
  `pipeline/extraction.py`, `OpenRouterProvider.transcribe`).
- **The OpenRouter semaphore was keyed by `id(loop)`, and `id()` is recycled.**
  Celery creates a fresh event loop per task; once the old loop was collected a
  new one could be handed the dead loop's semaphore, and a semaphore bound to a
  dead loop raises — outside the retry loop, so it was not even retried. It is
  now a `weakref.WeakKeyDictionary` keyed by the loop object itself, which also
  stops the table growing for the life of the process.
- **The staged upload leaked.** `_buffer_upload` unlinked on every failure path,
  but nothing deleted the file after a *successful* ingest, so every ingested
  lecture left a full-size duplicate in `/tmp` until reboot.
  `IngestHandler._discard_staged_upload` now deletes it in a `finally`, guarded
  by shape-matching what the upload endpoint actually creates: the name starts
  with `tempfile.gettempprefix()`, the parent is exactly `tempfile.gettempdir()`,
  and it is a regular file. A YouTube URL and a developer's own file path both
  fail that guard, because deleting the wrong file is far worse than leaking one.
  Three tests cover it, including `test_a_callers_own_file_is_never_deleted`.

### 3.12 The frontend, briefly

He should know about one bug here because **the demo runs straight through it**.

After a flow completed, the Run button stayed spinning and disabled forever.
`isRunning` was only cleared by `applyFlowState`, which needs the whole
node-state map — and that map only arrives on the initial run response and on a
socket snapshot. The incremental `flow.node` events go through `setNodeStatus`
and never carry it, so a run that finished purely over the event stream, which is
every real run, left the button stuck until a page reload. The `flow.completed`
and `flow.failed` handlers now call `finishFlowRun()` directly.

Worth one sentence if it comes up: *"the state that says whether a run is
finished was being derived from a snapshot the incremental events don't carry —
so it worked in the test path and never in the real one."* That is the same
mistake as §3.3 stated in React: a property that holds in one code path and is
assumed to hold in all of them. Do not oversell it; the frontend is still the
weak half and §8 says so.

### 3.13 And the shape of it changed

| Before | After |
|---|---|
| One 1,060-line `main.py`: hand-rolled Supabase HTTP client, auth, every endpoint | `main.py` is 199 lines of assembly. Six packages with a one-way dependency rule |
| Jobs on an `asyncio.create_task` loop inside the API process | A job table, an atomic claim, a reaper, and a pluggable transport (Celery, or an in-process pool through the same executor) |
| Supabase, Cloudflare R2, Vertex, Gemini, Deepgram — 96 packages | SQLite, a local file store with signed links, OpenRouter — 52 pinned packages |
| Tests: effectively none | 172, no network, no keys, including two real-thread concurrency tests |

**The local-first reasoning, in his words:** personal projects rot when a free
tier lapses or a key gets rotated, which is exactly what happened here — the
Deepgram key started returning 401 on both the transcription and the project
endpoints. The instinct is to add another vendor. Instead I checked and
OpenRouter already accepts audio as an `input_audio` content part, so one key now
covers generation *and* transcription. One vendor, one key, one failure mode.
Verified live end to end.

---

## 4. Architecture at a glance

This is the diagram to redraw on a whiteboard. Practise it once — about 40
seconds.

```
   browser
     │  HTTP                          WebSocket (one per project)
     ▼                                        ▲
  ┌──────────────────────────┐                │
  │ FastAPI                  │                │
  │  api/routes  api/deps    │                │
  └────────────┬─────────────┘                │
               │ 1. write the job row  ── committed BEFORE dispatch
               │ 2. dispatch           ── may fail; the row survives
               ▼                                │
        ┌──────────────┐   progress events      │
        │  Redis / bus │────────────────────────┘
        └──────┬───────┘
               ▼
        ┌──────────────────────────┐
        │ Worker                   │
        │   3. claim_job()         │  atomic — exactly one worker wins
        │   4. handler.run(job)    │  → JobBundle. NO database writes
        │   5. commit_bundle()     │  artifacts + edges + status, one txn
        │   6. flow.on_job_finished│  one txn: read → queue → write back;
        └──────────┬───────────────┘  events, dispatch and the returned row
                   │                  all wait for the commit
                   ▼
          ┌──────────────────┐
          │  SQLite + files  │
          └──────────────────┘
```

Three processes: an API that accepts work, a worker that does it, Redis between
them. **Without Redis all three collapse into one** — the API runs its own worker
pool and an in-process bus, so `uvicorn backend.main:app` is a complete install.
`dispatch_mode()` decides once, at startup, by asking whether the broker answers.

### Packages

| Package | Responsibility | The one file to know |
|---|---|---|
| `api/` | HTTP and WebSocket surface, one route module per resource | `api/deps.py` |
| `handlers/` | One class per job type. Pure — they return work, never write it | `handlers/base.py` |
| `pipeline/` | Source → knowledge core: ingestion, extraction, media, cleaning | `pipeline/knowledge.py` |
| `services/` | Persistence, files, events, queueing, generation, flow execution | `services/flow/engine.py` |
| `llm/` | Model providers behind one interface | `llm/base.py` |
| `models/` | The domain vocabulary every layer shares | `models/graph.py` |

**The dependency direction is one-way:**
`api` → `handlers` → `services`/`pipeline` → `llm`/`models`. Nothing lower ever
imports anything higher. Say this out loud — it is what makes the package table
mean something rather than being folder names.

### Data model — six tables

`projects`, `jobs`, `artifacts`, `artifact_edges`, `flow_runs`, `chat_messages`.
The interesting one is `artifact_edges`, and there are two things to say:

- **Provenance is a DAG, not a tree.** An artifact generated from three lectures
  gets three `derived_from` edges. That is what "multiple inputs" means once it
  reaches storage, and it is what lets lineage answer "where did this question
  come from?".
- **The knowledge core has indegree zero.** It is the root. Provenance back to
  the source *file* is carried by `created_by_job_id`, not by an edge, because
  the core was not derived from anything already in the graph.

---

## 5. The five files to show

If they ask "walk me through a piece of it", open these, in this order. Each
walkthrough is about 30 seconds.

**This list changed.** It used to be `flow/engine.py`, `flow/plan.py`,
`database.py`, `llm/schema.py`, `tests/test_seams.py`. Two of those moved down:
`llm/schema.py` is a genuinely good bug but it is a bug about *reading a
provider's docs carefully*, and `test_seams.py` proves the abstraction
boundaries — both are strong for "did you design this", and neither is strong for
"what have you learned since we last spoke", which is the question this interview
is actually asking. They are now [two more if there is time](#two-more-if-there-is-time),
and both are still cited in §6 and §7.

What replaced them: `pipeline/ingestion.py`, because the SSRF is the best story
in the repository and the file is short enough to read on screen; and
`services/job_runner.py`, because it is where the second concurrency bug, the
retry classification and the re-dispatch fix all live, and because it is the file
that shows the transaction boundary from the runner's side rather than the
engine's.

### 1. `backend/services/flow/engine.py` — the concurrency bug

*Why first:* it is the strongest thing in the repository. A real race, in his own
code, with a number attached.

> `on_job_finished` records a step's outcome and schedules what it unblocked.
> The whole body is inside `with self._database.transaction()`: read the run,
> merge the completion into `node_states`, write it back, then `_schedule` queues
> every step whose parents are now complete — all one atomic unit. It returns the
> job ids it queued, and `_hand_off` dispatches them *after* the transaction
> commits, because telling a worker about an uncommitted row means the worker can
> look it up and not find it.
>
> Before, all of that was outside a transaction, and the read-modify-write of the
> `node_states` blob meant two overlapping callers each saw a step as pending and
> each queued a job. FastAPI's sync routes run on the threadpool while workers
> run on the event loop, so they genuinely overlap. Eight threads reporting the
> same step complete produced nine dispatches; now it produces two.

Then open `test_pipeline.py::TestFlowConcurrency` in the next tab and show the
`threading.Barrier(8)`. The assertions are `len(dispatched) == 2` and two job
rows in the database.

Scroll up to `EventOutbox` at the top of the same file while you are there — it
is fifteen lines and it is the sequel: `record` inside the transaction, `flush`
after it, so a rollback cannot leave the browser holding a green node the
database says never ran. Both `advance` and `on_job_finished` end the same way:
flush, hand off, then re-read the row to return it, all outside the `with`.

### 2. `backend/pipeline/ingestion.py` — the SSRF guard

*Why second:* it is the best story he has and the code is 100 lines of it. It
also answers the security question and the "what did you learn" question with the
same file.

> `YouTubeUrlGuard.check` is the whole thing. `_host` parses the URL and refuses
> anything that is not http or https — that is the old fix, and it is not
> sufficient. `_is_youtube` is the part that was missing: the host must equal an
> allowed name or end with `.` plus an allowed name. A proper suffix match, never
> a substring test, because `"youtube.com" in "youtube.com.evil.tld"` is true.
> Then `HostResolver.addresses` resolves the name and every answer goes through
> `_is_public`, which is a `not any` over private, loopback, link-local,
> multicast, reserved and unspecified. One bad answer refuses the request,
> because a resolver can return several addresses of which only one is internal.
> `_address` unwraps IPv4-mapped IPv6 first and refuses anything that will not
> parse — fail closed, not fail open.
>
> The guard is called on the first line of `store_youtube`, before yt-dlp is even
> constructed. That placement is the actual fix. The old check was on the request
> schema, and I already knew a request schema is the wrong place because I'd
> watched a different route reach the same code by another door.

Two things to volunteer here without being asked: `UnsafeSourceError` is
deliberately classified permanent, so a refused fetch fails once instead of being
replayed to the attempt limit; and the check is at *resolve* time, not connect
time, so DNS rebinding and a redirect from an allowed host to an internal address
are both still open. Say the second one yourself. It is the difference between
"I fixed it" and "I know what I fixed".

`test_api.py::TestYouTubeIngestGuard` is the tab to have open next to it.

### 3. `backend/services/flow/plan.py` — the algorithm

*Why:* the only file containing a classical algorithm applied to a real product
problem, and short enough to read on screen.

> `FlowCompiler.compile` takes React Flow's nodes and edges. `_classify` splits
> nodes into sources — already pointing at an artifact — and generators, which
> will produce one; a generator with no resolvable output type is rejected here
> with the list of valid types. `_adjacency` builds incoming and outgoing maps
> and rejects self-loops as it goes. `_require_inputs` rejects any generator
> nothing feeds. Then `_topological_order` is Kahn: seed the queue with indegree
> zero, pop, decrement children, carrying a depth as `max(existing, parent + 1)`
> so a node sits one wave below its *deepest* parent, not its first. If the order
> comes out shorter than the runnable set, what is left is a cycle, and I name up
> to five of the nodes involved. The canvas calls this as you wire nodes
> together, so a broken graph is visible before any tokens are spent.

If they push: `MAX_NODES = 100` is a deliberate cost ceiling, and
`FlowPlan.waves` is a derived property rather than stored state, so it cannot
drift from `steps`. And the compiler has no database handle at all — which is
exactly why `POST /flow/validate` can typecheck a canvas without touching
storage.

### 4. `backend/services/database.py` — the correctness primitives

*Why:* four of the system's invariants live in one file, and it is the natural
second half of the handler contract.

> `_transaction` takes the write lock, issues `BEGIN IMMEDIATE`, and rolls back
> on `BaseException` — not `Exception`, because a cancellation escaping with the
> transaction open leaves the connection unusable for every later write on that
> thread. The `COMMIT` is inside that same `try` for the same reason: a commit
> can fail on its own, and when it did it used to leave the transaction open
> behind it and break every later write on the thread. It also joins an
> already-open transaction instead of issuing a second `BEGIN`, which is what
> lets the flow engine wrap several calls that each transact on their own.
>
> `claim_job` is the atomic claim: `BEGIN IMMEDIATE` takes the write lock
> *before* the read, so the select-then-update is one critical section and two
> workers cannot see the same pending row. `commit_bundle` is the other half of
> the handler contract — the handler returned a `JobBundle` and wrote nothing;
> this writes the artifacts, the edges and the terminal status in one
> transaction, and refuses outright if the job is already terminal.
>
> And `fail_job` has a terminal guard. A job reclaimed by the reaper runs twice,
> and I had the loser flipping a `completed` job to `failed` and then skipping a
> subtree that had already succeeded.

`_abandon` is worth a sentence if they look at it: the rollback is best effort
and logs rather than raises, because it runs while another error is already on
its way to the caller and *that* error is the one worth seeing.

### 5. `backend/services/job_runner.py` — the transaction boundary, from the other side

*Why:* three separate fixes live in this file, and it is where "handlers are
pure" stops being a claim about handlers and becomes a claim about the runner.

> `JobExecutor.execute` is the whole contract in twenty lines: publish started,
> get the handler, `await handler.run(job)` under a timeout, `commit_bundle`,
> publish, notify the flow. The handler wrote nothing; every write in that
> sequence is `commit_bundle`, in one transaction. And `execute` never raises —
> a failed job is an outcome, not an exception, because the worker loop has to
> stay up.
>
> `handler_for` caches one handler per type, and one executor serves the whole
> pool — which is where my second concurrency bug was. `with_progress` used to
> assign the reporter onto that shared instance, so a job still in flight would
> publish its progress into another project under another job's id. It returns a
> `copy.copy` now, shallow, so the expensive collaborators stay shared and only
> the per-job reporter differs.
>
> `is_transient` is the retry classifier. `TRANSIENT_STATUS` only matches a
> status code where it is *labelled* as one, so a UUID beginning `429` is not
> retried. But the bigger fix was upstream: the provider was wrapping every
> failure as a plain `LLMError`, so the `isinstance` branch could never fire, and
> `str(httpx.ConnectTimeout(""))` is empty so there was nothing to match either.
> Timeouts and refusals both classified permanent. `TransientFailure` subclasses
> `ConnectionError` so the type carries the answer instead of the words.
>
> And `_record_failure` calls `_redispatch` when `fail_job` returns `pending`.
> That was missing: the row went back to `pending` and nobody told a worker. It
> worked because the local pool polls and Celery beat sweeps every 120 seconds,
> which is exactly the kind of accident that hides a bug.

`test_seams.py::TestProgressAttribution` and `TestRetryDispatch` are the paired
tests, and `test_pipeline.py::TestProviderFailureClassification` is the third.

### Two more if there is time

Both were on this list before and are still worth showing — they are just not the
answer to "what changed since we last spoke".

#### `backend/llm/schema.py` — the subtlest bug

*Why:* `strict_schema` is under 30 lines and the fix is one nobody would guess.
It shows he read a provider's constraints rather than assuming the library did
the right thing.

> Pydantic's `model_json_schema()` factors nested models into `$defs` and
> references them with `$ref`. Providers accept that but cannot police it in
> strict mode, and a model handed a reference-heavy schema stops treating field
> bounds as binding — my mind map ran a single string field to 100k characters
> and failed three retries. `strict_schema` walks the tree, splices each `$ref`
> back inline, and on every object sets `additionalProperties: false` and marks
> every property required. That is what strict mode needs to actually enforce a
> shape. Same tree, two-second response.

Pair it with `OpenRouterProvider._content_of` one file down:
`finish_reason == "length"` raises `TruncatedResponse`, which subclasses
`PermanentFailure`, so `_send` surfaces it immediately instead of retrying away
the one error message that told the user what to change.

#### `backend/tests/test_seams.py` — the evidence

*Why:* it turns "I applied SOLID" from an assertion into something they can watch
execute.

> This file tests the abstraction boundaries rather than the features.
> `RecordingProvider` is a fake `LLMProvider` that answers from a script and
> remembers what it was asked, and the tests drive `ArtifactGenerator` and
> `GenerateHandler` through it — real handler, real database, real transaction,
> fake model. `test_a_generate_handler_uses_the_injected_generator` asserts the
> committed artifact came from the fake and that exactly one provenance edge was
> written. That only passes because nothing downstream can tell one provider from
> another, which is Liskov doing work rather than being cited. `TestStagedUploads`
> is the same idea with stub pipeline stages, and it includes the one I care
> about most — `test_a_callers_own_file_is_never_deleted` — because the cleanup I
> added is an `unlink`, and I wanted a test standing between it and someone's
> actual files.

It also now holds `TestProgressAttribution`, which is the second concurrency
bug's regression test, so if the conversation lands here anyway it is a clean
route back to §3.3.

---

## 6. Where SOLID actually shows up

Not a definition list. Point at the file.

**Single responsibility.** `JobExecutor` owns the transaction boundary and
nothing else. `FlowCompiler` compiles; `FlowEngine` schedules — separate files,
and the compiler has no database handle, which is why validation is free.
`ExtractionService` routes to a reader, `DocumentReader` reads documents,
`Transcriber` handles speech. Each was one class before the split, and each was
hard to test because you could not exercise one behaviour without the others.

**Open/closed.** Adding an artifact type is one entry in `SPECS`
(`services/generators.py`) and one in `ARTIFACT_MODELS` (`models/artifacts.py`).
No handler change, no new branch in the runner, no new validation rule —
`GeneratorSpec.validate` reads its thresholds from the spec. That is why going
from five types to eight touched two dictionaries. The canvas even builds its
palette from `/api/capabilities`, derived from `GENERATED_TYPES`, so the UI picks
up a new type without a frontend change.

Be precise if they count: `ARTIFACT_MODELS` has eight, `SPECS` has seven. The
exam is deliberately not spec-driven — it is a two-stage generation with three
question batches under `asyncio.gather` — and that is the honest answer to "does
your abstraction actually hold". It holds for seven of eight, and the eighth
needed a different shape rather than being forced through the same one.

**Liskov.** `OfflineProvider` and `OpenRouterProvider` are interchangeable
everywhere. The proof is that the entire suite runs the real handlers against the
offline one — only possible because nothing downstream can tell them apart. If
that substitution were leaky, 172 tests would fail.

The limit of that, which is worth volunteering: the substitution is so complete
that the offline provider never calls `extract_json`, so a real parser bug lived
in it for months with a green suite. Testing through a substitute means the seam
itself needs tests of its own.

**Interface segregation.** `LLMProvider` has three methods and `transcribe` is
optional with a default that raises, so a caller that only generates text does
not depend on audio; `supports_audio` is a class attribute callers check rather
than a method they must implement. `FileStore` exposes put/get/sign/resolve, not
a general filesystem.

**Dependency inversion.** Every handler takes its collaborators as constructor
arguments with a sensible default:

```python
def __init__(self, database=None, resolver=None, generator=None, merger=None, exporter=None):
    self._database = database or get_database()
```

Production passes nothing; tests pass fakes. Handlers depend on `LLMProvider` and
`Database` — the abstractions — never on OpenRouter or SQLite. `llm/factory.py`
is the single place that decides which concrete provider exists, and it degrades
to offline rather than raising when a key is absent.

---

## 7. Anticipated questions

Answers are 2–4 sentences. Say them roughly like this, not verbatim.

**"Did you write this?"**
> I used AI assistance, and I'd rather be direct about that than have it come up
> awkwardly. What I drove was every architectural decision: the handler-returns-
> a-bundle contract, the wave-depth scheduler, making the queue a table instead
> of a message, the strict-schema fix. The clearest evidence is the bugs — nothing
> generated that scheduler race for me. I found it reasoning about where
> FastAPI's threadpool and the event loop overlap, and I wrote a barrier test to
> prove it. Same with the SSRF: that came from asking what else my own fix had
> left open, not from a tool telling me. Open any file and I'll walk you through
> it.

If they follow up on a specific file, go to the code, do not paraphrase. The five
walkthroughs in §5 exist so there is always a concrete place to land, and
`docs/walkthrough/` is the thing that means any *other* file is survivable too.

**"You interviewed with this project before. What's different?"**

This is the question the whole interview is really asking. Have a 30-second
answer that is not a list of features.

> The code is mostly the same product. What changed is that I went back over work
> I'd already shipped and treated it as somebody else's. That found a critical
> SSRF in a field I had *already fixed once* — I'd constrained the URL scheme and
> never asked what the host could be, and yt-dlp will fetch anything, so my server
> would read a cloud metadata endpoint and hand the response back to the caller as
> an artifact. It found a second concurrency bug of a completely different kind
> from the first. And I ran a mutation sweep over my own test suite, which told me
> two of my ten regression tests would have passed against the bugs they were
> written for. That last one is the thing I actually took away: I had tests that
> made me feel covered and did not cover anything.

**"Have you found any other concurrency bugs?"**
> Yes, one, and it's a different kind. The first was a read-modify-write race on
> a database row. The second is shared mutable state on an object: the worker
> pool builds one executor, the executor caches one handler per job type, and
> attaching a progress reporter wrote onto that shared instance. So four workers
> running four jobs meant the last one to attach owned the callback, and a job
> still in flight published its progress into a different project under a
> different job's id. Cross-project misattribution, not a dropped event. It
> returns a shallow copy now — collaborators stay shared, only the reporter is
> per job.

**"Why didn't your tests catch that one?"**
> Because Celery mode builds a fresh executor per task, so there's no sharing to
> corrupt, and that's the path the tests exercised. The bug only existed in the
> in-process worker pool. It's the same failure as my old idempotence test: the
> test ran a configuration in which the property genuinely held, so it told me
> nothing about the configuration where it didn't. That's the pattern I now look
> for first.

**"How do you know your tests are any good?"**

Use this instead of quoting a coverage number. It is the strongest behavioural
answer in the document.

> I ran a mutation sweep. I copied the repo, applied about 45 mutations one at a
> time — each breaking exactly one behaviour — and recorded which tests died. I
> cared most about the ten regression tests I'd written for bugs I'd already
> fixed, because those are the ones I was leaning on. Eight held. The flow
> concurrency one is the real thing: reverting the fix failed it 20 out of 20,
> and 19 of those were exactly `assert 9 == 2`.
>
> Two didn't. The locale bug had no test at all, so putting the original bug back
> left 108 tests green. Idempotency had no negative test, so re-adding
> "completed" to the in-flight set — which *is* the original bug — survived too.
> And one test was passing by scheduling luck: the client fixture starts a real
> worker pool, and the deduplication test only passed because the idle backoff
> kept the worker asleep between two requests. At a 1 ms backoff it failed 3 out
> of 3.
>
> All 21 survivors are killed now and the suite went from 108 to 172. But the
> answer to your question isn't the number — it's that coverage told me those
> lines ran and mutation testing told me nothing would have noticed if they were
> wrong.

**"What was the hardest bug?"**

Two good answers. Lead with the first; offer the second if they want more.

> The one that cost me most was a locale mismatch. My offline provider — the
> no-API-key fallback — decides whether a prompt wants its input edited or wants
> something new derived from it, and the gate was "does the prompt contain *do
> NOT summarize*". American spelling. My cleaning prompt says *summarise*.
> British. So the check never matched, and the cleaning pass — whose entire job
> is to hand the transcript back repaired — replaced the whole lecture with a
> synthetic study document instead, and every artifact downstream was then built
> on that stub rather than on the actual lecture. Nothing errored. The output was
> just quietly, plausibly wrong. It's now a tuple of markers covering both
> spellings and the phrases that actually appear in the prompt, behind a named
> method with a docstring saying what it's for.

Why that story is good: silent data corruption from a one-word difference,
plausible output masking it, no exception anywhere. It has a sequel worth one
extra sentence if they engage with it: the *same* shape turned up again in the
cleaning rules, which deleted every parenthesised and bracketed span on every
source type, so a maths PDF lost `f(x)`, `[0,1]` and `O(n log n)` and nothing
raised. Split into a document path and a transcript path, with the safe one
holding the plain name `clean` so a caller who doesn't know what it's holding
can't destroy notation by accident.

If they seem to want something more technical:

> The other one was structured-output drift. A mind map would burn 100k
> characters on a single string field and fail all three retries, and everything
> pointed at the model being bad. It was the schema: Pydantic factors nested
> models into `$defs` and `$ref`, providers accept that but can't enforce it in
> strict mode, and given a reference-heavy schema the model stops treating field
> bounds as binding. Inline every reference, close every object, mark everything
> required — same tree, two-second response. What made it hard is that nothing in
> the error said "schema"; it said "unterminated string".

**"How do you know the atomic claim works?"**
> `claim_job` opens with `BEGIN IMMEDIATE`, which takes SQLite's write lock
> *before* the read — the equivalent of `SELECT … FOR UPDATE SKIP LOCKED`. So the
> select-then-update is one critical section. There are two tests: one inserts a
> job and asserts the second `claim_job` returns `None`, and
> `test_racing_workers_partition_the_queue` puts six real threads on a barrier
> against a 24-job queue and asserts every job was claimed exactly once. That
> second one is the honest test — the first would pass on a broken
> implementation, which is the same mistake my old idempotence test made.

**"Why SQLite and not Postgres?"**
> Because the workload is one local workspace with a handful of concurrent jobs,
> and the whole persistence surface is behind `Database`. WAL mode plus
> `BEGIN IMMEDIATE` gives me a real atomic claim and real transactions, which is
> the only concurrency primitive I actually needed. The honest reason is that the
> previous version died when its Supabase free tier lapsed, and a project that
> stops running when a key rotates is not a project. If I needed multi-tenancy
> I'd swap the implementation behind `Database`, not restructure anything above.

**"What happens when the model returns garbage?"**
> Three layers. Structured output — `strict_schema` sends a closed,
> fully-required, `$ref`-free schema with `strict: true`, and `parse_as` strips
> code fences and prose wrappers before validating. Then semantic validation in
> `GeneratorSpec.validate`: a quiz with two questions parses perfectly and is
> useless, so it's rejected with "expected at least 5 questions, got 2". Then
> classification — a schema violation is permanent, so the job fails cleanly
> rather than burning three attempts producing the same garbage. That last part
> is a fix: `RETRYABLE_STATUS` used to be inert, so a 401 burned three attempts
> and the useful error got retried away.

If they follow the classification thread, that is the door to §3.7 — the version
of this answer I could give six months ago was wrong in a way I only found by
measuring it: the provider wrapped every error as a plain `LLMError`, so the type
check could never fire, and connect timeouts and refused connections both
classified permanent while a 429 classified transient. The two most common real
failures were the two the retry logic had stopped covering.

**"Why not stream generation?"**
> Because I validate before I display. A quiz is not useful half-rendered, and if
> I streamed I'd have to show output that `GeneratorSpec.validate` might then
> reject — so the user watches something appear and then vanish. Instead I stream
> *progress*: every handler reports named stages over the WebSocket, so you see
> "merging sources", "writing quiz", "saving". Same perceived responsiveness,
> nothing I have to retract.

**"How would you scale this to 1,000 users?"**
> Three changes, in order. Swap the `Database` implementation for Postgres —
> `claim_job` becomes `SELECT … FOR UPDATE SKIP LOCKED`, which is the same
> semantics I already rely on, and nothing above the class changes. Then the
> local file store becomes S3 or R2; `FileStore` already exposes exactly the
> put/get/sign surface an object store gives you. Then Celery workers scale
> horizontally, which they already can. The genuinely new work is multi-tenancy:
> `resolve_user` becomes a real token check and every query grows a tenant
> predicate — and I'd be careful there, because most of the ownership holes I
> found were exactly the shape of "checked one level of ownership and stopped".
> I'd also want an egress proxy before anything multi-tenant, because my SSRF
> guard resolves the host and then lets yt-dlp open its own socket, and that gap
> only closes properly at the network layer.

**"How do you test something that calls an LLM?"**
> I don't mock the LLM; I substitute the provider. `OfflineProvider` implements
> the same interface and derives artifacts from the source text with frequency
> analysis, so the tests run the *real* handlers, the real transactions and the
> real DAG traversal against a temp SQLite database — 172 tests, no network, no
> keys, under two seconds. Where I need to assert on what the model was *asked*,
> `test_seams.py` uses `RecordingProvider`, which answers from a script and
> records the prompts. Mocking `httpx` would only have tested my mock.
>
> The cost of that choice is real and I'd rather name it: the offline provider
> never calls `extract_json`, so a genuine parser bug sat behind a green suite
> until I went looking. Substituting at the seam is still right, but the seam
> needs its own tests, which it now has.

**"Why is the knowledge core the root of the graph?"**
> Because it has indegree zero — it wasn't derived from anything already in the
> graph. The source *file* is an artifact too, but the edge would be lying: the
> core comes from the file's extracted text, not from the file as a graph node.
> So ingest emits exactly two artifacts and zero edges, and the link back to the
> file is `created_by_job_id`. That keeps `artifact_edges` meaning one thing
> only — "this was generated from that" — so lineage queries stay honest.

**"What would you do differently?"**
> Three things. I'd write the concurrency tests first. My old idempotence test
> called `advance` twice on one thread and passed, which gave me false confidence
> in exactly the property that was broken — a test that proves a weaker claim
> than you think it does is worse than no test. I'd have built the offline
> provider first. It ended up being what made the test suite possible and what
> makes `docker compose up` work with an empty `.env`, and I built it late, as a
> fallback, without realising it was load-bearing infrastructure. And I'd put the
> validation on the layer that makes the dangerous call, not on the request
> schema. Every one of my security holes was a check in the wrong place rather
> than a missing check — I validated the type and not the value, or I validated
> at the door and not at the exit.

**"What did you actually learn from all this?"**

If they give you an opening for one sentence rather than a list, use this one.

> That most of my bugs weren't gaps, they were checks placed one layer too high —
> and that the thing which finds them isn't reading the diff, it's asking what
> *else* reaches this code and what *else* this value could be.

---

## 8. Honest limitations

Volunteer these before you are asked. Naming your own gaps reads as judgement;
being caught out by them reads as the opposite. Two or three is enough — pick
what fits the conversation. The first is the strongest thing on this list.

| Limitation | The line to say |
|---|---|
| **The SSRF guard checks at resolve time, not connect time** | "This is the sharpest edge I know about, and it's a gap in a fix I'm otherwise pleased with. I resolve the host and check every address, then hand the URL to yt-dlp, which opens its own socket. A DNS rebind — public answer for my check, internal answer a moment later for the fetch — gets through, and so does a redirect from a genuine YouTube host to an internal address. Closing it properly means pinning the resolved IP into the socket or putting an egress proxy in front, and yt-dlp doesn't give me a connect hook clean enough to do the first. I'd do the proxy before any multi-user deployment." |
| **`ingest` submitted directly to `POST /api/jobs` with a non-YouTube `source_ref` is still an arbitrary local file read** | "Same family, still open. The upload route sets `source_ref` server-side and now refuses `youtube` outright, and the youtube branch has a real guard on it, but `IngestRequest` still doesn't constrain `source_ref` for `pdf`, `audio`, `video`, `pptx` or `md` — name a local path and `IngestHandler` reads it, extracts the text and commits it as an artifact you can download. It's single-user and local-only, so today the 'attacker' is the operator, and the workspace page deliberately lets a developer type a local path. The fix is making `source_ref` a storage key rather than a filesystem path, and I've left it deliberately rather than not seen it." |
| **Single-user, no multi-tenancy** | "`resolve_user` takes an `Authorization` header and ignores it — one local user for every caller. Ownership is recorded and enforced on every read, so the queries are already correct; there's just no identity provider behind it. Deliberate: one seam to replace, not a refactor. Worth being precise though — that makes the *cross-tenant* holes unexploitable today, and it does nothing for the SSRF or the signing key, which were exploitable by anyone who could reach the API." |
| **A retried ingest orphans its first copy** | "`store_upload` mints a fresh uuid key per attempt, so a failed-then-retried ingest leaves the first attempt's copy in the file store referenced by nothing. Small, but it's unbounded growth, and the fix is either keying on job id or sweeping artifacts with no row." |
| **Mutation testing was a one-off, not a habit** | "I ran about 45 mutations by hand against a sandbox copy and killed all 21 survivors, but it isn't in CI and there's no tooling behind it. The suite runs in under two seconds so there's no real reason it couldn't be — I just haven't wired it up, and until I do, the next regression test I write gets the same benefit of the doubt the two broken ones did." |
| **No vector store / RAG** | "A lecture fits in a modern context window, and the knowledge core is a better summary than top-k chunks — it's structured, and every generator reads the same one, which is what keeps artifacts consistent. RAG would have been resume-driven." |
| **No streaming generation** | "Deliberate, for the reason above: I validate before I display, so I stream progress instead of tokens." |
| **The frontend is weaker than the backend** | "That's where I'd go next, and it's genuinely the weak half. The canvas works and the WebSocket wiring is clean, but there's duplicated state between the React Flow store and the fetched artifacts, and the dashboard pages accumulated during the hackathon and never got the treatment the backend did. The one that caught me: the Run button stayed spinning forever after a flow finished, because the flag was only cleared by a code path the incremental socket events never reach. Fixed, but it's the sort of thing the backend's tests would have caught and the frontend has nothing equivalent." |
| **`OfflineProvider` output is genuinely poor** | "It's frequency analysis, not a model. Its job is to prove the pipeline runs, not to be useful — but it's not a stub either. It goes through every stage." |
| **Exports depend on a LaTeX install** | "`ExportService` catches render failures rather than failing the job, because an artifact is defined by its content and the file is a convenience. A missing LaTeX install costs you the PDF, not the generation." |

---

## Cheat sheet

Sixty seconds before the call.

### The three sentences

1. **"The graph you draw is the program that runs."** `FlowCompiler` compiles the
   canvas to a DAG, Kahn's algorithm assigns wave depths, `FlowEngine` dispatches
   wave by wave. Fan-in and fan-out are one mechanism from two ends.
2. **"Handlers never write to the database."** They return a `JobBundle`;
   `JobExecutor` commits it in one transaction. LLM calls fail often enough that
   a handler throwing midway is the common case.
3. **"Scheduling a step is transactional, and dispatch happens after commit."**
   Read → queue → write back, one transaction. Eight concurrent completions
   produced 9 dispatches before, 2 after. Events wait for the commit too, through
   an outbox.

### The three since last time

1. **The SSRF.** I fixed the URL *scheme* and never asked what the *host* could
   be. yt-dlp fetched a cloud metadata endpoint and my pipeline committed the
   response as an artifact the caller could read. Host allowlist plus resolved-IP
   checks, in the file that makes the call — not on the request schema.
2. **The second concurrency bug.** One shared handler, four workers, a progress
   reporter attached by mutation — jobs reported into each other's projects.
   `copy.copy` per job.
3. **Mutation testing.** ~45 mutations; 8 of 10 regression tests held, 2 proved
   nothing, 1 more was passing on scheduling luck. 108 tests → 172.

### The numbers

| | |
|---|---|
| Tests | **172** — no network, no API keys, temp SQLite + offline provider, ~1.4s |
| Test files | 72 API, 59 pipeline, 21 flow engine, 20 seams |
| The measurement | 8 concurrent completions → **9 dispatches before, 2 after** |
| Mutation sweep | ~45 mutations, **21 survivors, all now killed**; 108 tests → 172 |
| Racing-workers test | 6 threads, 24 jobs, every job claimed exactly once |
| SSRF guard tests | **18** in `TestYouTubeIngestGuard` |
| Dependencies | **52** pinned (was 96) |
| Artifact types | **8** in `ARTIFACT_MODELS` — quiz, exam, notes, slides, flashcards, study guide, cheat sheet, mind map (**7** in `SPECS`; the exam has its own two-stage path) |
| Source types | **6** — youtube, audio, video, pdf, pptx, md (5 uploadable; youtube is URL-only) |
| Tables | **6** — projects, jobs, artifacts, artifact_edges, flow_runs, chat_messages |
| Security holes found and fixed | **6** in `backend/api/`, plus the SSRF in `pipeline/ingestion.py` |
| Node ceiling | 100 per flow |
| Defaults | 3 attempts, 900s job timeout, 1800s stale cutoff, 4 workers, 6 concurrent LLM calls, 200 MB uploads |

### The file paths

| | |
|---|---|
| The SSRF guard | `backend/pipeline/ingestion.py` — `YouTubeUrlGuard`, `HostResolver` |
| Its tests | `backend/tests/test_api.py` — `TestYouTubeIngestGuard` |
| The concurrency fix | `backend/services/flow/engine.py` — `on_job_finished`, `_schedule`, `_hand_off`, `EventOutbox` |
| Its test | `backend/tests/test_pipeline.py` — `TestFlowConcurrency` |
| The second concurrency bug | `backend/handlers/base.py` — `with_progress`; test in `test_seams.py::TestProgressAttribution` |
| The runner | `backend/services/job_runner.py` — `execute`, `handler_for`, `is_transient`, `_redispatch` |
| The algorithm | `backend/services/flow/plan.py` — `FlowCompiler._topological_order` |
| The primitives | `backend/services/database.py` — `_transaction`, `claim_job`, `commit_bundle`, `fail_job` |
| The contract | `backend/handlers/base.py` — `JobHandler`, `JobBundle` |
| The subtlest bug | `backend/llm/schema.py` — `strict_schema`; and `extract_json` right below it |
| Failure classes | `backend/llm/openrouter.py` — `PermanentFailure`, `TransientFailure`, `_describe`, `_limiter` |
| The locale bug | `backend/llm/offline.py` — `PASS_THROUGH_MARKERS`, `_wants_the_source_back` |
| The corruption bug | `backend/pipeline/cleaning.py` — `clean` vs `clean_transcript`, `TRANSCRIBED_SOURCE_TYPES` |
| The signing-key guard | `backend/main.py` — `require_unforgeable_links`; `PUBLISHED_SECRETS` in `core/config.py` |
| Ownership | `backend/api/deps.py` — `require_project`, `require_project_artifact` |
| The SOLID evidence | `backend/tests/test_seams.py` — `RecordingProvider`, `TestStagedUploads` |
| Line by line, any file | `docs/walkthrough/` — start at `09-flow-engine.md` |

### If it goes wrong

- Demo fails → blank the key, `/health` shows `"model": "offline"`, everything
  still runs.
- Frontend hangs on Run → it's fixed, but reload the page and carry on; do not
  debug it live.
- Anything else fails → `backend/venv/bin/python -m pytest -q`, 172 tests, under
  two seconds.
- Asked something you don't know → "I don't know off the top of my head, let me
  look" and open the file. Reading your own code in front of them is a *good*
  outcome; guessing is not.

### Last thing

Lead with the canvas. Close the opener on the two bugs — the scheduler race and
the SSRF — and let them pick. When they ask about AI assistance, answer in one
honest sentence and immediately offer to open a file; the offer is the proof.

The thing this interview is testing is not whether the project got bigger. It is
whether you can reason about code you already wrote. Every one of the new stories
is you auditing your own work and finding it wanting. Say them that way.
