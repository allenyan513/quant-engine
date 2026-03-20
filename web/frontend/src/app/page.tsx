"use client";

import { useState, useEffect, useCallback } from "react";
import { Session, BacktestParams, BacktestResult, Message, SessionListItem } from "@/types";
import * as api from "@/lib/api";
import HistoryList from "@/components/HistoryList";
import ChatPanel from "@/components/ChatPanel";
import CodeEditor from "@/components/CodeEditor";
import ParamsPanel from "@/components/ParamsPanel";
import ResultsPanel from "@/components/ResultsPanel";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

const DEFAULT_PARAMS: BacktestParams = {
  symbols: ["AAPL"],
  start: "2023-01-01",
  end: "2025-12-31",
  initial_cash: 100000,
  fee_model: "per_share",
  slippage_rate: 0.0005,
};

export default function Home() {
  // Session state
  const [sessions, setSessions] = useState<SessionListItem[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [code, setCode] = useState("");
  const [params, setParams] = useState<BacktestParams>(DEFAULT_PARAMS);
  const [latestResult, setLatestResult] = useState<BacktestResult | null>(null);

  // UI state
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [chatLoading, setChatLoading] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [backtestProgress, setBacktestProgress] = useState(0);
  const [backtestProgressMsg, setBacktestProgressMsg] = useState("");

  // Load sessions on mount
  useEffect(() => {
    api.listSessions().then(setSessions).catch(console.error);
  }, []);

  // Load session data when active session changes
  const loadSession = useCallback(async (id: string) => {
    try {
      const session = await api.getSession(id);
      setActiveSessionId(id);
      setMessages(session.messages || []);
      setCode(session.strategy_code || "");
      setParams(session.params || DEFAULT_PARAMS);
      setLatestResult(session.backtest_results?.[0] || null);
    } catch (err) {
      console.error("Failed to load session:", err);
    }
  }, []);

  const handleCreateSession = useCallback(async () => {
    const session = await api.createSession();
    setSessions((prev) => [{ id: session.id, title: "", created_at: session.created_at, updated_at: session.created_at }, ...prev]);
    setActiveSessionId(session.id);
    setMessages([]);
    setCode("");
    setParams(DEFAULT_PARAMS);
    setLatestResult(null);
  }, []);

  const handleDeleteSession = useCallback(async (id: string) => {
    await api.deleteSession(id);
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (activeSessionId === id) {
      setActiveSessionId(null);
      setMessages([]);
      setCode("");
      setLatestResult(null);
    }
  }, [activeSessionId]);

  // Chat: send message to AI
  const handleChat = useCallback(async (message: string) => {
    if (!activeSessionId) return;

    // Add user message to UI immediately
    const userMsg: Message = {
      id: Date.now(),
      role: "user",
      content: message,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setChatLoading(true);
    setStreamingText("");

    let fullText = "";

    await api.streamChat(activeSessionId, message, (event) => {
      switch (event.type) {
        case "text":
          fullText += event.content;
          setStreamingText(fullText);
          break;
        case "code":
          setCode(event.content);
          break;
        case "error":
          setStreamingText((prev) => prev + "\n\n[Error: " + event.content + "]");
          break;
        case "done":
          // Add assistant message
          const assistantMsg: Message = {
            id: Date.now() + 1,
            role: "assistant",
            content: fullText,
            created_at: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, assistantMsg]);
          setStreamingText("");
          setChatLoading(false);
          // Refresh sessions list to get updated title
          api.listSessions().then(setSessions);
          break;
      }
    });

    setChatLoading(false);
    setStreamingText("");
  }, [activeSessionId]);

  // Save code to server
  const handleSaveCode = useCallback(async () => {
    if (!activeSessionId) return;
    await api.updateCode(activeSessionId, code);
  }, [activeSessionId, code]);

  // Save params to server
  const handleParamsChange = useCallback(async (newParams: BacktestParams) => {
    setParams(newParams);
    if (activeSessionId) {
      await api.updateParams(activeSessionId, newParams);
    }
  }, [activeSessionId]);

  // Run backtest
  const handleRunBacktest = useCallback(async () => {
    if (!activeSessionId || !code.trim()) return;

    // Save code first
    await api.updateCode(activeSessionId, code);
    await api.updateParams(activeSessionId, params);

    setBacktestRunning(true);
    setBacktestProgress(0);
    setBacktestProgressMsg("Starting...");
    setLatestResult(null);

    await api.streamBacktest(activeSessionId, (event) => {
      switch (event.type) {
        case "status":
        case "progress":
          setBacktestProgress(event.progress);
          setBacktestProgressMsg(event.content);
          break;
        case "fix":
          setBacktestProgressMsg(event.content);
          break;
        case "code":
          setCode(event.content);
          break;
        case "error_retry":
          setBacktestProgressMsg(event.content);
          break;
        case "result":
          setLatestResult(event.content as unknown as BacktestResult);
          break;
        case "error":
          setLatestResult({
            id: 0,
            session_id: activeSessionId,
            status: "failed",
            error: event.content,
            metrics: {},
            trade_summary: {},
            trades: [],
            equity_curve: [],
            benchmark_curve: [],
            drawdown_curve: [],
            created_at: new Date().toISOString(),
          });
          break;
        case "done":
          setBacktestRunning(false);
          break;
      }
    });

    setBacktestRunning(false);
  }, [activeSessionId, code, params]);

  return (
    <div className="h-screen flex">
      {/* Sidebar */}
      <div
        className={`${
          sidebarOpen ? "w-60" : "w-0"
        } transition-all duration-200 overflow-hidden border-r border-zinc-800 bg-[#0d0d14] shrink-0`}
      >
        <HistoryList
          sessions={sessions}
          activeId={activeSessionId}
          onSelect={loadSession}
          onCreate={handleCreateSession}
          onDelete={handleDeleteSession}
        />
      </div>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="h-11 border-b border-zinc-800 flex items-center px-3 gap-3 shrink-0 bg-[#0d0d14]">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-1 hover:bg-zinc-800 rounded transition-colors"
          >
            {sidebarOpen ? <PanelLeftClose size={16} className="text-zinc-500" /> : <PanelLeftOpen size={16} className="text-zinc-500" />}
          </button>
          <div className="text-sm font-semibold text-zinc-300">
            Quant Engine
          </div>
          <div className="text-xs text-zinc-600">
            AI-Powered Backtesting
          </div>
        </div>

        {!activeSessionId ? (
          /* Welcome screen */
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center space-y-4">
              <h1 className="text-2xl font-bold text-zinc-300">Quant Engine</h1>
              <p className="text-zinc-500 text-sm max-w-md">
                Describe your trading strategy in natural language. AI will generate the code,
                run backtests, and show you the results.
              </p>
              <button onClick={handleCreateSession} className="btn-primary">
                + New Session
              </button>
            </div>
          </div>
        ) : (
          /* Workspace */
          <div className="flex-1 flex min-h-0">
            {/* Left column: Chat + Params */}
            <div className="w-80 shrink-0 flex flex-col border-r border-zinc-800">
              <div className="flex-1 min-h-0">
                <ChatPanel
                  messages={messages}
                  streamingText={streamingText}
                  isLoading={chatLoading}
                  onSend={handleChat}
                />
              </div>
              <div className="h-72 border-t border-zinc-800 shrink-0">
                <ParamsPanel
                  params={params}
                  onChange={handleParamsChange}
                  onRun={handleRunBacktest}
                  isRunning={backtestRunning}
                  progress={backtestProgress}
                  progressMsg={backtestProgressMsg}
                  hasCode={!!code.trim()}
                />
              </div>
            </div>

            {/* Center: Code editor */}
            <div className="flex-1 min-w-0 border-r border-zinc-800">
              <CodeEditor
                code={code}
                onChange={setCode}
                onSave={handleSaveCode}
              />
            </div>

            {/* Right: Results */}
            <div className="w-[480px] shrink-0">
              <ResultsPanel result={latestResult} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
