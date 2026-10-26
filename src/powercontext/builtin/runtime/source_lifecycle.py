# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Propagate explicit evidence availability without rewriting historical bodies."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.source_lifecycle import available_nodes, load_lifecycle, save_lifecycle
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources import validate_scope_id
from powercontext.sources import SourceRef


class SourceLifecycleError(ValueError):
    """Invalid registration, event or generation use of unavailable evidence."""


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: StrictStr
    revision: StrictInt = Field(gt=0)
    sequence: StrictInt = Field(gt=0)
    available: StrictBool
    reason: StrictStr

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("event identity and reason must not be blank")  # noqa: TRY003
        return value


class SourceLifecycleApplication:
    def __init__(self, runtime):
        self.runtime = runtime
        # The standard Runtime owns one relational provider for durable operations.
        self.database = getattr(runtime._provider, "database", None)

    def for_scope(self, scope_id):
        return ScopedSourceLifecycle(self, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    def __init__(self, owner, scope_id):
        self.owner, self.scope_id = owner, scope_id
        self.runtime = owner.runtime

    async def _load(self):
        if self.owner.database is None:
            raise SourceLifecycleError("lifecycle requires durable relational storage")  # noqa: TRY003
        async with self.owner.database.transaction() as connection:
            return await load_lifecycle(connection, self.scope_id)

    async def _save(self, graph):
        async with self.owner.database.transaction() as connection:
            await save_lifecycle(connection, self.scope_id, graph)

    async def register_source(self, node_id, source_ref, *, revision):
        if type(revision) is not int or revision < 1 or not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source reference and revision are invalid")  # noqa: TRY003
        await self.runtime.records.for_scope(self.scope_id).get_source(source_ref.source_type, source_ref.source_id)
        await self._register(
            node_id,
            {
                "kind": "source",
                "reference": source_ref.model_dump(mode="json"),
                "revision": revision,
                "parents": [],
                "policy": "all",
                "event": None,
            },
        )

    async def register_memory(self, node_id, citation, *, parents, policy):
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("expected an exact Memory citation")  # noqa: TRY003
        await self.runtime.memory.for_scope(self.scope_id).get(GetMemoryEntryRequest(citation=citation))
        await self._register_derived(node_id, "memory", citation, parents, policy)

    async def register_topic(self, node_id, artifact_ref, *, parents, policy):
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("expected an exact Topic Memory reference")  # noqa: TRY003
        await self.runtime.records.for_scope(self.scope_id).get_artifact_revision(
            artifact_ref.family, artifact_ref.artifact_id, artifact_ref.revision
        )
        await self._register_derived(node_id, "topic", artifact_ref, parents, policy)

    async def _register_derived(self, node_id, kind, reference, parents, policy):
        if policy not in {"all", "any"} or not parents or len(set(parents)) != len(parents):
            raise SourceLifecycleError("derived evidence requires unique parents and an all/any policy")  # noqa: TRY003
        await self._register(
            node_id,
            {
                "kind": kind,
                "reference": reference.model_dump(mode="json"),
                "revision": None,
                "parents": list(parents),
                "policy": policy,
                "event": None,
            },
        )

    async def _register(self, node_id, node):
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("node id must not be blank")  # noqa: TRY003
        async with self.runtime._scope_operation(self.scope_id), self.runtime._locked(self.scope_id):
            graph = await self._load()
            existing = graph.get(node_id)
            if existing is not None:
                if {**existing, "event": None} != node:
                    raise SourceLifecycleError("node id is already bound to different evidence")  # noqa: TRY003
            else:
                if node_id in node["parents"] or any(parent not in graph for parent in node["parents"]):
                    raise SourceLifecycleError("parents must be registered before their child")  # noqa: TRY003
                if any(
                    other["kind"] == node["kind"] and other["reference"] == node["reference"]
                    for other in graph.values()
                ):
                    raise SourceLifecycleError("evidence is already bound to another node")  # noqa: TRY003
                graph[node_id] = node
                await self._save(graph)
            await self._reconcile(graph)

    async def apply(self, event):
        event = SourceLifecycleEvent.model_validate(event)
        async with self.runtime._scope_operation(self.scope_id), self.runtime._locked(self.scope_id):
            graph = await self._load()
            node = graph.get(event.node_id)
            if node is None or node["kind"] != "source" or node["revision"] != event.revision:
                raise SourceLifecycleError("event must match a registered Source revision")  # noqa: TRY003
            previous = node["event"]
            if previous is not None and (
                event.sequence < previous["sequence"]
                or (event.sequence == previous["sequence"] and event.model_dump() != previous)
            ):
                raise SourceLifecycleError("event sequence is stale or conflicts with a prior event")  # noqa: TRY003
            if previous != event.model_dump():
                # Persist intent before native changes; replay repairs any interrupted propagation.
                node["event"] = event.model_dump()
                await self._save(graph)
            await self._reconcile(graph)
            return sorted(available_nodes(graph))

    async def resolve(self, node_id, *, purpose):
        if purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("unknown evidence purpose")  # noqa: TRY003
        async with self.runtime._scope_operation(self.scope_id):
            graph = await self._load()
            node = graph.get(node_id)
            if node is None or (purpose == "generation" and node_id not in available_nodes(graph)):
                raise SourceLifecycleError("evidence is unknown or unavailable for generation")  # noqa: TRY003
            model = {"source": SourceRef, "memory": MemoryCitation, "topic": ArtifactRef}[node["kind"]]
            return model.model_validate(node["reference"])

    async def _reconcile(self, graph):
        active = available_nodes(graph)
        async with self.runtime._context(self.scope_id) as context:
            service = context.artifacts.memory
            memory_nodes = [(key, node) for key, node in graph.items() if node["kind"] == "memory"]
            if not memory_nodes:
                return
            current = await service.head(context.artifacts.memory_artifact_id)
            entries = {entry.entry_id: entry for entry in await service.entries(current)}
            states = {entry.entry_id: entry.state for entry in current.content.manifest.entries}
            for key, node in memory_nodes:
                citation = MemoryCitation.model_validate(node["reference"])
                desired = "active" if key in active else "inactive"
                if states[citation.entry_id] == desired:
                    continue
                operation = service.reactivate if desired == "active" else service.forget
                current = await operation(current, entries=(entries[citation.entry_id],), reason="Source availability")
                states[citation.entry_id] = desired
