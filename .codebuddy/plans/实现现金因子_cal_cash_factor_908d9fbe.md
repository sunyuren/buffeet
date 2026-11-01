---
name: 实现现金因子_cal_cash_factor
overview: 完成 factor.py 中预留的 cal_cash_factor(start_date, end_date) 函数：参照 cal_profit_factor 的自包含流程，基于三个现金子项（现金收入比、净现金利润比、带息债务占比）做行业内 rank_to_score 归一化并按 2:2:1 加权，计算现金因子落库到 StockFactor.cash，并剔除新股上市前财报。
todos:
  - id: impl-cash-factor
    content: 改写 cal_cash_factor 为自包含流程：取数、年报中报过滤、上市前剔除、三子项行业内归一化(2:2:1,R3翻转)、加权落库
    status: completed
  - id: update-test-entry
    content: 更新 factor.py __main__ 测试入口，增加现金因子测试块（参照 profit 样式）
    status: completed
    dependencies:
      - impl-cash-factor
  - id: run-verify
    content: 运行 cal_cash_factor 验证现金因子计算与 StockFactor.cash 落库正确
    status: completed
    dependencies:
      - impl-cash-factor
      - update-test-entry
---

## 用户需求

任务16：在 `src/factor.py` 中完成预留的 `cal_cash_factor` 函数（当前为 `...` 占位），实现现金因子的计算逻辑，主要包含取数、计算、归一化、加权合成与落库流程。

## 产品概述

现金因子用于刻画单只股票的现金质量与财务安全性，由"现金收入比""净现金利润比""带息债务/全部投入资本"三个财务子项经行业内归一化后加权合成，落库到 `StockFactor.cash` 列，供后续因子有效性分析（Rank IC）与选股策略使用。

## 核心功能

- 输入 `start_date`/`end_date`，基于 `get_all_date()` 形成并过滤交易日序列。
- 通过 `get_all_stocks()` 获取全量股票代码、名称、行业与上市日期。
- 按"公告日期窗口=[td前一年, td]"查询财务指标，仅保留年报（end_date 以 1231 结尾）与中报（0630），剔除一季报/三季报，并按股票取最新一期报告；剔除报告期早于个股上市日期的上市前财报。
- 在循环内逐交易日截面计算：
- R1 现金收入比 `salescash_to_or`：行业内 `rank_to_score`，权重 2（方向为正）。
- R2 净现金利润比 `opincome_of_ebt`：行业内 `rank_to_score`，权重 2（方向为正）。
- R3 带息债务/全部投入资本 `int_to_talcap`：行业内 `rank_to_score` 后翻转（越小越好，×-1），权重 1。
- 三子项加权合成（缺项按有效权重归一），向下取整为 int，组装含 `ts_code/name/industry/trade_date/cash` 的 DataFrame 并 `upsert_stock_factor` 落库。

## 技术栈选择

- 语言/运行时：Python 3 + pandas + SQLAlchemy（复用现有项目栈）。
- 核心模块：`src/factor.py`（因子计算）、`src/database.py`（数据访问）。
- 归一化工具：复用 `factor.py` 内已实现的 `rank_to_score(x, alpha)`。
- 数据访问：复用 `database.get_fina_indicator_by_ann_date`、`get_all_stocks`、`get_all_date`、`upsert_stock_factor`。

## 实现方法

整体策略：将 `cal_cash_factor` 从占位骨架改写为与 `cal_profit_factor` 完全同构的"自包含流程函数"（输入 `start_date/end_date`，逐交易日取数→过滤→归一化→加权→落库）。这样做可直接复用已经验证过的财务取数窗口逻辑、年报/中报过滤、最新一期选取、上市前财报剔除、行业内排名归一化与缺项归一加权落库模式，最大限度降低回归风险与维护成本。

关键决策与权衡：

1. **行业内归一化而非全市场**：三个现金比率（现金收入比、净现金利润比、带息债务占比）行业结构差异极大，必须行业内比较以做行业中性化，与 `cal_profit_factor` 的 `r3_score`/`r4_score` 处理风格一致。
2. **`rank_to_score` 而非 `robust_z_to_score`/`tanh_to_score`**：比率类指标用行业内排名百分比最稳健，对右偏与极端值不敏感；采用 `alpha=0.05` 做 5% 尾部截断（比 profit 因子的 0.01 更稳，属可调参数）。
3. **R3 反向处理**：`int_to_talcap` 越小越好，先 `rank_to_score` 再乘 `-1`，并用 `.where(int_to_talcap.notna())` 还原 NaN（参照 `cal_volatility_factor` 的反向+NaN 还原写法），避免翻转把缺失值变成 0。
4. **权重 2:2:1**：现金因子的核心是"变现质量"（R1/R2），杠杆风险（R3）作辅助，缺项时按有效权重归一（与 `cal_profit_factor` 的 numerator/denom 写法一致）。
5. **落库仅写 `cash` 列**：复用 `upsert_stock_factor(out_df)` 按主键 `(ts_code, trade_date)` 部分列 upsert，不覆盖其他因子列（size/valuation/profit 等）。

## 实现笔记

- **性能**：循环内每个交易日调用一次 `get_fina_indicator_by_ann_date`，与 `cal_profit_factor` 一致；虽可在循环外一次性区间取数优化，但会引入多期报告去重复杂度，本次以"正确性优先、与现有模式一致"为原则沿用逐日取数，便于增量计算（`start_date/end_date` 限定范围）。
- **日志**：沿用既有 `print(f"[cal_cash_factor] trade_date={td} 写入现金因子 {len(out_df)} 条")` 风格，便于与 profit 等因子输出对齐排查。
- **Blast Radius 控制**：仅修改 `cal_cash_factor` 函数体与 `__main__` 测试入口；`FACTOR_REGISTRY` 中现金因子三字段已登记且字段名一致，无需改动；`upsert_stock_factor` 按主键部分列更新，不影响其他因子已落库数据。严格按用户步骤实现，不擅自添加金融行业降级（用户规格未包含，可后续追加）。

## 架构设计

本次为单函数逻辑补全，属现有因子计算模块的局部扩展，不引入新架构或新文件。数据流与 `cal_profit_factor` 完全一致：`交易日序列 → 逐日财务取数(ann_date窗口) → 年报/中报过滤+最新一期+上市前剔除 → 行业内 rank_to_score → 加权合成 → 取整落库`。无需架构图。

## 目录结构

```
src/
└── factor.py   # [MODIFY] 1) 将 cal_cash_factor 占位(原 1368-1377 行)改写为自包含流程函数，
                #           含交易日序列、股票清单、财务取数、年报/中报过滤、上市前财报剔除、
                #           三子项行业内 rank_to_score(2:2:1, R3 翻转)、缺项归一加权、向下取整落库；
                #           2) 更新 __main__ 本地测试入口，增加现金因子测试块（参照 profit 测试样式）。
```

## 关键代码结构

```python
def cal_cash_factor(start_date: str | None = None, end_date: str | None = None) -> None:
    """现金因子（自包含流程函数，逐交易日计算）。

    三子项行业内归一化加权合成并落库到 StockFactor.cash（权重 2:2:1）：
      R1 salescash_to_or   现金收入比     行业内 rank_to_score，方向 +，权重 2
      R2 opincome_of_ebt   净现金利润比   行业内 rank_to_score，方向 +，权重 2
      R3 int_to_talcap     带息债务占比   行业内 rank_to_score 后翻转(×-1)，方向 -，权重 1
    start_date/end_date 限定计算范围，默认 None 时为全量。
    """

# 三子项权重（缺项按有效权重归一）
weights = {"r1_score": 2, "r2_score": 2, "r3_score": 1}
```