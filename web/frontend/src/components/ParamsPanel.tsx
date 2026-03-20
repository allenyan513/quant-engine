"use client";

import { BacktestParams } from "@/types";
import { Settings, Play, Loader2 } from "lucide-react";

interface Props {
  params: BacktestParams;
  onChange: (params: BacktestParams) => void;
  onRun: () => void;
  isRunning: boolean;
  progress: number;
  progressMsg: string;
  hasCode: boolean;
}

export default function ParamsPanel({
  params, onChange, onRun, isRunning, progress, progressMsg, hasCode,
}: Props) {
  const update = (partial: Partial<BacktestParams>) => {
    onChange({ ...params, ...partial });
  };

  return (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-zinc-800 flex items-center gap-2">
        <Settings size={14} className="text-zinc-500" />
        <h2 className="text-sm font-semibold text-zinc-300">Parameters</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        <div>
          <label className="label-text">Symbols (comma-separated)</label>
          <input
            type="text"
            className="input-field"
            value={params.symbols.join(", ")}
            onChange={(e) => update({ symbols: e.target.value.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) })}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="label-text">Start Date</label>
            <input
              type="date"
              className="input-field"
              value={params.start}
              onChange={(e) => update({ start: e.target.value })}
            />
          </div>
          <div>
            <label className="label-text">End Date</label>
            <input
              type="date"
              className="input-field"
              value={params.end}
              onChange={(e) => update({ end: e.target.value })}
            />
          </div>
        </div>

        <div>
          <label className="label-text">Initial Cash ($)</label>
          <input
            type="number"
            className="input-field"
            value={params.initial_cash}
            onChange={(e) => update({ initial_cash: Number(e.target.value) })}
          />
        </div>

        <div>
          <label className="label-text">Fee Model</label>
          <select
            className="input-field"
            value={params.fee_model}
            onChange={(e) => update({ fee_model: e.target.value as BacktestParams["fee_model"] })}
          >
            <option value="per_share">Per Share (IB Fixed)</option>
            <option value="percentage">Percentage (0.1%)</option>
            <option value="zero">Zero Fee</option>
          </select>
        </div>

        <div>
          <label className="label-text">Slippage Rate</label>
          <input
            type="number"
            step="0.0001"
            className="input-field"
            value={params.slippage_rate}
            onChange={(e) => update({ slippage_rate: Number(e.target.value) })}
          />
        </div>
      </div>

      {/* Run button + progress */}
      <div className="p-3 border-t border-zinc-800 space-y-2">
        {isRunning && (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-xs text-zinc-400">
              <Loader2 size={12} className="animate-spin" />
              <span className="truncate">{progressMsg || "Running..."}</span>
            </div>
            <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-300"
                style={{ width: `${Math.round(progress * 100)}%` }}
              />
            </div>
          </div>
        )}
        <button
          onClick={onRun}
          disabled={isRunning || !hasCode}
          className="w-full btn-success flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {isRunning ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Running...
            </>
          ) : (
            <>
              <Play size={16} />
              Run Backtest
            </>
          )}
        </button>
      </div>
    </div>
  );
}
