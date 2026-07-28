# 09 — The flow engine: `plan.py` and `engine.py`

Two files, 584 lines between them. `plan.py` turns a canvas into a plan.
`engine.py` runs that plan. Everything else in this document hangs off those two
sentences.

- `backend/services/flow/plan.py` — 255 lines. `FlowCompiler`, `FlowPlan`, `FlowStep`.
- `backend/services/flow/engine.py` — 329 lines. `FlowEngine`, `EventOutbox`.
- `backend/services/flow/__init__.py` — 17 lines, re-exports.

---

## Part 0 — What happens between pressing Run and the last node turning green

Read this once before you look at any code. Everything below is this story told
slowly.

You have an infinite React Flow canvas. You drag artifact nodes onto it (each one
already points at a stored artifact — usually a knowledge core distilled from a
lecture) and generator nodes (each one says "make me a quiz", "make me
flashcards"). You wire them together with edges. The canvas is just JSON:
a list of node objects and a list of edge objects.

**You press Run.** The frontend POSTs that JSON to
`POST /api/projects/{project_id}/flow/run`. Note carefully: the graph travels in
the request body. The server does not trust it, and we will come back to that.

**The route authorises the project.** `require_project` loads the project row and
checks the caller owns it. 404 if it does not exist, 403 if somebody else's.

**The route compiles the graph.** `FlowCompiler().compile(nodes, edges)`. This is
`plan.py` and it does five things:

1. Splits every node into a *source* (already has an artifact id) or a
   *generator* (will produce one). Anything else is ignored.
2. Builds `incoming` and `outgoing` adjacency maps from the edges, throwing away
   edges that point at nodes which no longer exist, deduplicating parallel edges,
   and rejecting self-loops.
3. Rejects any generator that nothing feeds into.
4. Runs Kahn's algorithm over the graph to get a topological order, and carries a
   *wave depth* along with it.
5. Emits a `FlowPlan`: a list of `FlowStep`s in dependency order, each carrying
   its own parents and its depth, plus a `seed_artifacts` dictionary mapping
   source node ids to artifact ids.

If any of that fails you get a `FlowValidationError` naming the offending node,
which `/flow/run` turns into a 422 and `/flow/validate` turns into a 200 with
`valid: false` and the message.

**The route authorises the seeds.** `_require_owned_seeds` walks
`plan.seed_artifacts` and checks every single artifact id actually lives in this
project and belongs to this caller. This check exists because of a real hole; see
Part 5.

**The engine starts the run.** `FlowEngine.start` builds an initial `node_states`
dictionary: every generator step starts `pending`, every seed node starts `ready`
with its artifact id already attached. That whole thing plus the serialised plan
goes into one `flow_runs` row. A `flow.started` event is published over the
WebSocket so the canvas can light up.

**The engine dispatches wave one.** `start` calls `advance`, which opens a
database transaction and calls `_schedule`. `_schedule` walks every step in the
plan, skips anything not `pending`, skips anything whose parents are not all
finished, and for the ones that are ready: collects the parents' artifact ids,
inserts a `jobs` row with `status: pending` carrying those ids as
`source_artifact_ids`, flips the step's state to `running`, and *records* a
`flow.node` event in an outbox. On the first pass the only steps whose parents are
all ready are the ones fed purely by source nodes — that is wave one, and only
wave one.

**The transaction commits. Then, and only then, anything outside the database
hears about it.** `_schedule` returns a list of job ids and leaves its events in
the `EventOutbox`. `advance` exits the `with` block, the commit happens, and only
after that does `outbox.flush()` publish the events and `_hand_off` call
`dispatch(job_id)` for each job. In Celery mode dispatch pushes onto Redis; in
local mode it is a no-op because the in-process worker pool is already polling the
`jobs` table. The rule is one rule applied twice: commit the fact, then announce
it — to the workers and to the browser alike.

**A worker picks up a job.** `Database.claim_job` does `BEGIN IMMEDIATE`, selects
one pending row, flips it to `running` — atomically, so exactly one worker wins.
`GenerateHandler.run(job)` resolves the `source_artifact_ids` into knowledge
cores, merges them with `CoreMerger` if there is more than one, calls the LLM, and
returns a `JobBundle`. The handler writes nothing to the database. `commit_bundle`
writes the artifacts, the provenance edges and the terminal job status in one
transaction.

**The worker notifies the flow.** `JobExecutor._notify_flow` reads
`flow_run_id` and `flow_node_id` back out of the job payload and calls
`FlowEngine.on_job_finished(...)`. That opens a transaction, merges the outcome
into `node_states`, writes it back, and calls `_schedule` again — which now finds
that the child step's parents are all `completed`, so it queues the child. Commit,
then flush the events, then dispatch, then re-read the row for the caller. Repeat.

**Fan-in and fan-out fall out of this for free.** A node with three incoming edges
has three entries in `step.parents`, so `_inputs_ready` returns false until all
three have finished, and then `_input_artifacts` hands it three artifact ids. A
node with three outgoing edges is simply the parent of three steps, so when it
completes, one pass of `_schedule` finds all three ready and queues all three.
Same loop, opposite ends.

**The run terminates.** Every time states are saved, `_save` checks whether every
step is in a terminal status (`completed`, `failed`, `skipped`). When they all
are, it tallies them, sets the run's status to `completed` or `failed`, stamps
`completed_at`, and records `flow.completed` or `flow.failed` in the outbox — which
goes out with everything else once the transaction commits. The canvas turns green.

**Verified end to end:** an 8-node flow ran in 2 waves with fan-out and all 8
steps completed.

---

## Part 1 — `plan.py`, line by line

### The header

```python
"""Compiles a canvas graph into a validated, ordered execution plan."""
```
`plan.py:1`. Says what it is.

```python
from __future__ import annotations
```
`plan.py:3`. Postpones evaluation of annotations, so you can write
`tuple[Dict[str, str], Dict[str, str]]` on Python 3.10 without the builtin-generic
syntax blowing up at import time. Boring, mechanical, present in every file here.

```python
from backend.models.artifacts import GENERATED_TYPES
```
`plan.py:9`. This is the important import. `GENERATED_TYPES` is
`frozenset(ARTIFACT_MODELS)` — the eight things the generator can produce: quiz,
exam, notes, slides, flashcards, study_guide, cheatsheet, mindmap. The compiler
uses it twice: to decide whether a node is a generator at all, and to decide
whether a generator has a valid output type. The single source of truth for
"what can be made" lives in `backend/models/artifacts.py:148`, not here, so
adding a ninth artifact type does not require touching the compiler.

### The three constants

```python
SOURCE_NODE_TYPES = frozenset({"asset", "artifactNode", "source", "result", "knowledgeCore"})
GENERATOR_NODE_TYPES = frozenset({"generator", "agent", "task"})
MAX_NODES = 100
```
`plan.py:13-15`.

The two node-type sets are broad on purpose. React Flow node types are strings
the frontend picks, and this project has had several generations of node
component (`asset`, `artifactNode`, `knowledgeCore` are all the same idea at
different points in the frontend's history). Accepting all the historical names
means an old saved `canvas_state` still compiles instead of producing an
inscrutable "Nothing to run".

`MAX_NODES = 100` is a denial-of-service bound. The graph arrives in a request
body, so without a cap somebody can POST a 50,000-node canvas and make the server
do 50,000 units of adjacency work and, worse, insert 50,000 job rows.

**Worth knowing:** the cap is on *nodes*, not edges. A 100-node canvas can carry
an unbounded number of edges, and `_adjacency` iterates every one. In practice
that is a linear scan over a list, not a job insert, so the damage is bounded —
but if an interviewer asks "what's the worst input", that's the honest answer.

```python
class FlowValidationError(ValueError):
    """A canvas graph cannot be turned into a runnable plan."""
```
`plan.py:18-19`. One exception type for "your canvas is wrong". It subclasses
`ValueError` rather than `Exception` so that any generic `except ValueError`
higher up still behaves sensibly, but the routes catch it by name so they can map
it to a 422 rather than a 500. That distinction matters: a bad canvas is the
user's problem, not a server fault, and it must never page anyone.

### `FlowStep`

```python
@dataclass
class FlowStep:
    """One generator node, and what has to finish before it can run."""

    node_id: str
    target_type: str
    parents: List[str] = field(default_factory=list)
    instructions: Optional[str] = None
    depth: int = 0
```
`plan.py:22-30`.

One step is one generator node. Five fields:

- `node_id` — the React Flow node id. This is the key the frontend uses to colour
  the right node, and the key the engine uses in `node_states`. It survives the
  whole round trip: canvas → plan → `flow_runs.node_states` → job payload
  (`flow_node_id`) → back into `on_job_finished`.
- `target_type` — which of the eight artifacts to make.
- `parents` — node ids this step waits on. **These are node ids, not artifact
  ids.** That is deliberate: a parent generator does not have an artifact id yet
  when the plan is compiled, only after it runs. The artifact id is looked up
  from `node_states` at dispatch time.
- `instructions` — free text from the node ("focus on chapter 3"), passed
  straight to the LLM prompt.
- `depth` — the wave number. Explained below.

`field(default_factory=list)` rather than `= []` is the standard dataclass rule:
a bare mutable default would be shared across every instance.

```python
    def to_dict(self) -> Dict[str, Any]:
```
`plan.py:32-39`. Plain serialisation. It exists because the plan is stored as
JSON in `flow_runs.plan`, and the engine may read it back in a completely
different process from the one that wrote it. See the `FlowEngine` class
docstring at `engine.py:52-59` — nothing is held in memory between calls.

```python
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FlowStep":
        return FlowStep(
            node_id=data["node_id"],
            target_type=data["target_type"],
            parents=list(data.get("parents") or []),
            instructions=data.get("instructions"),
            depth=int(data.get("depth", 0)),
        )
```
`plan.py:41-49`. The inverse. Note the asymmetry in strictness: `node_id` and
`target_type` use `data["..."]` and will raise `KeyError` if absent, because a
step without them is meaningless. Everything else uses `.get` with a default,
because a plan written by an older version of the code might not have had that
field. The `or []` after `.get("parents")` handles a stored `null` as well as a
missing key — `data.get("parents") or []` is `[]` for both `None` and `[]`.

### `FlowPlan`

```python
@dataclass
class FlowPlan:
    """A validated execution plan for one canvas."""

    steps: List[FlowStep]
    seed_artifacts: Dict[str, str]
```
`plan.py:52-57`.

Two fields. `steps` is the generators in topological order. `seed_artifacts` maps
source-node id → artifact id: the inputs the run starts with. Source nodes are
deliberately *not* steps — nothing has to be executed for them, they are already
done. But they are still in `parents` lists, and the engine puts them into
`node_states` with status `ready` so the same "are my parents finished?" check
works uniformly for seeds and for generated parents.

```python
    @property
    def waves(self) -> List[List[FlowStep]]:
        """Steps grouped by depth. Everything in a wave can run at once."""
        grouped: Dict[int, List[FlowStep]] = {}
        for step in self.steps:
            grouped.setdefault(step.depth, []).append(step)
        return [grouped[depth] for depth in sorted(grouped)]
```
`plan.py:59-65`.

Buckets the steps by depth and returns them in ascending depth order. The
`sorted(grouped)` at the end matters — dict insertion order follows the
topological order which is *usually* depth-ascending, but you should not rely on
that, and sorting makes it explicit.

This is used in two places and neither of them is scheduling. `/flow/validate`
returns `len(plan.waves)` so the UI can say "this will run in 2 waves", and
`start` publishes `waves: len(plan.waves)` in the `flow.started` event. The actual
execution does **not** iterate waves — it re-derives readiness from `node_states`
every time. That is important and an interviewer may well probe it: if the engine
walked waves it would have to hold a cursor somewhere, and that cursor would be
state that could go stale across processes. Instead, readiness is recomputed from
scratch on every pass, which is what makes `advance` safe to call at any moment.

```python
    def descendants_of(self, node_id: str) -> Set[str]:
        """Every step reachable from `node_id`."""
        children: Dict[str, List[str]] = {}
        for step in self.steps:
            for parent in step.parents:
                children.setdefault(parent, []).append(step.node_id)
```
`plan.py:67-72`.

The plan stores *parents* per step, because that is what the engine needs to
answer "can this run yet?". Failure propagation needs the opposite direction —
"what does this block?" — so this rebuilds the child map on the fly. At 100 nodes
that is trivial, and it avoids storing and keeping in sync a second adjacency
structure inside the serialised plan.

```python
        found: Set[str] = set()
        pending = list(children.get(node_id, []))
        while pending:
            current = pending.pop()
            if current not in found:
                found.add(current)
                pending.extend(children.get(current, []))
        return found
```
`plan.py:74-81`.

An iterative depth-first traversal collecting the transitive closure. The `if
current not in found` guard is what makes this terminate even in the presence of
a cycle — and although the compiler rejects cycles, this method can also be
called on a `FlowPlan` reconstructed from JSON in the database, which nothing
re-validates. Iterative rather than recursive so a long chain cannot blow the
Python stack. `pending.pop()` from the end is O(1); order does not matter since
the result is a set.

This is called from `FlowEngine._skip_downstream` and nowhere else.

```python
    def to_dict(self) -> Dict[str, Any]: ...
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FlowPlan": ...
```
`plan.py:83-94`. Same serialisation pattern as `FlowStep`, same `or {}` defensive
default on `seed_artifacts`.

### `FlowCompiler.compile`

```python
class FlowCompiler:
    """
    Turns React Flow nodes and edges into a `FlowPlan`.

    Every rejection names the offending node, so the canvas can point at the
    problem before any work is dispatched.
    """
```
`plan.py:97-103`.

That docstring is a design commitment, and every `raise` in this file honours it.
The reason is product-level: on an infinite canvas with thirty nodes, an error
that says "invalid graph" is useless. You need to know *which* node. Every message
in this file carries either the node's label or its id.

```python
    def compile(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> FlowPlan:
        """Validate the graph and return its execution plan."""
        if not nodes:
            raise FlowValidationError("The canvas is empty. Add a source and a generator to run.")
        if len(nodes) > MAX_NODES:
            raise FlowValidationError(f"Flows are limited to {MAX_NODES} nodes; this has {len(nodes)}.")
```
`plan.py:105-110`. The two cheapest checks first: nothing, and too much. Both
messages tell the user what to do next.

```python
        by_id = {str(node["id"]): node for node in nodes if node.get("id")}
```
`plan.py:112`. Index the nodes. Two things happening quietly:

- `if node.get("id")` drops nodes with a missing or empty id. They cannot be
  referenced by an edge and cannot be tracked in `node_states`, so there is
  nothing useful to do with them.
- `str(...)` normalises the key. Edge endpoints are also `str()`-ed in
  `_adjacency`, so numeric ids from one client and string ids from another still
  match.

If two nodes share an id, the later one wins. Not checked, and not worth
checking — React Flow generates unique ids.

```python
        generators, seeds = self._classify(by_id)

        if not generators:
            raise FlowValidationError(
                "Nothing to run. Drag in a generator node and connect a source to it."
            )
```
`plan.py:113-118`. A canvas of nothing but artifact nodes is a picture, not a
program. Pinned by `test_canvas_with_no_generators_is_rejected` in
`backend/tests/test_flow_engine.py:130`.

```python
        incoming, outgoing = self._adjacency(by_id, edges)
        runnable = set(generators) | set(seeds)
        self._require_inputs(generators, incoming, runnable, by_id)
```
`plan.py:120-122`.

`runnable` is the set of node ids the plan cares about: every generator, plus
every source that actually resolved to an artifact id. Anything else on the canvas
— a sticky note, a comment box, a source node someone dragged on but never bound
to an artifact — is outside `runnable` and is filtered out everywhere below. That
single set is why decorative nodes cannot break a run.

```python
        order, depth = self._topological_order(runnable, incoming, outgoing, by_id)
```
`plan.py:124`. Kahn. Detailed below.

```python
        steps = [
            FlowStep(
                node_id=node_id,
                target_type=generators[node_id],
                parents=[parent for parent in incoming[node_id] if parent in runnable],
                instructions=(by_id[node_id].get("data") or {}).get("instructions"),
                depth=depth[node_id],
            )
            for node_id in order
            if node_id in generators
        ]
```
`plan.py:126-136`.

Build the steps by walking the topological `order` and keeping only the
generators. Sources are dropped here — they are already in `seed_artifacts`.
Because we iterate `order`, `plan.steps` is itself in dependency order, which is
why `_schedule` can walk it in a single forward pass.

`parents=[parent for parent in incoming[node_id] if parent in runnable]` is the
filter that matters. Without `if parent in runnable`, a generator wired to a
decorative node would list that node as a parent, `_inputs_ready` would look it
up in `node_states`, find nothing, and the step would wait forever.

`(by_id[node_id].get("data") or {}).get("instructions")` — the `or {}` handles
`data` being absent *or* explicitly `null` in the JSON. This idiom appears about
eight times in this file for the same reason: the input is client JSON, and
`None.get` is a 500.

```python
        logger.info("Compiled %d steps across %d waves", len(steps), len({s.depth for s in steps}))
        return FlowPlan(steps=steps, seed_artifacts=seeds)
```
`plan.py:138-139`. One log line per compile, and the plan.

### `_classify`

```python
    def _classify(self, by_id: Dict[str, Dict[str, Any]]) -> tuple[Dict[str, str], Dict[str, str]]:
        generators: Dict[str, str] = {}
        seeds: Dict[str, str] = {}

        for node_id, node in by_id.items():
            if self._is_generator(node):
```
`plan.py:141-146`.

**The order of these two branches is load-bearing.** Generator is checked first.
Look at the frontend: `store/useCanvasStore.ts:516-536` attaches
`data.artifact = <the produced artifact>` to a generator node once it has run, so
the node can render a preview. That means after one run, a generator node carries
*both* `type: "generator"` and `data.artifact.id` — which satisfies `_is_source`
as well. If sources were checked first, pressing Run a second time would classify
every completed generator as a seed and the flow would do nothing at all.
Checking generator first means pressing Run again re-generates, which is what the
button says it does.

```python
                target = self._target_type(node)
                if not target:
                    label = (node.get("data") or {}).get("label") or node_id
                    raise FlowValidationError(
                        f"Generator '{label}' has no output type. "
                        f"Choose one of: {', '.join(sorted(GENERATED_TYPES))}."
                    )
                generators[node_id] = target
```
`plan.py:147-154`.

A generator with no resolvable output type is rejected *here*, at compile time,
rather than being dispatched and failing in the handler ten seconds later with a
worse message. The error lists every valid type, and `sorted(...)` makes that list
stable — a frozenset iterates in arbitrary order and a test asserting on the
message would be flaky otherwise. `label or node_id` is the "always name the
node" rule: prefer the human label, fall back to the id.

```python
            elif self._is_source(node):
                artifact_id = self._artifact_id(node)
                if artifact_id:
                    seeds[node_id] = artifact_id
```
`plan.py:155-158`.

A source node with no artifact id is *silently* not added to `seeds`. That looks
like a swallowed error but it is the right behaviour: an empty artifact node is
what you get the instant you drag one onto the canvas, before you have bound it
to anything. Failing here would mean you cannot have a half-built canvas. Instead
the node just is not `runnable`, and if a generator depends on it, `_require_inputs`
produces the much better message "Generator 'quiz' has no input. Connect a source
or another generator to it before running."

### `_adjacency`

```python
    @staticmethod
    def _adjacency(...) -> tuple[Dict[str, List[str]], Dict[str, List[str]]]:
        incoming: Dict[str, List[str]] = {node_id: [] for node_id in by_id}
        outgoing: Dict[str, List[str]] = {node_id: [] for node_id in by_id}
```
`plan.py:162-168`. Pre-seed both maps with every known node id so later code can
index without `KeyError` and without `defaultdict` magic.

```python
        for edge in edges or []:
            source, target = str(edge.get("source")), str(edge.get("target"))
```
`plan.py:170-171`. `edges or []` handles `edges=None`. `str()` for the same
normalisation reason as `by_id`.

```python
            if source not in by_id or target not in by_id:
                continue
```
`plan.py:172-173`.

**Dangling edges are dropped, not rejected.** This is a real-world fix, not
defensive padding. React Flow's own delete handling has historically left edges
behind when a node is removed, and a stale `canvas_state` saved before a node was
deleted will contain edges pointing at ghosts. Rejecting them would make a canvas
that *looks* completely fine unrunnable, with an error naming a node the user
cannot see. Pinned by `test_dangling_edges_from_deleted_nodes_are_ignored`
(`test_flow_engine.py:86`).

```python
            if source == target:
                raise FlowValidationError(f"Node '{target}' is connected to itself.")
```
`plan.py:174-175`.

A self-loop *is* rejected, because unlike a dangling edge it is visible on the
canvas and it is unambiguously wrong. It is caught here rather than left to Kahn
because Kahn would report it as a generic cycle, and "this node is connected to
itself" is a far better message. Pinned by `test_self_loop_is_rejected`
(`test_flow_engine.py:109`).

```python
            if source in incoming[target]:
                continue
            incoming[target].append(source)
            outgoing[source].append(target)
```
`plan.py:176-179`.

Duplicate-edge suppression. Two edges between the same pair happens easily —
drag from a handle, release, drag again. Without this, `parents` would list the
same node twice, and more importantly `indegree` in Kahn's algorithm would count
2 while only one decrement ever arrives, so the child would never reach zero and
would be reported as part of a cycle. A duplicated edge would have looked like a
cycle. Pinned by `test_duplicate_edges_do_not_duplicate_parents`
(`test_flow_engine.py:79`).

Checking only `incoming` is sufficient because both lists are always appended to
together, so they can never disagree.

### `_require_inputs`

```python
    @staticmethod
    def _require_inputs(generators, incoming, runnable, by_id) -> None:
        for node_id, target in generators.items():
            if not any(parent in runnable for parent in incoming[node_id]):
                label = (by_id[node_id].get("data") or {}).get("label") or target
                raise FlowValidationError(
                    f"Generator '{label}' has no input. Connect a source or another "
                    "generator to it before running."
                )
```
`plan.py:183-196`.

Every generator must have at least one *runnable* parent. Note `any`, not `all` —
a generator needs one input to be meaningful, not every input.

Why this check exists: a generator with no input would sail through Kahn as an
indegree-zero root, be scheduled immediately in wave one, and then `_schedule`
would find `sources == []` and mark it failed at `engine.py:142-157`. The run
would reach a terminal state, but only after creating a `flow_runs` row, only
after publishing events, and with a message ("This node's inputs produced no
artifacts") that describes a symptom rather than the mistake. Catching it in the
compiler means the whole request is refused with a message that tells you what to
do. Pinned by `test_generator_without_input_is_rejected` (`test_flow_engine.py:116`).

Note also the fallback label here is `target` (the artifact type) rather than
`node_id`, because for a freshly dragged node "quiz" reads better than a UUID.

### `_topological_order` — Kahn's algorithm

This is the algorithm. `plan.py:198-232`.

```python
        indegree = {
            node_id: len([p for p in incoming[node_id] if p in runnable])
            for node_id in runnable
        }
```
`plan.py:205-208`.

Kahn's algorithm is: repeatedly take a node with no unsatisfied dependencies,
emit it, and remove it from the graph. `indegree` is the bookkeeping — for each
node, how many dependencies remain unsatisfied.

The `if p in runnable` filter is the same idea as everywhere else: an edge from a
decorative node must not count toward the indegree, or that node would never be
"emitted", the decrement would never arrive, and the child would be stuck at a
non-zero indegree forever — reported at the end as a cycle. Restricting the whole
algorithm to the `runnable` subgraph is what keeps that from happening.

```python
        depth = {node_id: 0 for node_id in runnable}
```
`plan.py:209`. Every node starts at depth 0 and is pushed down as parents are
processed.

```python
        queue = [node_id for node_id, count in indegree.items() if count == 0]
        order: List[str] = []
```
`plan.py:210-211`.

Seed the queue with every node that depends on nothing. In practice these are the
seed artifact nodes, since `_require_inputs` has already guaranteed no generator
is a root. If this list is empty on a non-empty graph, every node is in or behind
a cycle, and the loop below does nothing — which the length check catches.

```python
        while queue:
            node_id = queue.pop(0)
            order.append(node_id)
```
`plan.py:213-215`.

Take from the front, emit. `pop(0)` on a list is O(n) — with `MAX_NODES = 100`
that is at most 10,000 pointer moves in the worst case, which is nothing. A
`collections.deque` would be the textbook choice; at this bound it does not
matter.

Because we pop from the front and append to the back, this is breadth-first, so
`order` comes out roughly wave by wave. That is a convenience, not something
anything depends on.

```python
            for child in outgoing.get(node_id, []):
                if child not in runnable:
                    continue
```
`plan.py:216-218`. Same subgraph restriction on the way out.

```python
                depth[child] = max(depth[child], depth[node_id] + 1)
```
`plan.py:219`.

**This one line is the wave depth.** A node sits one level below its *deepest*
parent, not its first parent.

Why `max` and not just `depth[node_id] + 1`? Consider a fan-in: `g3` has parents
`g1` (depth 1) and `g2` (depth 2). If `g1` is processed second, a plain assignment
would knock `g3` back to depth 2 when it should be 3. `max` makes the order in
which parents happen to be processed irrelevant.

And why is this correct — why is `depth[node_id]` final at the moment we read it?
Because of Kahn's invariant: a node is only enqueued when its indegree reaches
zero, which happens only after every one of its runnable parents has been popped
and processed. So by the time we pop `node_id` and read `depth[node_id]`, every
update that could ever be applied to it has already been applied. Depth is the
length of the longest path from any root, computed in one pass, for free,
alongside the sort.

**Wave depth versus plain topological order — this is a likely question.** A
topological order is a *sequence*: g1, g2, g3. It tells you a legal order to run
things in, one at a time. It does not tell you that g1 and g2 are independent. The
depth tells you that: two nodes at the same depth have no path between them, so
they can run at the same time. Turning the sequence into layers is what converts
"a valid order" into "a parallel schedule". A linear chain of 8 nodes has 8 waves
and no concurrency; the verified 8-node run has 2 waves because it fans out, and
the whole second wave goes to the workers at once.

```python
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
```
`plan.py:220-222`.

Decrement, and enqueue exactly when the count hits zero. `== 0` rather than
`<= 0` — with duplicate edges suppressed in `_adjacency` and the `runnable`
filter applied symmetrically in both the indegree computation and this loop, the
counter cannot undershoot. If it ever did, the node would be silently dropped and
surface as a phantom cycle. That is precisely the failure the duplicate-edge check
at `plan.py:176` prevents.

```python
        if len(order) != len(runnable):
            stuck = sorted(runnable - set(order))
            labels = [(by_id[node_id].get("data") or {}).get("label") or node_id for node_id in stuck[:5]]
            raise FlowValidationError(
                "This flow contains a cycle: a node eventually feeds back into itself. "
                f"Involved: {', '.join(labels)}."
            )
```
`plan.py:224-230`.

**Cycle detection.** This is the whole of it, and it is the classic Kahn property:
if the algorithm terminates having emitted fewer nodes than it started with, the
leftovers are exactly the nodes whose indegree never reached zero — which is only
possible if each is waiting, directly or transitively, on something inside a
cycle. No separate cycle-finding pass is needed; the sort detects it as a
by-product of failing.

`runnable - set(order)` is that leftover set. `sorted(...)` makes the message
deterministic so it can be asserted on. `[:5]` truncates — a badly wired canvas
can have thirty nodes downstream of a cycle and listing all of them is noise.

The set is not *only* the cycle: it also contains everything downstream of the
cycle, which never got unblocked either. The message says "Involved", not "the
cycle is", which is honest.

**What the API returns for a cycle:**
- `POST /flow/run` — `flows.py:104-107` catches `FlowValidationError` and raises
  `HTTPException(status_code=422, detail=str(error))`. 422 because the request was
  well-formed JSON but semantically unprocessable. Nothing is written: no
  `flow_runs` row, no jobs.
- `POST /flow/validate` — `flows.py:71-74` catches it and returns HTTP **200**
  with `FlowPlanResponse(valid=False, error=str(error))`. Not an error status,
  because "I asked whether this is valid and you told me it isn't" is a successful
  request. The frontend calls this as you wire nodes together, so it must not
  spam the console with 4xx.

Pinned by `test_cycle_is_rejected` (`test_flow_engine.py:102`) and
`test_validate_explains_why_a_bad_graph_will_not_run` (`test_api.py:193`).

```python
        return order, depth
```
`plan.py:232`.

### The four predicates

```python
    @staticmethod
    def _is_generator(node: Dict[str, Any]) -> bool:
        data = node.get("data") or {}
        return node.get("type") in GENERATOR_NODE_TYPES or data.get("subType") in GENERATED_TYPES
```
`plan.py:234-237`. Either the React Flow node type says generator, or the node's
`data.subType` names a producible artifact. Two ways in because the frontend has
used both conventions.

```python
    @staticmethod
    def _is_source(node: Dict[str, Any]) -> bool:
        data = node.get("data") or {}
        return node.get("type") in SOURCE_NODE_TYPES or bool((data.get("artifact") or {}).get("id"))
```
`plan.py:239-242`. Either the type says source, or it is carrying a bound
artifact. The second clause is what makes an unrecognised node type still work if
it has an artifact attached.

**Worth knowing:** because `_is_generator` is tested first in `_classify`, a
*source* node that happened to carry `data.subType: "quiz"` would be misclassified
as a generator and then rejected only if it also failed `_target_type` — which it
would not. It would be silently turned into a generator. Today the frontend only
sets `subType` on generator nodes (`components/canvas/CanvasSidebar.tsx`), so this
is theoretical. But it is the kind of coupling an interviewer will find, and the
honest answer is "the classification is heuristic over untyped client JSON; a
discriminated node schema validated at the boundary would be the real fix".

```python
    @staticmethod
    def _artifact_id(node: Dict[str, Any]) -> Optional[str]:
        data = node.get("data") or {}
        artifact = data.get("artifact") or {}
        found = artifact.get("id") or data.get("artifactId")
        return str(found) if found else None
```
`plan.py:244-249`. Two supported shapes: a nested `data.artifact.id` (the full
artifact object embedded, which is what the frontend does so it can render a
preview) or a flat `data.artifactId`. `str(...)` normalises, and the `if found`
guard turns empty string into `None` rather than `"None"`.

**This function is the security surface.** Whatever it returns ends up in
`plan.seed_artifacts`, and from there into a job's `source_artifact_ids`. See
Part 5.

```python
    @staticmethod
    def _target_type(node: Dict[str, Any]) -> Optional[str]:
        data = node.get("data") or {}
        candidate = data.get("subType") or data.get("targetType") or data.get("type")
        return candidate if candidate in GENERATED_TYPES else None
```
`plan.py:251-255`. Three supported field names, tried in order, and — critically —
the result is only returned **if it is in `GENERATED_TYPES`**. That final check is
what stops a client asking the generator to produce an arbitrary string as a type.
Anything unrecognised returns `None`, which `_classify` turns into the "no output
type" rejection.

---

## Part 2 — `engine.py`, line by line

### Header and constants

```python
"""Runs a compiled canvas plan, one wave of independent steps at a time."""
```
`engine.py:1`.

```python
from backend.services.database import Database, get_database
from backend.services.events import (
    FLOW_COMPLETED, FLOW_FAILED, FLOW_NODE, FLOW_STARTED, publish,
)
from backend.services.flow.plan import FlowCompiler, FlowPlan, FlowStep
```
`engine.py:9-17`. Three dependencies: the database, the event bus, the compiler.
Nothing else. In particular the engine does not import the job runner or the
dispatcher — dispatch arrives as a callable parameter, which is what lets the
tests pass `dispatched.append` and observe every dispatch without a broker.

```python
Dispatch = Callable[[str], Any]
```
`engine.py:21`. A type alias for that callable: takes a job id, returns whatever.
In production it is `backend.services.dispatcher.enqueue`.

```python
READY_STATUSES = frozenset({"ready", "completed"})
FINISHED_STATUSES = frozenset({"completed", "failed", "skipped"})
```
`engine.py:23-24`.

Two different questions, two different sets, and the difference matters.

- `READY_STATUSES` answers "can my child run?". A seed node is `ready` (it never
  runs, it just has an artifact). A generator that succeeded is `completed`. Both
  hand an artifact downstream. `failed` and `skipped` are deliberately absent —
  a child must not run on a parent that produced nothing.
- `FINISHED_STATUSES` answers "is this step over?", used only by `_save` to decide
  whether the run as a whole has terminated. Here `failed` and `skipped` *do*
  count, because a failed step is finished even though it is not ready.

Conflating these two is exactly the bug described in Part 3: if `failed` counted
as ready, failures would cascade into garbage generations; if it did not count as
finished, the run would never terminate.

### `EventOutbox` — the newest thing in this file

```python
class EventOutbox:
    """
    Holds flow events until the transaction that produced them has committed.

    Publishing from inside an open transaction announces a node the database
    has not stored yet: if the commit fails, or anything in the block raises,
    the write rolls back but the browser keeps the green node it was already
    shown. Delivery is also a blocking network round trip on the Redis bus, and
    waiting on it while holding the write lock stalls every other writer.
    """

    def __init__(self) -> None:
        self._pending: List[Tuple[str, str, Dict[str, Any]]] = []

    def record(self, project_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """Note an event to publish once the row it describes exists."""
        self._pending.append((project_id, event_type, data))

    def flush(self) -> None:
        """Publish what was recorded, in the order it happened."""
        for project_id, event_type, data in self._pending:
            publish(project_id, event_type, data)
        self._pending.clear()
```
`engine.py:27-49`.

Twenty-three lines and there is almost nothing to it: a list, an append, and a
loop that publishes. The interesting part is entirely in why it exists, which is
Part 4's second half — read that section for the full story. The short version:
every `publish` in this file used to happen *inside* the open write transaction,
so the browser could be told a node had completed and then have the write rolled
back underneath it. The outbox holds the events until the caller's `with` block
has closed and then publishes them, which is exactly the shape `_hand_off` had
already been using for dispatch since the original concurrency fix.

Three details worth being able to point at:

- **It stores a tuple, not a built envelope.** `(project_id, event_type, data)` are
  the three arguments `publish` takes, kept exactly as the caller passed them. The
  envelope — the `type`, `project_id`, `ts` and `data` wrapper — is built inside
  `events.make_event` at publish time, so the timestamp on an event is the moment
  it went out, not the moment it was recorded. That is the right way round: the
  timestamp should describe when the client could have known.
- **`flush` iterates in insertion order.** That is what makes the change
  unobservable from outside. `flow.node` for a step running, then `flow.node` for
  it completing, then `flow.completed` — the same sequence, the same payloads, just
  later. There is a test that asserts the exact sequence,
  `test_a_finished_run_publishes_its_events_in_order` (`test_pipeline.py:552`), and
  the point of it is that it passes against the *pre-fix* code as well. A test that
  only passes after a change tells you the change happened; a test that passes
  before and after tells you nothing else changed with it.
- **It is created per call, not per engine.** `advance` and `on_job_finished` each
  build their own on their first line. Nothing is shared between calls, so two
  threads inside the engine at once cannot mix each other's events — which matters,
  because two threads inside the engine at once is precisely the scenario Part 4 is
  about.

**The one thing it does not do is guarantee delivery.** If the process dies between
the commit and the flush, those events are lost — the row is correct and the
browser never hears. That is deliberate and it is the honest thing to say when
asked: this is an outbox in shape, not a transactional outbox in the durable sense,
which would mean writing the events to a table inside the transaction and having a
separate process ship them. The recovery path here is not durability but resync:
`GET /flow/runs/{id}` (`flows.py:127-146`) re-reads the row, and the WebSocket
client can ask for a fresh snapshot at any time. The event stream is an
optimisation over polling, and the row is the truth.

### `FlowEngine.__init__`

```python
class FlowEngine:
    """
    Schedules the steps of a flow as their inputs become available.

    The engine keeps nothing in memory between calls: the job that unblocks a
    step may finish in a different process from the one that started the run, so
    all progress lives in the `flow_runs` row.
    """
```
`engine.py:52-59`.

Read that docstring twice — it is the whole architecture. With Celery, the API
process that handled `/flow/run` and the worker process that finishes a job are
different operating-system processes. An in-memory scheduler would simply not
work. Every scheduling decision is therefore re-derived from the `flow_runs` row
on every call. That is also why the concurrency bug in Part 4 was a *database*
race rather than a Python one, and why the fix is a database transaction.

```python
    def __init__(
        self,
        database: Optional[Database] = None,
        compiler: Optional[FlowCompiler] = None,
    ) -> None:
        self._database = database or get_database()
        self._compiler = compiler or FlowCompiler()
```
`engine.py:61-67`. Constructor injection with sensible defaults. Every test passes
a `database` fixture pointing at a temporary file. `get_database()` returns the
process-wide singleton.

### `start`

```python
    def start(
        self,
        project_id: str,
        nodes: List[Dict[str, Any]],
        edges: List[Dict[str, Any]],
        *,
        dispatch: Optional[Dispatch] = None,
    ) -> Dict[str, Any]:
        """Compile the graph, record the run, and dispatch its first wave."""
        plan = self._compiler.compile(nodes, edges)
```
`engine.py:69-78`.

`dispatch` is keyword-only (the bare `*`). A positional boolean-ish callable in a
five-argument signature is exactly the kind of thing that gets passed in the
wrong slot; forcing the keyword removes the possibility.

Note `start` compiles again even though `/flow/run` already compiled the same
graph at `flows.py:105` in order to validate the seeds. That is a duplicated
compile — cheap (pure CPU over at most 100 nodes, no I/O) and it keeps `start`
usable on its own, which is how every test in `TestScheduling` calls it.

```python
        states: Dict[str, Dict[str, Any]] = {
            step.node_id: {"status": "pending", "target_type": step.target_type}
            for step in plan.steps
        }
        for node_id, artifact_id in plan.seed_artifacts.items():
            states[node_id] = {"status": "ready", "artifact_id": artifact_id}
```
`engine.py:80-85`.

The initial state map. Generators start `pending`. Seeds are inserted as `ready`
with their artifact id already present — this is the trick that makes seeds and
completed generators indistinguishable to the readiness check. `_inputs_ready`
does not care whether a parent is a source node or a generator that just
finished; it only asks whether its status is in `READY_STATUSES` and reads its
`artifact_id`. One code path, both cases.

`target_type` is stored redundantly on each state (it is already in the plan)
because the frontend renders directly from `node_states` and would otherwise have
to cross-reference the plan.

```python
        run = self._database.insert("flow_runs", {
            "project_id": str(project_id),
            "status": "running",
            "plan": plan.to_dict(),
            "node_states": states,
            "result": {},
        })[0]
```
`engine.py:87-93`.

One row. `plan`, `node_states` and `result` are all declared as JSON columns in
`JSON_COLUMNS` (`database.py:23-29`), so `Database._encode` serialises them on the
way in and `_decode` parses them on the way out — you hand it dicts and get dicts
back. Status starts `running`, not `pending`: the run genuinely is under way the
moment the row exists.

`[0]` because `Database.insert` re-selects and returns a list.

```python
        publish(project_id, FLOW_STARTED, {
            "flow_run_id": run["id"],
            "steps": len(plan.steps),
            "waves": len(plan.waves),
        })
        logger.info("Flow run %s started with %d steps", run["id"], len(plan.steps))
```
`engine.py:95-100`. The WebSocket event that tells the canvas a run has begun and
how big it is, so the UI can draw a progress bar with a correct denominator
before any node has moved.

**This is the one `publish` in the file that is still a direct call**, and if you
have just explained the `EventOutbox` you should expect to be asked why. The
answer is that there is no open transaction here to be inside. `Database.insert`
on line 87 opened one, wrote the row, and committed before it returned. By the
time line 95 runs, the `flow_runs` row this event describes is already durable —
which is the exact property the outbox exists to provide. Routing it through an
outbox would be ceremony with no protection attached. Every other `publish` in
this file was inside a `with self._database.transaction():` block, and every one
of those now goes through the outbox.

```python
        self.advance(run["id"], dispatch=dispatch)
        return self.get(run["id"]) or run
```
`engine.py:102-103`.

Kick off wave one, then re-read the row so the caller sees the post-dispatch
state — `run` as captured at line 87 still says every step is `pending`, and the
route serialises whatever is returned straight into the 202 response. Without the
re-read the UI would show a freshly started run with nothing running.
`or run` is a fallback for the impossible case of the row disappearing between
the two statements.

**Worth knowing:** the insert at line 87 commits in its own transaction, and
`advance` opens a separate one at line 118. If `advance` raised in between you
would be left with a `flow_runs` row stuck at `running` with everything `pending`
and no jobs — and nothing reaps stale flow runs (the reaper in
`job_runner.py:304-314` only handles the `jobs` table). It is a small hole and
worth naming yourself rather than being caught by it.

### `advance` — the transaction boundary

```python
    def advance(self, flow_run_id: str, *, dispatch: Optional[Dispatch] = None) -> Dict[str, Any]:
        """
        Dispatch every step whose inputs are now satisfied.

        Idempotent: reading a step's state, creating its job row and marking it
        running happen inside one transaction, so a repeated or concurrent
        completion notification cannot start the same step twice.

        Events, dispatch and the row handed back to the caller all wait for the
        commit, so nobody is told about progress the database rolled back.
        """
        outbox = EventOutbox()

        with self._database.transaction():
            queued = self._schedule(flow_run_id, outbox)

        outbox.flush()
        self._hand_off(queued, dispatch)
        return self.get(flow_run_id) or {}
```
`engine.py:105-123`. Nineteen lines, and the most important nineteen lines in the
repository.

- **`engine.py:116`** — a fresh outbox for this call.
- **`engine.py:118`** — the transaction opens.
- **`engine.py:119`** — `_schedule` does all the reading, all the job inserts and
  the write-back inside it, and records its events in the outbox rather than
  publishing them.
- **End of line 119** — the `with` block exits and the transaction commits.
- **`engine.py:121`** — the events go out, now that the rows they describe exist.
- **`engine.py:122`** — dispatch, after the commit.
- **`engine.py:123`** — *then* read the row to hand back to the caller.

The last line is easy to skim past and it is a fix in its own right. It used to be
`run = self.get(flow_run_id) or {}` **inside** the `with` block, on the reasoning
that reading inside the transaction gives the caller a consistent snapshot. It does
— but consistent with a transaction that has not committed yet. If the commit then
failed, the HTTP caller had already been handed a dictionary describing state the
database threw away, and `/flow/run` serialises exactly that dictionary into its
202 response. Reading after the commit costs one extra `SELECT` and means the
caller is only ever shown state that is durable. The same change was made in
`on_job_finished`.

The docstring's claim of idempotence is now true, and it is true *because of* the
transaction, not in spite of it. Before, that docstring was a lie; see Part 4. The
second paragraph of the docstring is the newer fix, and it covers all three ways
this function talks to the outside world — events, dispatch, return value — in one
sentence, because they are one rule.

Note what `advance` does not do: it does not take a step, or a wave number, or
any hint about what changed. It just says "look at the row and dispatch anything
that is now runnable". That statelessness is why it is safe to call from
anywhere, at any time, as many times as you like.

### `_schedule` — the scheduling pass

```python
    def _schedule(self, flow_run_id: str, outbox: EventOutbox) -> List[str]:
        """Queue the ready steps and return their job ids. Caller holds the transaction."""
```
`engine.py:125-126`.

That docstring sentence is the contract. `_schedule` never opens a transaction
itself; both of its callers (`advance` at line 119, `on_job_finished` at line 237)
have one open. Two consequences: it can never be called safely from anywhere else,
and it returns job ids rather than dispatching them, because it has no way of
knowing when its caller's transaction will commit.

The `outbox` parameter is the same idea for events. `_schedule` cannot publish for
exactly the reason it cannot dispatch — it does not know when its caller's
transaction will commit — so it records instead and lets the caller flush. Passing
the outbox in rather than returning one keeps a single ordered list across the
whole of `on_job_finished`, which records the completion event itself *before*
calling `_schedule`; two separate lists would have to be concatenated in the right
order by hand, and getting that wrong would reorder what the browser sees.

```python
        run = self.get(flow_run_id)
        if not run or run["status"] != "running":
            return []
```
`engine.py:127-129`.

Re-read the row. This is not a wasted query even when `on_job_finished` has just
read it — `on_job_finished` wrote the completion back at line 234 before calling
`_schedule`, and this read is how `_schedule` sees it. The two functions
communicate through the database row, not through a parameter. Inside a single
transaction on a single SQLite connection, an uncommitted write is visible to a
subsequent read on that same connection, so this works.

The `status != "running"` guard is the terminal-state stop: once a run is
`completed` or `failed`, a late notification cannot resurrect it and queue more
work.

```python
        plan = FlowPlan.from_dict(run["plan"])
        states = dict(run["node_states"])
        project_id = run["project_id"]
        queued: List[str] = []
```
`engine.py:131-134`.

Rehydrate the plan from JSON. `dict(...)` copies the states so mutations below are
local until `_save` writes them; `_decode` already returns a fresh object per
read, so this is belt and braces, but it makes the intent obvious.

```python
        for step in plan.steps:
            if states.get(step.node_id, {}).get("status") != "pending":
                continue
```
`engine.py:136-138`.

Walk every step, every time. This is the "recompute from scratch" design — no
cursor, no wave index, no memory of what was done last time.

**`!= "pending"` is the guard that makes a step run at most once.** Anything
already `running`, `completed`, `failed` or `skipped` is skipped. Inside a
transaction, this is a compare-and-swap: read `pending`, write `running`, and no
other transaction can interleave between the two. Outside a transaction, this
line is exactly the check-then-act race described in Part 4.

```python
            if not self._inputs_ready(step, states):
                continue
```
`engine.py:139-140`. Not all parents finished yet. This is the fan-in wait.

```python
            sources = self._input_artifacts(step, states)
            if not sources:
                reason = "This node's inputs produced no artifacts"
                states[step.node_id] = {
                    **states.get(step.node_id, {}),
                    "status": "failed",
                    "error": reason,
                }
                self._skip_downstream(step.node_id, plan, states)
                outbox.record(project_id, FLOW_NODE, {...})
                continue
```
`engine.py:142-157`.

Every parent is finished, but none of them left an artifact id behind. This
happens when a parent job "succeeded" without producing an artifact —
`_notify_flow` passes `artifact_id=bundle.result.get("artifact_id")`
(`job_runner.py:149`), which is `None` if the handler's result did not name one.

This step cannot run, and it must not be left pending. So it is marked `failed`
with an explanation, everything below it is `skipped`, and a `flow.node` event
is recorded for the outbox to publish after the commit.
`continue` moves to the next step — one dud branch does not abort the pass, and
independent branches keep going.

The `{**states.get(...), ...}` spread preserves whatever was already on the state
(`target_type`, and any `job_id` from an earlier attempt) while overwriting
status. Merging rather than replacing means nothing the frontend renders
disappears when a status changes.

Pinned by `test_a_step_with_no_usable_input_still_reaches_a_terminal_state`
(`test_flow_engine.py:217`), whose docstring is the exact bug: "A parent that
finished without an artifact must not strand the run as running."

```python
            job = self._queue_job(project_id, flow_run_id, step, sources)
            states[step.node_id] = {
                **states.get(step.node_id, {}),
                "status": "running",
                "job_id": job["id"],
                "source_artifact_ids": sources,
            }
```
`engine.py:159-165`.

The dispatch itself. Insert the job row, then immediately mark the step `running`
with the job id and the exact sources it was given. Both happen inside the
caller's transaction, so either both land or neither does. That is the atomicity
that makes the `!= "pending"` check at line 137 meaningful.

Storing `source_artifact_ids` on the node state is not required for execution —
the job row has them too — but it makes the `flow_runs` row a complete audit
record of what fed what, which is what the canvas renders and what you would read
when debugging a bad generation.

```python
            outbox.record(project_id, FLOW_NODE, {...})
            queued.append(job["id"])
```
`engine.py:166-171`. Note the canvas that this node is running, and remember the
job id for `_hand_off`. Neither the event nor the dispatch leaves this function;
both are handed to the caller to release once the transaction has committed.

```python
        self._save(flow_run_id, project_id, plan, states, outbox)
        return queued
```
`engine.py:174-175`. One write for the whole pass, then hand the ids back. The
outbox goes down into `_save` too, because `_save` is where the run's own terminal
event — `flow.completed` or `flow.failed` — is produced, and that event is inside
the transaction like every other.

**This used to be the honest gap in this section.** The `outbox.record` calls at
lines 151 and 166 were `publish` calls, and they ran *inside* the transaction. If
the transaction rolled back, those WebSocket events had already gone out,
announcing a state that never became real. The document used to name that as a
known hole and leave it there. It is now closed, and the reasoning is in Part 4's
second half.

### `_hand_off`

```python
    @staticmethod
    def _hand_off(job_ids: List[str], dispatch: Optional[Dispatch]) -> None:
        """Tell the workers about jobs only once their rows are committed."""
        if not dispatch:
            return
        for job_id in job_ids:
            dispatch(job_id)
```
`engine.py:177-183`.

Six lines that exist entirely to be called after the `with` block. The docstring
is the reason. Both call sites — `engine.py:122` and `engine.py:240` — sit just
after the transaction closes, immediately behind the matching `outbox.flush()`.
This method was the original template: when the events problem was found, the fix
was to give events the shape `_hand_off` already had.

`if not dispatch: return` supports calling the engine with no dispatcher at all,
which several tests do (`dispatch=lambda _: None` or nothing). The job rows still
get written; nobody is told about them. In local mode the polling worker pool
would pick them up anyway — `dispatcher.enqueue` is itself a no-op in local mode
(`dispatcher.py:44-45`), because the row *is* the queue.

That last point is worth holding on to: because the row is the queue, a dispatch
that fails is a delay, not a loss. `enqueue` catches broker errors and logs
"leaving it pending" (`dispatcher.py:52-54`), and the reaper plus the next poll
will find the row.

### `on_job_finished`

```python
    def on_job_finished(
        self,
        flow_run_id: str,
        node_id: str,
        *,
        artifact_id: Optional[str] = None,
        error: Optional[str] = None,
        dispatch: Optional[Dispatch] = None,
    ) -> Dict[str, Any]:
```
`engine.py:185-193`.

The callback from the worker. `artifact_id` and `error` are mutually exclusive in
practice — `job_runner.py:149` passes the artifact on success, `job_runner.py:203`
passes the error on failure. Keyword-only again.

```python
        """
        Record a step's outcome and schedule whatever it unblocked.

        The read of `node_states`, the write back and the scheduling that
        follows share one transaction. Two parents of a fan-in step finishing at
        once would otherwise each overwrite the other's completion, and the step
        below them would wait on a parent the row no longer remembers.

        Events, dispatch and the row handed back to the caller all wait for the
        commit, so nobody is told about progress the database rolled back.
        """
```
`engine.py:194-204`. Two paragraphs, two bug reports. The first names the fix, the
scenario and the observed symptom for the concurrency race. The second is the
sequel: the same function was announcing over the WebSocket, and returning state
to its HTTP caller, from inside a transaction that had not committed. Both are
told in full in Part 4.

```python
        outbox = EventOutbox()

        with self._database.transaction():
```
`engine.py:205-207`. **The transaction opens at 207** and does not close until
after line 237. The outbox is built first, outside it, so it survives the block.

```python
            run = self.get(flow_run_id)
            if not run:
                logger.warning("Completion for unknown flow run %s", flow_run_id)
                return {}
```
`engine.py:208-211`.

A completion for a run that no longer exists — the project was deleted while a
job was in flight, and `ON DELETE CASCADE` (`database.py:81`) took the
`flow_runs` row with it. Log and return; a job that outlived its flow is not an
error worth raising. Returning from inside the `with` still exits it cleanly and
commits an empty transaction.

```python
            states = dict(run["node_states"])
            project_id = run["project_id"]

            if error:
                states[node_id] = {**states.get(node_id, {}), "status": "failed", "error": error}
                self._skip_downstream(node_id, FlowPlan.from_dict(run["plan"]), states)
            else:
                states[node_id] = {
                    **states.get(node_id, {}),
                    "status": "completed",
                    "artifact_id": artifact_id,
                }
```
`engine.py:213-224`.

Merge the outcome in. The failure branch also runs `_skip_downstream`
immediately, in the same breath — that is the failure-propagation fix and it is
covered properly in Part 3.

On success, `artifact_id` is written onto the state. That is the *only* place a
generated artifact id enters `node_states`, and it is what the child step will
read as its input on the very next pass.

```python
            outbox.record(project_id, FLOW_NODE, {
                "flow_run_id": flow_run_id,
                "node_id": node_id,
                "status": states[node_id]["status"],
                "artifact_id": artifact_id,
                "error": error,
            })
```
`engine.py:226-232`. Note the canvas of the outcome. `status` is read back out of
the state that was just written rather than recomputed, so the event and the row
cannot disagree.

This is the single most important `record` in the file, because it is the one that
turns a node green. Published from inside the transaction, as it used to be, it was
the concrete version of the whole problem: the browser draws a completed node, the
commit then fails, the row still says `running`, and the two never reconcile until
the user reloads. The payload is byte-identical to what it was; only the moment it
leaves has moved.

```python
            self._database.update(
                "flow_runs", [("id", f"eq.{flow_run_id}")], {"node_states": states}
            )
```
`engine.py:234-236`.

**Load-bearing.** This is how the completion gets to `_schedule`. `_schedule`
re-reads the row at line 127; without this write it would read the pre-completion
states and never notice that anything finished. The two functions do not share the
dict — they share the row.

The `[("id", f"eq.{flow_run_id}")]` filter shape is the PostgREST-style syntax
`Database._where` translates (`database.py:512-538`), a leftover from when this
project spoke to Supabase. It parses `eq.` and parameterises the value, so it is
not a SQL injection vector, but it is worth being able to explain that the format
is historical.

```python
            queued = self._schedule(flow_run_id, outbox)

        outbox.flush()
        self._hand_off(queued, dispatch)
        return self.get(flow_run_id) or {}
```
`engine.py:237-241`.

Schedule inside, **commit at the end of line 237**, then the three things that
talk to anyone outside the database, in order: flush the events at 239, dispatch
the jobs at 240, read the row for the caller at 241.

The read at 241 used to be `outcome = self.get(flow_run_id) or {}` on the line
above `_schedule`'s, inside the block. `on_job_finished` returns that dictionary
and `JobExecutor._notify_flow` is not its only caller — it is also what a test
asserts on, and what any future route returning flow state would serialise. Handing
back a snapshot of an uncommitted transaction means handing back state that may not
survive the next line. Reading after the commit costs one `SELECT` and removes the
question.

Note that `on_job_finished` writes `node_states` twice: once at line 234 and again
inside `_save` at line 329. That is redundant on the surface, but the first write
is the handoff to `_schedule` and the second carries `_schedule`'s own mutations
plus the terminal-status bookkeeping. Both are in the same transaction, so it is
one commit either way.

### `get` and `list_for_project`

```python
    def get(self, flow_run_id: str) -> Optional[Dict[str, Any]]:
        rows = self._database.select("flow_runs", [("id", f"eq.{flow_run_id}")])
        return rows[0] if rows else None
```
`engine.py:243-245`. Single-row read. Used everywhere, including inside
transactions, which is fine — `select` does not open one.

```python
    def list_for_project(self, project_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self._database.select(
            "flow_runs", [("project_id", f"eq.{project_id}")],
            order="created_at.desc", limit=limit,
        )
```
`engine.py:247-253`. Recent runs, newest first, capped at ten. Backs
`GET /flow/runs` and is how every test finds the id of the run it just started.
There is an index on `(project_id, created_at)` at `database.py:108`.

### `_queue_job`

```python
    def _queue_job(self, project_id, flow_run_id, step, sources) -> Dict[str, Any]:
        return self._database.insert("jobs", {
            "project_id": project_id,
            "type": "generate",
            "status": "pending",
            "payload": {
                "target_type": step.target_type,
                "source_artifact_ids": sources,
                "instructions": step.instructions,
                "flow_run_id": flow_run_id,
                "flow_node_id": step.node_id,
            },
        })[0]
```
`engine.py:255-273`.

The bridge from the flow world to the job world. The row is written `pending` —
step 1 of the job lifecycle, committed before anything is dispatched, so the row
survives a dispatch that fails.

The payload has two halves. `target_type`, `source_artifact_ids` and
`instructions` are what `GenerateHandler` needs to do the work.
`flow_run_id` and `flow_node_id` are the return address: `JobModel` exposes them
as properties reading straight out of the payload (`backend/models/jobs.py:78-84`),
and `JobExecutor._notify_flow` checks for both before calling back
(`job_runner.py:230`). A job with no flow ids is a standalone job and simply
does not notify anyone. That is how the same job pipeline serves both the canvas
and the plain "generate a quiz" button, with no branching in the handler.

### `_inputs_ready` and `_input_artifacts` — where `source_artifact_ids` come from

```python
    @staticmethod
    def _inputs_ready(step: FlowStep, states: Dict[str, Dict[str, Any]]) -> bool:
        return all(
            (states.get(parent) or {}).get("status") in READY_STATUSES
            for parent in step.parents
        )
```
`engine.py:275-280`.

**`all`. This is the fan-in wait, in one word.** Three parents means three
statuses must be in `{ready, completed}`. A step with no parents cannot exist —
`_require_inputs` guarantees it — but `all([])` is `True`, so it would be treated
as immediately runnable if one ever did.

A parent that is missing from `states` yields `None`, which is not in
`READY_STATUSES`, so the step waits rather than crashing. A parent that `failed`
or was `skipped` is likewise not ready, so the step never runs — and would sit
`pending` forever if `_skip_downstream` had not already marked it `skipped`. The
two mechanisms are complementary: `READY_STATUSES` stops the child running,
`_skip_downstream` gives it a terminal status.

Pinned by `test_fan_in_node_waits_for_every_parent` (`test_flow_engine.py:175`),
which asserts that after one parent finishes, `g3` is still `pending` — "one
parent is not enough".

```python
    @staticmethod
    def _input_artifacts(step: FlowStep, states: Dict[str, Dict[str, Any]]) -> List[str]:
        found: List[str] = []
        for parent in step.parents:
            artifact_id = (states.get(parent) or {}).get("artifact_id")
            if artifact_id and artifact_id not in found:
                found.append(artifact_id)
        return found
```
`engine.py:282-289`.

**This is where `source_artifact_ids` come from, and it is worth tracing the
whole path out loud:**

1. A seed node's artifact id is lifted off the canvas JSON by
   `FlowCompiler._artifact_id` (`plan.py:244`) into `plan.seed_artifacts`.
2. `start` writes it into `node_states[node_id]["artifact_id"]` with status
   `ready` (`engine.py:84-85`).
3. A generated artifact id arrives from the worker and is written into
   `node_states[node_id]["artifact_id"]` with status `completed`
   (`engine.py:220-224`).
4. This function walks `step.parents`, reads `artifact_id` off each, and returns
   the list.
5. `_schedule` passes that list to `_queue_job` as `source_artifact_ids`
   (`engine.py:159`, `engine.py:268`).
6. `GenerateHandler` reads it, resolves each id to a knowledge core, and if there
   is more than one, `CoreMerger.merge` combines them into a single
   `CombinedContext` before the LLM sees anything.

So fan-in "merging" is really two separate things: this function assembling the
list, and `CoreMerger` merging the content. The engine's job is only the list.

Order is preserved from `step.parents`, which comes from `incoming[node_id]`,
which is edge-insertion order — so it is stable for a given canvas but not
semantically meaningful. Duplicates are dropped by `artifact_id not in found`,
which matters when two different parents happen to have produced the same
artifact, or when the same source feeds a node through two paths.

A `None` artifact_id is skipped, which is how `sources` can come back empty at
line 143 even though every parent is "finished".

### `_skip_downstream`

```python
    @staticmethod
    def _skip_downstream(node_id: str, plan: FlowPlan, states: Dict[str, Dict[str, Any]]) -> None:
        """Mark everything below a failed node as skipped rather than leaving it pending."""
        for blocked in plan.descendants_of(node_id):
            if states.get(blocked, {}).get("status") == "pending":
                states[blocked] = {
                    **states.get(blocked, {}),
                    "status": "skipped",
                    "error": f"Upstream node {node_id} failed",
                }
```
`engine.py:291-300`. See Part 3 — this is the failure-propagation fix.

### `_save`

```python
    def _save(self, flow_run_id, project_id, plan, states, outbox) -> None:
        update: Dict[str, Any] = {"node_states": states}
        statuses = [states.get(step.node_id, {}).get("status") for step in plan.steps]
```
`engine.py:302-311`. The real signature spreads those five parameters over seven
lines with types; the compressed form is above so the shape is visible at a glance.
`outbox` is the last of them and it is there for one reason: the terminal event
below.

The write and the terminal check, together. `statuses` is built from
`plan.steps` only — **seed nodes are excluded**. That is essential: a seed sits at
status `ready`, which is not in `FINISHED_STATUSES`, so if seeds were counted the
run could never terminate. Only work that has to be done counts toward being done.

```python
        if all(status in FINISHED_STATUSES for status in statuses):
```
`engine.py:313`. Every step is `completed`, `failed` or `skipped`. `all([])` is
`True`, but a plan with no steps cannot be compiled, so that case does not arise.

```python
            tally = {
                "completed": statuses.count("completed"),
                "failed": statuses.count("failed"),
                "skipped": statuses.count("skipped"),
            }
            failed = tally["failed"] + tally["skipped"] > 0
```
`engine.py:314-319`.

**A run with any skipped step is a failed run**, not a partially successful one.
That is a judgement call and defensible either way, but the reasoning is: a
skipped step is a step the user asked for and did not get. Reporting "completed"
when three of eight nodes are grey would be misleading. The tally is kept so the
UI can say exactly what happened.

```python
            update["status"] = "failed" if failed else "completed"
            update["completed_at"] = datetime.now(timezone.utc).isoformat()
            update["result"] = tally
```
`engine.py:321-323`. `timezone.utc` explicitly — a naive `datetime.now()` would
record the server's local time and compare wrongly against every other timestamp
in the database, all of which are UTC ISO strings.

```python
            outbox.record(project_id, FLOW_FAILED if failed else FLOW_COMPLETED,
                          {"flow_run_id": flow_run_id, **tally})
            logger.info("Flow run %s finished: %s", flow_run_id, tally)
```
`engine.py:325-327`. The terminal event, carrying the tally so the client does not
need a follow-up request.

This was the worst of the in-transaction publishes and it is worth being specific
about why. Look at the order it used to run in: `record` here is line 325 and the
`UPDATE` that actually stores `status`, `completed_at` and `result` is line 329,
four lines *below* it. So `flow.completed` went out before the run was marked
completed even in its own function, let alone before the outer transaction
committed. A client that reacted to `flow.completed` by fetching
`GET /flow/runs/{id}` — which is exactly what a client should do — could read the
row back and find it still `running`. The outbox makes the order unambiguous:
the row is written at 329, the transaction commits, and only then does the event
go out.

```python
        self._database.update("flow_runs", [("id", f"eq.{flow_run_id}")], update)
```
`engine.py:329`.

One write, whether or not the run finished. If it did, `update` carries four keys;
if not, just `node_states`. Doing it as one statement rather than two branches
means there is exactly one place where flow state reaches the database from
`_schedule`, and it is inside the caller's transaction.

### `__init__.py`

```python
"""Compiles and executes the canvas graph."""

from backend.services.flow.engine import FlowEngine
from backend.services.flow.plan import (
    FlowCompiler, FlowPlan, FlowStep, FlowValidationError,
)

__all__ = ["FlowCompiler", "FlowEngine", "FlowPlan", "FlowStep", "FlowValidationError"]
```
`__init__.py:1-17`.

A facade. Callers write `from backend.services.flow import FlowEngine` and never
name `engine` or `plan`, so the internal split between the two modules can change
without touching `flows.py`, `job_runner.py` or the tests. `__all__` states the
public surface explicitly — note that `FlowValidationError` is in it, because
`flows.py` has to catch it by name to produce a 422 instead of a 500.

---

## Part 3 — Failure propagation

**What used to break:** a failed flow step left its whole subtree at `pending`.
`_save` checks whether every step is in a terminal status; a `pending` step is
not, so the condition at `engine.py:313` was never satisfied. The run stayed
`running` forever. No `flow.completed`, no `flow.failed`, no `completed_at`, and a
canvas with a spinner that never stopped. Nothing reaped it, because the reaper
only touches the `jobs` table.

And nothing was going to rescue it, because those pending steps could never be
scheduled either: `_inputs_ready` requires every parent to be in
`READY_STATUSES = {ready, completed}`, and a failed parent is in neither. The
subtree was permanently blocked *and* permanently non-terminal.

**The fix is `_skip_downstream`** (`engine.py:291-300`), called from both places
where a step can fail:

- `engine.py:217` — the step's job reported an error.
- `engine.py:150` — the step could not be dispatched because its inputs produced
  no artifacts.

```python
        for blocked in plan.descendants_of(node_id):
```
Every step transitively reachable from the failed one, via `FlowPlan.descendants_of`
(`plan.py:67-81`). Transitive, not just immediate children — a failure three
levels up has to reach the bottom.

```python
            if states.get(blocked, {}).get("status") == "pending":
```
**Only `pending` steps are touched.** This is the important condition. A
descendant that is already `running` has a real job in flight; overwriting it to
`skipped` would leave the job to finish and call `on_job_finished` for a step the
row says is skipped. A descendant that already `completed` (possible in a diamond
— it depended on a different, successful branch) must obviously keep its result.
A descendant already `skipped` by another failure needs no second visit, and the
guard also keeps the "which failure gets the blame" message stable.

```python
                states[blocked] = {
                    **states.get(blocked, {}),
                    "status": "skipped",
                    "error": f"Upstream node {node_id} failed",
                }
```
`skipped`, not `failed`, and the distinction is deliberate. These steps did not
fail — they never ran. The error message names the node that actually broke, so a
user staring at a grey node three levels down is told where to look.

Both statuses are in `FINISHED_STATUSES`, so once the propagation has run, the
`all(...)` at line 313 becomes satisfiable and the run terminates. Both count
toward `failed = tally["failed"] + tally["skipped"] > 0`, so the run terminates as
`failed`.

Pinned by two tests:

- `test_failure_skips_everything_downstream` (`test_flow_engine.py:200`) —
  `g1` fails, `g2` becomes `skipped`, run status is `failed`.
- `test_a_step_with_no_usable_input_still_reaches_a_terminal_state`
  (`test_flow_engine.py:217`) — a three-deep chain where `g1` completes with
  `artifact_id=None`. `g2` is dispatched-then-failed by the `not sources` branch,
  `g3` is skipped, run is `failed`. Its docstring: "A parent that finished without
  an artifact must not strand the run as running."

**Worth knowing:** the "blame" message names the immediate cause each propagation
started from, so in a diamond where two branches both fail, whichever failure
arrived first owns the message for the shared descendants. Harmless, but if
someone asks whether the error attribution is exact, it is not.

**Also worth knowing:** `_notify_flow` in `job_runner.py:223-242` wraps the whole
callback in `try/except` and only logs on failure. So if the flow engine itself
throws, the job is correctly recorded but the flow never learns about it and stays
`running` — the same stranded state, reached by a different route. That is the
remaining gap in this area, and it has no test.

---

## Part 4 — The concurrency bug, and the same lesson a second time

This is the headline. Read this section on its own and be able to tell it without
the code in front of you.

It is two bugs and they are the same bug. The first was found when the same run
could be advanced by two callers at once, and the fix was: put the read, the queue
and the write-back inside one transaction, and move the dispatch out to after the
commit. The second was found by going back and asking what *else* was inside that
transaction that should not have been. The answer was every `publish`, and the row
handed back to the HTTP caller. Same shape, same fix, one revision apart.

Tell them in that order. The second one is a much better answer to "did you check
whether the fix was complete?" than any amount of insisting the first one was
right.

### First half — the schedule was not atomic

#### What the code used to do

`FlowEngine.advance` carried a docstring saying it was idempotent. There was even
a test asserting it — `test_advance_is_idempotent` at `test_flow_engine.py:258`,
which still exists:

```python
        engine.advance(run_id, dispatch=dispatched.append)
        engine.advance(run_id, dispatch=dispatched.append)

        assert len(dispatched) == 1
```

That test passed. It has always passed. It proves nothing about the actual
property, because it calls `advance` **twice in a row on one thread**. Sequential
idempotence and concurrent idempotence are different properties, and the code only
had the first.

The old shape was:

1. `on_job_finished` read the whole `flow_runs` row.
2. It merged the completion into the in-memory `node_states` dict.
3. It wrote the whole blob back with an `UPDATE`.
4. It called `advance`, which re-read the row.
5. `advance` walked the plan, found steps whose status was `pending` and whose
   parents were ready, **inserted a `jobs` row for each**, and dispatched it.
6. Only at the very end did it write the mutated `node_states` back.

None of that was inside a transaction. There was therefore a long window —
spanning a job insert and a network dispatch — between "I read this step's status
as `pending`" and "I wrote its status as `running`". Classic check-then-act.

#### Why the window actually got hit

Two independent reasons, and it is worth being able to give both.

**One: FastAPI's threading model.** The flow routes in `flows.py` are declared
`def`, not `async def`. FastAPI runs synchronous route handlers on a threadpool so
they cannot block the event loop. Meanwhile the in-process `WorkerPool`
(`job_runner.py:245`) runs its workers as asyncio tasks *on* the event loop, and
each of those calls `on_job_finished` when a job finishes. So a request thread and
an event-loop task can be inside the same engine code at the same instant, on the
same SQLite file. This is not a theoretical interleaving — it is two different
execution contexts with no lock between them.

**Two: fan-in.** Two parents of the same child finishing at the same moment. Each
read the whole `node_states` blob, each merged in only *its own* completion, and
each wrote the whole blob back. The second write clobbered the first. The child's
state then said one parent was still `running`, `_inputs_ready` returned `False`
forever, and the child was stranded — along with everything below it, and the run
never reached a terminal state.

Note these are two different failure modes from the same root cause. The first
does too much work (duplicate jobs). The second does too little (a lost
completion). Read-modify-write of a whole JSON blob outside a transaction produces
both.

#### The measurement

Eight threads on a `threading.Barrier(8)`, all reporting the *same* step complete
at the same instant.

**Before: 9 dispatches and 9 job rows. After: 2 and 2.**

Nine, not eight: eight racing threads each read the child as `pending` and each
queued a job for it, plus the one legitimate dispatch of the parent step in wave
one. Two afterwards: the parent, and the child, once.

The regression test is
`TestFlowConcurrency::test_concurrent_completions_queue_the_next_step_once`. It
lives in **`backend/tests/test_pipeline.py:493-528`** — not in
`test_flow_engine.py`, which is worth knowing before you go looking for it on
screen. It fails with `9 != 2` against the old engine.

```python
        ready = threading.Barrier(8)
        failures: list[BaseException] = []

        def notify() -> None:
            ready.wait()
            try:
                engine.on_job_finished(run_id, "g1", artifact_id="notes-1", dispatch=dispatched.append)
            except BaseException as error:
                failures.append(error)

        run_threads(notify, count=8)

        assert not failures
        assert len(dispatched) == 2
        assert len(database.select("jobs", [("project_id", f"eq.{project['id']}")])) == 2
        assert engine.get(run_id)["node_states"]["g2"]["status"] == "running"
```
`test_pipeline.py:513-528`.

The `Barrier(8)` is the point. Eight real OS threads all block on `ready.wait()`
and are released simultaneously, which makes the window get hit reliably rather
than occasionally. `run_threads` (`test_pipeline.py:54-61`) starts them, joins with
a 30-second timeout, and asserts none is still alive — a deadlock shows up as a
failed assertion rather than a hung suite.

Four assertions, and each one covers a different thing that could go wrong:
`not failures` catches an exception or a `database is locked`; `dispatched == 2`
catches over-dispatch; the job-row count catches over-insertion even if dispatch
were somehow deduplicated; and the `g2` status catches the *opposite* bug — a lost
update leaving the child stranded at `pending`.

#### The fix

Two changes.

**Change one: one transaction around read, queue and write-back.**

```python
        with self._database.transaction():
            run = self.get(flow_run_id)
            ...
            self._database.update(
                "flow_runs", [("id", f"eq.{flow_run_id}")], {"node_states": states}
            )
            queued = self._schedule(flow_run_id, outbox)
```
`engine.py:207-237`. The transaction opens at **207** and closes at the end of
**237**. Everything that reads or writes flow state is inside: the read at 208,
the merge at 213-224, the write-back at 234, and the whole of `_schedule` at 237,
which is where the job inserts and the `pending` → `running` flip happen.

The same shape in `advance`:

```python
        with self._database.transaction():
            queued = self._schedule(flow_run_id, outbox)
```
`engine.py:118-119`. Opens at **118**, closes at the end of **119**.

Why this is sufficient comes down to `Database._transaction` (`database.py:153-182`):

```python
        with self._write_lock:
            connection = self._connection
            if connection.in_transaction:
                yield connection
                return

            connection.execute("BEGIN IMMEDIATE")
```

Two mechanisms, both load-bearing.

- **`self._write_lock`** is a process-wide `threading.RLock` held for the entire
  duration of the block. Within one process, the whole read-queue-write sequence
  is mutually exclusive. That is what defeats the threadpool-versus-event-loop
  overlap.
- **`BEGIN IMMEDIATE`** takes SQLite's write lock at the *start* of the
  transaction rather than lazily on first write. Between processes — Celery
  workers and the API in separate OS processes — this is what serialises them.
  A deferred transaction would take the read lock first and could hit
  `SQLITE_BUSY` on upgrade; immediate cannot.

The `in_transaction` check is the third piece. `_schedule` calls
`Database.insert` and `Database.update`, each of which opens `_transaction`
itself. SQLite rejects a nested `BEGIN`. So `_transaction` detects an already-open
transaction on this thread's connection, yields the connection without a second
`BEGIN`, and returns without committing — the outermost `with` owns the commit.
That is exactly what makes it possible to wrap a sequence of operations that were
each written to be self-transacting.

Note the lock is an `RLock`, not a `Lock`, for the same reason: the same thread
re-enters it on every nested call.

**Change two: dispatch after the commit.**

`_schedule` returns a list of job ids instead of dispatching them. Both callers
dispatch after the `with` block:

```python
        self._hand_off(queued, dispatch)
```
`engine.py:122` in `advance`, `engine.py:240` in `on_job_finished`. Both sit just
after the transaction closes.

**Why dispatching inside the transaction would be wrong — this is the question to
be crisp on.** Three reasons, in order of severity:

1. **The worker can look up a row that does not exist yet.** `enqueue` pushes the
   job id onto Redis. A Celery worker in another process can pick it up
   microseconds later and call `Database.claim_job(job_id)`, which does
   `SELECT id FROM jobs WHERE id = ? AND status = 'pending'`. If the inserting
   transaction has not committed, that row is invisible to the other process's
   connection. `claim_job` returns `None`, `run_job` logs "was not claimable;
   another worker has it" (`job_runner.py:162`) and returns. The job is silently
   dropped: the row *will* exist a moment later, but nobody is ever told about it
   again. The node hangs.

2. **The transaction can roll back.** If anything after the dispatch raises — a
   later insert, the `_save` write — the whole transaction rolls back and the job
   row ceases to exist. But the message is already on Redis and cannot be
   recalled. A worker now holds a pointer to a row that will never exist.

3. **It holds the write lock across a network call.** `enqueue` talks to Redis.
   Doing that inside `BEGIN IMMEDIATE`, while holding the process-wide `RLock`,
   means every other writer in the process — every job claim, every artifact
   commit — is blocked for the duration of a network round trip, and blocked for
   a Redis *timeout* if the broker is slow. Transactions should not contain I/O to
   other systems.

Reason 1 is the one to lead with, because it is the one that actually loses work.

The general principle, which is worth stating as a principle: **commit the fact,
then announce it.** The `jobs` row is the durable fact; the dispatch is the
announcement. This is the same rule as step 1 of the job lifecycle — the row is
written `pending` and committed *before* dispatch, so a failed dispatch is a
delay rather than a loss. `dispatcher.enqueue` says so in its own docstring: "the
row is committed first, so a broker outage delays the work rather than losing it"
(`dispatcher.py:41-43`).

### Second half — the events were still inside the transaction

The first fix moved dispatch out. It did not move `publish` out, and nobody noticed
at the time because the two look like different kinds of thing: one is queueing
work, the other is "just a UI update". They are the same kind of thing. Both are
telling something outside the database about a fact the database has not committed.

**What the code did.** In `on_job_finished` the order was:

1. Mutate `node_states` in memory with the outcome.
2. `publish(project_id, FLOW_NODE, ...)` — the browser is told the node completed.
3. `UPDATE flow_runs SET node_states = ...` — the row is written.
4. `_schedule(...)` — which itself published a `flow.node` per step it queued, and
   whose `_save` published `flow.completed` or `flow.failed` **before** its own
   `UPDATE` wrote the terminal status.
5. The outer `COMMIT`.

So every event describing the run went out before the write it described, and all
of them went out before the commit. `advance` had the identical shape through
`_schedule`.

**What that costs.** If the `COMMIT` failed, or anything in the block raised, the
whole transaction rolled back — and the browser had already been told the node
completed and the run finished. The canvas showed a green node the database said
had never run, and a completed run whose row still said `running`. Nothing
reconciles that until the user reloads, because the frontend has no reason to
re-fetch state it was just told about.

This is not a hypothetical raise, either. `Database._transaction` rolls back on
`BaseException`, so a worker shutdown cancelling the task mid-block does it. So
does a failing `COMMIT` — which is the `database.py` bug described at the end of
this section. The two compound: a commit fails on a full disk, the row is
discarded, and the user is looking at a finished flow.

**The fix: an `EventOutbox`** (`engine.py:27-49`). Events are recorded during the
transaction and published in `flush()` after it commits. `advance` and
`on_job_finished` each build one on their first line, pass it down through
`_schedule` and `_save`, and flush it as the first statement after the `with`
block — one line above the `_hand_off` that was already there for exactly the same
reason. Twenty-three lines of new code, no behaviour change, and the ordering rule
now covers everything that leaves the process.

**The second defect fixed in the same pass: the return value.** Both `advance` and
`on_job_finished` read the run row *inside* the uncommitted transaction and returned
it. `/flow/run` serialises that dictionary straight into its 202 response, so an
HTTP caller could be handed state that then rolled back — the same lie as the
events, on a different channel. Both now re-read after the commit (`engine.py:123`
and `engine.py:241`).

**Why the Redis point matters, and it is the one people miss.** `publish` is not
cheap and it is not asynchronous. `RedisEventBus.publish` (`events.py:142-146`) calls
the **synchronous** redis client, built with `socket_timeout=5` at `events.py:139`.
That is a blocking network round trip. Executing it inside the transaction meant
holding `Database._write_lock` — a process-wide `RLock` — and an open `BEGIN
IMMEDIATE` across a network call, for up to five seconds if Redis was slow to
answer. Every other writer in the process waits behind that: every `claim_job`,
every `commit_bundle`. A flow with eight nodes finishing does eight of those round
trips inside the lock. The correctness argument is the one to lead with, but this is
the one that shows you thought about what the code actually does at runtime.

#### How it is pinned

Two tests, and the second one is the interesting one.

- `test_a_rolled_back_completion_publishes_nothing` (`test_pipeline.py:530`).
  Monkeypatches `FlowEngine._schedule` to raise, calls `on_job_finished`, and
  asserts two things: nothing was published at all, and `g1` is still `running` in
  the row. Its docstring is the requirement in one line — "The browser must never
  be shown a finished node the transaction threw away." Against the pre-fix code
  the `flow.node` for `g1` completing has already gone out by the time `_schedule`
  raises, so the first assertion fails.
- `test_a_finished_run_publishes_its_events_in_order` (`test_pipeline.py:552`).
  Runs a two-step flow to completion and asserts the exact sequence of six events —
  `flow.started`, then `flow.node` running/completed for `g1`, the same pair for
  `g2`, then `flow.completed` with its tally. **This test passes against the
  pre-fix code as well, and that is the entire point of it.** It is the evidence
  that holding events back changed nothing observable: same events, same payloads,
  same order, later. If you are asked "how do you know you did not break the UI",
  this is the answer, and "I wrote a test that passes both before and after" is a
  better answer than "I checked".

Both use `record_flow_events` (`test_pipeline.py:79`), which monkeypatches the
`publish` name *in the engine module* rather than the bus, so it captures exactly
what this file emits and nothing else.

### Follow-up questions to have ready

**"Why didn't your idempotence test catch it?"** Because it tested sequential
idempotence, a different property. `advance` twice in a row on one thread genuinely
was idempotent — the first call wrote `running` before the second call read. The
window only opens when two callers interleave, which needs real threads and a
barrier to reproduce reliably. That is why the new test uses `threading.Barrier(8)`.

**"Is SQLite really the right database for this?"** No, and the honest answer is
that the transaction primitive is doing work a row-level lock would do better. The
correct shape on Postgres is `SELECT ... FOR UPDATE` on the `flow_runs` row, or —
better still — not storing the whole schedule as one JSON blob at all, but as one
row per step with a unique constraint that makes double-queueing impossible at the
schema level. The blob is what forces the coarse lock. On a single-workspace local
deployment, one process-wide write lock is genuinely enough, and it is one seam.

**"Why not just make `advance` async and use an asyncio lock?"** Because the two
contenders are not both on the event loop. One is a threadpool thread running a
sync FastAPI route, and in Celery mode one is a different process entirely. An
asyncio lock protects neither. The lock has to live at the database.

**"What about two `start` calls at once?"** They create two separate `flow_runs`
rows and both run. That is arguably correct — pressing Run twice means running
twice — and it is not what the bug was about. The bug was two callers acting on
*the same* run.

**"Why publish at all, if the row is the truth?"** Because polling eight nodes on
a timer is what this replaced, and the latency difference is visible. The right
framing is that the event stream is an optimisation and the row is the source of
truth: events may be lost — the outbox is not durable, and a process that dies
between the commit and the flush drops them — and the recovery path is
`GET /flow/runs/{id}` (`flows.py:127-146`) plus the WebSocket's `resync`. What must
never happen is not "an event is missing" but "an event is *wrong*", and that is
what the outbox guarantees.

**"Is the outbox thread-safe?"** It does not need to be. One is constructed per
call, on the stack, and never shared. Two threads inside `on_job_finished` at once
have two outboxes. The list is only ever touched by the thread that owns it.

**The related fixes in `database.py`, worth two sentences.** Rollback in
`_transaction` is on `BaseException`, not `Exception` (`database.py:180`): an
`asyncio.CancelledError` — which does not subclass `Exception` — escaping with
`BEGIN IMMEDIATE` still open left the connection in a transaction forever, and every
later write on that thread failed. Worker shutdown cancels tasks, so this was
reachable. And the `COMMIT` itself is now *inside* that `try` (`database.py:179`);
it used to sit on the line after it, so a commit that failed on a full disk or an
I/O error stranded the connection in exactly the state the `BaseException` change
had been written to prevent — the same hole, one line lower down. The failure path
is `Database._abandon` (`database.py:184-199`), which returns the connection to
autocommit best-effort. That is the third telling of the same lesson in this
codebase, which is worth noticing out loud: **whenever something leaves the
transaction — an event, a message, a return value, a connection — check what
happens if the commit does not.**

---

## Part 5 — The security hole in front of the compiler

### What was open

The canvas nodes arrive in the request body of `POST /flow/run`. The compiler read
artifact ids straight out of them — `FlowCompiler._artifact_id` at `plan.py:244`
lifts `data.artifact.id` into `plan.seed_artifacts` — and `FlowEngine.start`
wrote them into `node_states`, from which `_input_artifacts` copied them into a
generate job's `source_artifact_ids`. `GenerateHandler` then resolved those ids
with no ownership check of its own, because by design handlers do no
authorisation.

So: run a flow in a project you own, seeded with a node naming somebody else's
artifact, and the backend fetches and generates from it. **Confirmed exploitable
before the fix: a 202, with the foreign artifact id visible in the queued job.**

The direct `POST /api/jobs` route already validated `source_artifact_ids`. That
fix did not close this, because `/flow/run` reached the same handler through a
different door.

**And there was a third door.** `POST /flow/run` with an empty body falls back to
the project's stored canvas (`flows.py:28-32`), and `canvas_state` is
caller-written through `PATCH /api/projects/{id}` (`projects.py:68-85`). So you
could save a poisoned canvas and then run it with no body at all.

### What stands there now

```python
def _require_owned_seeds(
    plan: FlowPlan,
    project_id: str,
    user_id: str,
    database: Database,
) -> None:
    for node_id, artifact_id in plan.seed_artifacts.items():
        try:
            require_project_artifact(artifact_id, project_id, user_id, database)
        except HTTPException as error:
            raise HTTPException(
                status_code=error.status_code,
                detail=f"Node '{node_id}': {error.detail}",
            ) from error
```
`flows.py:35-57`.

It is called at `flows.py:76` in `validate_flow` and `flows.py:109` in `run_flow`
— **after** compiling, **before** `FlowEngine(database).start(...)` at
`flows.py:110`. That ordering matters: it means a refused run leaves no
`flow_runs` row, no job rows, and no events. Nothing is persisted before the check.

**Exactly what it checks**, via `require_project_artifact` (`deps.py:70-87`),
which is three checks in sequence:

1. `require_artifact` → `database.get_artifact(artifact_id)`. If the artifact does
   not exist: **404 "Artifact not found"**.
2. `require_project(artifact["project_id"], user_id)` — load the project the
   artifact actually lives in and check `project["user_id"] == user_id`. If not:
   **403 "Access denied"**. This is the case the exploit hit.
3. `str(artifact["project_id"]) != str(project_id)` — the artifact exists and you
   own it, but it is in a *different* project of yours: **400 "Artifact belongs to
   a different project"**. This is not a security check but a data-integrity one;
   provenance edges are filed under a single project, so an edge to a parent living
   elsewhere renders as a dangling link on the canvas.

Two design decisions in that function are worth being able to defend:

- **It checks `plan.seed_artifacts`, not the raw nodes.** The plan is the
  normalised form. Checking the nodes would mean reimplementing `_artifact_id`'s
  two accepted shapes in a second place, and any future third shape would be a
  new hole. Checking the plan means the check is applied to exactly the ids that
  will be used.
- **The whole request fails; the offending node is not dropped.** The docstring
  says why: "a flow that quietly ran without one of its inputs is worse than one
  that refused". Dropping the node would produce a quiz generated from two of
  three lectures with no indication anything was missing.

The re-raise preserves the original status code and prefixes the node id, so the
canvas can point at the exact node — the same "always name the node" rule the
compiler follows. The test asserts on it: `assert "s1" in response.json()["detail"]`.

Note the ids the check does *not* cover: a **generator** node carrying
`data.artifact.id` (which the frontend attaches after a run) is classified as a
generator, not a source, so it never enters `seed_artifacts`. It is not checked —
and it does not need to be, because that id is never read as an input. The
generator's inputs come from its parents' states.

**Three tests, one per door** (`test_api.py`, class `TestSecurity`):

- `test_a_flow_seeded_with_another_users_artifact_is_refused` (line 337) — the
  request-body door. Asserts 403, the node id in the detail, **and** that no job
  rows and no `flow_runs` rows were created.
- `test_a_saved_canvas_cannot_smuggle_a_foreign_seed_into_a_run` (line 357) — the
  stored-canvas door. Writes the poisoned canvas directly, then POSTs an empty
  body. Asserts 403.
- `test_validating_a_foreign_seed_is_refused_the_same_way` (line 369) — the
  validate door. Its docstring: "Validate compiles the same graph, so it must not
  report the flow as runnable." Without this, `/flow/validate` would confirm that
  a canvas seeded with a stolen artifact is valid — an oracle telling an attacker
  their id exists. Note this endpoint returns 403 and not `valid: false`: a
  compile failure is the user's graph being wrong, an ownership failure is a
  refusal, and they are different things.

### The honest limitation

`PATCH /api/projects/{id}` still stores `canvas_state` without validating the
artifact ids inside it.

```python
    changes = request.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status_code=400, detail="No fields to update")

    rows = database.update("projects", [("id", f"eq.{project_id}")], changes)
```
`projects.py:78-82`. `ProjectUpdate.canvas_state` is typed
`Optional[Dict[str, Any]]` (`schemas.py:22`) — arbitrary JSON, unvalidated.

So you can *save* a canvas containing a foreign artifact id and get a 200. The
run is still refused, because `_require_owned_seeds` sits in front of the
compiler on both `/flow/run` and `/flow/validate`, and it re-derives the seeds
from whatever graph is actually about to be compiled — request body or stored
canvas, it makes no difference. But the refusal happens at **run time as a 403**,
not at save time as a 400.

**Why this is a real limitation and not a hole:** nothing between saving and
running reads those ids. The canvas is inert JSON on the project row until a
compile turns it into a plan, and the plan is checked. The consequence is a
usability one — you find out your canvas is unrunnable when you press Run rather
than when you save — plus a small storage-of-untrusted-data concern: another
user's artifact id is sitting in your project row. It is an id, not content.

**Why it was left:** validating on save means either parsing the canvas on every
autosave keystroke, which is expensive and debounced anyway, or duplicating the
seed-extraction logic outside the compiler, which creates exactly the second
implementation that `_require_owned_seeds` was written to avoid. The defensible
answer is that the check belongs at the point of use, and the point of use is
compilation. Saying that yourself is much better than being asked.

---

## Quick reference — line numbers to jump to

| What | Where |
|---|---|
| Kahn's algorithm | `plan.py:198-232` |
| Wave depth, the one line | `plan.py:219` |
| Cycle detection | `plan.py:224-230` |
| Duplicate-edge suppression | `plan.py:176-179` |
| Where seed artifact ids are read off the canvas | `plan.py:244-249` |
| Generator-before-source classification order | `plan.py:146` |
| `EventOutbox` | `engine.py:27-49` |
| `advance` transaction opens / closes | `engine.py:118` / end of `engine.py:119` |
| `on_job_finished` transaction opens / closes | `engine.py:207` / end of `engine.py:237` |
| Events flushed, after the commit | `engine.py:121` and `engine.py:239` |
| Dispatch, after the commit | `engine.py:122` and `engine.py:240` |
| Run row re-read for the caller, after the commit | `engine.py:123` and `engine.py:241` |
| The only direct `publish` left, and why it is safe | `engine.py:95-100` |
| The `!= "pending"` compare-and-swap | `engine.py:137` |
| Job row insert | `engine.py:159`, `engine.py:262` |
| Fan-in wait (`all`) | `engine.py:277-280` |
| Fan-in artifact assembly | `engine.py:282-289` |
| Failure propagation | `engine.py:291-300`, called at `150` and `217` |
| Terminal-state detection | `engine.py:313-327` |
| Nested-transaction join | `database.py:170-182` |
| `COMMIT` inside the `try`, and `_abandon` | `database.py:179`, `database.py:184-199` |
| Seed ownership check | `flows.py:35-57`, called at `76` and `109` |
| The unvalidated PATCH | `projects.py:68-85` |
| Concurrency regression test | `test_pipeline.py:493-528` |
| Rolled-back completion publishes nothing | `test_pipeline.py:530-550` |
| Event order unchanged by the outbox | `test_pipeline.py:552-578` |
