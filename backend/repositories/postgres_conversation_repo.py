from __future__ import annotations

from uuid import UUID, uuid4

import asyncpg
import tiktoken

from backend.models import Turn
from backend.repositories.base import ConversationRepository

_ENCODING = tiktoken.encoding_for_model("gpt-4o")


def _count_tokens(text: str) -> int:
    return len(_ENCODING.encode(text))


class PostgresConversationRepository(ConversationRepository):
    """Stores conversation turns as individual role/content rows.

    The DB schema has one row per message (role = user | assistant).
    save_turn inserts two rows; get_recent_turns pairs them back into Turns.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def save_turn(self, turn: Turn) -> Turn:
        async with self._pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO conversation_turns
                    (turn_id, conversation_id, tenant_id, role, content, tokens)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                [
                    (
                        str(turn.id),
                        str(turn.conversation_id),
                        turn.tenant_id,
                        "user",
                        turn.user_message,
                        _count_tokens(turn.user_message),
                    ),
                    (
                        str(uuid4()),
                        str(turn.conversation_id),
                        turn.tenant_id,
                        "assistant",
                        turn.assistant_message,
                        _count_tokens(turn.assistant_message),
                    ),
                ],
            )
        return turn

    async def get_recent_turns(
        self, conversation_id: UUID, limit: int = 3
    ) -> list[Turn]:
        """Return the last `limit` user+assistant pairs, oldest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content, created_at
                FROM conversation_turns
                WHERE conversation_id = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                str(conversation_id),
                limit * 2,   # each Turn = 2 rows
            )

        rows = list(reversed(rows))   # oldest first
        return _pair_rows(rows, conversation_id)

    async def delete_conversation(self, conversation_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM conversation_turns WHERE conversation_id = $1",
                str(conversation_id),
            )

    async def list_conversations(self, tenant_id: str) -> list[dict]:
        """Return one summary row per conversation, most recent first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    conversation_id,
                    MAX(created_at)  AS last_active,
                    COUNT(*)         AS message_count,
                    (
                        SELECT content FROM conversation_turns inner_ct
                        WHERE  inner_ct.conversation_id = outer_ct.conversation_id
                          AND  inner_ct.role = 'user'
                        ORDER  BY created_at ASC LIMIT 1
                    ) AS first_message
                FROM   conversation_turns outer_ct
                WHERE  tenant_id = $1
                GROUP  BY conversation_id
                ORDER  BY MAX(created_at) DESC
                """,
                tenant_id,
            )
        return [
            {
                "conversation_id": str(r["conversation_id"]),
                "last_active": r["last_active"].isoformat(),
                "message_count": r["message_count"],
                "preview": (r["first_message"] or "")[:80],
            }
            for r in rows
        ]

    async def get_messages(self, conversation_id: UUID, tenant_id: str) -> list[dict]:
        """Return all messages for a conversation as [{role, content}], oldest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT role, content FROM conversation_turns
                WHERE  conversation_id = $1 AND tenant_id = $2
                ORDER  BY created_at ASC
                """,
                str(conversation_id),
                tenant_id,
            )
        return [{"role": r["role"], "content": r["content"]} for r in rows]


def _pair_rows(rows: list, conversation_id: UUID) -> list[Turn]:
    """Group consecutive user+assistant rows into Turn objects."""
    turns: list[Turn] = []
    i = 0
    while i < len(rows) - 1:
        if rows[i]["role"] == "user" and rows[i + 1]["role"] == "assistant":
            turns.append(
                Turn(
                    conversation_id=conversation_id,
                    user_message=rows[i]["content"],
                    assistant_message=rows[i + 1]["content"],
                    created_at=rows[i]["created_at"],
                )
            )
            i += 2
        else:
            i += 1   # skip orphan row (shouldn't happen in normal flow)
    return turns
