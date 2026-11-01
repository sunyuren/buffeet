---
name: 实现反转因子(乖离率+MACD环比+CCI+BOLL)
overview: 将占位骨架 cal_reverse_factor 改写为自包含流程函数,按用户选定方案合成四子因子:60周均线乖离率(R1)、MACD水下收敛/金叉含环比(R2)、CCI用tanh_to_score(R3)、BOLL %B(R4),等权合成落库 StockFactor.reverse。同步补充 get_weekly_indicator_by_trade_date 导入并修正 FACTOR_REGISTRY 反转区错配字段。
todos:
  - id: fix-registry-import
    content: 修正 FACTOR_REGISTRY 反转区字段错配与135行重复项，并补充 get_weekly_indicator_by_trade_date 导入
    status: completed
  - id: rewrite-reverse-factor
    content: 改写 cal_reverse_factor 为自包含周频流程函数（取数/merge/R1-R4 四子分计算/等权合成/floor 落库）
    status: completed
    dependencies:
      - fix-registry-import
  - id: lint-verify
    content: 运行 lint 校验 factor.py 无新增错误与残留占位引用
    status: completed
    dependencies:
      - rewrite-reverse-factor
---

## 用户需求

计算反转因子(均值回归),由四个技术子因子合成:60周均线乖离率、MACD、CCI、BOLL。方向统一为"超卖/下跌偏离 → 高分"(即跌得越狠越该反弹),落库到 `StockFactor.reverse`(值域 [-100,100] int)。

## 核心功能

- **R1 60周均线乖离率**:价格相对 60 周均线的偏离,深度超跌得高分。
- **R2 MACD 水下收敛/金叉(含环比)**:柱为负(水下)且柱回升(收敛/金叉)得高分;柱为负但仍下跌(接飞刀)被扣分。
- **R3 CCI 超卖**:CCI 深度负值(超卖)得高分,使用 `tanh_to_score` 平滑极端值。
- **R4 BOLL %B**:价格贴近/跌破布林下轨得高分。
- **等权合成**:四个子分等权(1:1:1:1)、缺项按有效权重归一,向下取整落库。

## 技术栈

- 语言/运行时:Python 3 + pandas + numpy(与现有 `factor.py` 一致)。
- 复用既有函数:`get_all_date`、`get_all_stocks`、`get_weekly_by_trade_date`(已导入)、`get_weekly_indicator_by_trade_date`(需新增导入)、`upsert_stock_factor`、`robust_z_to_score`、`tanh_to_score`。
- 落库表:`StockFactor.reverse`(列已存在,database.py:1114-1115),值域 [-100,100] int。

## 实现方案

将 `cal_reverse_factor`(factor.py:673-681,当前为占位骨架 `...`)整体改写为与 `cal_volatility_factor`(465-665)一致的自包含周频流程函数:`get_all_date()` 取周频截面序列 → `get_all_stocks()` 取清单 → 循环外一次性区间取数 → 逐截面 merge 计算四子分 → 等权合成 → `np.floor` 取整 → `upsert_stock_factor`。

**关键决策与理由**:

- **R1、R4 依赖 `close`**:`stock_weekly_indicator` 无 `close`,须从 `stock_weekly` 取 `close` 后按 `(ts_code, trade_date)` 合并(与 cal_volatility_factor 取数范式一致)。
- **R2 环比(水下收敛/金叉)**:在循环外对 indicator 全区间按 `groupby("ts_code").shift(1)` 取 `macd_bar_prev`;仅当上一行 trade_date 等于全局序列紧邻前一周时才有效,否则 diff 置 NaN 以避开停牌跳变。`r2_raw = -macd_bar + k*(macd_bar - macd_bar_prev)`(k=2,转向权重 2×深度,可调),再 `robust_z_to_score`。该式使"水下+回升"得高分、"水下+续跌"被压低。
- **R3 用 `tanh_to_score(-cci)`**:CCI 天然有界,`tanh_to_score`(factor.py:48,内部已 mean/std 标准化并 *100,**无 alpha 参数**)对极端值平滑稳健;注意直接传 `-cci`,不要额外 `/100`。
- **R1/R4 等权保留**:两者周期不同(60周 vs 20周布林),正交性尚可,默认等权;冗余风险以等权自然稀释。
- **方向一致性**:四子分均已统一为"超卖→高分",合成无需再反向;完成后应与 `momentum`(趋势强→高分)整体负相关。

## 实现注意事项

- **缺项鲁棒**:`ma60` 前导窗口不足、`(boll_upper-boll_lower)<=0`、CCI/close 任一为 NaN → 对应子分 NaN → 合成时该权重自动剔除(denom 不含该项),沿用 `cal_valuation_factor` 的 numerator/denom 模式。
- **环比相邻性校验**:`macd_bar_prev` 仅当上一 trade_date 严格等于序列紧邻前一周才生效,否则 diff=NaN,防止停牌/断周造成伪信号。
- **Blast radius 控制**:不改 `StockFactor` 表结构、`FACTOR_REGISTRY` 其他因子、`cal_volatility_factor`/`cal_valuation_factor` 等;仅改 `factor.py` 反转相关片段。
- **日志**:保留逐截面 `print(f"[cal_reverse_factor] trade_date={td} 写入反转因子 {len(out_df)} 条")`,与现有因子一致。

## 架构设计

纯函数内部改造,数据流(与现有周频因子一致):
`get_all_date() → 循环外取 stock_weekly_indicator + stock_weekly(close) → 按(ts_code,trade_date)合并 → 逐截面算 R1-R4 → 等权归一合成 → floor int → upsert_stock_factor`。

```mermaid
flowchart TD
    A[get_all_date 周频截面序列] --> B[get_all_stocks 股票清单]
    B --> C[循环外一次性取数]
    C --> C1[get_weekly_indicator_by_trade_date<br/>ma5/ma60/dif/dea/macd_bar/cci/boll_*]
    C --> C2[get_weekly_by_trade_date<br/>close]
    C1 --> D[按 ts_code,trade_date 合并]
    C2 --> D
    D --> E[逐截面遍历]
    E --> R1[R1 乖离率: -bias60]
    E --> R2[R2 MACD: -macd_bar + k*diff 环比]
    E --> R3[R3 CCI: tanh(-cci)]
    E --> R4[R4 BOLL: -pctB]
    R1 --> S[robust_z/tanh 归一化 各→[-100,100]]
    R2 --> S
    R3 --> S
    R4 --> S
    S --> T[等权合成 + 缺项归一]
    T --> U[floor 取整 → upsert_stock_factor.reverse]
```

## 目录结构(仅改动文件)

```
src/
└── factor.py   # [MODIFY]
                #  - import 块(14-22):新增 get_weekly_indicator_by_trade_date
                #  - FACTOR_REGISTRY 反转区(125-129):修正错配字段为
                #    ma60 / macd_bar / cci / boll_lower,并清理 135 行重复项
                #  - cal_reverse_factor(673-681):整体改写为自包含周频流程函数,
                #    实现 R1 乖离率 / R2 MACD水下收敛环比 / R3 CCI(tanh) / R4 BOLL %B
                #    四子分等权合成、floor 取整、upsert 落库
```

## 关键代码结构

四子分(方向统一:超卖→高分)与合成核心片段:

```python
# R1 60周均线乖离率
bias = (close - ma60) / ma60
r1 = robust_z_to_score(-bias, alpha=0.05)

# R2 MACD 水下收敛/金叉(含环比, k=2)
r2_raw = -macd_bar + 2.0 * (macd_bar - macd_bar_prev)   # macd_bar_prev 仅相邻周有效,否则 NaN
r2 = robust_z_to_score(r2_raw, alpha=0.05)

# R3 CCI 超卖(tanh,内部已 *100,无 alpha)
r3 = tanh_to_score(-cci)

# R4 BOLL %B
band = boll_upper - boll_lower
pctB = (close - boll_lower) / band.where(band > 0)      # band<=0 → NaN
r4 = robust_z_to_score(-pctB, alpha=0.05)

# 等权合成(缺项按有效权重归一)
score_cols = {"r1": "bias60", "r2": "macd", "r3": "cci", "r4": "boll"}
weights = {"bias60": 1, "macd": 1, "cci": 1, "boll": 1}
# numerator = Σ w*score, denom = Σ w ; reverse = floor(numerator/denom)
```