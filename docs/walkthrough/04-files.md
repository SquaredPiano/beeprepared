# 04 — The file store and the download route

`backend/services/files.py` and `backend/api/routes/files.py` are the two halves of one idea. The service half owns a directory on disk and decides what a key is allowed to mean; the route half serves bytes out of that directory to anybody holding a link the service signed. Everything in BeePrepared that produces a file goes through here: the lecture recording or PDF you upload, the audio yt-dlp pulls off a YouTube link, and the rendered exports the generators produce (an exam PDF, a slides `.pptx`, a notes `.md`). None of those are served by a static file mount and none of them sit behind a bearer token. They are served by one endpoint that takes a key, an expiry and an HMAC signature, and refuses everything else.

That design exists for a specific reason. These URLs end up in places that cannot send an `Authorization` header: an `<img>` tag, an `<iframe>` previewing a PDF, the browser's own download manager when you click a link. So the credential has to live in the URL itself. Once the credential is in the URL, it will be logged, pasted into Slack, and left in browser history, so it has to expire. That is the whole shape of this package: a signature that is the credential, and an expiry that limits how long a leaked credential is worth anything.

This used to be Cloudflare R2, and R2's presigned URLs did exactly this. When R2 came out, the presigned-URL contract had to be rebuilt locally, and this file is that rebuild. It is worth saying that plainly in the interview: the interface was kept and the backend swapped, which is why the rest of the codebase only ever asks for "a key" and "a signed URL" and never knows whether the bytes are local or remote.

---

## backend/services/files.py

### The header and the imports, lines 1 to 18

```python
"""Content-addressed file storage with expiring, signed download links."""
```

Line 1. **Worth knowing:** this docstring is wrong in one word, and it is the first line an interviewer's eye lands on. "Content-addressed" has a specific meaning — the key is derived from a hash of the bytes, so identical content always lands at the same key and deduplication is free. That is not what happens here. Every caller chooses its own key, and the keys are built from UUIDs and artifact IDs, not from content hashes. The store is *key*-addressed. If someone asks "so is it content-addressed?", the honest answer is no, the docstring overstates it: keys are opaque and caller-assigned, and the same file uploaded twice is stored twice. Do not defend the word.

```python
from __future__ import annotations
```

Line 3. Makes annotations lazy strings rather than evaluated objects. It is at the top of nearly every module in this backend; it is house style, not a decision specific to this file.

Lines 5 to 14 are the imports and they are almost a summary of the file. `hashlib` and `hmac` are the signing. `logging` is logging. `mimetypes` guesses a content type from a filename extension. `shutil` does the file copying. `threading` exists solely for the lock guarding the module-level singleton at the bottom. `time` gives the epoch seconds the expiry is built from. `Path` from `pathlib` does all the path arithmetic, including the containment check. `Optional` is typing. `quote` from `urllib.parse` percent-encodes the key and the filename when they go into a URL.

```python
from backend.core.config import get_settings
```

Line 16. The store gets its root directory and its signing secret from the settings snapshot rather than reading environment variables itself. `get_settings()` is `lru_cache`d in `backend/core/config.py:77`, so the whole process resolves configuration once.

Line 18 is the module logger. Boring.

### StorageError, lines 21 and 22

```python
class StorageError(RuntimeError):
    """A file could not be written, read, or addressed."""
```

One exception type for the whole module. The value of having it is at the route boundary: `backend/api/routes/files.py:37` catches `StorageError` specifically and turns it into a 404, and `backend/api/routes/artifacts.py:114` does the same on the download path. If the store raised bare `OSError` or `ValueError`, those handlers would either have to catch something far too broad or let a raw filesystem error escape as a 500. Note the word "addressed" in the docstring — this type covers both "the bytes are not there" and "that key is not allowed", which are different failures wearing one name.

### The class and its docstring, lines 25 to 31

```python
    Download links are HMAC-signed over the key and expiry together, so a link
    cannot be extended or repointed by editing the query string.
```

Lines 29 and 30. This is the sentence to have memorised. "Together" is the load-bearing word, and the two failure modes it names — *extended* and *repointed* — are exactly the two things an attacker would try with a URL in their address bar. Extended means changing `expires=` to a date next year. Repointed means changing the key in the path to somebody else's file. Both are defeated by the same fact: the signature covers both fields, so touching either invalidates it, and you cannot recompute the signature without the secret.

### Opening the store, lines 33 to 39

```python
    def __init__(self, root: Optional[Path] = None, secret: Optional[str] = None) -> None:
        settings = get_settings()
```

Lines 33 and 34. Both constructor arguments are optional and both fall back to settings. That is not decoration — it is what lets the tests build a throwaway store with `FileStore(tmp_path / "files", "secret")` (`backend/tests/test_seams.py:306`) and, in one test, build *two* stores with different secrets to prove that a signature from one is refused by the other (`backend/tests/test_seams.py:321`). You cannot write that test against a store that only reads global config.

```python
        self.root = Path(root or settings.data_dir / "files").expanduser().resolve()
```

Line 35. Three things happen here and the third one matters more than it looks. `root or settings.data_dir / "files"` picks the override or the default, which is `backend/.storage/files` unless `BEE_DATA_DIR` says otherwise (`backend/core/config.py:49` and `:82`). `.expanduser()` turns a leading `~` into a real home directory, because the data directory is configurable by environment variable and people write `~/beeprepared-data`. `.resolve()` makes the path absolute and collapses symlinks — and *that* is what makes the containment check at line 82 sound. The check compares a fully resolved candidate against `self.root`. If `self.root` were left unresolved while the candidate was resolved, the two sides would be in different namespaces: on a Mac where `/tmp` is a symlink to `/private/tmp`, every single key would resolve to something not "relative to" the root and every operation would fail. Resolving both sides is the only way the comparison means anything.

```python
        self.root.mkdir(parents=True, exist_ok=True)
```

Line 36. Create the directory tree if it is not there. `exist_ok=True` makes it idempotent, which matters because the store is constructed on API startup, and again in each Celery worker process, all pointing at the same directory.

```python
        self._secret = (secret or settings.signing_secret).encode()
```

Line 37. The secret, encoded to bytes once at construction because `hmac.new` wants bytes and this saves re-encoding on every signature. The underscore prefix is the usual "do not touch this from outside" convention.

**Worth knowing:** the default in `backend/core/config.py:50` is the literal string `"beeprepared-dev-secret"`, and nothing in the codebase refuses to start when that default is still in place. Anybody who has seen the repository can forge a valid signature for any key against a deployment that never set `SIGNING_SECRET`. That is fine for a local dev default and it is a real gap for a deployment. If asked "what would you fix first", this is a good, honest answer: fail startup when the signing secret is the default and the app is not in dev mode.

Line 39 logs where the store landed. It is genuinely useful — the most common confusion with a local file store is two processes disagreeing about the root — and the same value is surfaced at `/health` (`backend/main.py:151`) so you can check it without reading logs.

### Writing into the store: put and put_bytes, lines 41 to 54

```python
    def put(self, source_path: str, key: str) -> str:
        """Copy a file into the store under `key` and return that key."""
        target = self.resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
```

Lines 41 to 45. Every write goes through `self.resolve(key)` first. That is the single choke point: there is no path in this class that touches the disk without asking `resolve` whether the key is allowed. `mkdir(parents=True)` creates the per-project subdirectories on demand, so nothing has to pre-create `{project_id}/sources/` before the first upload.

`shutil.copyfile` rather than `open().write()` is worth a sentence. It copies in chunks internally, so a 200 MB lecture recording never exists as a 200 MB Python object; on macOS it can go further and ask the filesystem to clone the file. It is a *copy*, not a move, which is deliberate — the source is the API's staged temp file, and the ingest handler is responsible for deleting that later (see the section on temp files below). Moving it here would pull the rug out from under the caller.

```python
        logger.info("Stored %s (%d bytes)", key, target.stat().st_size)
        return key
```

Lines 46 and 47. A `stat` call purely for the log line. Returning the key rather than nothing lets callers write `return StoredSource(key=self._store.put(...))`-style code, though in practice they build the key first and use it directly.

```python
    def put_bytes(self, data: bytes, key: str) -> str:
```

Lines 49 to 54. The in-memory sibling, used when the content was generated rather than uploaded — the markdown exporter at `backend/services/exports/__init__.py:117` encodes a string to UTF-8 and hands it straight over. It is safe to hold these in memory because they are model output, measured in kilobytes, not uploads. Note it does not log, unlike `put`. Harmless asymmetry, but if an interviewer notices it, that is the answer: `put` is the large-file path worth tracing, `put_bytes` is the small one.

### Reading back out: copy_to, lines 56 to 63

```python
    def copy_to(self, key: str, destination: str) -> str:
        """Copy a stored object out to a local path."""
        source = self.resolve(key)
        if not source.exists():
            raise StorageError(f"Object not found: {key}")
```

Lines 56 to 60. This is the operation that only makes sense because the store used to be remote. When files lived in R2, code that wanted to run a PDF parser or Whisper over a stored object had to download it to local disk first. `copy_to` is that download, and the local implementation kept the signature so nothing upstream had to change.

It has exactly one caller, `backend/pipeline/extraction.py:173`, inside `extract_stored`, which makes a `TemporaryDirectory`, copies the object into it, extracts text, and lets the context manager delete the copy on the way out. Note that the caller wraps it in `asyncio.to_thread` — `copy_to` is blocking I/O and the local worker pool shares an event loop with the API, so copying a large recording on the loop thread would stall every in-flight HTTP request.

The `exists` check before copying is there so the failure is a `StorageError` with the key in the message rather than a raw `FileNotFoundError` pointing at some path inside `.storage`. Lines 61 to 63 create the destination's parent directory and do the copy.

### delete, exists, size_of, lines 65 to 73

```python
    def delete(self, key: str) -> None:
        """Remove a stored object. A missing object is not an error."""
        self.resolve(key).unlink(missing_ok=True)
```

Lines 65 to 67. `missing_ok=True` makes deletion idempotent, which is the right default for anything a retry might run twice.

**Worth knowing:** `delete` and `exists` have no callers anywhere in the backend, including the tests. Nothing in BeePrepared ever removes a file from the store. Deleting a project (`backend/api/routes/projects.py:87`) removes the database rows and lets artifacts, edges and jobs cascade, but the bytes under `{project_id}/` stay on disk forever. That is a known gap, not a subtle one, and it is better to name it than to be caught by it. The honest framing is that the store has no garbage collection, only the primitives one would be built from.

`exists` at 69 and `size_of` at 73 are one-liners over `resolve`. `size_of` is used right after every write, by ingestion (`backend/pipeline/ingestion.py:50`) and the exporter (`backend/services/exports/__init__.py:129`), to record the byte count in metadata. Note that `size_of` will raise a bare `FileNotFoundError` from `stat()` on a missing key rather than a `StorageError` — it does not go through `open_path`. It is only ever called immediately after a successful write, so it has never mattered.

### resolve — the method that keeps the store a store, lines 75 to 84

```python
    def resolve(self, key: str) -> Path:
        """Map a key to a path, refusing anything that escapes the store root."""
        cleaned = key.strip().lstrip("/")
        if not cleaned:
            raise StorageError("Empty storage key")
```

Lines 75 to 79. Every other method in this class is built on this one, so this is where a path traversal would have to be caught. `strip()` removes surrounding whitespace, which matters because keys arrive from the URL path and from JSON in the database, and either can carry a stray newline. `lstrip("/")` removes leading slashes so that `self.root / cleaned` cannot be hijacked — this is a real `pathlib` behaviour worth knowing cold: `Path("/a/b") / "/etc/passwd"` evaluates to `Path("/etc/passwd")`, because joining with an absolute path *discards the left side entirely*. Without that `lstrip`, a key of `/etc/passwd` would silently escape the store before any check ran. The empty-key check catches a key that was nothing but slashes or whitespace, which would otherwise resolve to the root directory itself.

```python
        candidate = (self.root / cleaned).resolve()
        if not candidate.is_relative_to(self.root):
            raise StorageError(f"Key escapes the storage root: {key}")
        return candidate
```

Lines 81 to 84. Join, resolve, then check containment. The order is the whole point. `.resolve()` collapses `..` segments and follows symlinks, so `../../etc/passwd` becomes a real absolute path outside the root, and a symlink planted inside the store pointing at `/etc` resolves to `/etc`. Only *after* that flattening is the containment tested, so both tricks are caught by the same line. Checking for the substring `..` in the key instead — the naive version of this — would miss the symlink case entirely and would also reject legitimate keys that merely contained two dots.

`is_relative_to` is a `pathlib` method from Python 3.9; this backend runs 3.10, so it is available. The alternative would be `os.path.commonpath` or comparing string prefixes, and string prefixes are the classic bug: `/data/files-evil` starts with `/data/files` as a string but is not inside it. `is_relative_to` compares path components, so it does not have that flaw.

Two tests pin this: `backend/tests/test_seams.py:329` asserts `resolve("../../etc/passwd")` raises, and `backend/tests/test_api.py:515` asserts the same through `put_bytes`, which proves the guard is on the shared path rather than bolted onto one method.

### open_path, lines 86 to 91

```python
    def open_path(self, key: str) -> Path:
        """The path of a stored object, raising if it is not there."""
        path = self.resolve(key)
        if not path.exists():
            raise StorageError(f"Object not found: {key}")
        return path
```

Read-side counterpart to `resolve`: same safety check, plus a definite answer about existence. The route uses this so it can distinguish "you asked for something outside the store" and "you asked for something that is not there" — both `StorageError` — from "your signature is bad", which is checked before this is ever called. It returns a `Path` rather than an open handle because the caller is `FileResponse`, which wants a path and does its own streaming.

### signed_url — where a link is made, lines 93 to 108

```python
    def signed_url(
        self,
        key: str,
        *,
        filename: str,
        inline: bool = False,
        expires_in: int = 3600,
    ) -> str:
```

Lines 93 to 100. The bare `*` forces everything after `key` to be passed by name. That is a small thing with a real payoff: `signed_url(key, "notes.pdf", True, 60)` is unreadable and easy to get wrong, and this makes it a syntax error. `expires_in` defaults to 3600 seconds. An hour is a compromise — long enough that a user can open the download panel, get distracted, come back and still have a working link; short enough that a URL leaked into a chat log or a server access log is worthless by the time anyone reads it.

```python
        expiry = int(time.time()) + expires_in
```

Line 102. The expiry is computed as an absolute Unix timestamp here, at signing time, and travels in the URL. It is not a duration. That distinction matters: a duration in the URL would have to be measured from something, and whatever that something was would also need signing, so an absolute instant is simply the smaller thing to protect.

```python
        disposition = "inline" if inline else "attachment"
```

Line 103. Translates the boolean into the `Content-Disposition` value the route will echo back. `attachment` makes the browser download the file; `inline` makes it render in place, which is what the preview modal wants when it embeds a rendered PDF in an iframe (`frontend/components/canvas/modals/ArtifactPreviewModal.tsx` requests the link with `inline` and drops it into the viewer).

```python
        return (
            f"/api/files/{quote(key)}"
            f"?expires={expiry}&signature={self.sign(key, expiry)}"
            f"&disposition={disposition}&filename={quote(filename)}"
        )
```

Lines 104 to 108. Four things to notice.

First, the URL is **relative**. There is no scheme and no host. That is deliberate: the backend does not reliably know its own public origin — behind a tunnel or a reverse proxy it would guess wrong — so it returns a path and lets the client join it. The frontend does exactly that at `frontend/lib/api.ts:286`, checking whether `download_url` starts with `/` and prefixing `BACKEND_URL` if so.

Second, `quote(key)` percent-encodes the key for the path segment. Keys contain forward slashes, and `quote` leaves `/` alone by default, which is what you want here because the route captures the whole tail with a `:path` converter.

Third, the signature is computed over `key` and `expiry` — the *unencoded* key. That is consistent with verification, because FastAPI decodes the path parameter before handing it over, so both sides sign the same string. This is the sort of thing that silently breaks the day a key contains a character `quote` touches; it works today because keys are UUIDs, slashes and file extensions.

Fourth, `disposition` and `filename` are in the URL but **not** in the signature. Deliberate on the face of it — they are presentation, not authorisation — but see the note under `sign` below, because there is a consequence.

### sign — what is actually in the payload, lines 110 and 111

```python
    def sign(self, key: str, expiry: int) -> str:
        return hmac.new(self._secret, f"{key}:{expiry}".encode(), hashlib.sha256).hexdigest()
```

This is the core of the file. Unpack it slowly, because it is the most likely thing you will be asked to explain line by line.

`hmac.new(secret, message, hashlib.sha256)` computes HMAC-SHA256. HMAC is not the same as hashing the secret and the message concatenated together. It hashes twice with two derived keys, which is what makes it immune to the length-extension attack that `sha256(secret + message)` suffers from — with a naive concatenation an attacker who has one valid `(message, digest)` pair can compute a valid digest for `message + extra` without ever knowing the secret. Using the standard library's `hmac` means never having to think about that.

The message is `f"{key}:{expiry}"`. That is the entire signed payload: the storage key, a colon, the expiry timestamp. Nothing else. The output is `.hexdigest()`, 64 hex characters, because it has to survive a trip through a URL query string.

**Why the expiry is inside the payload rather than checked separately.** This is the question the prompt for this file flags, and the answer is short: an expiry that is not signed is a suggestion. The server would read `expires=` from the query string and compare it to the clock, but the query string is under the attacker's complete control. They change `expires=1753660000` to `expires=9999999999` and the check passes. The signature is what binds that number to the server's intent. Signing the pair `(key, expiry)` means the server is asserting "I authorised *this key* until *this instant*", and neither half can be moved without invalidating the assertion. Verification then has two independent parts — is the assertion authentic, and is it still current — and both must hold.

**What an attacker gains if a field leaves the signature.** Work through it field by field, because that is how the question will be asked.

Drop the *key* and sign only the expiry: every link issued in the same second becomes interchangeable. Request your own artifact's download link, then edit the path from `.../abc/exports/mine.pdf` to `.../xyz/exports/theirs.pdf` while keeping `expires` and `signature`. The signature still verifies, because it never said anything about which file. You now have read access to every file in the store, limited only by guessing keys — and keys are guessable in the sense that anyone who has ever seen a project's IDs can construct them. This is the worst of the three.

Drop the *expiry* and sign only the key: the link becomes permanent. That sounds mild until you remember why the expiry exists — these URLs go into browser history, referrer headers, proxy logs and screenshots. A leaked link that never dies is a permanent, unrevocable read capability with no way to withdraw it short of rotating the secret and breaking every link at once.

Drop *both* — which is to say, no signature at all — and `/api/files/{key}` is an unauthenticated read of the entire store.

Now the fields that genuinely are outside the signature, `filename` and `disposition`. **Worth knowing:** because they are unsigned, anyone holding a valid link can edit them freely. Changing `filename` changes only the name the browser saves the file under, which nobody cares about. Changing `disposition=attachment` to `disposition=inline` is more interesting: it asks the browser to render the file in the page rather than download it. The route constrains the value to `attachment|inline` with a regex (`backend/api/routes/files.py:22`) so nothing else can be injected, and the `Content-Type` is derived from the *key's* extension rather than from anything the caller sends (line 42), so the attacker cannot serve `notes.md` as `text/html`. The residual risk is that a file type the browser renders inline could carry script and would run on the API's origin. There is no `X-Content-Type-Options: nosniff` header on the response, which would be the standard belt-and-braces addition. Given that everything in the store today is `.md`, `.pdf` or `.pptx`, and that an attacker needs a valid signed link to their own file to try any of this, it is a defensible gap rather than an open door. Say it that way; do not claim the header is there.

**Worth knowing, on the delimiter.** The payload is joined with a colon, and in principle "key:expiry" is ambiguous — if a key contained a colon, two different `(key, expiry)` pairs could produce the same signed string, which is a classic canonicalisation bug. It is not exploitable here, because the route declares `expires: int` and FastAPI rejects anything that is not an integer with a 422 before `verify` runs, so the trailing field can never absorb part of the key. It is still a fair thing for an interviewer to poke at, and the clean fix is to sign a length-prefixed or JSON-encoded payload instead of a delimited string.

### verify — the two independent checks, lines 113 to 117

```python
    def verify(self, key: str, expiry: int, signature: str) -> bool:
        """True when the signature matches and the link has not expired."""
        if expiry < int(time.time()):
            return False
        return hmac.compare_digest(self.sign(key, expiry), signature)
```

The expiry check comes first and is a plain integer comparison — no cryptography involved, because at this point the expiry is not yet trusted. That ordering is worth understanding: an expired-but-authentic link and a forged link both return `False`, and the caller cannot tell them apart, which is the right amount of information to give out. The check is a strict `<`, so a link is valid through the exact second it expires. Nothing depends on that.

Then the signature. `self.sign(key, expiry)` recomputes what the signature *should* be from the values that actually arrived, and the result is compared against what the caller sent. Note that verification is recomputation, not lookup: nothing is stored anywhere. There is no table of issued links, no revocation list, no state at all. That is the whole appeal of signed URLs — the server can hand out capabilities and later validate them without remembering that it did. The cost is that a link cannot be individually revoked; the only lever is rotating the secret, which invalidates every outstanding link.

**`hmac.compare_digest` and why `==` is the wrong tool.** Python's `==` on strings short-circuits: it compares byte by byte and returns as soon as it finds a mismatch. Comparing `"a..."` against the real signature returns after one byte; comparing a string with a correct first byte returns after two. The difference is tiny — nanoseconds — but it is *correlated with how much of the signature you got right*, and that is a side channel. An attacker who can time responses guesses the first hex character, trying all 16, and keeps whichever is consistently a hair slower. Then the second. Sixty-four characters at sixteen guesses is about a thousand probes, each repeated enough times to average out network noise. That is a forgery in an afternoon, against a signature space of 2^256. Timing attacks of exactly this shape have been demonstrated against real web frameworks over real networks; it is not a theoretical concern kept alive by textbooks.

`hmac.compare_digest` compares in time that does not depend on the *contents* of the two inputs. It always looks at every byte, and combines the differences with bitwise operations rather than branching, so there is no early return to measure. It is the correct tool for comparing any secret to a user-supplied value — signatures, API keys, password hashes, CSRF tokens.

**Worth knowing:** `compare_digest` accepts `str` arguments only if both are ASCII-only; otherwise it raises `TypeError: comparing strings with non-ASCII characters is not supported`. Here `signature` comes straight from the query string with no validation, so a request with `?signature=é` raises `TypeError` inside `verify`, which nothing catches, and the global handler at `backend/main.py:129` turns it into a 500 instead of a 403. It is not a security hole — no secret leaks and no access is granted — but it is a wrong status code on a path where every other bad input is a clean 403, and it puts a stack trace in the logs for what is really just a malformed request. The fix would be a cheap shape check on the signature before comparing, or comparing bytes instead of strings.

### content_type, lines 119 to 122

```python
    @staticmethod
    def content_type(key: str) -> str:
        guessed, _ = mimetypes.guess_type(key)
        return guessed or "application/octet-stream"
```

The MIME type is guessed from the key's extension using the standard library's table, with `application/octet-stream` as the fallback for anything unrecognised. `application/octet-stream` is the "I do not know what this is, download it, do not try to render it" type, which is the safe default. A `@staticmethod` because it touches no instance state — it does not even need the store to exist.

The important detail is what it does *not* do: it does not read the file, and it does not trust anything the caller sent. The type is a function of the stored key alone. Since keys are minted by the server (see the key scheme below), the caller has no influence over the `Content-Type` header, which closes off the "serve my file as `text/html`" line of attack mentioned earlier.

### The module-level singleton, lines 125 to 136

```python
_store: Optional[FileStore] = None
_lock = threading.Lock()


def get_file_store() -> FileStore:
    """The shared file store, opened on first use."""
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = FileStore()
    return _store
```

This is the double-checked locking pattern, and the doubled `if _store is None` is intentional, not a copy-paste slip. The outer check is the fast path: once the store exists, every call returns it without touching the lock at all, and the lock is the expensive part. The inner check is the correctness path: two threads can both pass the outer check, then queue on the lock, and without the second check the loser would construct a second store and overwrite the first. Rechecking inside the lock means the loser sees the winner's work and returns it.

A lock is needed here because this backend really is multi-threaded — FastAPI runs synchronous endpoints in a thread pool, and `asyncio.to_thread` is used for blocking I/O in the extraction pipeline. Constructing two stores would not be catastrophic (they would point at the same directory and hold the same secret), but it would do the `mkdir` and the log line twice and would make identity comparisons in tests unreliable.

This is also the FastAPI dependency, used as `store: FileStore = Depends(get_file_store)` in both routes. That is why it is a function rather than a bare module-level instance: `Depends` gives the tests a seam to override, and constructing on first use rather than at import time means importing the module does not create directories on disk.

### reset_file_store, lines 139 to 143

```python
def reset_file_store() -> None:
    """Discard the cached store so the next call reopens it."""
    global _store
    with _lock:
        _store = None
```

Exists for the tests. `backend/tests/conftest.py:74` calls it between tests so each one gets a store rooted in its own `tmp_path`; without it, the first test to touch the store would pin every later test to that directory. It takes the same lock as the constructor so a reset cannot interleave with a construction. Nothing in production calls it.

---

## backend/api/routes/files.py

Forty-seven lines, one endpoint. It is short because all the judgement lives in the service; this file's job is to translate between HTTP and that service.

```python
"""Serves stored files to holders of a valid signed link."""
```

Line 1. Note the phrasing: *holders of a valid signed link*, not *authenticated users*. That is the security model stated in one line, and it is deliberately different from every other route in the backend.

Lines 3 to 10 are imports. `quote` for percent-encoding the filename into a header. `APIRouter`, `Depends`, `HTTPException`, `Query` from FastAPI. `FileResponse` from `fastapi.responses`, which is the piece that matters: it streams a file from disk in chunks, sets `Content-Length` and `Last-Modified`, and handles HTTP range requests, which is what lets a browser's PDF viewer seek within a document without downloading all of it. Writing this by hand and getting ranges right would be a real amount of code. Then `FileStore`, `StorageError` and `get_file_store` from the service.

```python
router = APIRouter(prefix="/api/files", tags=["files"])

CACHE_SECONDS = 300
```

Lines 12 and 14. The prefix has to match what `signed_url` builds at `backend/services/files.py:105`; those two strings are coupled and there is no constant shared between them. The router is mounted in the loop at `backend/main.py:139`. `CACHE_SECONDS` is five minutes and is used once, at line 45.

```python
@router.get("/{key:path}")
def serve_file(
    key: str,
```

Lines 17 and 19. The `:path` converter is essential. A normal path parameter stops at the first `/`, so `{key}` would capture only `abc` out of `abc/exports/file.pdf`. `:path` greedily takes the whole remainder including slashes, which is what lets a key be a nested path. Because it is greedy, this route would swallow anything else registered under `/api/files/`, which is a reason to keep this router single-purpose.

The handler is `def`, not `async def`. That matters more than it looks: FastAPI runs synchronous handlers in a worker thread, so the blocking filesystem work inside `FileResponse` does not occupy the event loop. Had it been `async def` with the same body, serving a large file would block every other request on the same loop.

```python
    expires: int = Query(description="Unix timestamp after which the link is dead"),
    signature: str = Query(description="HMAC over the key and expiry"),
```

Lines 20 and 21. Both are declared with no default, which makes them **required** query parameters — a request missing either gets a 422 from FastAPI before the handler body runs. Declaring `expires` as `int` also means FastAPI does the parsing and rejects garbage; by the time `verify` sees it, it is genuinely an integer, which is what closes the delimiter ambiguity discussed earlier. The descriptions are there for the generated OpenAPI docs.

```python
    disposition: str = Query("attachment", pattern="^(attachment|inline)$"),
    filename: str = Query("download"),
```

Lines 22 and 23. `disposition` defaults to `attachment` — download, do not render — and the regex allows only the two known values. That pattern is doing real work: both values are echoed into a response header, and an unconstrained string echoed into a header is a header injection waiting to happen. FastAPI enforces the pattern and returns 422 for anything else, so the handler body can interpolate it without further thought. `filename` defaults to the harmless `"download"` and is percent-encoded at line 44 rather than pattern-checked, which is the appropriate treatment for a value that genuinely can be arbitrary text.

```python
    store: FileStore = Depends(get_file_store),
) -> FileResponse:
```

Lines 24 and 25. The dependency injection seam. In tests the store is reset per-test rather than overridden, but the seam is what makes either approach possible.

```python
    The signature is the credential: these links go to image tags, iframes and
    download managers that cannot send a bearer token, and they expire.
```

Lines 29 and 30. The docstring exists to answer, in advance, the obvious review question: why is there no `Depends(get_current_user)` on this route when every other route in the backend has one? Because the clients of this endpoint structurally cannot send a header. It is the same trade every object store makes with presigned URLs. Have this ready — an interviewer scanning the file will notice the missing auth dependency within seconds.

```python
    if not store.verify(key, expires, signature):
        raise HTTPException(status_code=403, detail="This link is invalid or has expired")
```

Lines 32 and 33. The first statement in the body, before any disk access. Ordering is the point: nothing touches the filesystem until the signature has been checked, so an unauthenticated caller cannot use this endpoint to probe which keys exist by timing or by error differences.

The single 403 covers both failure modes — bad signature and expired link — and the message deliberately says "invalid or has expired" without saying which. Distinguishing them would tell an attacker whether their forged signature was correct but stale, which is information they should not get. The status is 403 rather than 401 because 401 means "authenticate and try again", and there is no authentication scheme to point them at; the credential they presented was simply not good.

```python
    try:
        path = store.open_path(key)
    except StorageError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
```

Lines 35 to 38. Only now does anything look at the disk. `open_path` re-runs the containment check and confirms the file exists, and both of its failure modes arrive as `StorageError` and become a 404.

Two things to note. First, this converts "key escapes the storage root" into a 404 rather than a 400 — arguably the wrong code, but a defensible one, since it gives a prober the same answer for "outside the store" and "not in the store". Second, reaching this line means the signature was already valid, so the only way to get here with a traversal key is if the *server itself* signed one, which brings us to the hole below. `from error` preserves the exception chain in the logs.

```python
    return FileResponse(
        path,
        media_type=store.content_type(key),
```

Lines 40 to 42. `FileResponse` does the streaming and range handling. The media type is derived from the key by the service, not from anything in the request.

```python
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
```

Lines 43 and 44. `filename*=UTF-8''...` is RFC 5987 encoding — the extended form of the `filename` parameter that can carry non-ASCII characters. The two single quotes are not a typo; the grammar is `charset'language'value` and the language part is left empty. This form is what lets a file called `Cálculo Semana 3.pdf` download under its real name instead of a mangled one. `quote(filename)` percent-encodes the value, which is both what the RFC requires and what stops a filename containing a newline or a semicolon from breaking out into a header of its own.

**Worth knowing:** only the extended `filename*` form is sent, with no plain `filename=` fallback alongside it. Every browser in current use understands `filename*`, so this is fine in practice, but a very old client or a scripted downloader that only looks for `filename=` would fall back to the URL's last path segment — which is the UUID key. Purely cosmetic if it happens.

```python
            "Cache-Control": f"private, max-age={CACHE_SECONDS}",
```

Line 45. `private` means only the end user's browser may cache this, never a shared proxy or CDN — important, because these are per-user files behind a per-link credential and a shared cache could serve one user's export to another. `max-age=300` lets the browser reuse the bytes for five minutes, which is what makes the preview modal feel instant when you close and reopen it instead of re-downloading a PDF each time. Five minutes is comfortably shorter than the one-hour link lifetime, so the cache never outlives the credential by much.

---

## Three things that span both files

### The storage key scheme, and why it is not the user's filename

There are two key shapes in the system and both are minted by the server.

Sources, at `backend/pipeline/ingestion.py:43`:

```python
        key = f"{project_id}/sources/{uuid.uuid4()}{suffix}"
```

Exports, at `backend/services/exports/__init__.py:127`:

```python
        key = f"{project_id}/exports/{artifact_id}.{extension}"
```

The user's filename is never part of the key. Only its extension survives — `Path(original_name).suffix` at `ingestion.py:42` — and the human-readable name is carried separately as `original_name` on the `StoredSource` record, so nothing is lost from the user's point of view.

There are four reasons, and they are worth being able to give in order.

*Collisions.* Two students uploading `lecture.pdf` into the same project must not overwrite each other. A UUID cannot collide; a filename collides constantly.

*Path safety.* A filename is attacker-controlled text. `../../etc/passwd`, a name with a null byte, a name 4,000 characters long, a name that is `CON` on Windows — all of these become filesystem problems the moment you build a path out of them. `resolve` would catch the traversal, but the better answer is to never construct the dangerous string in the first place. A UUID plus a suffix has a fixed, known shape.

*Guessability.* The key travels in the URL and is what the signature protects. Keys derived from filenames are enumerable — if you know a course, you can guess `week3_notes.pdf`. That matters less here than it would elsewhere, because the signature is the real gate, but defence in depth is the correct posture for something one bug away from being served directly.

*Content type.* Because `content_type` guesses from the key, and the key's extension is derived from the upload rather than copied from an arbitrary caller-supplied string, the `Content-Type` header stays under server control.

The `{project_id}/` prefix on both shapes is what makes the directory layout browsable during debugging and makes a per-project cleanup a single `rmtree` if one is ever written. It is worth stating clearly that the prefix is *organisational, not a security boundary* — nothing in `FileStore` checks that the project in the key belongs to the caller. Ownership is enforced upstream, by `require_artifact` and `require_project` in `backend/api/deps.py`, before a link is ever signed. Which leads directly to the next section.

### The hole: `update_artifact` used to merge client content wholesale

This is the most interesting thing to be able to talk about here, and it is worth being precise, because the vulnerable code was not in either of these files and the fix is not here either. These files were the *weapon*; the bug was the trigger.

The download endpoint, `backend/api/routes/artifacts.py:101` to `:113`, does this:

```python
    export = (artifact.get("content") or {}).get("binary")
    ...
    key = export.get("storage_path")
    ...
        url = store.signed_url(key, filename=filename, inline=inline)
```

It reads a storage key out of the artifact's own content JSON and asks `FileStore.signed_url` to sign a link for it. That is entirely reasonable *provided that field was written by the server*. The export block is produced by the renderer at `backend/services/exports/__init__.py:44` and is supposed to be renderer-owned.

The PATCH endpoint used to merge whatever `content` the client sent straight over the stored content. So a caller could PATCH an artifact they legitimately owned with `content.binary.storage_path` set to any key they liked, then immediately GET `/api/artifacts/{id}/download`. Ownership was checked — but only on the artifact, which was theirs. Nobody checked the *key*. `signed_url` would faithfully sign it, because signing is a mechanical operation with no notion of who owns what, and `/api/files` would serve it, because a valid signature is by definition sufficient.

What makes it as bad as it is: the signature converts a self-service database edit into a durable, transferable read capability for any file in the store. Not a one-off read — a URL that works for an hour, from any browser, with no session. The path guard in `resolve` does not help, because the attacker does not need to escape the store; everyone's files are already inside it. And the attack needs no special access at all — only one artifact of your own to write into.

The fix lives at `backend/api/routes/artifacts.py:76` to `:80`:

```python
    existing = artifact.get("content") or {}
    merged = {**existing, **updates.content, "edited_by_user": True}
    merged.pop("binary", None)
    if "binary" in existing:
        merged["binary"] = existing["binary"]
```

The merge still happens, because a client that sends only `data` must not wipe the export metadata. But `binary` is then unconditionally removed from the merged result and restored *only* from what was already stored. If the client supplied a `binary` block it is discarded; if the artifact never had one, none is created. There is no request shape that puts a client-chosen key into that field. Two tests hold the line: `backend/tests/test_api.py:415` proves a PATCH cannot repoint an existing export and that the download still serves the original bytes, and `:446` proves a PATCH cannot attach an export to an artifact that had none.

The principle worth stating out loud: the field was not data, it was a capability. Anything that names a file the server will later act on has to be treated as privileged, and the boundary belongs at the write, not at the read. It could equally have been fixed by validating the key at download time — checking that it starts with the artifact's own project prefix — and that would be a reasonable second layer. But keeping untrusted values out of the record entirely is the stronger fix, because it means every future reader of that field can trust it without knowing this story.

### Streaming, temp files, and one copy that gets left behind

An upload takes three hops, and it is worth knowing that none of them holds the whole file in memory.

Hop one, `backend/api/routes/projects.py:180`:

```python
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as buffered:
        path = buffered.name
        while chunk := await file.read(UPLOAD_CHUNK_BYTES):
            written += len(chunk)
            if written > limit:
```

The request body is read in one-megabyte chunks (`UPLOAD_CHUNK_BYTES` at `projects.py:25`) and written straight to a temp file, with the size limit enforced *as it goes* rather than after the fact — so a 10 GB upload against a 200 MB limit is aborted after 200 MB, not after 10 GB. On breach it closes the handle, unlinks the partial file and raises 413. `delete=False` is necessary because the file has to outlive the request: its path is stored as the job's `source_ref` and the ingest worker picks it up later, possibly in another process.

Hop two, `FileStore.put` at `files.py:45`, uses `shutil.copyfile`, which also copies in chunks. Hop three, reading back out for extraction, uses `copy_to` into a `TemporaryDirectory` that cleans itself up.

An earlier version of this code did `contents = await file.read()` with no argument, which reads the entire body into one `bytes` object. A 200 MB upload became 200 MB of resident memory per concurrent request, and several at once took the process down. That is why the loop and the walrus operator are there, and why the route's docstring at `projects.py:128` explicitly says "does not become an equally large resident process".

The staged temp file is deleted by the ingest handler, at `backend/handlers/ingest_handler.py:167`, in a `finally` so it happens whether ingestion succeeded or failed. The deletion is guarded (`ingest_handler.py:207` to `:213`): the path must sit directly in the system temp directory and carry the temp-file prefix, otherwise nothing is deleted. That guard exists because `source_ref` is also how a YouTube URL and a caller-supplied path arrive, and deleting the wrong file is much worse than leaking one. An earlier version deleted nothing at all, so every successful upload left a full-size duplicate in `/tmp` forever.

**The honest limitation.** `store_upload` mints a fresh UUID key on every call (`ingestion.py:43`), and nothing ever removes the previous one. If an ingest gets as far as `_store` and then fails later — extraction produced too little text, the LLM call timed out — the durable copy it already made stays in the store. Retrying produces a second copy under a second key. The database only ever references the key from the attempt that finally succeeded, so the earlier ones are orphans: real bytes on disk, referenced by nothing, invisible to the application, never cleaned up. `FileStore.delete` exists and would do the job, and nothing calls it.

That ordering is not accidental — the comment at `ingest_handler.py:171` says the store step sits deliberately outside the cleanup block, because until it returns the staged temp file is the only copy in existence. So the choice was made knowingly: durability first, tidiness second. The right fix is a reaper that walks `{project_id}/sources/` and removes keys no row references, or storing the key on the job record so a failed attempt knows what to clean up. Neither exists. If asked, describe it as a known operational gap with a known shape, and note that it is bounded — orphans are only created by failed ingests, not by ordinary use.
