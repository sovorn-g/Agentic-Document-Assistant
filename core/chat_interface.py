import json
import re
import traceback
import uuid

from langchain_core.messages import AIMessageChunk, AIMessage, HumanMessage, SystemMessage, ToolMessage

import config

SILENT_NODES = {"rewrite_query"}
SYSTEM_NODES = {"summarize_history", "rewrite_query"}

SYSTEM_NODE_CONFIG = {
    "rewrite_query": {"title": "Query Analysis & Rewriting"},
    "summarize_history": {"title": "Chat History Summary"},
}

CLARIFICATION_FALLBACK = "Please ask a specific question about the current project or uploaded documents."


_RESOURCE_PATTERNS = re.compile(
    # "do you have any files/documents/resources..."
    r"(?:do\s+(?:you|we|i|there)\s+(?:have|got|possess)\s+(?:any\s+)?"
    r"(?:files?|documents?|resources?|uploads?|papers?|pdfs?))(?:\s|$)"
    r"|"
    # "are there any files / is there any doc / do we have any resource"
    r"(?:(?:are|is)\s+there|(?:(?:have|do)\s+(?:you|we|i))\s+have)"
    r"\s+(?:any\s+)?(?:files?|documents?|resources?|uploads?|papers?|pdfs?)(?:\s|$)"
    r"|"
    # "show/list/what files/documents/resources"
    r"(?:(?:show\s+(?:me\s+)?(?:the\s+)?)|(?:list\s+(?:the\s+)?)|(?:what\s+))"
    r"(?:files?|documents?|resources?|uploads?)(?:\s|$)"
    r"|"
    # "uploaded/indexed/added any files"
    r"(?:uploaded|indexed|added)\s+(?:any\s+)?(?:files?|documents?|resources?|uploads?)(?:\s|$)"
    r"|"
    # "file/document/resource status/list/available/exist"
    r"(?:files?|documents?|resources?)\s+(?:status|list|available|exist)(?:\s|$)",
    re.IGNORECASE,
)


def _is_resource_status_question(message: str) -> bool:
    """Check if the user is asking about whether files/documents/resources exist."""
    return bool(_RESOURCE_PATTERNS.search(message.strip()))


def _resource_status_answer(project_id: str, store) -> str | None:
    """Return a natural answer about file/document status, or None if not applicable."""
    if not project_id:
        return None
    docs = store.list_documents(project_id)
    if not docs:
        return "No, there are currently no files or documents uploaded to this project yet. You can upload PDF or Markdown files to get started."
    filenames = [d["filename"] for d in docs]
    count = len(filenames)
    if count == 1:
        return f"Yes, there is **1 file** uploaded: `{filenames[0]}`"
    # Show first 5, then count
    shown = filenames[:5]
    remainder = count - 5
    if remainder > 0:
        return f"Yes, there are **{count} files** uploaded: " + ", ".join(f"`{f}`" for f in shown) + f" and **{remainder} more**."
    return f"Yes, there are **{count} files** uploaded: " + ", ".join(f"`{f}`" for f in shown)


def parse_sources_from_text(text):
    sources = []
    current = {}
    for line in str(text or "").splitlines():
        if line.startswith("Parent ID:"):
            if current:
                sources.append(current)
            current = {"parent_id": line.split(":", 1)[1].strip()}
        elif line.startswith("File Name:"):
            if not current:
                current = {}
            current["filename"] = line.split(":", 1)[1].strip()
    if current:
        sources.append(current)

    deduped = []
    seen = set()
    for source in sources:
        key = (source.get("filename", ""), source.get("parent_id", ""))
        if key not in seen and any(key):
            seen.add(key)
            deduped.append(source)
    return deduped


def make_message(content, *, title=None, node=None):
    msg = {"role": "assistant", "content": content}
    if title or node:
        msg["metadata"] = {k: v for k, v in {"title": title, "node": node}.items() if v}
    return msg


def find_msg_idx(messages, node):
    return next(
        (i for i, m in enumerate(messages) if m.get("metadata", {}).get("node") == node),
        None,
    )


def parse_rewrite_json(buffer):
    match = re.search(r"\{.*\}", buffer, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except Exception:
        return None


def format_rewrite_content(buffer):
    data = parse_rewrite_json(buffer)
    if not data:
        return "Analyzing query..."
    if data.get("is_clear"):
        lines = ["**Query is clear**"]
        if data.get("questions"):
            lines += ["\n**Rewritten queries:**"] + [f"- {q}" for q in data["questions"]]
    else:
        lines = ["**Query is unclear**"]
        clarification = data.get("clarification_needed", "")
        if clarification and clarification.strip().lower() != "no":
            lines.append(f"\nClarification needed: *{clarification}*")
    return "\n".join(lines)


class ChatInterface:
    def __init__(self, rag_system):
        self.rag_system = rag_system
        self.store = rag_system.store

    def format_history(self, session_id):
        return [
            {"role": message["role"], "content": message["content"]}
            for message in self.store.list_messages(session_id)
        ]

    def _model_messages(self, session_id):
        rows = self.store.list_messages(session_id, limit=config.MEMORY_RECENT_MESSAGE_COUNT)
        messages = []
        for row in rows:
            if row["role"] == "user":
                messages.append(HumanMessage(content=row["content"]))
            elif row["role"] == "assistant":
                messages.append(AIMessage(content=row["content"]))
        return messages

    def _graph_config(self, thread_id):
        cfg = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": self.rag_system.recursion_limit,
        }
        handler = self.rag_system.observability.get_handler()
        if handler:
            cfg["callbacks"] = [handler]
        return cfg

    def _handle_system_node(self, chunk, node, response_messages, system_node_buffer):
        system_node_buffer[node] = system_node_buffer.get(node, "") + chunk.content
        buffer = system_node_buffer[node]
        title = SYSTEM_NODE_CONFIG[node]["title"]
        content = format_rewrite_content(buffer) if node == "rewrite_query" else buffer

        idx = find_msg_idx(response_messages, node)
        if idx is None:
            response_messages.append(make_message(content, title=title, node=node))
        else:
            response_messages[idx]["content"] = content

        if node == "rewrite_query":
            self._surface_clarification(buffer, response_messages)

    def _surface_clarification(self, buffer, response_messages):
        data = parse_rewrite_json(buffer) or {}
        clarification = data.get("clarification_needed", "")
        if not data.get("is_clear") and clarification.strip().lower() not in ("", "no"):
            cidx = find_msg_idx(response_messages, "clarification")
            if cidx is None:
                response_messages.append(make_message(clarification, node="clarification"))
            else:
                response_messages[cidx]["content"] = clarification

    def _handle_tool_call(self, chunk, response_messages, active_tool_calls):
        for tc in chunk.tool_calls:
            if tc.get("id") and tc["id"] not in active_tool_calls:
                response_messages.append(
                    make_message(f"Running `{tc['name']}`...", title=f"{tc['name']}")
                )
                active_tool_calls[tc["id"]] = len(response_messages) - 1

    def _handle_tool_result(self, chunk, response_messages, active_tool_calls):
        idx = active_tool_calls.get(chunk.tool_call_id)
        if idx is not None:
            preview = str(chunk.content)[:300]
            suffix = "\n..." if len(str(chunk.content)) > 300 else ""
            response_messages[idx]["content"] = f"```\n{preview}{suffix}\n```"

    def _handle_llm_token(self, chunk, node, response_messages):
        last = response_messages[-1] if response_messages else None
        if not (last and last.get("role") == "assistant" and "metadata" not in last):
            response_messages.append(make_message(""))
        response_messages[-1]["content"] += chunk.content

    def _final_assistant_content(self, response_messages):
        for message in reversed(response_messages):
            if message.get("role") == "assistant" and not message.get("metadata"):
                content = message.get("content", "").strip()
                if content:
                    return content

        for message in reversed(response_messages):
            if message.get("metadata", {}).get("node") == "clarification":
                content = message.get("content", "").strip()
                if content:
                    return content
        return ""

    def _compact_memory_if_needed(self, session_id):
        total = self.store.count_messages(session_id)
        if total <= config.MEMORY_COMPACTION_MESSAGE_THRESHOLD:
            return

        session = self.store.get_session(session_id)
        if not session:
            return

        all_messages = self.store.list_messages(session_id)
        older = all_messages[:-config.MEMORY_RECENT_MESSAGE_COUNT]
        if not older:
            return

        existing_summary = session.get("memory_summary", "")
        transcript = "\n".join(
            f"{row['role'].title()}: {row['content']}" for row in older[-30:]
        )
        prompt = (
            "Create a compact memory summary for future RAG turns. Preserve user goals, "
            "constraints, named entities, document references, and unresolved questions. "
            "Do not include greetings or tool chatter.\n\n"
            f"Existing summary:\n{existing_summary or '(none)'}\n\n"
            f"Older transcript:\n{transcript}"
        )
        response = self.rag_system.llm.with_config(temperature=0.2).invoke(
            [
                SystemMessage(content="You maintain concise durable chat memory."),
                HumanMessage(content=prompt),
            ]
        )
        self.store.update_session_summary(session_id, response.content)

    def chat(self, project_id, session_id, message):
        if not self.rag_system.llm or not self.rag_system.collection:
            yield [{"role": "assistant", "content": "System not initialized."}]
            return

        text = (message or "").strip()
        if not text:
            yield self.format_history(session_id)
            return

        session_id = self.store.get_or_create_session(project_id, session_id)
        self.store.add_message(session_id, "user", text)
        base_history = self.format_history(session_id)

        # --- Resource-status shortcut ---
        if _is_resource_status_question(text):
            answer = _resource_status_answer(project_id, self.store)
            if answer:
                self.store.add_message(session_id, "assistant", answer)
                yield self.format_history(session_id)
                return
        # --------------------------------

        yield base_history

        session = self.store.get_session(session_id) or {}
        graph = self.rag_system.create_agent_graph(project_id)
        graph_config = self._graph_config(f"{session_id}-{uuid.uuid4()}")
        stream_input = {
            "messages": self._model_messages(session_id),
            "conversation_summary": session.get("memory_summary", ""),
        }

        response_messages = []
        active_tool_calls = {}
        system_node_buffer = {}

        try:
            for chunk, metadata in graph.stream(stream_input, config=graph_config, stream_mode="messages"):
                node = metadata.get("langgraph_node", "")

                if node in SYSTEM_NODES and isinstance(chunk, AIMessageChunk) and chunk.content:
                    self._handle_system_node(chunk, node, response_messages, system_node_buffer)
                elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    self._handle_tool_call(chunk, response_messages, active_tool_calls)
                elif isinstance(chunk, ToolMessage):
                    self._handle_tool_result(chunk, response_messages, active_tool_calls)
                elif isinstance(chunk, AIMessageChunk) and chunk.content and node not in SILENT_NODES:
                    self._handle_llm_token(chunk, node, response_messages)

                yield base_history + response_messages

            final_content = self._final_assistant_content(response_messages)
            if not final_content:
                final_content = CLARIFICATION_FALLBACK
            if final_content:
                self.store.add_message(session_id, "assistant", final_content)
                self._compact_memory_if_needed(session_id)
                yield self.format_history(session_id)

        except Exception as e:
            traceback.print_exc()
            error = f"Error: {str(e)}"
            self.store.add_message(session_id, "assistant", error)
            yield self.format_history(session_id)

    def stream_events(self, project_id, session_id, message):
        if not self.rag_system.llm or not self.rag_system.collection:
            yield {"event": "error", "data": {"message": "System not initialized."}}
            return

        text = (message or "").strip()
        if not text:
            yield {"event": "history", "data": {"messages": self.format_history(session_id)}}
            yield {"event": "done", "data": {"messages": self.format_history(session_id)}}
            return

        session_id = self.store.get_or_create_session(project_id, session_id)
        self.store.add_message(session_id, "user", text)
        base_history = self.format_history(session_id)

        # --- Resource-status shortcut ---
        if _is_resource_status_question(text):
            answer = _resource_status_answer(project_id, self.store)
            if answer:
                self.store.add_message(session_id, "assistant", answer)
                yield {"event": "history", "data": {"messages": self.format_history(session_id)}}
                yield {"event": "assistant_delta", "data": {"content": answer}}
                yield {"event": "done", "data": {"messages": self.format_history(session_id)}}
                return
        # --------------------------------

        yield {"event": "history", "data": {"messages": base_history}}

        session = self.store.get_session(session_id) or {}
        graph = self.rag_system.create_agent_graph(project_id)
        graph_config = self._graph_config(f"{session_id}-{uuid.uuid4()}")
        stream_input = {
            "messages": self._model_messages(session_id),
            "conversation_summary": session.get("memory_summary", ""),
        }

        response_messages = []
        active_tool_calls = {}
        system_node_buffer = {}
        emitted_sources = set()

        try:
            for chunk, metadata in graph.stream(stream_input, config=graph_config, stream_mode="messages"):
                node = metadata.get("langgraph_node", "")

                if node in SYSTEM_NODES and isinstance(chunk, AIMessageChunk) and chunk.content:
                    self._handle_system_node(chunk, node, response_messages, system_node_buffer)
                    title = SYSTEM_NODE_CONFIG.get(node, {}).get("title", node)
                    yield {"event": "status", "data": {"title": title, "content": response_messages[-1]["content"]}}
                elif hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    self._handle_tool_call(chunk, response_messages, active_tool_calls)
                    for tc in chunk.tool_calls:
                        yield {
                            "event": "status",
                            "data": {
                                "title": tc.get("name", "Tool"),
                                "content": f"Running `{tc.get('name', 'tool')}`...",
                            },
                        }
                elif isinstance(chunk, ToolMessage):
                    self._handle_tool_result(chunk, response_messages, active_tool_calls)
                    yield {
                        "event": "status",
                        "data": {
                            "title": getattr(chunk, "name", "Tool result") or "Tool result",
                            "content": str(chunk.content)[:300],
                        },
                    }
                    for source in parse_sources_from_text(chunk.content):
                        key = (source.get("filename", ""), source.get("parent_id", ""))
                        if key not in emitted_sources:
                            emitted_sources.add(key)
                            yield {"event": "source", "data": source}
                elif isinstance(chunk, AIMessageChunk) and chunk.content and node not in SILENT_NODES:
                    self._handle_llm_token(chunk, node, response_messages)
                    yield {
                        "event": "assistant_delta",
                        "data": {"content": self._final_assistant_content(response_messages)},
                    }

            final_content = self._final_assistant_content(response_messages)
            if not final_content:
                final_content = CLARIFICATION_FALLBACK
                yield {
                    "event": "assistant_delta",
                    "data": {"content": final_content},
                }
            if final_content:
                self.store.add_message(session_id, "assistant", final_content)
                self._compact_memory_if_needed(session_id)
            yield {"event": "done", "data": {"messages": self.format_history(session_id)}}

        except Exception as e:
            traceback.print_exc()
            error = f"Error: {str(e)}"
            self.store.add_message(session_id, "assistant", error)
            yield {"event": "error", "data": {"message": error}}
            yield {"event": "done", "data": {"messages": self.format_history(session_id)}}

    def clear_session(self):
        self.rag_system.observability.flush()
