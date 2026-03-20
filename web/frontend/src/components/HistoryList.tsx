"use client";

import { SessionListItem } from "@/types";
import { Plus, Trash2, MessageSquare } from "lucide-react";

interface Props {
  sessions: SessionListItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (id: string) => void;
}

export default function HistoryList({ sessions, activeId, onSelect, onCreate, onDelete }: Props) {
  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-zinc-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-zinc-300">Sessions</h2>
        <button onClick={onCreate} className="p-1.5 hover:bg-zinc-700 rounded-lg transition-colors" title="New session">
          <Plus size={16} className="text-zinc-400" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions.map((s) => (
          <div
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors ${
              activeId === s.id ? "bg-blue-600/20 border border-blue-500/30" : "hover:bg-zinc-800"
            }`}
          >
            <MessageSquare size={14} className="text-zinc-500 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm truncate">{s.title || "New Session"}</div>
              <div className="text-xs text-zinc-600">{new Date(s.updated_at).toLocaleDateString()}</div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(s.id);
              }}
              className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/20 rounded transition-all"
            >
              <Trash2 size={12} className="text-red-400" />
            </button>
          </div>
        ))}
        {sessions.length === 0 && (
          <div className="text-center text-zinc-600 text-sm py-8">
            No sessions yet.<br />Click + to create one.
          </div>
        )}
      </div>
    </div>
  );
}
