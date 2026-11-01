---
name: 实现动量因子管线 cal_momentum_factor
overview: "将 factor.py 中未被调用的旧占位组件打分器 cal_momentum_factor(df: pd.DataFrame) 改写为自包含管线函数 cal_momentum_factor(start_date=None, end_date=None)，按周频截面计算 R1 阳线占比(12周)、R2 量价同向率(12周)、R3 MA20贴合度、R4 MA60贴合度四个子分，全市场 robust_z_to_score(alpha=0.05) 等权 1:1:1:1 合成，clip/取整后落库到 StockFactor.momentum，风格与 cal_reverse_factor/cal_volatility_factor 一致。"
todos:
  - id: impl-pipeline
    content: 改写 cal_momentum_factor 为管线函数：回看12周取数、合并周线/指标表、预计算 R1/R2 滚动占比与 R3/R4 偏离度
    status: completed
  - id: normalize-upsert
    content: 逐截面四子分 robust_z(alpha=0.05)、等权1:1:1:1合成、clip[-100,100]、取整并 upsert 到 StockFactor.momentum
    status: completed
    dependencies:
      - impl-pipeline
  - id: test-entry
    content: 在 factor.py __main__ 测试块新增 cal_momentum_factor() 调用入口与日志
    status: completed
    dependencies:
      - normalize-upsert
---

## 用户需求

完成任务14「动量因子」计算：在 src/factor.py 中将预留的 cal_momentum_factor 占位改写为自包含管线函数，参照 cal_reverse_factor / cal_volatility_factor 的模式，实现取数、计算、归一化、合成、落库到 StockFactor.momentum 的完整流程。

## 产品概述

实现动量（技术稳定度）因子，按周频截面逐期计算并写入因子库。函数输入 start_date/end_date 限定计算区间，支持全量运行。

## 核心功能

- 输入 start_date/end_date，调用 get_all_date() 形成周频 trade_date 序列并按区间过滤；调用 get_all_stocks() 获取 ts_code/name/industry。
- 循环外一次性取数：StockWeekly 取 open/close/vol，StockWeeklyIndicator 取 boll_mid(MA20)/ma60；因 R1/R2 需过去12周窗口，取数区间向前回看12个截面。
- 逐截面遍历 trade_date，计算四个子分（方向：趋势/同向越强或价格越贴合均线得分越高）：
- R1 阳线占比（12周）：close>open 的周占比；
- R2 量价同向率（12周）：周涨方向与周量方向一致占比；
- R3 MA20贴合度：|close-boll_mid|/boll_mid 的负偏离，越贴合越高；
- R4 MA60贴合度：|close-ma60|/ma60 的负偏离，越贴合越高。
- 归一化与权重（按用户最新确认）：
- R1、R2 使用 rank_to_score(alpha=0.05)（截面排名百分比映射到 [-100,100]，占比越高得分越高）；
- R3、R4 使用 robust_z_to_score(alpha=0.05)（越贴合均线得分越高）；
- 四子分等权权重调整为 R1:R2:R3:R4 = 2:2:1:1，缺项按有效权重归一；
- 合成结果 clip[-100,100]、取整为 int 后 upsert 到 StockFactor.momentum。
- 在 **main** 测试块新增 cal_momentum_factor() 调用入口。

## 技术栈

- 语言/运行时：Python 3（与现有项目一致）
- 数据处理：pandas、numpy（项目已依赖）
- 数据访问：SQLAlchemy ORM + 现有 database 模块助手（get_all_date / get_all_stocks / get_weekly_by_trade_date / get_weekly_indicator_by_trade_date / upsert_stock_factor）
- 落库目标：StockFactor.momentum（Integer 列，已存在）

## 实现方案

**策略**：沿用 cal_reverse_factor / cal_volatility_factor 已验证的「自包含管线」范式（循环外一次性区间取数 → 主表合并 → 逐截面归一化 → 加权合成 → upsert），把 cal_momentum_factor 占位（当前签名 df:pd.DataFrame->pd.Series，未被任何代码调用，可安全替换）改写为同范式管线函数 `cal_momentum_factor(start_date=None, end_date=None) -> None`。

**关键技术决策**：

1. **取数区间回看**：R1/R2 需过去12周窗口，故以请求起始日期在 trade_date 中的下标为基准向前回溯12个周期作为 extended_start，查询 [extended_start, q_end]，避免首批截面无历史。仅发起两次区间查询（weekly 表、indicator 表各一次），杜绝逐周 N+1 查询。
2. **主表合并与预计算**：将两表按 (ts_code, trade_date) 合并为一张 merged 表，按 [ts_code, trade_date] 排序后，用 groupby(ts_code).rolling(12, min_periods=8) 向量化预计算 R1 占比（is_up=close>open 的 sum/count）与 R2 占比（price_up=close>前周close、vol_up=vol>前周vol，same_dir=price_up==vol_up 的 sum/count）；R3/R4 偏离度列一次性计算。min_periods=8 保证窗口统计稳健。
3. **逐截面归一化与合成**：循环内对当前截面 sub 计算：

- R1 = rank_to_score(sub["r1_ratio"], alpha=0.05)（占比越高分越高）；
- R2 = rank_to_score(sub["r2_ratio"], alpha=0.05)；
- R3 = robust_z_to_score(-|close-boll_mid|/boll_mid, alpha=0.05)（boll_mid>0 防护）；
- R4 = robust_z_to_score(-|close-ma60|/ma60, alpha=0.05)（ma60>0 防护）；
- 按权重 R1:R2:R3:R4 = 2:2:1:1 加权合成（缺项按有效权重归一），result→clip[-100,100]→round 转 int→dropna→组装 out_df(ts_code,name,industry,trade_date,momentum)→upsert_stock_factor。

4. **方向约定**（按用户确认）：R1/R2 为正向（占比越高分越高）；R3/R4 为负偏离送归一化（越贴合均线分越高）。

**性能与可靠性**：取数批量、计算向量化（rolling/groupby），逐截面仅做轻量 cross-section 归一化，无重复遍历；防御性 clip 与 NaN 还原避免越界与 ORM 类型不匹配（int 落库）。

## 实现注意事项

- **除法防护**：R3/R4 偏离度需 boll_mid>0、ma60>0 才计算，否则置 NaN（用 np.errstate 屏蔽除零告警）；close/ma 任一为 NaN 时该子分 NaN，由有效权重归一吸收。
- **日志与回退**：沿用 print 风格（如 `[cal_momentum_factor] trade_date=... 写入动量因子 N 条`），避免空截面 upsert；out_df 仅保留 momentum 非空的行，并 cast 为 python int 防 numpy int ORM 报错。
- **影响面控制**：仅改写 cal_momentum_factor 占位与 **main** 测试块；不动 cal_reverse_factor/cal_volatility_factor 及其它因子；StockFactor.momentum 列已存在，无需改数据库 schema。

## 架构设计

与现有因子管线完全一致（数据访问层 database 模块 → 因子计算层 factor 模块 → 因子库 StockFactor）。新增 cal_momentum_factor 与其它因子并列，入口在 factor.py **main** 测试块，未来可纳入统一调度。

```mermaid
flowchart TD
    A[cal_momentum_factor start/end] --> B[get_all_date 过滤区间]
    B --> C[get_all_stocks 列表]
    C --> D[回看12周 区间取数: weekly+indicator]
    D --> E[合并+排序 预计算 R1/R2 滚动占比 R3/R4 偏离度]
    E --> F[循环 trade_date 截面]
    F --> G[R1/R2 rank_to_score(alpha=0.05); R3/R4 robust_z(alpha=0.05)]
    G --> H[加权 2:2:1:1 合成 clip/取整]
    H --> I[upsert_stock_factor -> StockFactor.momentum]
```

## 目录结构

```
src/
└── factor.py   # [MODIFY] 改写 cal_momentum_factor 占位（约 867-875 行）：
                #   1) 改为 cal_momentum_factor(start_date=None, end_date=None) -> None 管线函数；
                #   2) 实现取数（回看12周）、合并、R1/R2 滚动占比预计算、R3/R4 偏离度；
                #   3) 逐截面 R1/R2 rank_to_score(alpha=0.05)、R3/R4 robust_z(alpha=0.05)、
                #      权重 2:2:1:1 合成、clip/取整、upsert 落库 momentum；
                #   4) 在函数末尾 __main__ 测试块（参考约 1008-1019 行 cal_reverse_factor 调用）
                #      新增 cal_momentum_factor() 全量调用入口（附区间注释版）。
```

## 关键代码结构

```python
def cal_momentum_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """动量因子管线：取数 -> R1~R4 计算 -> 归一化 -> 加权合成 -> 落库 StockFactor.momentum"""

# 四子分定义（R1/R2 用 rank_to_score，R3/R4 用 robust_z_to_score，alpha=0.05）
# R1 = rank_to_score( rolling12(is_up).ratio , alpha=0.05 )        # is_up = close > open
# R2 = rank_to_score( rolling12(same_dir).ratio , alpha=0.05 )     # same_dir = (close>prev_close)==(vol>prev_vol)
# R3 = robust_z_to_score( -|close - boll_mid| / boll_mid , alpha=0.05 )   # boll_mid>0 防护
# R4 = robust_z_to_score( -|close - ma60| / ma60 , alpha=0.05 )           # ma60>0 防护
# 权重：R1:R2:R3:R4 = 2:2:1:1
# 合成：momentum = clip( (2*R1 + 2*R2 + 1*R3 + 1*R4) / 有效权重 , -100, 100 )，round 为 int
```