"""
Chainlit UI for Jenkins RCA — BAT.AI
Wraps the FastAPI backend. Supports log file upload + multi-turn Q&A.
"""
import os
import httpx
import chainlit as cl

API_URL = os.getenv("API_URL", "http://api:8000")


@cl.on_chat_start
async def start():
    await cl.Message(content=(
        "## 🔍 Jenkins RCA — BAT.AI\n\n"
        "Multi-agent self-corrective RAG for Jenkins log root-cause analysis.\n\n"
        "**Pipeline:** Retrieve (BM25 + FAISS) → Rerank → Grade → Generate → Self-correct\n\n"
        "---\n"
        "**How to use:**\n"
        "1. Click **📎** and upload your Jenkins `.log` / `.txt` file\n"
        "2. Ask a question:\n"
        "   - *What caused the build failure?*\n"
        "   - *Analyze the log file and find the failure messages*\n"
        "   - *What are the critical errors in the log file?*\n"
        "   - *Why did the Maven tests fail?*\n\n"
        "The log stays loaded for the session — ask follow-up questions freely."
    )).send()

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            r    = await client.get(f"{API_URL}/api/health")
            data = r.json()
        icon = "✅" if data.get("ollama") == "ok" else "⚠️"
        await cl.Message(content=(
            f"{icon} **Backend:** Ollama `{data.get('ollama')}` · "
            f"LLM `{data.get('llm_model')}` · "
            f"Embed `{data.get('embed_model')}`"
        )).send()
    except Exception:
        await cl.Message(
            content="⚠️ Cannot reach API — is the stack running? (`make up`)"
        ).send()


@cl.on_message
async def message(msg: cl.Message):
    # Resolve log file
    log_path = None
    if msg.elements:
        for el in msg.elements:
            if hasattr(el, "path") and el.path:
                cl.user_session.set("log_path", el.path)
                log_path = el.path
                break
    if not log_path:
        log_path = cl.user_session.get("log_path")

    if not log_path:
        await cl.Message(content=(
            "📎 **No log file loaded.**\n\n"
            "Use the attachment button to upload a Jenkins log file first."
        )).send()
        return

    question = msg.content.strip()
    if not question:
        await cl.Message(content="Please type a question about the log.").send()
        return

    status = cl.Message(content=(
        "⏳ **Running BAT.AI pipeline…**\n\n"
        "```\n"
        "Retrieve (BM25 + FAISS)\n"
        "  → Rerank\n"
        "  → Grade documents\n"
        "  → Generate\n"
        "  → Self-correct if needed (max 2 retries)\n"
        "```"
    ))
    await status.send()

    try:
        with open(log_path, "rb") as fh:
            raw = fh.read()

        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                f"{API_URL}/api/analyze",
                files={"log_file": ("jenkins.log", raw, "text/plain")},
                data={"question": question},
            )

        await status.remove()

        if resp.status_code != 200:
            detail = resp.json().get("detail", resp.text)
            await cl.Message(
                content=f"❌ **API error {resp.status_code}:** {detail}"
            ).send()
            return

        data      = resp.json()
        answer    = data.get("answer", "")
        documents = data.get("documents", [])
        final_q   = data.get("question", question)

        md = f"## 🩺 Root Cause Analysis\n\n{answer}\n\n"

        if final_q != question:
            md += f"> **Refined query used:** _{final_q}_\n\n"

        if documents:
            md += f"---\n### 📄 Evidence ({len(documents)} excerpt(s))\n\n"
            for i, doc in enumerate(documents[:5], 1):
                meta  = doc.get("metadata", {})
                src   = meta.get("source", "")
                snip  = doc["content"][:800].replace("```", "'''")
                md += (
                    f"<details>\n"
                    f"<summary>📋 Excerpt {i}"
                    f"{' — ' + src if src else ''}</summary>\n\n"
                    f"```\n{snip}\n```\n\n"
                    f"</details>\n\n"
                )

        await cl.Message(content=md).send()

    except httpx.TimeoutException:
        await status.remove()
        await cl.Message(content=(
            "⏱️ **Timed out.** The log may be large or the model still loading. "
            "Try again in a moment."
        )).send()
    except Exception as exc:
        await status.remove()
        await cl.Message(content=f"❌ **Error:** {exc}").send()
