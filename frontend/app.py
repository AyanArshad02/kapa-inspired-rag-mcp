"""
Kapa RAG Demo — Streamlit chat frontend.

Sidebar:  configure API key, add knowledge sources, view/delete indexed sources
Main:     chat interface with source citations and conversation memory
"""
from __future__ import annotations

import os

import requests
import streamlit as st

INGESTION_URL = os.getenv("INGESTION_URL", "http://localhost:8001")
QUERY_URL = os.getenv("QUERY_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Kapa RAG Demo",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state ─────────────────────────────────────────────────────────────

_DEFAULTS: dict = {
    "api_key": "dev-test-key-123",
    "conversation_id": None,
    "messages": [],
    "pending_jobs": [],  # list of {"job_id", "label", "status"}
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _h() -> dict:
    return {"Authorization": f"Bearer {st.session_state.api_key}"}


def _get(path: str, base: str = INGESTION_URL, **kw) -> requests.Response | None:
    try:
        return requests.get(f"{base}{path}", headers=_h(), timeout=5, **kw)
    except requests.exceptions.ConnectionError:
        return None


def _post(path: str, base: str = INGESTION_URL, **kw) -> requests.Response | None:
    try:
        return requests.post(f"{base}{path}", headers=_h(), timeout=30, **kw)
    except requests.exceptions.ConnectionError:
        return None


def _delete(path: str, base: str = INGESTION_URL, **kw) -> requests.Response | None:
    try:
        return requests.delete(f"{base}{path}", headers=_h(), timeout=10, **kw)
    except requests.exceptions.ConnectionError:
        return None


# ── Knowledge source helpers ──────────────────────────────────────────────────

def list_sources() -> list[dict]:
    resp = _get("/sources")
    return resp.json() if resp and resp.status_code == 200 else []


def delete_source(source_url: str) -> bool:
    resp = _delete("/ingest/upload", params={"source_url": source_url})
    return resp is not None and resp.status_code == 200


def _enqueue(url: str, source_type: str) -> str | None:
    resp = _post("/ingest", json={"source_url": url, "source_type": source_type})
    if resp and resp.status_code == 202:
        return resp.json()["job_id"]
    st.error(f"Failed ({resp.status_code if resp else 'no connection'}): "
             f"{resp.text if resp else 'ingestion service unreachable'}")
    return None


def upload_file(file_bytes: bytes, filename: str) -> str | None:
    try:
        resp = requests.post(
            f"{INGESTION_URL}/ingest/upload",
            files={"file": (filename, file_bytes, "application/octet-stream")},
            headers=_h(),
            timeout=30,
        )
    except requests.exceptions.ConnectionError:
        st.error("Ingestion service unreachable")
        return None
    if resp.status_code == 202:
        return resp.json()["job_id"]
    st.error(f"Upload failed ({resp.status_code}): {resp.text}")
    return None


def poll_job(job_id: str) -> str:
    resp = _get(f"/ingest/{job_id}")
    if resp and resp.status_code == 200:
        return resp.json()["status"]
    return "unknown"


# ── Query helper ──────────────────────────────────────────────────────────────

def ask(question: str) -> dict | None:
    resp = _post(
        "/query",
        base=QUERY_URL,
        json={
            "query": question,
            "stream": False,
            "conversation_id": st.session_state.conversation_id,
        },
    )
    if resp and resp.status_code == 200:
        return resp.json()
    st.error(
        f"Query failed ({resp.status_code if resp else 'no connection'}): "
        f"{resp.text if resp else 'query service unreachable'}"
    )
    return None


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🤖 Kapa RAG")
    st.caption("Ask questions about your indexed documentation")

    # API Key
    with st.expander("🔑 API Key", expanded=False):
        new_key = st.text_input(
            "Bearer token",
            value=st.session_state.api_key,
            type="password",
            label_visibility="collapsed",
        )
        if new_key != st.session_state.api_key:
            st.session_state.update(api_key=new_key, conversation_id=None, messages=[])
            st.rerun()

    st.divider()

    # Add knowledge sources
    st.subheader("📚 Add Knowledge Source")
    tab_upload, tab_github, tab_docs = st.tabs(["Upload", "GitHub", "Docs URL"])

    with tab_upload:
        uploaded = st.file_uploader(
            "PDF or Markdown",
            type=["pdf", "md"],
            label_visibility="collapsed",
        )
        if st.button("Ingest File", key="btn_upload", disabled=uploaded is None):
            job_id = upload_file(uploaded.read(), uploaded.name)
            if job_id:
                st.session_state.pending_jobs.append(
                    {"job_id": job_id, "label": uploaded.name, "status": "pending"}
                )
                st.success(f"Queued: {uploaded.name}")

    with tab_github:
        gh_url = st.text_input(
            "GitHub repo URL",
            placeholder="https://github.com/org/repo",
            key="gh_url",
        )
        if st.button("Ingest Repo", key="btn_github"):
            if gh_url.strip():
                job_id = _enqueue(gh_url.strip(), "github")
                if job_id:
                    st.session_state.pending_jobs.append(
                        {"job_id": job_id, "label": gh_url.strip(), "status": "pending"}
                    )
                    st.success("Repo queued")
            else:
                st.warning("Enter a GitHub URL first")

    with tab_docs:
        docs_url = st.text_input(
            "Documentation URL",
            placeholder="https://docs.example.com",
            key="docs_url",
        )
        if st.button("Ingest Docs", key="btn_docs"):
            if docs_url.strip():
                job_id = _enqueue(docs_url.strip(), "docs_site")
                if job_id:
                    st.session_state.pending_jobs.append(
                        {"job_id": job_id, "label": docs_url.strip(), "status": "pending"}
                    )
                    st.success("Docs queued")
            else:
                st.warning("Enter a docs URL first")

    # Pending jobs
    if st.session_state.pending_jobs:
        st.divider()
        st.subheader("⚙️ Processing Jobs")
        active = []
        for job in st.session_state.pending_jobs:
            job["status"] = poll_job(job["job_id"])
            icon = {"pending": "⏳", "processing": "🔄", "completed": "✅", "failed": "❌"}.get(
                job["status"], "❓"
            )
            label = job["label"]
            short = (label[:32] + "…") if len(label) > 32 else label
            st.caption(f"{icon} {short}")
            if job["status"] not in ("completed", "failed"):
                active.append(job)
        st.session_state.pending_jobs = active

    st.divider()

    # Indexed sources
    st.subheader("📋 Indexed Sources")
    col_r, _ = st.columns([1, 3])
    if col_r.button("↻ Refresh", key="btn_refresh"):
        st.rerun()

    sources = list_sources()
    if not sources:
        st.caption("No sources indexed yet")
    else:
        for src in sources:
            url = src["source_url"]
            stype = src["source_type"]
            icon = "📄" if stype == "pdf" else "🐙" if stype == "github" else "🌐"
            name = url.split("/")[-1] or url
            name = (name[:26] + "…") if len(name) > 26 else name
            c1, c2 = st.columns([5, 1])
            c1.caption(f"{icon} {name}")
            if c2.button("✕", key=f"del_{url}", help=f"Delete {url}"):
                if delete_source(url):
                    st.success("Deleted")
                    st.rerun()
                else:
                    st.error("Delete failed")


# ── Main chat area ─────────────────────────────────────────────────────────────

h_col, btn_col = st.columns([6, 1])
h_col.title("Chat with your Docs")
if btn_col.button("New Chat", type="secondary"):
    st.session_state.update(conversation_id=None, messages=[])
    st.rerun()

# Render conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            srcs = msg.get("source_urls", [])
            if srcs:
                with st.expander(f"📎 Sources ({len(srcs)})"):
                    for u in srcs:
                        st.markdown(f"- {u}")
            if msg.get("cached"):
                st.caption("⚡ Cached response")

# Chat input
if prompt := st.chat_input("Ask a question about your docs…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            result = ask(prompt)

        if result:
            st.session_state.conversation_id = result["conversation_id"]
            st.markdown(result["answer"])

            srcs = result.get("source_urls", [])
            if srcs:
                with st.expander(f"📎 Sources ({len(srcs)})"):
                    for u in srcs:
                        st.markdown(f"- {u}")

            if result.get("cached"):
                st.caption("⚡ Cached response")

            st.session_state.messages.append({
                "role": "assistant",
                "content": result["answer"],
                "source_urls": srcs,
                "cached": result.get("cached", False),
            })
        else:
            fallback = "Could not get a response. Ensure query service is running (`docker compose up`)."
            st.error(fallback)
            st.session_state.messages.append({
                "role": "assistant",
                "content": fallback,
                "source_urls": [],
                "cached": False,
            })
