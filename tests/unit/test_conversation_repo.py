from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.models import Turn
from backend.repositories.postgres_conversation_repo import _pair_rows


class TestPairRows:
    """Pure logic — no DB needed."""

    def test_pairs_user_assistant_into_turns(self):
        from datetime import datetime
        conv_id = uuid4()
        rows = [
            {"role": "user",      "content": "What is X?",  "created_at": datetime.utcnow()},
            {"role": "assistant", "content": "X is Y.",      "created_at": datetime.utcnow()},
            {"role": "user",      "content": "Tell me more", "created_at": datetime.utcnow()},
            {"role": "assistant", "content": "More details.", "created_at": datetime.utcnow()},
        ]
        turns = _pair_rows(rows, conv_id)

        assert len(turns) == 2
        assert turns[0].user_message == "What is X?"
        assert turns[0].assistant_message == "X is Y."
        assert turns[1].user_message == "Tell me more"

    def test_orphan_row_skipped(self):
        from datetime import datetime
        conv_id = uuid4()
        rows = [
            {"role": "assistant", "content": "Orphan.",       "created_at": datetime.utcnow()},
            {"role": "user",      "content": "Real question", "created_at": datetime.utcnow()},
            {"role": "assistant", "content": "Real answer.",  "created_at": datetime.utcnow()},
        ]
        turns = _pair_rows(rows, conv_id)
        assert len(turns) == 1
        assert turns[0].user_message == "Real question"

    def test_empty_rows_returns_empty(self):
        turns = _pair_rows([], uuid4())
        assert turns == []


class TestPostgresConversationRepo:
    async def test_save_turn_inserts_two_rows(self):
        from backend.repositories.postgres_conversation_repo import PostgresConversationRepository

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        repo = PostgresConversationRepository(mock_pool)
        turn = Turn(
            conversation_id=uuid4(),
            tenant_id="t1",
            user_message="Hello",
            assistant_message="Hi there",
        )

        await repo.save_turn(turn)

        mock_conn.executemany.assert_called_once()
        args = mock_conn.executemany.call_args[0][1]   # list of row tuples
        assert args[0][3] == "user"
        assert args[1][3] == "assistant"
        assert args[0][4] == "Hello"
        assert args[1][4] == "Hi there"
