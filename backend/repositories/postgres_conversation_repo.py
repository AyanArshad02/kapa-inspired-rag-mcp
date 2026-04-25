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
