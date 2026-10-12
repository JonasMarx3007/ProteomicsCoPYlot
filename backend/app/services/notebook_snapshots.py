"""Bounded, session-owned immutable recipes for successful plot renders."""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import secrets
from threading import RLock, get_ident
import time

from app.services.notebook_archive import NotebookRecipe
from app.services.notebook_limits import notebook_memory_budgets


class RetainedReplay:
    """Deferred calculation with explicitly accounted, shared input frames."""

    def __init__(self, finish, frames):
        self.finish = finish
        self.frames = tuple(frames)

    def __call__(self):
        return self.finish()


def recipe_size(recipe) -> int:
    """Owned recipe bytes; retained shared frames are accounted separately."""
    size = sum(map(len, recipe.resources.values())) + len(recipe.source.code.encode())
    # Serialize small mutable values to count them and reject non-finite options.
    size += len(json.dumps([recipe.settings, recipe.provenance], allow_nan=False).encode())
    size += sum(len(value.encode()) for value in (
        recipe.calculation, recipe.preparation, recipe.imputation_recipe,
        recipe.input_explanation, recipe.plot_name, recipe.original_filename,
    ))
    size += sum(len(heading.encode()) + len(code.encode()) for heading, code in recipe.calculation_sections)
    return size


def forget_session(session: str) -> None:
    """Drop a session's exports when its data is reset or it logs out."""
    snapshots.clear_session(session)


class PendingRecipe:
    """A captured recipe whose original-file replay is prepared when it is downloaded.

    `finish` holds references to the frames the plot was rendered from; they are
    never mutated, so the pending recipe is shared rather than deep-copied.
    """

    def __init__(self, recipe: NotebookRecipe, finish):
        self.recipe = recipe
        self.finish = finish

    def __deepcopy__(self, memo):
        return self


@dataclass(frozen=True)
class _Snapshot:
    session: str
    recipe: NotebookRecipe
    size: int
    expires: float
    retained: tuple = ()


class NotebookSnapshots:
    """Tokens reference render-time inputs, never the currently selected dataset.

    Keep this separate from the ordinary plot cache: changing a data source must
    not silently retarget an already-rendered figure's notebook download.
    """

    def __init__(self, *, max_bytes: int | None = None, max_total_bytes: int | None = None,
                 per_session: int = 48, ttl: float = 1800, clock=time.monotonic):
        """`max_bytes` is each session's own budget; `max_total_bytes` bounds the server.

        A session that exceeds its budget evicts only its own oldest exports. The
        server-wide ceiling bounds all sessions together; only when it is reached is the
        least recently used export of any session dropped.
        """
        session_default, total_default = notebook_memory_budgets()
        if max_total_bytes is None:
            max_total_bytes = total_default
        if max_bytes is None:
            max_bytes = min(session_default, max_total_bytes)
        if max_bytes <= 0 or max_total_bytes <= 0 or per_session <= 0 or ttl <= 0:
            raise ValueError("Snapshot limits must be positive.")
        self.max_bytes = max_bytes
        self.max_total_bytes = max_total_bytes
        self.per_session = per_session
        self.ttl = ttl
        self.clock = clock
        self._lock = RLock()
        self._entries: OrderedDict[str, _Snapshot] = OrderedDict()
        self._preparing: dict[str, tuple[int, Future[None]]] = {}

    def _expire(self):
        now = self.clock()
        for token in list(self._entries):
            if self._entries[token].expires <= now:
                del self._entries[token]

    def capture(self, session: str, recipe, size: int | None = None) -> str:
        if not session:
            raise ValueError("A notebook snapshot requires a session owner.")
        if size is None:
            size = recipe_size(recipe.recipe if isinstance(recipe, PendingRecipe) else recipe)
        retained = tuple((id(frame), int(frame.memory_usage(index=True, deep=True).sum()))
                         for frame in getattr(getattr(recipe, 'finish', None), 'frames', ()))
        snapshot = _Snapshot(session, deepcopy(recipe), size, self.clock() + self.ttl, retained)
        with self._lock:
            self._expire()
            token = secrets.token_urlsafe(24)
            self._admit(token, snapshot)
            return token

    @staticmethod
    def _usage(entries):
        retained = dict(item for entry in entries for item in entry.retained)
        return sum(entry.size for entry in entries) + sum(retained.values())

    def _admit(self, token, snapshot):
        needed = self._usage([snapshot])
        if needed > min(self.max_bytes, self.max_total_bytes):
            raise ValueError(
                f'This plot exceeds the notebook snapshot memory limit: {needed / 1024**2:,.0f} MiB required. '
                'Configure COPYLOT_NOTEBOOK_SESSION_MEMORY_MB and COPYLOT_NOTEBOOK_MEMORY_MB for a suitably sized machine.')
        candidates = OrderedDict(self._entries)
        candidates.pop(token, None)
        candidates[token] = snapshot
        owned = [key for key, entry in candidates.items() if entry.session == snapshot.session]
        while len(owned) > self.per_session or self._usage([candidates[key] for key in owned]) > self.max_bytes:
            del candidates[owned.pop(0)]
        while self._usage(list(candidates.values())) > self.max_total_bytes:
            candidates.popitem(last=False)
        self._entries = candidates

    def _entry(self, session: str, token: str):
        with self._lock:
            self._expire()
            snapshot = self._entries.get(token)
            if snapshot is None or snapshot.session != session:
                raise KeyError("Notebook snapshot unavailable; render the plot again.")
            self._entries.move_to_end(token)
            # A use keeps the export available while it is being used.
            self._entries[token] = replace(snapshot, expires=self.clock() + self.ttl)
            return snapshot.recipe

    def get(self, session: str, token: str) -> NotebookRecipe:
        """The finished recipe, preparing the original-file replay on first use."""
        with self._lock:
            item = self._entry(session, token)
            if not isinstance(item, PendingRecipe):
                return deepcopy(item)
            pending = self._preparing.get(token)
            owner = pending is None
            if pending is None:
                future: Future[None] = Future()
                self._preparing[token] = (get_ident(), future)
            else:
                if any(thread == get_ident() for thread, _ in self._preparing.values()):
                    raise RuntimeError("Notebook preparation cannot wait on another nested preparation.")
                _, future = pending
        if owner:
            try:
                finished = item.finish()
                self.replace_recipe(session, token, finished)
                future.set_result(None)
            except BaseException as exc:
                future.set_exception(exc)
                raise
            finally:
                with self._lock:
                    self._preparing.pop(token, None)
        else:
            future.result()
        # Do not return a recipe cleared, expired or evicted while preparing/waiting.
        return deepcopy(self._entry(session, token))

    def peek(self, session: str, token: str) -> NotebookRecipe:
        """The recipe as captured, without preparing it: for reading its tables."""
        item = self._entry(session, token)
        return deepcopy(item.recipe if isinstance(item, PendingRecipe) else item)

    def replace_recipe(self, session: str, token: str, recipe) -> None:
        """Keep the finished recipe, so a second download does not prepare it again."""
        with self._lock:
            self._expire()
            snapshot = self._entries.get(token)
            if snapshot is None or snapshot.session != session:
                raise KeyError("Notebook snapshot unavailable; render the plot again.")
            self._admit(token, replace(snapshot, recipe=deepcopy(recipe), size=recipe_size(recipe), retained=()))

    def clear_session(self, session: str):
        with self._lock:
            for token in list(self._entries):
                if self._entries[token].session == session:
                    del self._entries[token]


# The one store of captured notebook recipes; `notebook_qc.snapshots` is the same object.
snapshots = NotebookSnapshots()
