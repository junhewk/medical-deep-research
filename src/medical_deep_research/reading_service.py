"""Reading session service — RAG-based reading helper for ranked studies."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator

from sqlmodel import col, select

from .models import (
    ArtifactType,
    EventType,
    ReadingChatMessage,
    ReadingHighlight,
    ReadingSession,
    ResearchArtifact,
    ResearchRun,
    ResearchStatus,
    RuntimeEvent,
    utcnow,
)
from .persistence import AppDatabase
from .rag import PaperIndex
from .research.models import ScoredStudy

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ReadingService:
    def __init__(self, database: AppDatabase) -> None:
        self.database = database
        self._paper_indices: dict[str, PaperIndex] = {}  # "{run_id}:{ref_num}"

    # -- Session lifecycle --------------------------------------------------

    def get_or_create_session(self, run_id: str) -> ReadingSession | None:
        """Return existing session for *run_id*, or create one if the run is
        completed and has ranked results."""
        with self.database.session() as session:
            existing = session.exec(
                select(ReadingSession).where(ReadingSession.run_id == run_id)
            ).first()
            if existing:
                existing.last_accessed_at = utcnow()
                session.commit()
                session.refresh(existing)
                return existing

            run = session.get(ResearchRun, run_id)
            if not run or run.status != ResearchStatus.COMPLETED.value:
                return None

            artifact = session.exec(
                select(ResearchArtifact).where(
                    ResearchArtifact.run_id == run_id,
                    ResearchArtifact.artifact_type == ArtifactType.RANKED_RESULTS.value,
                )
            ).first()
            if not artifact or not artifact.content_json:
                return None

            reading = ReadingSession(run_id=run_id)
            session.add(reading)
            session.commit()
            session.refresh(reading)
            return reading

    def get_session(self, session_id: str) -> ReadingSession | None:
        with self.database.session() as session:
            return session.get(ReadingSession, session_id)

    # -- Study data (from artifacts) ----------------------------------------

    def get_ranked_studies(self, run_id: str) -> list[ScoredStudy]:
        with self.database.session() as session:
            artifact = session.exec(
                select(ResearchArtifact).where(
                    ResearchArtifact.run_id == run_id,
                    ResearchArtifact.artifact_type == ArtifactType.RANKED_RESULTS.value,
                )
            ).first()
            if not artifact or not artifact.content_json:
                return []

        data = json.loads(artifact.content_json)
        raw_studies = data if isinstance(data, list) else data.get("studies", [])
        studies: list[ScoredStudy] = []
        for item in raw_studies:
            try:
                studies.append(ScoredStudy.model_validate(item))
            except Exception:
                continue
        return studies

    def get_study(self, run_id: str, ref_num: int) -> ScoredStudy | None:
        for s in self.get_ranked_studies(run_id):
            if s.reference_number == ref_num:
                return s
        return None

    # -- Fulltext retrieval (from runtime events) ---------------------------

    def get_fulltext(self, run_id: str, ref_num: int) -> str | None:
        """Get fulltext from: 1) user-uploaded artifacts, 2) runtime parse_pdf events."""
        # Check user-uploaded / on-demand stored fulltext first
        artifact_name = f"fulltext_study_{ref_num}"
        with self.database.session() as session:
            artifact = session.exec(
                select(ResearchArtifact).where(
                    ResearchArtifact.run_id == run_id,
                    ResearchArtifact.name == artifact_name,
                )
            ).first()
            if artifact and artifact.content_text:
                return artifact.content_text

        # Then check runtime events from the research run
        with self.database.session() as session:
            events = session.exec(
                select(RuntimeEvent).where(
                    RuntimeEvent.run_id == run_id,
                    RuntimeEvent.event_type == EventType.TOOL_RESULT.value,
                ).order_by(col(RuntimeEvent.sequence))
            ).all()

        for event in events:
            if not event.tool_name or "parse_pdf" not in event.tool_name:
                continue
            if not event.payload_json:
                continue
            try:
                payload = json.loads(event.payload_json)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                if payload.get("rank") == ref_num and payload.get("fulltext"):
                    return payload["fulltext"]
        return None

    def store_fulltext(self, run_id: str, ref_num: int, text: str) -> None:
        """Persist user-uploaded or on-demand fulltext as an artifact."""
        artifact_name = f"fulltext_study_{ref_num}"
        with self.database.session() as session:
            existing = session.exec(
                select(ResearchArtifact).where(
                    ResearchArtifact.run_id == run_id,
                    ResearchArtifact.name == artifact_name,
                )
            ).first()
            if existing:
                existing.content_text = text
            else:
                session.add(ResearchArtifact(
                    run_id=run_id,
                    artifact_type="fulltext_upload",
                    name=artifact_name,
                    content_text=text,
                ))
            session.commit()
        # Invalidate cached index
        self._paper_indices.pop(f"{run_id}:{ref_num}", None)

    # -- RAG index cache ----------------------------------------------------

    def _get_or_build_index(self, run_id: str, ref_num: int) -> PaperIndex | None:
        """Lazily build an in-memory BM25 index for one paper."""
        cache_key = f"{run_id}:{ref_num}"
        if cache_key in self._paper_indices:
            return self._paper_indices[cache_key]

        fulltext = self.get_fulltext(run_id, ref_num)
        if not fulltext:
            return None

        study = self.get_study(run_id, ref_num)
        abstract = study.abstract if study else None
        index = PaperIndex(fulltext, abstract=abstract)
        self._paper_indices[cache_key] = index
        _log.info("[READING] Built BM25 index for %s: %d chunks", cache_key, len(index.chunks))
        return index

    async def fetch_fulltext_on_demand(
        self, run_id: str, ref_num: int, api_keys: dict[str, str]
    ) -> str | None:
        """Fetch and parse a PDF on demand using existing agentic_tools."""
        from .agentic_tools import AgenticEventBridge, tool_fetch_fulltext, tool_parse_pdf
        from .models import RunRequest

        studies = self.get_ranked_studies(run_id)
        if not studies:
            return None

        with self.database.session() as session:
            run = session.get(ResearchRun, run_id)
            if not run:
                return None

        bridge = AgenticEventBridge()
        bridge.ranked_studies = studies

        request = RunRequest(
            run_id=run_id,
            query=run.query,
            query_type=run.query_type,
            mode=run.mode,
            provider=run.provider,
            model=run.model,
            language=run.language,
            api_keys=api_keys,
        )

        try:
            await tool_fetch_fulltext(request, bridge)
        except Exception as exc:
            _log.warning("[READING] fetch_fulltext failed: %s", exc)
            return None

        if ref_num not in bridge._pdf_urls:
            return None

        try:
            result = await tool_parse_pdf(request, bridge, ref_num)
            text = result.get("fulltext")
            if text:
                self.store_fulltext(run_id, ref_num, text)
            return text
        except Exception as exc:
            _log.warning("[READING] parse_pdf failed for rank %d: %s", ref_num, exc)
            return None

    # -- Chat ---------------------------------------------------------------

    def get_chat_history(self, session_id: str, scope: str) -> list[ReadingChatMessage]:
        with self.database.session() as session:
            return list(session.exec(
                select(ReadingChatMessage).where(
                    ReadingChatMessage.session_id == session_id,
                    ReadingChatMessage.scope == scope,
                ).order_by(col(ReadingChatMessage.created_at))
            ))

    def save_message(
        self, session_id: str, scope: str, role: str, content: str
    ) -> ReadingChatMessage:
        msg = ReadingChatMessage(
            session_id=session_id, scope=scope, role=role, content=content
        )
        with self.database.session() as session:
            session.add(msg)
            session.commit()
            session.refresh(msg)
        return msg

    # -- Highlights ---------------------------------------------------------

    def save_highlight(
        self, session_id: str, scope: str, text: str, note: str | None = None
    ) -> ReadingHighlight:
        hl = ReadingHighlight(session_id=session_id, scope=scope, text=text, note=note)
        with self.database.session() as session:
            session.add(hl)
            session.commit()
            session.refresh(hl)
        return hl

    def get_highlights(self, session_id: str, scope: str | None = None) -> list[ReadingHighlight]:
        with self.database.session() as session:
            stmt = select(ReadingHighlight).where(
                ReadingHighlight.session_id == session_id
            )
            if scope:
                stmt = stmt.where(ReadingHighlight.scope == scope)
            return list(session.exec(stmt.order_by(col(ReadingHighlight.created_at))))

    def delete_highlight(self, highlight_id: str) -> None:
        with self.database.session() as session:
            hl = session.get(ReadingHighlight, highlight_id)
            if hl:
                session.delete(hl)
                session.commit()

    # -- Export notes -------------------------------------------------------

    def export_notes(self, session_id: str, scope: str, run_id: str) -> str:
        """Compile highlights + chat history into structured markdown."""
        with self.database.session() as db:
            run = db.get(ResearchRun, run_id)
        if not run:
            return ""

        study_info = ""
        if scope.startswith("study:"):
            ref_num = int(scope.split(":")[1])
            study = self.get_study(run_id, ref_num)
            if study:
                study_info = (
                    f"**{study.title}**\n\n"
                    f"Authors: {', '.join(study.authors[:5])}\n\n"
                    f"Journal: {study.journal or 'N/A'}, {study.publication_year or 'N/A'}\n\n"
                    f"Evidence Level: {study.evidence_level or 'N/A'} | "
                    f"Score: {study.composite_score:.2f} | Citations: {study.citation_count}\n\n"
                    f"DOI: {study.doi or 'N/A'} | PMID: {study.pmid or 'N/A'}\n"
                )

        highlights = self.get_highlights(session_id, scope)
        history = self.get_chat_history(session_id, scope)

        lines = ["# Reading Notes\n"]
        lines.append(f"## Research Question\n\n{run.query}\n")

        if study_info:
            lines.append(f"## Study\n\n{study_info}\n")

        if highlights:
            lines.append("## Highlights\n")
            for hl in highlights:
                text_preview = hl.text[:200]
                note_part = f" — *{hl.note}*" if hl.note else ""
                lines.append(f"- \"{text_preview}\"{note_part}\n")
            lines.append("")

        if history:
            lines.append("## Discussion\n")
            for msg in history:
                if msg.role == "user":
                    lines.append(f"### Q: {msg.content[:120]}\n")
                else:
                    lines.append(f"{msg.content}\n")
            lines.append("")

        return "\n".join(lines)

    async def ask(
        self,
        *,
        session_id: str,
        scope: str,
        user_message: str,
        run_id: str,
        provider: str,
        model: str,
        api_keys: dict[str, str],
    ) -> AsyncIterator[str]:
        """Stream an AI response to *user_message* in the given scope."""

        # Persist the clean user message (no RAG context)
        self.save_message(session_id, scope, "user", user_message)

        # Retrieve relevant chunks via RAG
        augmented_msg = self._augment_with_rag(run_id, scope, user_message)

        # Build system prompt and messages
        system_prompt = self._build_system_prompt(run_id, scope)
        history = self.get_chat_history(session_id, scope)
        messages = [{"role": m.role, "content": m.content} for m in history[-20:]]
        # Replace the last user message with the RAG-augmented version
        if messages and messages[-1]["role"] == "user":
            messages[-1] = {"role": "user", "content": augmented_msg}
        # Sanitize: Anthropic requires messages to start with "user" and alternate roles
        messages = _sanitize_messages(messages)

        # Stream response
        full_response: list[str] = []
        async for chunk in _stream_reading_llm(provider, model, api_keys, system_prompt, messages):
            full_response.append(chunk)
            yield chunk

        # Persist assistant message
        self.save_message(session_id, scope, "assistant", "".join(full_response))

    async def open_discussion(
        self,
        *,
        session_id: str,
        scope: str,
        run_id: str,
        provider: str,
        model: str,
        api_keys: dict[str, str],
    ) -> AsyncIterator[str]:
        """Generate the AI's opening overview — no user message stored."""
        system_prompt = self._build_system_prompt(run_id, scope)

        # Retrieve chunks using the research question
        with self.database.session() as db:
            run = db.get(ResearchRun, run_id)
        research_query = run.query if run else ""
        augmented_opening = self._augment_with_rag(run_id, scope, research_query)

        opening_prompt = (
            f"{augmented_opening}\n\n"
            "Give a brief overview of this study using this format:\n\n"
            "**Overview**\nWhat this paper found and how it relates to the research question (2-3 sentences).\n\n"
            "**Key methodology**\nONE notable aspect of the study design.\n\n"
            "**Cross-study**\nONE connection to the strongest or most contrasting study in the review."
        )

        messages = [{"role": "user", "content": opening_prompt}]

        full_response: list[str] = []
        async for chunk in _stream_reading_llm(provider, model, api_keys, system_prompt, messages):
            full_response.append(chunk)
            yield chunk

        # Only persist the assistant response
        self.save_message(session_id, scope, "assistant", "".join(full_response))

    def _augment_with_rag(self, run_id: str, scope: str, query: str) -> str:
        """Retrieve relevant chunks and prepend them to the query."""
        chunks = []
        if scope.startswith("study:"):
            ref_num = int(scope.split(":")[1])
            index = self._get_or_build_index(run_id, ref_num)
            if index:
                chunks = index.retrieve(query, top_k=4)
        elif scope.startswith("cross:"):
            ref_nums = [int(x) for x in scope.split(":")[1].split(",")]
            for rn in ref_nums:
                index = self._get_or_build_index(run_id, rn)
                if index:
                    for c in index.retrieve(query, top_k=2):
                        c.header = f"Study #{rn} — {c.header}" if c.header else f"Study #{rn}"
                        chunks.append(c)

        if not chunks:
            return query

        context = "RELEVANT PASSAGES FROM THE PAPER:\n\n"
        for c in chunks:
            section = f"[{c.header}] " if c.header else ""
            context += f"{section}{c.text}\n\n---\n\n"
        return f"{context}QUESTION: {query}"

    # -- System prompt construction (lean — no fulltext, RAG handles that) ---

    def _build_system_prompt(self, run_id: str, scope: str) -> str:
        with self.database.session() as session:
            run = session.get(ResearchRun, run_id)
        if not run:
            return "You are a reading helper for a medical research paper."

        studies = self.get_ranked_studies(run_id)
        query = run.query

        if scope.startswith("study:"):
            return self._build_study_prompt(query, run_id, scope, studies)
        elif scope.startswith("cross:"):
            return self._build_cross_study_prompt(query, scope, studies)
        else:
            return self._build_session_prompt(query, studies)

    def _build_study_prompt(
        self, query: str, run_id: str, scope: str, studies: list[ScoredStudy]
    ) -> str:
        ref_num = int(scope.split(":")[1])
        study = next((s for s in studies if s.reference_number == ref_num), None)
        if not study:
            return f"You are a reading helper. The research question is: {query}"

        has_fulltext = self.get_fulltext(run_id, ref_num) is not None

        other_studies = "\n".join(
            f"  #{s.reference_number}: {s.title} ({s.evidence_level or 'N/A'}, {s.publication_year or 'N/A'})"
            for s in studies if s.reference_number != ref_num
        )

        return f"""You are a reading helper for a medical research paper.

RESEARCH QUESTION:
{query}

STUDY:
Title: {study.title}
Authors: {', '.join(study.authors[:5])}
Journal: {study.journal or 'N/A'}, {study.publication_year or 'N/A'}
Evidence Level: {study.evidence_level or 'Not classified'} | Composite Score: {study.composite_score:.2f} | Citations: {study.citation_count}
DOI: {study.doi or 'N/A'} | PMID: {study.pmid or 'N/A'}

ABSTRACT:
{study.abstract or 'No abstract available.'}

{"Full text is available — relevant passages will be provided with each question." if has_fulltext else "Full text is NOT available. Discussion is based on abstract only."}

OTHER STUDIES IN THIS REVIEW:
{other_studies or '  No other studies.'}

RESPONSE FORMAT — use this structure for every response:

**Answer**
Direct answer to the user's question. Ground it in the RELEVANT PASSAGES provided.
If the passages don't contain the answer, say so.

**Related**
ONE related observation from a different part of the paper (methodology,
limitations, secondary findings, etc.). Pick the single most useful thing.
Do not repeat what's already in the Answer.

**Cross-study**
ONE connection to another study in this review, if relevant.
Reference by number: "Study #3 found..."
Omit this section entirely if no other study is relevant.

RULES:
- Be concise. Short paragraphs.
- Quote or paraphrase the provided passages when answering.
- Do NOT ask the user questions.
- No preambles ("Great question!", "Let me help you with that")."""

    def _build_cross_study_prompt(
        self, query: str, scope: str, studies: list[ScoredStudy]
    ) -> str:
        ref_nums = [int(x) for x in scope.split(":")[1].split(",")]
        selected = [s for s in studies if s.reference_number in ref_nums]

        studies_text = ""
        for s in selected:
            abstract_snippet = (s.abstract or "No abstract")[:300]
            studies_text += f"""
#{s.reference_number}: {s.title}
  Authors: {', '.join(s.authors[:3])} | {s.journal or 'N/A'}, {s.publication_year or 'N/A'}
  Evidence Level: {s.evidence_level or 'N/A'} | Score: {s.composite_score:.2f} | Citations: {s.citation_count}
  Abstract: {abstract_snippet}
"""

        return f"""You are a reading helper comparing studies from a systematic literature review.

RESEARCH QUESTION:
{query}

STUDIES BEING COMPARED:
{studies_text}

RESPONSE FORMAT:
**Answer** — Direct answer grounded in the provided passages.
**Related** — ONE related observation from a different part of these papers.
**Cross-study** — ONE comparison between the selected studies (if not already in Answer).

RULES:
- Be concise. Quote or paraphrase passages. Do NOT ask questions."""

    def _build_session_prompt(self, query: str, studies: list[ScoredStudy]) -> str:
        summary_lines = "\n".join(
            f"  #{s.reference_number}: {s.title} ({s.evidence_level or 'N/A'}, {s.publication_year or 'N/A'}, score={s.composite_score:.2f})"
            for s in studies
        )
        return f"""You are a reading helper discussing the overall evidence landscape of a systematic literature review.

RESEARCH QUESTION:
{query}

ALL RANKED STUDIES:
{summary_lines}

RESPONSE FORMAT:
**Answer** — Direct answer to the question.
**Related** — ONE related observation about the evidence landscape.

RULES:
- Be concise. Do NOT ask questions."""


# ---------------------------------------------------------------------------
# Message sanitization
# ---------------------------------------------------------------------------

def _sanitize_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Ensure messages start with 'user' and alternate roles.

    Anthropic requires: first message is user, roles alternate.
    Other providers are more lenient but this format works for all.
    """
    if not messages:
        return messages

    sanitized: list[dict[str, str]] = []
    for msg in messages:
        if sanitized and sanitized[-1]["role"] == msg["role"]:
            # Merge consecutive same-role messages
            sanitized[-1] = {
                "role": msg["role"],
                "content": sanitized[-1]["content"] + "\n\n" + msg["content"],
            }
        else:
            sanitized.append(msg)

    # Must start with user
    if sanitized and sanitized[0]["role"] != "user":
        sanitized.insert(0, {"role": "user", "content": "(continuing discussion)"})

    return sanitized


# ---------------------------------------------------------------------------
# Streaming LLM calls (multi-provider)
# ---------------------------------------------------------------------------

_FALLBACK_MODELS = {
    "openai": "gpt-5-mini",
    "anthropic": "claude-haiku-4-5-20251001",
    "google": "gemini-2.5-flash",
}


def _resolve_provider(provider: str, model: str, api_keys: dict[str, str]) -> tuple[str, str]:
    """Resolve to a provider that actually has an API key configured."""
    # Check if requested provider has a key
    key_map = {
        "openai": api_keys.get("openai") or os.getenv("OPENAI_API_KEY", ""),
        "anthropic": api_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY", ""),
        "google": api_keys.get("google") or api_keys.get("gemini") or os.getenv("GOOGLE_API_KEY", ""),
    }
    if key_map.get(provider):
        return provider, model

    # Fallback to any provider with a key
    for fallback_provider, key in key_map.items():
        if key and fallback_provider != provider:
            fallback_model = _FALLBACK_MODELS.get(fallback_provider, model)
            _log.info("[READING] Provider %s has no key; falling back to %s/%s", provider, fallback_provider, fallback_model)
            return fallback_provider, fallback_model

    # No keys at all — return original and let it fail with a clear error
    return provider, model


async def _stream_reading_llm(
    provider: str,
    model: str,
    api_keys: dict[str, str],
    system_prompt: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    """Stream tokens from the LLM. Supports OpenAI, Anthropic, Google, Local."""

    # Resolve to a provider that has a key
    provider, model = _resolve_provider(provider, model, api_keys)

    if provider == "anthropic":
        yield_from = _stream_anthropic(model, api_keys, system_prompt, messages)
    elif provider == "google":
        yield_from = _stream_google(model, api_keys, system_prompt, messages)
    elif provider == "openai":
        yield_from = _stream_openai(model, api_keys, system_prompt, messages, base_url=None)
    else:
        # Local / fallback — OpenAI-compatible
        base_url = os.getenv("MDR_LOCAL_BASE_URL", "http://127.0.0.1:11434/v1")
        yield_from = _stream_openai(model, api_keys, system_prompt, messages, base_url=base_url)

    async for chunk in yield_from:
        yield chunk


async def _stream_openai(
    model: str,
    api_keys: dict[str, str],
    system_prompt: str,
    messages: list[dict[str, str]],
    *,
    base_url: str | None,
) -> AsyncIterator[str]:
    from openai import AsyncOpenAI

    api_key = api_keys.get("openai") or os.getenv("OPENAI_API_KEY", "")
    if base_url:
        api_key = "local"
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    llm_messages = [{"role": "system", "content": system_prompt}, *messages]
    stream = await client.chat.completions.create(
        model=model, messages=llm_messages, stream=True, max_tokens=4096,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


async def _stream_anthropic(
    model: str,
    api_keys: dict[str, str],
    system_prompt: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    import anthropic

    api_key = api_keys.get("anthropic") or os.getenv("ANTHROPIC_API_KEY", "")
    client = anthropic.AsyncAnthropic(api_key=api_key)

    async with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _stream_google(
    model: str,
    api_keys: dict[str, str],
    system_prompt: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    from google import genai

    api_key = api_keys.get("google") or api_keys.get("gemini") or os.getenv("GOOGLE_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # Google Genai expects a flat contents string or list of Content objects.
    # Build a simple conversation with system instruction prepended.
    contents = f"{system_prompt}\n\n"
    for msg in messages:
        role_label = "User" if msg["role"] == "user" else "Assistant"
        contents += f"{role_label}: {msg['content']}\n\n"

    async for chunk in await client.aio.models.generate_content_stream(
        model=model, contents=contents,
    ):
        try:
            if chunk.text:
                yield chunk.text
        except (ValueError, AttributeError):
            pass
