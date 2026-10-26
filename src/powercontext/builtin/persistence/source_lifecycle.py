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


"""Persist the bounded evidence graph of a single Scope."""

import json

from sqlalchemy import insert, select, update

from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_TABLE


async def load_lifecycle(connection, scope_id):
    payload = await connection.scalar(
        select(SOURCE_LIFECYCLE_TABLE.c.payload).where(SOURCE_LIFECYCLE_TABLE.c.scope_id == scope_id)
    )
    return {} if payload is None else json.loads(payload)


async def save_lifecycle(connection, scope_id, graph):
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).encode()
    exists = await connection.scalar(
        select(SOURCE_LIFECYCLE_TABLE.c.scope_id).where(SOURCE_LIFECYCLE_TABLE.c.scope_id == scope_id)
    )
    if exists is None:
        await connection.execute(insert(SOURCE_LIFECYCLE_TABLE).values(scope_id=scope_id, payload=payload))
    else:
        await connection.execute(
            update(SOURCE_LIFECYCLE_TABLE).where(SOURCE_LIFECYCLE_TABLE.c.scope_id == scope_id).values(payload=payload)
        )


def available_nodes(graph):
    """Evaluate the registered DAG, independent of JSON object key order."""
    available = set()
    visited = set()

    def visit(node_id):
        if node_id in visited:
            return node_id in available
        node = graph[node_id]
        if node["kind"] == "source":
            event = node["event"]
            active = event is None or event["available"]
        else:
            support = [visit(parent) for parent in node["parents"]]
            active = all(support) if node["policy"] == "all" else any(support)
        visited.add(node_id)
        if active:
            available.add(node_id)
        return active

    for node_id in graph:
        visit(node_id)
    return available
