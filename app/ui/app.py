"""
Chainlit UI — Log-RCA
Target users: QA and engineering teams

Key features:
  - Log file upload (drag & drop or attach)
  - Live agent step display as pipeline runs
  - Structured RCA output: Summary, Key Issues, Evidence, Recommendations
  - Session memory: log stays loaded, ask follow-up questions
  - Quick question buttons for common QA queries
  - Replace log, export last report, build info panel
"""
import os
import json
import tempfile
from typing import List, Optional

import httpx
import chainlit as cl

API_URL = os.getenv("API_URL", "http://api:8000")
# Match API cap (docker default 50 MB); Chainlit AskFileMessage allows at most 100 MB.
_MAX_LOG_MB = min(100, int(os.getenv("MAX_LOG_MB", "50")))
_EVIDENCE_MAX = max(1, int(os.getenv("EVIDENCE_MAX_CHUNKS", "8")))
_EVIDENCE_CHARS = max(200, int(os.getenv("EVIDENCE_PREVIEW_CHARS", "1500")))

# Avoid HTTP/2 + helps prevent httpcore/anyio cancel-scope teardown races with Chainlit.
_HTTPX_TIMEOUT = httpx.Timeout(600.0, connect=30.0)
_HTTPX_TRANSPORT = httpx.AsyncHTTPTransport(http2=False)

# Common QA questions shown as quick-action buttons
QA_QUICK_QUESTIONS = [
    "What caused the build failure?",
    "List all ERROR and EXCEPTION messages",
    "Which test cases failed and why?",
    "What is the root cause of the failure?",
    "Are there any timeout or connection errors?",
    "Summarise this log in 5 bullet points",
]

# Step display: node → (icon, short label, detail for sidebar)
STEP_CONFIG = {
    "retrieve":        ("🔍", "Retrieve",           "Hybrid BM25 + FAISS retrieval"),
    "rerank":          ("📊", "Rank",               "Cross-encoder relevance scoring"),
    "grade_documents": ("✅", "Grade",              "Filter irrelevant chunks"),
    "transform_query": ("🔄", "Refine query",       "Rewrite query for better retrieval"),
    "generate":        ("🤖", "Analyze",            "Root cause narrative"),
}

_ACCEPT_FILES = {
    "text/plain": [".log", ".txt", ".text"],
    "application/octet-stream": [".log"],
}


def _toolbar_actions(include_export: bool) -> list:
    """Quick questions + replace log (+ export when a report exists)."""
    actions = [
        cl.Action(name="replace_log", value="1", label="Replace log"),
    ]
    if include_export:
        actions.append(cl.Action(name="export_report", value="1", label="Export last report"))
    actions.extend(
        cl.Action(name="quick_q", value=q, label=q) for q in QA_QUICK_QUESTIONS
    )
    return actions


async def _send_toolbar(content: str, *, include_export: bool) -> None:
    await cl.Message(
        content=content,
        actions=_toolbar_actions(include_export=include_export),
    ).send()


def _render_pipeline(
    *,
    steps_done: List[str],
    current_step: Optional[str] = None,
    done: bool = False,
    error: Optional[str] = None,
    refine_used: bool = False,
    retry_count: int = 0,
) -> str:
    """Render the live pipeline checklist (includes optional refine step)."""
    order = [
        "retrieve",
        "rerank",
        "grade_documents",
        "transform_query",
        "generate",
    ]
    lines = ["### Analysis pipeline", ""]

    if retry_count > 0:
        lines.append(
            f"> Self-correction round **{retry_count}** — retrieval runs again "
            "with a refined query.\n"
        )

    lines.append("*Large logs: first-time indexing may take several minutes.*\n")

    for step in order:
        icon, label, _ = STEP_CONFIG.get(step, ("·", step, ""))
        if step == "transform_query" and done and not refine_used:
            lines.append(f"- ~~{icon} {label}~~ — _not needed_")
            continue
        if step in steps_done:
            lines.append(f"- ~~{icon} {label}~~ ✓")
        elif step == current_step:
            lines.append(f"- **{icon} {label}** …")
        else:
            lines.append(f"- {icon} {label}")

    if error:
        lines.append(f"\n**Error:** {error}")
    elif done:
        lines.append("\n**Complete**")

    return "\n".join(lines)


def _build_report_markdown(
    *,
    question: str,
    final_q: str,
    answer: str,
    documents: List[dict],
    refine_used: bool,
    retry_count: int,
) -> str:
    """Full markdown report for display, copy, and export."""
    md = "## Root cause analysis\n\n"

    if final_q != question:
        md += f"> **Refined query:** _{final_q}_\n\n"

    md += f"{answer.strip()}\n\n"

    if documents:
        show = documents[:_EVIDENCE_MAX]
        extra = len(documents) - len(show)
        md += (
            f"---\n### Supporting evidence "
            f"— {len(show)} excerpt(s)"
            f"{f' ({extra} more not shown)' if extra else ''}\n\n"
        )
        for i, doc in enumerate(show, 1):
            meta = doc.get("metadata", {})
            source = meta.get("source", "")
            raw = doc.get("content") or ""
            snip = raw[:_EVIDENCE_CHARS].replace("```", "'''")
            if len(raw) > _EVIDENCE_CHARS:
                snip += "\n… _(truncated)_"
            title = f"Excerpt {i}"
            if source:
                title += f" — `{os.path.basename(source)}`"
            md += f"#### {title}\n\n```\n{snip}\n```\n\n"

    if retry_count > 0:
        md += (
            "\n---\n_Self-correction: "
            f"{retry_count} retrieval refinement loop(s)._"
        )

    return md


# ── Session start ─────────────────────────────────────────────────────────────


@cl.on_chat_start
async def start():
    cl.user_session.set("log_path", None)
    cl.user_session.set("log_name", None)
    cl.user_session.set("log_lines", None)
    cl.user_session.set("last_report_md", None)

    uploaded = await cl.AskFileMessage(
        content=(
            "## Log-RCA\n\n"
            "Upload a build log (`.log` or `.txt`) via **Browse** or drag-and-drop. "
            "The service analyses failures using retrieval-augmented multi-step reasoning.\n\n"
            "**Tip:** After the first upload you can **Replace log** from the buttons "
            "below or attach a new file in the composer.\n\n"
            "_Follow-up questions reuse the same log until you replace it._"
        ),
        accept=_ACCEPT_FILES,
        max_size_mb=_MAX_LOG_MB,
        max_files=1,
        timeout=600,
        raise_on_timeout=False,
    ).send()

    if not uploaded:
        await cl.Message(
            content="No log file was received. Refresh the page to upload a build log."
        ).send()
        return

    await _apply_log_session(uploaded[0].path, uploaded[0].name)

    await _send_toolbar(
        "**Common questions** — click a button or type your own:",
        include_export=False,
    )

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r = await client.get(f"{API_URL}/api/health")
            data = r.json()
        ok = data.get("ollama") == "ok"
        status = "**Ready** — models reachable" if ok else "**Degraded** — check Ollama"
        be = data.get("llm_backend", "ollama")
        await cl.Message(
            content=(
                f"{status}  \n"
                f"_Backend `{be}` · LLM `{data.get('llm_model')}` · "
                f"Embed `{data.get('embed_model')}` · Ollama status `{data.get('ollama')}`_"
            )
        ).send()
    except Exception:
        await cl.Message(
            content=(
                "**Cannot reach the API.** "
                "Confirm `api` and `ollama` services are up (e.g. `docker compose ps`)."
            )
        ).send()


# ── Actions ───────────────────────────────────────────────────────────────────


@cl.action_callback("quick_q")
async def on_quick_question(action: cl.Action):
    await run_analysis(action.value)


@cl.action_callback("replace_log")
async def on_replace_log(action: cl.Action):
    uploaded = await cl.AskFileMessage(
        content="## Replace log\n\nChoose a new `.log` or `.txt` file.",
        accept=_ACCEPT_FILES,
        max_size_mb=_MAX_LOG_MB,
        max_files=1,
        timeout=600,
        raise_on_timeout=False,
    ).send()
    if not uploaded:
        await cl.Message(content="Replace cancelled — previous log is still loaded.").send()
        return
    await _apply_log_session(uploaded[0].path, uploaded[0].name)
    cl.user_session.set("last_report_md", None)
    await _send_toolbar(
        "**Log replaced.** Ask a question below.",
        include_export=False,
    )


@cl.action_callback("export_report")
async def on_export_report(action: cl.Action):
    md = cl.user_session.get("last_report_md")
    if not md:
        await cl.Message(
            content="No report to export yet — run an analysis first."
        ).send()
        return
    fd, path = tempfile.mkstemp(suffix=".md", prefix="log-rca-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(md)
        await cl.Message(
            content="**Download** — Markdown report attached.",
            elements=[
                cl.File(
                    name="log-rca-report.md",
                    path=path,
                    display="inline",
                )
            ],
        ).send()
        if len(md) <= 28000:
            await cl.Message(
                content=(
                    "---\n### Copy as Markdown\n\n"
                    f"```markdown\n{md}\n```"
                )
            ).send()
        else:
            await cl.Message(
                content=(
                    "_Report is long — use the **download** above for the full file._"
                )
            ).send()
    except Exception as exc:
        await cl.Message(content=f"Export failed: {exc}").send()


# ── Message handler ───────────────────────────────────────────────────────────


@cl.on_message
async def on_message(msg: cl.Message):
    if msg.elements:
        for el in msg.elements:
            if hasattr(el, "path") and el.path:
                await _handle_log_upload(el)
                if msg.content.strip():
                    await run_analysis(msg.content.strip())
                return

    await run_analysis(msg.content.strip())


async def _apply_log_session(log_path: str, log_name: str):
    try:
        with open(log_path, "r", errors="replace") as f:
            content = f.read()
        line_count = len(content.splitlines())
    except Exception:
        line_count = 0

    cl.user_session.set("log_path", log_path)
    cl.user_session.set("log_name", log_name)
    cl.user_session.set("log_lines", line_count)

    await cl.Message(
        content=(
            f"**Log:** `{log_name}`  \n"
            f"**Lines:** {line_count:,}\n\n"
            "Ask a question or pick a shortcut."
        )
    ).send()


async def _handle_log_upload(el):
    log_path = el.path
    log_name = getattr(el, "name", os.path.basename(log_path))
    await _apply_log_session(log_path, log_name)


# ── Core analysis ─────────────────────────────────────────────────────────────


async def run_analysis(question: str):
    if not question:
        await cl.Message(content="Please enter a question about the log.").send()
        return

    log_path = cl.user_session.get("log_path")
    log_name = cl.user_session.get("log_name") or "jenkins.log"
    if not log_path:
        await cl.Message(
            content=(
                "**No log loaded.** Use **Replace log**, attach a file in the composer, "
                "or refresh and upload again."
            )
        ).send()
        return

    steps_done: List[str] = []
    retry_count = 0
    refine_used = False

    pipeline_msg = cl.Message(
        content=_render_pipeline(
            steps_done=[],
            current_step=None,
            refine_used=False,
            retry_count=0,
        )
        + "\n\n_Starting…_"
    )
    await pipeline_msg.send()

    result_data = None

    try:
        with open(log_path, "rb") as fh:
            raw = fh.read()

        async with httpx.AsyncClient(
            timeout=_HTTPX_TIMEOUT,
            transport=_HTTPX_TRANSPORT,
        ) as client:
            async with client.stream(
                "POST",
                f"{API_URL}/api/analyze/stream",
                files={"log_file": (log_name, raw, "text/plain")},
                data={"question": question},
            ) as resp:
                try:
                    if resp.status_code != 200:
                        body = await resp.aread()
                        try:
                            err = json.loads(body).get("detail", body.decode())
                        except Exception:
                            err = body.decode(errors="replace")
                        await pipeline_msg.remove()
                        await cl.Message(
                            content=f"**API error {resp.status_code}:** {err}"
                        ).send()
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        event = json.loads(line[6:])
                        etype = event.get("type")

                        if etype == "step":
                            node = event["node"]

                            if node == "transform_query":
                                refine_used = True
                                retry_count += 1
                                for s in ("retrieve", "rerank", "grade_documents"):
                                    if s in steps_done:
                                        steps_done.remove(s)

                            pipeline_msg.content = _render_pipeline(
                                steps_done=steps_done,
                                current_step=node,
                                refine_used=refine_used,
                                retry_count=retry_count,
                            )
                            await pipeline_msg.update()

                            icon, label, detail = STEP_CONFIG.get(
                                node, ("·", node, "")
                            )
                            async with cl.Step(name=f"{icon} {label}") as step:
                                step.output = detail
                                if node == "transform_query":
                                    step.output = (
                                        f"{detail}\n\n_Original question:_ {question}"
                                    )

                            if node not in steps_done:
                                steps_done.append(node)

                        elif etype == "result":
                            result_data = event
                            pipeline_msg.content = _render_pipeline(
                                steps_done=steps_done,
                                done=True,
                                refine_used=refine_used,
                                retry_count=retry_count,
                            )
                            await pipeline_msg.update()

                        elif etype == "error":
                            pipeline_msg.content = _render_pipeline(
                                steps_done=steps_done,
                                error=event.get("message", "Unknown error"),
                                refine_used=refine_used,
                                retry_count=retry_count,
                            )
                            await pipeline_msg.update()
                            return
                finally:
                    try:
                        await resp.aread()
                    except Exception:
                        pass

    except httpx.TimeoutException:
        pipeline_msg.content = _render_pipeline(
            steps_done=steps_done,
            error="Request timed out",
            refine_used=refine_used,
            retry_count=retry_count,
        )
        await pipeline_msg.update()
        await cl.Message(
            content=(
                "**Timed out.** The log may be very large or the model still loading. "
                "Retry in a moment or use a smaller `LLM_MODEL`."
            )
        ).send()
        return
    except Exception as exc:
        pipeline_msg.content = _render_pipeline(
            steps_done=steps_done,
            error=str(exc),
            refine_used=refine_used,
            retry_count=retry_count,
        )
        await pipeline_msg.update()
        await cl.Message(content=f"**Unexpected error:** {exc}").send()
        return

    if not result_data:
        await cl.Message(content="No result returned from the pipeline.").send()
        return

    answer = result_data.get("answer", "")
    documents = result_data.get("documents", [])
    final_q = result_data.get("question", question)

    md = _build_report_markdown(
        question=question,
        final_q=final_q,
        answer=answer,
        documents=documents,
        refine_used=refine_used,
        retry_count=retry_count,
    )
    cl.user_session.set("last_report_md", md)

    await cl.Message(content=md).send()

    await _send_toolbar(
        "**Ask another question** — or export the report above.",
        include_export=True,
    )

