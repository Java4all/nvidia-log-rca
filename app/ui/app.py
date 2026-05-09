"""
Chainlit UI — Jenkins RCA / BAT.AI
Target users: QA engineers

Key features:
  - Log file upload (drag & drop or attach)
  - Live agent step display as pipeline runs
  - Structured RCA output: Summary, Key Issues, Evidence, Recommendations
  - Session memory: log stays loaded, ask follow-up questions
  - Quick question buttons for common QA queries
  - Build info panel showing log filename + line count
"""
import os
import json
import httpx
import chainlit as cl

API_URL = os.getenv("API_URL", "http://api:8000")
# Match API cap (docker default 50 MB); Chainlit AskFileMessage allows at most 100 MB.
_MAX_LOG_MB = min(100, int(os.getenv("MAX_LOG_MB", "50")))

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

# Step display config: node → (emoji, short label, colour hint for QA context)
STEP_CONFIG = {
    "retrieve":        ("🔍", "Searching log",        "Hybrid BM25 + FAISS retrieval"),
    "rerank":          ("📊", "Ranking results",       "Scoring by relevance"),
    "grade_documents": ("✅", "Grading chunks",        "Filtering irrelevant content"),
    "generate":        ("🤖", "Writing RCA",           "LLM generating root cause analysis"),
    "transform_query": ("🔄", "Refining query",        "Self-correcting — rewriting for better retrieval"),
}


# ── Session start ─────────────────────────────────────────────────────────────

@cl.on_chat_start
async def start():
    cl.user_session.set("log_path",  None)
    cl.user_session.set("log_name",  None)
    cl.user_session.set("log_lines", None)

    # Dedicated upload widget (Browse / drag-drop). Composer may not show a paperclip icon.
    uploaded = await cl.AskFileMessage(
        content=(
            "## 🔍 Jenkins RCA — BAT.AI\n\n"
            "Upload a Jenkins log (`.log` or `.txt`) using the **drag-and-drop area** "
            "or **Browse** below — this app analyses build failures with a self-corrective "
            "multi-agent RAG pipeline.\n\n"
            "_After your log is loaded you can ask follow-up questions without uploading again._"
        ),
        accept={
            "text/plain": [".log", ".txt", ".text"],
            "application/octet-stream": [".log"],
        },
        max_size_mb=_MAX_LOG_MB,
        max_files=1,
        timeout=600,
        raise_on_timeout=False,
    ).send()

    if not uploaded:
        await cl.Message(
            content="⚠️ No log file was received. Refresh the page to upload your Jenkins log."
        ).send()
        return

    await _apply_log_session(uploaded[0].path, uploaded[0].name)

    # Show quick question buttons
    actions = [
        cl.Action(name="quick_q", value=q, label=q)
        for q in QA_QUICK_QUESTIONS
    ]
    await cl.Message(
        content="**Common QA questions — click to ask:**",
        actions=actions,
    ).send()

    # Health check
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r    = await client.get(f"{API_URL}/api/health")
            data = r.json()
        icon = "✅" if data.get("ollama") == "ok" else "⚠️"
        await cl.Message(content=(
            f"{icon} **System:** "
            f"LLM `{data.get('llm_model')}` · "
            f"Embed `{data.get('embed_model')}` · "
            f"Ollama `{data.get('ollama')}`"
        )).send()
    except Exception:
        await cl.Message(
            content="⚠️ Cannot reach API backend. Is the stack running? (`make up`)"
        ).send()


# ── Quick question buttons ────────────────────────────────────────────────────

@cl.action_callback("quick_q")
async def on_quick_question(action: cl.Action):
    """Handle quick question button click — run as if user typed it."""
    await run_analysis(action.value)


# ── Message handler ───────────────────────────────────────────────────────────

@cl.on_message
async def on_message(msg: cl.Message):
    # Check for new log file attachment
    if msg.elements:
        for el in msg.elements:
            if hasattr(el, "path") and el.path:
                await _handle_log_upload(el)
                # If message also has text, run analysis on it
                if msg.content.strip():
                    await run_analysis(msg.content.strip())
                return

    # Plain question — run analysis with existing log
    await run_analysis(msg.content.strip())


async def _apply_log_session(log_path: str, log_name: str):
    """Store log path in session and confirm to the user."""
    try:
        with open(log_path, "r", errors="replace") as f:
            content = f.read()
        line_count = len(content.splitlines())
    except Exception:
        line_count = 0

    cl.user_session.set("log_path",  log_path)
    cl.user_session.set("log_name",  log_name)
    cl.user_session.set("log_lines", line_count)

    await cl.Message(content=(
        f"📂 **Log loaded:** `{log_name}`\n"
        f"📏 **Lines:** {line_count:,}\n\n"
        "Ask a question or use a quick question below to analyse this log."
    )).send()


async def _handle_log_upload(el):
    """Process a log attached on a follow-up message (same session)."""
    log_path = el.path
    log_name = getattr(el, "name", os.path.basename(log_path))
    await _apply_log_session(log_path, log_name)


# ── Core analysis function ────────────────────────────────────────────────────

async def run_analysis(question: str):
    """Stream the BAT.AI pipeline and display steps + result to QA engineer."""

    # Validate inputs
    if not question:
        await cl.Message(content="Please type a question about the log.").send()
        return

    log_path = cl.user_session.get("log_path")
    log_name = cl.user_session.get("log_name") or "jenkins.log"
    if not log_path:
        await cl.Message(content=(
            "📎 **No log file loaded.**\n\n"
            "Attach your Jenkins log file first using the 📎 button."
        )).send()
        return

    # ── Pipeline step tracking ────────────────────────────────────────────────
    steps_done  = []
    retry_count = 0

    # Outer step container — shows overall pipeline progress
    pipeline_msg = cl.Message(content="")
    await pipeline_msg.send()

    def _render_pipeline(current_step=None, done=False, error=None):
        """Render the live pipeline progress box."""
        all_steps = ["retrieve", "rerank", "grade_documents", "generate"]
        lines = ["**⚙️ BAT.AI Pipeline**\n"]

        if retry_count > 0:
            lines.append(f"> 🔄 Self-correction loop — attempt {retry_count + 1}\n")

        for step in all_steps:
            emoji, label, _ = STEP_CONFIG.get(step, ("⚙️", step, ""))
            if step in steps_done:
                lines.append(f"- ~~{label}~~ ✓")
            elif step == current_step:
                lines.append(f"- **{emoji} {label}…**")
            else:
                lines.append(f"- {label}")

        if error:
            lines.append(f"\n❌ **Error:** {error}")
        elif done:
            lines.append("\n✅ **Complete**")

        return "\n".join(lines)

    # ── Stream pipeline via SSE ───────────────────────────────────────────────
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
                        err  = json.loads(body).get("detail", body.decode())
                        await pipeline_msg.remove()
                        await cl.Message(
                            content=f"❌ **API error {resp.status_code}:** {err}"
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
                                retry_count += 1
                                for s in ["retrieve", "rerank", "grade_documents"]:
                                    if s in steps_done:
                                        steps_done.remove(s)

                            pipeline_msg.content = _render_pipeline(current_step=node)
                            await pipeline_msg.update()

                            icon, label, detail = STEP_CONFIG.get(
                                node, ("⚙️", node, "")
                            )
                            async with cl.Step(name=f"{icon} {label}") as step:
                                step.output = detail
                                if node == "transform_query":
                                    step.output = (
                                        f"{detail}\n\n"
                                        f"_Original:_ {question}"
                                    )

                            if node not in steps_done and node != "transform_query":
                                steps_done.append(node)

                        elif etype == "result":
                            result_data = event
                            pipeline_msg.content = _render_pipeline(done=True)
                            await pipeline_msg.update()

                        elif etype == "error":
                            pipeline_msg.content = _render_pipeline(
                                error=event.get("message", "Unknown error")
                            )
                            await pipeline_msg.update()
                            return
                finally:
                    try:
                        await resp.aread()
                    except Exception:
                        pass

    except httpx.TimeoutException:
        pipeline_msg.content = _render_pipeline(error="Request timed out")
        await pipeline_msg.update()
        await cl.Message(content=(
            "⏱️ **Timed out.** The log may be large or the model is still loading. "
            "Try again in a moment, or try a smaller/faster model."
        )).send()
        return
    except Exception as exc:
        pipeline_msg.content = _render_pipeline(error=str(exc))
        await pipeline_msg.update()
        await cl.Message(content=f"❌ **Unexpected error:** {exc}").send()
        return

    if not result_data:
        await cl.Message(content="⚠️ No result received from pipeline.").send()
        return

    # ── Format and display RCA result ─────────────────────────────────────────
    answer    = result_data.get("answer", "")
    documents = result_data.get("documents", [])
    final_q   = result_data.get("question", question)

    md = "## 🩺 Root Cause Analysis\n\n"

    # Show if query was refined by self-correction
    if final_q != question:
        md += f"> 🔄 **Query refined to:** _{final_q}_\n\n"

    md += f"{answer}\n\n"

    # Evidence section — collapsible log excerpts with line metadata
    if documents:
        md += f"---\n### 📄 Supporting Evidence — {len(documents)} log excerpt(s)\n\n"
        for i, doc in enumerate(documents[:5], 1):
            meta   = doc.get("metadata", {})
            source = meta.get("source", "")
            snip   = doc["content"][:1000].replace("```", "'''")
            caption = f"Excerpt {i}"
            if source:
                caption += f" — `{os.path.basename(source)}`"

            md += (
                f"<details>\n"
                f"<summary>📋 {caption}</summary>\n\n"
                f"```\n{snip}\n```\n\n"
                f"</details>\n\n"
            )

    # Show retry info for QA engineers
    if retry_count > 0:
        md += (
            f"\n---\n"
            f"_Pipeline ran {retry_count} self-correction loop(s) "
            f"to improve retrieval quality._"
        )

    await cl.Message(content=md).send()

    # Refresh quick question buttons after each answer
    actions = [
        cl.Action(name="quick_q", value=q, label=q)
        for q in QA_QUICK_QUESTIONS
    ]
    await cl.Message(
        content="**Ask another question:**",
        actions=actions,
    ).send()
