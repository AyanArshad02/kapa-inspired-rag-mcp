"""
Locust load test for Kapa RAG query pipeline.

Flow per virtual user:
  1. Login → get JWT  (auth service, port 8004)
  2. POST /query with a random question from a fixed pool
  3. Wait 1–3s (think time) → repeat

Fixed question pool → cache warms up after first hit per question.
Subsequent users get cache hits: realistic production behaviour.

Run:
  locust -f tests/load/locustfile.py --headless -u 10 -r 2 -t 60s \
         --host http://localhost:8000 --csv tests/load/results
"""
from __future__ import annotations

import os
import random

from locust import HttpUser, between, events, task

# Auth service runs on a different port from the query service.
# self.client uses --host (query service). Auth calls use this constant.
AUTH_BASE = os.getenv("AUTH_URL", "http://localhost:8004")

# Credentials for the test account. Override via env vars if needed.
TEST_EMAIL = os.getenv("LOAD_TEST_EMAIL", "ayanarshad2002@gmail.com")
TEST_PASSWORD = os.getenv("LOAD_TEST_PASSWORD", "test1234")

# Fixed pool — same questions every run so the semantic cache warms up
# and subsequent users benefit from cache hits.
QUESTIONS = [
    "What is FastAPI and what are its main features?",
    "How do I define path parameters in FastAPI?",
    "What is dependency injection in FastAPI?",
    "How does FastAPI handle request validation with Pydantic?",
    "How do I create a background task in FastAPI?",
]


class RAGUser(HttpUser):
    """Simulates a tenant making repeated RAG queries."""

    wait_time = between(1, 3)

    def on_start(self) -> None:
        """Called once per virtual user when it starts. Gets a JWT."""
        self._token: str | None = None
        self._conversation_id: str | None = None
        self._login()

    def _login(self) -> None:
        # Use full URL so Locust routes to auth service, not query service.
        res = self.client.post(
            f"{AUTH_BASE}/auth/login",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
            name="[auth] /auth/login",
        )
        if res.status_code == 200:
            self._token = res.json().get("access_token")
        else:
            # Fall back to guest session so the user can still run queries.
            guest = self.client.post(
                f"{AUTH_BASE}/auth/guest",
                name="[auth] /auth/guest",
            )
            if guest.status_code == 200:
                self._token = guest.json().get("access_token")

    @task
    def query(self) -> None:
        """Main task: POST /query with a question from the fixed pool."""
        if not self._token:
            self._login()
            return

        question = random.choice(QUESTIONS)

        with self.client.post(
            "/query",
            json={
                "query": question,
                "stream": False,
                "conversation_id": self._conversation_id,
            },
            headers={"Authorization": f"Bearer {self._token}"},
            name="/query",
            catch_response=True,
        ) as res:
            if res.status_code == 200:
                data = res.json()
                self._conversation_id = data.get("conversation_id")
                cached = data.get("cached", False)
                # Tag cached vs non-cached in Locust's name column
                # so we can see both latencies separately in the report.
                res.success()
                # Manually emit a second stat entry with cache label
                label = "/query [cache hit]" if cached else "/query [llm call]"
                events.request.fire(
                    request_type="POST",
                    name=label,
                    response_time=res.elapsed.total_seconds() * 1000,
                    response_length=len(res.content),
                    exception=None,
                    context={},
                )
            elif res.status_code == 429:
                # Rate limit is expected behaviour — mark as success so it
                # doesn't inflate the failure rate metric.
                res.success()
            elif res.status_code == 401:
                # Token expired — refresh and mark this request as a failure
                # (it will be retried on the next tick).
                res.failure("Token expired — will re-login on next tick")
                self._token = None
            else:
                res.failure(f"Unexpected {res.status_code}: {res.text[:200]}")
