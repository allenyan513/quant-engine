export interface SessionListItem {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

export interface BacktestParams {
  symbols: string[];
  start: string;
  end: string;
  initial_cash: number;
  fee_model: "per_share" | "percentage" | "zero";
  slippage_rate: number;
}

export interface Trade {
  symbol: string;
  direction: string;
  entry_time: string;
  entry_price: number;
  exit_time: string;
  exit_price: number;
  quantity: number;
  net_pnl: number;
  return_pct: number;
  holding_days: number;
}

export interface BacktestResult {
  id: number;
  session_id: string;
  status: "running" | "completed" | "failed";
  error?: string;
  metrics: Record<string, number | null>;
  trade_summary: Record<string, number>;
  trades: Trade[];
  equity_curve: [number, number][];
  benchmark_curve: [number, number][];
  drawdown_curve: [number, number][];
  created_at: string;
}

export interface Session {
  id: string;
  title: string;
  strategy_code: string;
  params: BacktestParams;
  messages: Message[];
  backtest_results: BacktestResult[];
  created_at: string;
  updated_at: string;
}
