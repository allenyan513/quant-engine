"""FastAPI backend — API endpoints for the quant-engine web UI."""

from __future__ import annotations

import asyncio
import json
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from web.backend import database as db
from web.backend.ai_service import AIService
from web.backend.backtest_runner import run_backtest
from web.backend.models import (
    ChatRequest,
    CreateSessionRequest,
    UpdateCodeRequest,
    UpdateParamsRequest,
)

app = FastAPI(title="Quant Engine Web", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ai_service = AIService()

MAX_AUTO_FIX_RETRIES = 3


@app.on_event("startup")
async def startup():
    db.init_db()


# ---------------------------------------------------------------------------
# Sessions CRUD
# ---------------------------------------------------------------------------

@app.post("/api/sessions")
async def create_session(req: CreateSessionRequest):
    session = db.create_session(title=req.title)
    return session


@app.get("/api/sessions")
async def list_sessions():
    return db.list_sessions()


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    # Also fetch latest backtest result
    results = db.get_backtest_results(session_id)
    session["backtest_results"] = results
    return session


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    if not db.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Code & Params
# ---------------------------------------------------------------------------

@app.put("/api/sessions/{session_id}/code")
async def update_code(session_id: str, req: UpdateCodeRequest):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.update_session_code(session_id, req.code)
    return {"ok": True}


@app.put("/api/sessions/{session_id}/params")
async def update_params(session_id: str, req: UpdateParamsRequest):
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    db.update_session_params(session_id, req.model_dump())
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chat — SSE streaming
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    """
    Multi-turn chat with AI to generate/modify strategy code.
    Returns SSE stream with partial text + final code extraction.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Save user message
    db.add_message(session_id, "user", req.message)

    # Auto-generate title on first message
    if not session["title"]:
        try:
            title = await ai_service.generate_title(req.message)
            db.update_session_title(session_id, title)
        except Exception:
            db.update_session_title(session_id, req.message[:20])

    # Build conversation history for multi-turn
    history = []
    for msg in session["messages"]:
        history.append({"role": msg["role"], "content": msg["content"]})
    # Add current user message
    history.append({"role": "user", "content": req.message})

    # If there's existing code, include it as context
    if session["strategy_code"]:
        # Prepend code context to the last user message
        code_context = f"Current strategy code:\n```python\n{session['strategy_code']}\n```\n\nUser request: {req.message}"
        history[-1]["content"] = code_context

    async def event_stream():
        full_response = ""
        try:
            async for chunk in ai_service.generate_strategy(history):
                full_response += chunk
                yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

            # Extract code from the full response
            code = ai_service.extract_code(full_response)

            # Save assistant message and code
            db.add_message(session_id, "assistant", full_response)
            db.update_session_code(session_id, code)

            yield f"data: {json.dumps({'type': 'code', 'content': code})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Backtest — SSE streaming with auto-fix
# ---------------------------------------------------------------------------

@app.post("/api/sessions/{session_id}/backtest")
async def run_backtest_endpoint(session_id: str):
    """
    Run backtest with SSE progress streaming.
    Auto-fixes code errors up to MAX_AUTO_FIX_RETRIES times.
    """
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    code = session["strategy_code"]
    if not code.strip():
        raise HTTPException(status_code=400, detail="No strategy code to run")

    params = session["params"]

    async def event_stream():
        result_id = db.save_backtest_result(session_id, status="running")
        yield f"data: {json.dumps({'type': 'status', 'content': 'Starting backtest...', 'progress': 0})}\n\n"

        current_code = code
        last_error = None

        for attempt in range(MAX_AUTO_FIX_RETRIES + 1):
            try:
                if attempt > 0:
                    yield f"data: {json.dumps({'type': 'fix', 'content': f'Auto-fixing code (attempt {attempt})...', 'progress': 0.02})}\n\n"
                    try:
                        current_code = await ai_service.fix_code(current_code, last_error)
                        db.update_session_code(session_id, current_code)
                        yield f"data: {json.dumps({'type': 'code', 'content': current_code})}\n\n"
                    except Exception as fix_err:
                        yield f"data: {json.dumps({'type': 'error', 'content': f'Auto-fix failed: {fix_err}'})}\n\n"
                        break

                # Run backtest in a thread to avoid blocking
                progress_queue: asyncio.Queue = asyncio.Queue()

                def on_progress(msg: str, pct: float):
                    progress_queue.put_nowait((msg, pct))

                loop = asyncio.get_event_loop()
                task = loop.run_in_executor(
                    None,
                    lambda: run_backtest(
                        code=current_code,
                        symbols=params.get("symbols", ["AAPL"]),
                        start=params.get("start", "2023-01-01"),
                        end=params.get("end", "2025-12-31"),
                        initial_cash=params.get("initial_cash", 100_000),
                        fee_model_name=params.get("fee_model", "per_share"),
                        slippage_rate=params.get("slippage_rate", 0.0005),
                        on_progress=on_progress,
                    ),
                )

                # Stream progress while backtest runs
                while not task.done():
                    try:
                        msg, pct = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                        yield f"data: {json.dumps({'type': 'progress', 'content': msg, 'progress': pct})}\n\n"
                    except asyncio.TimeoutError:
                        pass

                # Drain remaining progress messages
                while not progress_queue.empty():
                    msg, pct = progress_queue.get_nowait()
                    yield f"data: {json.dumps({'type': 'progress', 'content': msg, 'progress': pct})}\n\n"

                result = await asyncio.wrap_future(task)

                # Save results
                db.update_backtest_result(
                    result_id,
                    status="completed",
                    metrics=result["metrics"],
                    trade_summary=result["trade_summary"],
                    trades=result["trades"],
                    equity_curve=result["equity_curve"],
                    benchmark_curve=result["benchmark_curve"],
                    drawdown_curve=result["drawdown_curve"],
                )

                yield f"data: {json.dumps({'type': 'result', 'content': result, 'result_id': result_id})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return  # success

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                if attempt < MAX_AUTO_FIX_RETRIES:
                    yield f"data: {json.dumps({'type': 'error_retry', 'content': f'Error: {e}. Attempting auto-fix...'})}\n\n"
                else:
                    db.update_backtest_result(result_id, status="failed", error=last_error)
                    yield f"data: {json.dumps({'type': 'error', 'content': f'Backtest failed after {MAX_AUTO_FIX_RETRIES} auto-fix attempts: {e}'})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Backtest results
# ---------------------------------------------------------------------------

@app.get("/api/sessions/{session_id}/results")
async def get_results(session_id: str):
    return db.get_backtest_results(session_id)
