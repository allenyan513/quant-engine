# quant-engine vs QuantConnect 差距分析

> 分析日期: 2026-03-20

## 概览

quant-engine 在核心回测功能 (事件驱动引擎、风控、手续费/滑点模型、Walk-Forward 优化) 上已比较完善。与 QuantConnect 的主要差距集中在 **数据层 (分钟线 + 多资产类别)**、**调度系统** 和 **实盘交易能力**。

---

## 一、数据层 (差距最大)

| 能力 | quant-engine | QuantConnect |
|------|-------------|--------------|
| 数据频率 | 日线 only | Tick / 秒 / 分钟 / 小时 / 日线 |
| 数据源 | yfinance + CSV (2 个) | 100+ 数据源 (Polygon, IQFeed, IBKR...) |
| 资产类别 | 美股/ETF only | 股票、期权、期货、外汇、加密货币 |
| 另类数据 | 无 | 新闻情绪、SEC filing、社交媒体等 |
| 历史深度 | yfinance 能提供多少就多少 | 20+ 年 tick 级数据 |

**关键影响**: 没有分钟线就无法做日内策略，这是 Roadmap 近期任务。资产类别缺期权/期货是中期目标。

---

## 二、调度系统 (完全缺失)

QuantConnect 提供强大的 `schedule.on()` API:

```python
# QC 示例
self.schedule.on(self.date_rules.every_day(),
                 self.time_rules.after_market_open("SPY", 30),
                 self.rebalance)
self.schedule.on(self.date_rules.month_start(),
                 self.time_rules.at(10, 0),
                 self.monthly_rebalance)
```

quant-engine 的策略只能在 `on_bar()` 里手动判断日期来模拟定时调仓 (如 `dual_momentum.py` 的月度判断)。日线模式下影响不大，但分钟线支持后调度系统就是必需品。

---

## 三、Universe Selection (动态选股)

| quant-engine | QuantConnect |
|-------------|--------------|
| 手动指定 symbols 列表 | `UniverseSelectionModel` 动态筛选 |
| 回测期间 symbols 固定 | 支持按基本面/技术面/市值动态增减 |
| — | Coarse/Fine universe filter |

Roadmap 已标注依赖付费数据源 (Polygon/Alpaca 才能覆盖几千只股票)。目前 ETF 轮动手动指定 symbols 够用。

---

## 四、指标库

| quant-engine (7 个函数) | QuantConnect (100+) |
|------------------------|---------------------|
| SMA, EMA, MACD | 全部趋势指标 |
| RSI | Stochastic, CCI, Williams %R, ADX, MFI... |
| ATR, Bollinger | Keltner, Ichimoku, Parabolic SAR... |
| Donchian | 自定义指标框架 + 自动预热 |

**实际影响不大** — 纯 numpy 函数加新指标很容易，按需添加即可。QC 的优势主要在指标自动预热 (warm-up) 和流式更新 (incremental update)，我们是批量计算模式。

---

## 五、Algorithm Framework (模块化架构)

QuantConnect 的五模块分离:

```
Alpha Model → Portfolio Construction → Risk Management → Execution → Universe Selection
```

quant-engine 是单一 `on_bar()` 模式，所有逻辑在策略内部。Roadmap 已评估过：改动太大 (11 策略重写 + 194 测试失效)，当前模式更灵活直观，暂不做。如果未来策略数量和复杂度大幅增长再考虑。

---

## 六、实盘交易

| quant-engine | QuantConnect |
|-------------|--------------|
| 纯回测 | 实盘 + 纸盘 (IBKR, Tradier, Coinbase...) |
| 无实时数据 | WebSocket 实时推送 |
| 无订单管理 | 实时订单状态 + 部分成交 |

Roadmap 中期目标有 IBKR 对接。

---

## 七、其他差距明细

| 功能 | quant-engine | QuantConnect | 影响 |
|------|-------------|--------------|------|
| 期权定价/Greeks | 无 | 完整期权链 + Greeks | 中 |
| 期货换月 | 无 | 自动 continuous contract | 中 |
| 事件日历 | 无 | 财报日/FOMC/分红除息 | 低 |
| 因子研究 | 无 | IC/IR/因子衰减 | 低 |
| 分布式回测 | 单线程 | 云端并行 | 低 |
| 订单类型 | 4 种 (MARKET/LIMIT/STOP/STOP_LIMIT) | +MOC/MOO/IOC/FOK/GTC 等 | 低 |
| 部分成交 | 不支持 | 支持 | 低 |
| 分红/拆股处理 | 依赖 yfinance adjusted price | 原始价格 + 事件处理 | 低 |
| Web UI | 无 (CLI + PNG 报告) | 完整 IDE + 可视化 | 低 |

---

## 八、我们已有而 QC 不突出的优势

- **QC 导出 + 对账**: LLM 翻译策略到 QC + 自动对比回测结果，形成闭环验证
- **本地数据缓存**: CachedFeed 装饰器模式，增量更新，零网络请求
- **Walk-Forward 优化**: 内置网格搜索 + 滚动窗口 + 参数稳定性分析
- **代码简洁性**: 纯 Python + numpy，无框架锁定，策略代码量远小于 QC
- **可插拔模型**: 手续费/滑点/保证金/执行/风控全部可插拔，扩展简单

---

## 九、优先级建议

### 短期高价值 (现有架构直接做)

1. **分钟/小时线数据源** — 接入 Polygon.io 或 Alpaca，是日内策略和调度系统的前提
2. **调度系统** (`schedule.on()`) — 有了分钟线后必须配套，日线下也能简化月度调仓逻辑
3. **按需补指标** — ADX, Stochastic, CCI 等常用指标，工作量小

### 中期 (架构扩展)

4. **IBKR 实盘对接** — 实时数据 + 下单，策略信号到实际订单的桥接
5. **动态 Universe Selection** — 等付费数据源就绪后实现
6. **期权基础支持** — covered call / protective put 场景

### 不急 (ROI 低或改动太大)

7. **Algorithm Framework 五模块分离** — 当前 `on_bar()` 模式够用
8. **分布式回测** — 单策略单线程性能足够
9. **Web UI** — CLI + PNG 报告满足研究需求
10. **事件日历 / 因子研究** — 非核心功能

---

## 十、结论

quant-engine 的核心回测能力已经成熟，和 QC 的差距主要在 **基础设施层面** (数据、实盘) 而非 **策略逻辑层面**。分钟线数据源是打开日内策略、调度系统、VWAP 执行等一系列能力的钥匙，应优先推进。
