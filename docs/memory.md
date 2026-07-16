# Memory Architecture — Two-Tier Design

The agent uses a two-tier memory system:

1. **Checkpointer** (short-term session state) — LangGraph ``PostgresSaver``
2. **Memory Store** (long-term cross-session) — Custom ``MemoryStore`` with pgvector

Plus Redis for ephemeral caching and pub/sub (not used for memory directly).

---

## Tier 1: Checkpointer

**File:** ``src/nexus/memory/checkpointer.py``

Persistence for LangGraph's thread/session state so the agent can resume
interrupted runs after a server restart (enables HITL, time-travel,
and multi-turn conversations).

### Implementation

- Uses ``PostgresSaver`` from ``langgraph.checkpoint.postgres``
- Connected via a ``psycopg.AsyncConnectionPool``
- ``thread_id = session_id`` (UUID string, < 255 chars)
- ``setup()`` creates checkpoint tables if they don't exist

### Tables (created by LangGraph's ``setup()`` SQL)

| Table | Purpose |
|-------|---------|
| ``checkpoints`` | Stores checkpoint data per thread/node |
| ``checkpoint_blobs`` | Binary blob data for checkpoints |
| ``checkpoint_writes`` | Writes between graph nodes |
| ``checkpoint_migrations`` | Migration version tracking |

### Wiring

The checkpointer is wired in ``src/nexus/agent/api.py``:

```python
if settings.memory.checkpointer_type == "postgres":
    checkpointer = await get_checkpointer()
graph = build_agent_graph(checkpointer=checkpointer)
```

If the DB is unavailable or ``checkpointer_type`` is ``"memory"``, the
graph falls back to ``MemorySaver()`` (in-memory, not persistent).

### Migration

Alembic migration ``0003_checkpoint_tables.py`` creates the required
checkpoint tables.  Run with:

```bash
uv run alembic upgrade head
```

---

## Tier 2: Memory Store

**File:** ``src/nexus/memory/store.py``

Cross-session long-term memory backed by the existing ``Memory``
SQLAlchemy model with pgvector for semantic search.

### Namespace Convention

| Part | Value | Example |
|------|-------|---------|
| tenant_id | UUID string | ``"00000000-0000-0000-0000-000000000001"`` |
| collection | fixed string | ``"memories"`` |
| kind | memory type | ``"preference"``, ``"fact"``, ``"procedural"``, ``"episodic"`` |

Full namespace: ``(tenant_id, "memories", memory_kind)``

### Operations

| Method | Description |
|--------|-------------|
| ``put(namespace, content, embedding, ...)`` | Create or update a memory entry |
| ``get(namespace, memory_id)`` | Retrieve a single memory by ID |
| ``search(query_embedding, namespace, top_k, metadata_filter)`` | Semantic search via cosine similarity |
| ``delete(namespace, memory_id)`` | Delete a memory by ID |

Search uses pgvector's ``<=>`` cosine similarity operator on the
``embedding`` column (VECTOR 1536).  Results are ordered by similarity
descending.

### Memory Table Schema

The ``Memory`` table (from Phase 3) contains:

| Column | Type | Description |
|--------|------|-------------|
| ``id`` | UUID | Primary key |
| ``tenant_id`` | UUID (FK) | Multi-tenant isolation |
| ``session_id`` | UUID (FK, nullable) | Source session |
| ``kind`` | string | episodic, semantic, procedural, preference |
| ``content`` | text | The memory text |
| ``embedding`` | VECTOR(1536) | pgvector embedding for semantic search |
| ``metadata_`` | JSONB | Arbitrary metadata (user_id, session_id, etc.) |
| ``importance`` | float (0-1) | Salience score |
| ``last_accessed_at`` | timestamp | For decay calculations |
| ``created_at`` | timestamp | Row creation time |

---

## Memory Manager

**File:** ``src/nexus/memory/manager.py``

Orchestrates extraction, storage, and retrieval using the Store and the LLM.

### `extract_and_store`

Called by the ``finalize`` node after each agent run:

1. Build a transcript from the agent state
2. LLM extracts structured memories (preferences, facts, decisions, procedures)
3. Generate embeddings for each extracted memory
4. **Deduplication**: Search for similar existing memory (cosine > 0.92);
   if found, update instead of insert
5. Store with importance score
6. Generate and store an episodic summary via ``EpisodicSummarizer``

### `retrieve_relevant`

Called during session setup to inject relevant memories into the system prompt:

1. Generate embedding for the user's query
2. Semantic search top-K memories (configurable via ``retrieval_top_k``)
3. Filter by tenant_id and user_id
4. Return results formatted for system prompt injection

### `decay`

Periodic maintenance job:

1. Find memories not accessed in N days (default 90)
2. Halve their importance score
3. Archive memories below ``importance_threshold`` (default 0.3)

---

## EpisodicSummarizer

**File:** ``src/nexus/memory/summarizer.py``

Compresses a finished agent run into a 3-5 sentence summary using the LLM.
Captures: user goal, tools called + key results, decisions/preferences,
final outcome.  Used by the MemoryManager during ``extract_and_store``.

---

## Configuration

| Env Variable | Default | Description |
|-------------|---------|-------------|
| ``NEXUS_MEMORY__ENABLED`` | ``true`` | Enable memory extraction and retrieval |
| ``NEXUS_MEMORY__RETRIEVAL_TOP_K`` | ``5`` | Memories per query |
| ``NEXUS_MEMORY__IMPORTANCE_THRESHOLD`` | ``0.3`` | Minimum importance to retain |
| ``NEXUS_MEMORY__SIMILARITY_THRESHOLD`` | ``0.92`` | Cosine similarity for dedup |
| ``NEXUS_MEMORY__CHECKPOINTER_TYPE`` | ``"postgres"`` | ``"postgres"`` or ``"memory"`` |
| ``NEXUS_LLM__EMBEDDING_MODEL`` | ``"text-embedding-3-small"`` | Model for generating embeddings |

---

## Files Reference

| File | Purpose |
|------|---------|
| ``src/nexus/memory/__init__.py`` | Module exports |
| ``src/nexus/memory/checkpointer.py`` | PostgresSaver singleton |
| ``src/nexus/memory/store.py`` | MemoryStore with pgvector |
| ``src/nexus/memory/manager.py`` | MemoryManager service |
| ``src/nexus/memory/summarizer.py`` | EpisodicSummarizer |
| ``alembic/versions/0003_checkpoint_tables.py`` | Checkpoint table migration |
