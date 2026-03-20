"use client";

import { useState } from "react";
import { BacktestResult } from "@/types";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  AreaChart, Area, CartesianGrid, Legend,
} from "recharts";
import { BarChart3, TrendingUp, TrendingDown, ArrowUpDown, Clock } from "lucide-react";

interface Props {
  result: BacktestResult | null;
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return "N/A";
  return (v * 100).toFixed(2) + "%";
}

function formatNum(v: number | null | undefined, decimals = 2): string {
  if (v == null) return "N/A";
  return v.toFixed(decimals);
}

function formatMoney(v: number | null | undefined): string {
  if (v == null) return "N/A";
  return "$" + v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function formatDate(ms: number): string {
  return new Date(ms).toLocaleDateString("en-US", { month: "short", year: "2-digit" });
}

type Tab = "overview" | "trades";

export default function ResultsPanel({ result }: Props) {
  const [tab, setTab] = useState<Tab>("overview");

  if (!result) {
    return (
      <div className="flex items-center justify-center h-full text-zinc-600 text-sm">
        <div className="text-center space-y-2">
          <BarChart3 size={32} className="mx-auto text-zinc-700" />
          <p>Run a backtest to see results</p>
        </div>
      </div>
    );
  }

  if (result.status === "failed") {
    return (
      <div className="p-4">
        <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
          <strong>Backtest Failed</strong>
          <pre className="mt-2 whitespace-pre-wrap text-xs">{result.error}</pre>
        </div>
      </div>
    );
  }

  const m = result.metrics;
  const ts = result.trade_summary;

  // Prepare chart data
  const equityData = result.equity_curve.map(([t, v], i) => ({
    time: t,
    strategy: v,
    benchmark: result.benchmark_curve[i]?.[1] ?? null,
  }));

  const drawdownData = result.drawdown_curve.map(([t, v]) => ({
    time: t,
    drawdown: v,
  }));

  const totalReturnColor = (m.total_return ?? 0) >= 0 ? "text-emerald-400" : "text-red-400";
  const sharpeColor = (m.sharpe_ratio ?? 0) >= 1 ? "text-emerald-400" : (m.sharpe_ratio ?? 0) >= 0.5 ? "text-yellow-400" : "text-red-400";

  return (
    <div className="flex flex-col h-full">
      {/* Tabs */}
      <div className="p-3 border-b border-zinc-800 flex items-center gap-4">
        <button
          onClick={() => setTab("overview")}
          className={`text-sm font-medium pb-0.5 border-b-2 transition-colors ${
            tab === "overview" ? "border-blue-500 text-blue-400" : "border-transparent text-zinc-500 hover:text-zinc-300"
          }`}
        >
          Overview
        </button>
        <button
          onClick={() => setTab("trades")}
          className={`text-sm font-medium pb-0.5 border-b-2 transition-colors ${
            tab === "trades" ? "border-blue-500 text-blue-400" : "border-transparent text-zinc-500 hover:text-zinc-300"
          }`}
        >
          Trades ({ts.total_trades ?? 0})
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {tab === "overview" && (
          <div className="space-y-4">
            {/* KPI Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="kpi-card">
                <div className={`kpi-value ${totalReturnColor}`}>{formatPct(m.total_return)}</div>
                <div className="kpi-label">Total Return</div>
              </div>
              <div className="kpi-card">
                <div className={`kpi-value ${totalReturnColor}`}>{formatPct(m.cagr)}</div>
                <div className="kpi-label">CAGR</div>
              </div>
              <div className="kpi-card">
                <div className={`kpi-value ${sharpeColor}`}>{formatNum(m.sharpe_ratio)}</div>
                <div className="kpi-label">Sharpe Ratio</div>
              </div>
              <div className="kpi-card">
                <div className="kpi-value text-red-400">{formatPct(m.max_drawdown)}</div>
                <div className="kpi-label">Max Drawdown</div>
              </div>
            </div>

            {/* Equity Curve */}
            <div className="panel p-3">
              <h3 className="text-xs font-semibold text-zinc-400 mb-2">Equity Curve</h3>
              <div className="h-[200px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={equityData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                    <XAxis
                      dataKey="time"
                      tickFormatter={formatDate}
                      stroke="#52525b"
                      tick={{ fontSize: 10 }}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      stroke="#52525b"
                      tick={{ fontSize: 10 }}
                      tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                    />
                    <Tooltip
                      contentStyle={{ background: "#1a1a2e", border: "1px solid #2a2a3e", borderRadius: 8, fontSize: 12 }}
                      labelFormatter={(v) => new Date(v).toLocaleDateString()}
                      formatter={(v: number) => ["$" + v.toLocaleString(), ""]}
                    />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="strategy" stroke="#3b82f6" dot={false} strokeWidth={1.5} name="Strategy" />
                    {result.benchmark_curve.length > 0 && (
                      <Line type="monotone" dataKey="benchmark" stroke="#6b7280" dot={false} strokeWidth={1} name="SPY" strokeDasharray="4 4" />
                    )}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Drawdown Chart */}
            <div className="panel p-3">
              <h3 className="text-xs font-semibold text-zinc-400 mb-2">Drawdown</h3>
              <div className="h-[120px]">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={drawdownData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2a2a3e" />
                    <XAxis
                      dataKey="time"
                      tickFormatter={formatDate}
                      stroke="#52525b"
                      tick={{ fontSize: 10 }}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      stroke="#52525b"
                      tick={{ fontSize: 10 }}
                      tickFormatter={(v) => `${v.toFixed(0)}%`}
                    />
                    <Tooltip
                      contentStyle={{ background: "#1a1a2e", border: "1px solid #2a2a3e", borderRadius: 8, fontSize: 12 }}
                      labelFormatter={(v) => new Date(v).toLocaleDateString()}
                      formatter={(v: number) => [`${v.toFixed(2)}%`, "Drawdown"]}
                    />
                    <Area type="monotone" dataKey="drawdown" stroke="#ef4444" fill="#ef444420" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Detailed Metrics */}
            <div className="panel p-3">
              <h3 className="text-xs font-semibold text-zinc-400 mb-2">Metrics</h3>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <div className="flex justify-between py-1 border-b border-zinc-800">
                  <span className="text-zinc-500">Initial Equity</span>
                  <span>{formatMoney(m.initial_equity)}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-zinc-800">
                  <span className="text-zinc-500">Final Equity</span>
                  <span>{formatMoney(m.final_equity)}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-zinc-800">
                  <span className="text-zinc-500">Volatility</span>
                  <span>{formatPct(m.volatility)}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-zinc-800">
                  <span className="text-zinc-500">Sortino</span>
                  <span>{formatNum(m.sortino_ratio)}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-zinc-800">
                  <span className="text-zinc-500">Calmar</span>
                  <span>{formatNum(m.calmar_ratio)}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-zinc-800">
                  <span className="text-zinc-500">PSR</span>
                  <span>{formatPct(m.psr)}</span>
                </div>
                {m.alpha != null && (
                  <>
                    <div className="flex justify-between py-1 border-b border-zinc-800">
                      <span className="text-zinc-500">Alpha</span>
                      <span>{formatPct(m.alpha)}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-zinc-800">
                      <span className="text-zinc-500">Beta</span>
                      <span>{formatNum(m.beta)}</span>
                    </div>
                  </>
                )}
                {ts.total_trades > 0 && (
                  <>
                    <div className="flex justify-between py-1 border-b border-zinc-800">
                      <span className="text-zinc-500">Win Rate</span>
                      <span>{formatPct(ts.win_rate)}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-zinc-800">
                      <span className="text-zinc-500">Profit Factor</span>
                      <span>{formatNum(ts.profit_factor)}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-zinc-800">
                      <span className="text-zinc-500">Avg Holding Days</span>
                      <span>{formatNum(ts.avg_holding_days, 1)}</span>
                    </div>
                    <div className="flex justify-between py-1 border-b border-zinc-800">
                      <span className="text-zinc-500">Total PnL</span>
                      <span className={ts.total_pnl >= 0 ? "text-emerald-400" : "text-red-400"}>
                        {formatMoney(ts.total_pnl)}
                      </span>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}

        {tab === "trades" && (
          <div className="overflow-x-auto">
            {result.trades.length === 0 ? (
              <div className="text-center py-8 text-zinc-600 text-sm">No trades recorded</div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-zinc-500 border-b border-zinc-800">
                    <th className="text-left py-2 px-2">Symbol</th>
                    <th className="text-left py-2 px-2">Dir</th>
                    <th className="text-right py-2 px-2">Qty</th>
                    <th className="text-right py-2 px-2">Entry</th>
                    <th className="text-right py-2 px-2">Exit</th>
                    <th className="text-right py-2 px-2">PnL</th>
                    <th className="text-right py-2 px-2">Return</th>
                    <th className="text-right py-2 px-2">Days</th>
                  </tr>
                </thead>
                <tbody>
                  {result.trades.map((t, i) => (
                    <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                      <td className="py-1.5 px-2 font-medium">{t.symbol}</td>
                      <td className="py-1.5 px-2">
                        <span className={t.direction === "LONG" ? "text-emerald-400" : "text-red-400"}>
                          {t.direction === "LONG" ? "LONG" : "SHORT"}
                        </span>
                      </td>
                      <td className="py-1.5 px-2 text-right">{t.quantity}</td>
                      <td className="py-1.5 px-2 text-right">${t.entry_price.toFixed(2)}</td>
                      <td className="py-1.5 px-2 text-right">${t.exit_price.toFixed(2)}</td>
                      <td className={`py-1.5 px-2 text-right ${t.net_pnl >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        ${t.net_pnl.toFixed(2)}
                      </td>
                      <td className={`py-1.5 px-2 text-right ${t.return_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                        {t.return_pct.toFixed(2)}%
                      </td>
                      <td className="py-1.5 px-2 text-right text-zinc-500">{t.holding_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
