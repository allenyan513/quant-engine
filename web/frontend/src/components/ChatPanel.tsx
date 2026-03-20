"use client";

import { useState, useRef, useEffect } from "react";
import { Message } from "@/types";
import { Send, Bot, User, Loader2 } from "lucide-react";

interface Props {
  messages: Message[];
  streamingText: string;
  isLoading: boolean;
  onSend: (message: string) => void;
}

export default function ChatPanel({ messages, streamingText, isLoading, onSend }: Props) {
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingText]);

  const handleSubmit = () => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput("");
    onSend(text);
    // Reset textarea height
    if (inputRef.current) inputRef.current.style.height = "auto";
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    // Auto-resize textarea
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-zinc-800">
        <h2 className="text-sm font-semibold text-zinc-300">AI Strategy Builder</h2>
        <p className="text-xs text-zinc-600 mt-0.5">Describe your trading strategy in natural language</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && !streamingText && (
          <div className="text-center py-12 space-y-3">
            <Bot size={32} className="mx-auto text-zinc-600" />
            <div className="text-zinc-500 text-sm">
              Describe your strategy, e.g.:
            </div>
            <div className="space-y-2 text-xs text-zinc-600">
              <p>"When 10-day SMA crosses above 30-day SMA, buy AAPL"</p>
              <p>"RSI oversold buy, overbought sell for TSLA"</p>
              <p>"Momentum rotation across QQQ, SPY, TLT, GLD"</p>
            </div>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.id} className={`flex gap-2 ${msg.role === "user" ? "justify-end" : ""}`}>
            {msg.role === "assistant" && (
              <div className="w-6 h-6 rounded-full bg-blue-600/20 flex items-center justify-center shrink-0 mt-0.5">
                <Bot size={12} className="text-blue-400" />
              </div>
            )}
            <div
              className={`max-w-[85%] px-3 py-2 rounded-lg text-sm ${
                msg.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-zinc-800 text-zinc-300"
              }`}
            >
              <pre className="whitespace-pre-wrap font-sans">{msg.content}</pre>
            </div>
            {msg.role === "user" && (
              <div className="w-6 h-6 rounded-full bg-zinc-700 flex items-center justify-center shrink-0 mt-0.5">
                <User size={12} className="text-zinc-400" />
              </div>
            )}
          </div>
        ))}

        {/* Streaming response */}
        {streamingText && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-full bg-blue-600/20 flex items-center justify-center shrink-0 mt-0.5">
              <Bot size={12} className="text-blue-400" />
            </div>
            <div className="max-w-[85%] px-3 py-2 rounded-lg text-sm bg-zinc-800 text-zinc-300">
              <pre className="whitespace-pre-wrap font-sans">{streamingText}</pre>
            </div>
          </div>
        )}

        {isLoading && !streamingText && (
          <div className="flex gap-2 items-center text-zinc-500 text-sm">
            <Loader2 size={14} className="animate-spin" />
            <span>Thinking...</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="p-3 border-t border-zinc-800">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Describe your strategy..."
            rows={1}
            className="flex-1 px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-sm text-zinc-200 resize-none focus:outline-none focus:border-blue-500 transition-colors"
          />
          <button
            onClick={handleSubmit}
            disabled={isLoading || !input.trim()}
            className="p-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg transition-colors"
          >
            <Send size={16} className="text-white" />
          </button>
        </div>
      </div>
    </div>
  );
}
