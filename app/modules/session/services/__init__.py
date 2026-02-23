"""Session service for orchestrating graph and streaming."""
import asyncio
import json
import logging
import traceback
from typing import AsyncGenerator, Any, Optional

from app.modules.session.repositories import SessionRepository
from app.modules.session.models import Session, SessionStatus
from app.modules.session.constants import STATUS_MESSAGES

logger = logging.getLogger(__name__)


class SessionService:
    """
    Service for session management and query streaming.

    Orchestrates the session graph and handles SSE streaming.
    """

    def __init__(
        self,
        repository: SessionRepository,
        graph: Any,  # CompiledGraph
        checkpointer: Any  # TypesenseCheckpointer
    ):
        """
        Initialize session service.

        Args:
            repository: Session repository
            graph: Compiled LangGraph
            checkpointer: Checkpointer for persistence
        """
        self.repository = repository
        self.graph = graph
        self.checkpointer = checkpointer

    async def create_session(
        self,
        db_connection_id: str,
        metadata: dict | None = None
    ) -> str:
        """
        Create a new session.

        Args:
            db_connection_id: Database connection for this session
            metadata: Optional custom metadata

        Returns:
            Created session ID
        """
        return await self.repository.create(
            db_connection_id=db_connection_id,
            metadata=metadata
        )

    async def get_session(self, session_id: str) -> Optional[Session]:
        """
        Get session by ID.

        Args:
            session_id: Session ID to retrieve

        Returns:
            Session if found, None otherwise
        """
        return await self.repository.get(session_id)

    async def list_sessions(
        self,
        db_connection_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[Session]:
        """
        List sessions with optional filters.

        Args:
            db_connection_id: Filter by database connection
            status: Filter by status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of matching sessions
        """
        return await self.repository.list(
            db_connection_id=db_connection_id,
            status=status,
            limit=limit,
            offset=offset
        )

    async def delete_session(self, session_id: str) -> None:
        """
        Delete a session.

        Args:
            session_id: Session ID to delete
        """
        await self.repository.delete(session_id)

    async def close_session(self, session_id: str) -> None:
        """
        Close a session (mark as closed).

        Args:
            session_id: Session ID to close
        """
        await self.repository.close(session_id)

    async def stream_query(
        self,
        session_id: str,
        query: str
    ) -> AsyncGenerator[str, None]:
        """
        Stream query processing via SSE.

        Executes the session graph and yields SSE events.
        Sends periodic heartbeat pings to prevent client timeout during
        long-running LLM/SQL operations.

        Args:
            session_id: Session ID
            query: Natural language query

        Yields:
            SSE formatted event strings
        """
        # Get session to validate it exists
        session = await self.repository.get(session_id)
        if not session:
            yield self._format_sse("error", {"message": "Session not found"})
            return

        if session.status == SessionStatus.CLOSED:
            yield self._format_sse("error", {"message": "Session is closed"})
            return

        # Prepare config for LangGraph
        config = {
            "configurable": {
                "thread_id": session_id
            }
        }

        # Prepare initial state update with query
        # Note: messages is an Annotated list with add reducer, so we don't initialize it here
        # LangGraph will restore messages from checkpoint or use empty list
        input_state = {
            "current_query": query,
            "db_connection_id": session.db_connection_id,
            "messages": []  # Initialize for first run, checkpoint will override
        }

        try:
            # Run LangGraph in a separate task so we can interleave heartbeat pings.
            # Without heartbeats, clients (and proxies) drop the SSE connection after
            # a few seconds of silence during long-running SQL/LLM operations.
            #
            # Queue item kinds:
            #   ("event",    <sse_str>)      – a normal SSE event string to forward
            #   ("done",     None)           – graph completed successfully
            #   ("error",    (exc, tb_str))  – graph raised an exception
            #   ("sentinel", <obj>)          – always last; signals the loop to exit
            event_queue: asyncio.Queue = asyncio.Queue()
            done_sentinel = object()

            async def _run_graph():
                try:
                    final_state = None
                    async for event in self.graph.astream_events(
                        input_state,
                        config=config,
                        version="v2"
                    ):
                        sse_events = self._process_graph_event(event)
                        for sse_event in sse_events:
                            await event_queue.put(("event", sse_event))

                        # Capture final state from chain end events
                        if event.get("event") == "on_chain_end":
                            output = event.get("data", {}).get("output", {})
                            if isinstance(output, dict) and output.get("messages"):
                                final_state = output

                    # Sync final state to session repository
                    await self._sync_state_to_session(session_id, final_state)
                    await event_queue.put(("done", None))
                except Exception as exc:
                    # Capture the traceback HERE (inside the producer task) while
                    # the exception context is still live.  The consumer side has no
                    # meaningful traceback to format.
                    tb_str = traceback.format_exc()
                    await event_queue.put(("error", (exc, tb_str)))
                finally:
                    # Always ensure the consumer loop can exit
                    await event_queue.put(("sentinel", done_sentinel))

            graph_task = asyncio.create_task(_run_graph())

            # Drain event queue and send heartbeat pings every 15 seconds
            # so the client knows the connection is still alive.
            HEARTBEAT_INTERVAL = 15  # seconds
            try:
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(
                            event_queue.get(),
                            timeout=HEARTBEAT_INTERVAL
                        )
                    except asyncio.TimeoutError:
                        # Send a comment-style SSE keepalive ping (RFC 6202 §5)
                        yield ": ping\n\n"
                        continue

                    if kind == "sentinel":
                        break
                    elif kind == "event":
                        yield payload
                    elif kind == "done":
                        yield self._format_sse("done", {
                            "session_id": session_id,
                            "status": "complete"
                        })
                    elif kind == "error":
                        exc, tb_str = payload
                        logger.error(f"Error in graph task for session {session_id}: {exc}")
                        logger.error(tb_str)
                        yield self._format_sse("error", {"message": str(exc)})
            finally:
                # Always cancel and clean up the background graph task.
                # This covers three cases:
                #   1. Normal completion  – task is already done, cancel() is a no-op
                #   2. Error path         – task finished with exception, already done
                #   3. Client disconnect  – GeneratorExit is raised, task must be cancelled
                #      to avoid a dangling task holding DB connections / LLM calls
                if not graph_task.done():
                    graph_task.cancel()
                    try:
                        await graph_task
                    except (asyncio.CancelledError, Exception):
                        pass

        except Exception as e:
            logger.error(f"Error in stream_query for session {session_id}: {e}")
            logger.error(traceback.format_exc())
            yield self._format_sse("error", {"message": str(e)})

    async def _sync_state_to_session(
        self,
        session_id: str,
        final_state: Optional[dict]
    ) -> None:
        """
        Sync graph state to session repository.

        Args:
            session_id: Session ID
            final_state: Final graph state with messages
        """
        if not final_state:
            return

        session = await self.repository.get(session_id)
        if not session:
            return

        # Update session with messages from graph state
        messages = final_state.get("messages", [])
        if messages:
            from app.modules.session.models import Message
            session.messages = [
                Message.from_dict(m) if isinstance(m, dict) else m
                for m in messages
            ]

        # Update summary if present
        if final_state.get("summary"):
            session.summary = final_state["summary"]

        # Update status
        status = final_state.get("status")
        if status:
            from app.modules.session.models import SessionStatus
            session.status = SessionStatus(status)

        await self.repository.update(session)

    def _process_graph_event(self, event: dict) -> list[str]:
        """
        Process LangGraph event and convert to SSE events.

        Args:
            event: LangGraph event

        Returns:
            List of SSE formatted strings
        """
        events = []
        event_type = event.get("event")

        if event_type == "on_chain_start":
            node = event.get("name", "")
            if node in STATUS_MESSAGES:
                events.append(self._format_sse("status", {
                    "step": node,
                    "message": STATUS_MESSAGES[node]
                }))

        elif event_type == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk:
                content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if content:
                    events.append(self._format_sse("chunk", {
                        "type": "text",
                        "content": content
                    }))

        elif event_type == "on_chain_end":
            node = event.get("name", "")
            output = event.get("data", {}).get("output", {})

            # Handle process_query output (combined SQL gen + execution + analysis)
            if node == "process_query":
                # SQL chunk
                if output.get("current_sql"):
                    events.append(self._format_sse("chunk", {
                        "type": "sql",
                        "content": output["current_sql"]
                    }))

                # Analysis chunks - split into separate chunks for easier parsing
                analysis = output.get("current_analysis", {})
                if analysis:
                    # Summary chunk
                    if analysis.get("summary"):
                        events.append(self._format_sse("chunk", {
                            "type": "summary",
                            "content": analysis["summary"]
                        }))

                    # Insights chunk
                    if analysis.get("insights"):
                        events.append(self._format_sse("chunk", {
                            "type": "insights",
                            "content": analysis["insights"]
                        }))

                    # Chart recommendations chunk
                    if analysis.get("chart_recommendations"):
                        events.append(self._format_sse("chunk", {
                            "type": "chart_recommendations",
                            "content": analysis["chart_recommendations"]
                        }))

                    # Error event if present
                    if analysis.get("error"):
                        events.append(self._format_sse("error", {
                            "message": analysis["error"]
                        }))

            # Handle reasoning_only output (context-based response without SQL)
            elif node == "reasoning_only":
                analysis = output.get("current_analysis", {})
                if analysis:
                    # Reasoning response chunk
                    if analysis.get("summary"):
                        events.append(self._format_sse("chunk", {
                            "type": "reasoning",
                            "content": analysis["summary"]
                        }))

        return events

    def _format_sse(self, event_type: str, data: dict) -> str:
        """
        Format data as SSE event.

        Args:
            event_type: Event type (status, chunk, done, error)
            data: Event data

        Returns:
            SSE formatted string
        """
        return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


__all__ = ["SessionService"]
