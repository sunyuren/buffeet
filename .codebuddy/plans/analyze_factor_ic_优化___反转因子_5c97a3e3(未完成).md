---
name: analyze_factor_ic 优化 + 反转因子
overview: 优化 src/analyze_factor_ic.py：将因子列表重构为配置驱动（便于扩展），并把反转因子 reverse 纳入数据分布、全市场 Rank IC、分行业 IC 三套分析；新增"分位前向收益"分析以直观验证反转因子的双向反转性。不改其它因子逻辑，不新增依赖。
todos:
  - id: config-and-select
    content: 新增 FACTORS 配置、更新 docstring、SELECT 加 reverse 列
    status: completed
  - id: loop-factors
    content: 分布段动态布局 + 全市场/分行业 IC 改为遍历 FACTORS
    status: completed
    dependencies:
      - config-and-select
  - id: quintile-analysis
    content: 新增 report_quintile_ret 分位收益分析并接入 main
    status: completed
    dependencies:
      - config-and-select
  - id: verify-run
    content: 运行脚本验证四因子产物与 reverse 单调性
    status: in_progress
    dependencies:
      - loop-factors
      - quintile-analysis
---

## 用户需求

优化因子有效性分析脚本 `src/analyze_factor_ic.py`，在分析体系中加入反转因子 `reverse` 的计算与验证。

## Product Overview

将现有「规模/估值/波动 三因子」IC 分析扩展为「规模/估值/波动/反转 四因子」，并新增更直观的「分位→未来收益」单调性分析，用于验证反转因子的双向反转特性（高分超跌档未来收益为正、低分超买档为负）。

## Core Features

- 将因子列名配置化，SELECT、分布、全市场 IC、分行业 IC 四处统一遍历因子列表，消除硬编码重复。
- 分析范围新增 `reverse` 因子（与 size/valuation/volility 同落 `stock_factor` 表，无需改表结构）。
- 四因子数据分布直方图（动态布局，复用现有 [-100,100] 分桶）。
- 四因子全市场 Rank IC / ICIR / 正率 / t（前向 12 周窗口）。
- 四因子分行业 Rank IC 并汇总 CSV。
- 新增「分位前向收益」分析：每日期截面内按因子值分 5 档，计算各档前向 12 周收益均值，输出柱状图与 CSV，直接观察单调性 / 双向反转。

## Tech Stack

- Python 3 + pandas / numpy / matplotlib（项目现有 venv `.env`，无新增依赖）。
- 数据源：SQLite `data/raw/stock.db` 的 `stock_factor`（含 size/valuation/volility/reverse/industry）与 `stock_weekly`（close，用于前向 12 周收益）。

## Implementation Approach

### 总体策略

将原本硬编码在 4 处的「三因子」列表收敛为一个配置 `FACTORS = [("列名","展示名"), ...]`，SELECT、分布、全市场 IC、分行业 IC 全部遍历该配置；并新增一个与 `report_ic`/`ic_by_industry` 风格一致的「分位前向收益」分析函数，复用同一份 `fwd_ret_w` 合并表。

### 关键技术决策

1. **配置化因子列表**：避免每加一个因子都要改 4 处硬编码（SELECT 字符串、分布循环、IC 循环、行业 IC 循环）。新增因子只需在 `FACTORS` 追加一行，符合 DRY/YAGNI。
2. **动态子图布局**：分布段由固定 `subplots(1,3)` 改为按因子数动态计算 `ncols=min(n,4); nrows=ceil(n/ncols)`，兼容 3→4（及未来更多）因子，不破坏现有三因子的显示。
3. **分位收益分析（核心优化）**：`report_quintile_ret(df, fcol, wcol, min_cs, label)`——按 trade_date 截面用 `pd.qcut(...,5,duplicates="drop")` 分档，跨日对各档 `fwd_ret_w` 取均值。比单纯 Rank IC 更直观：能直接看出 reverse 的 Q5（最超跌）收益 > Q1（最超买）收益，验证双向反转；对其它因子可看单调性方向。
4. **reverse 方向语义**：reverse 设计为正分=超跌=预期向上反转，故其 Raw Rank IC 应为正、分位收益应单调递增（Q1→Q5 升）。不人为翻转符号，保持与其它因子一致口径，仅通过分位图直观呈现。

### Performance & Reliability

- 数据量与现有脚本一致（周频全市场截面），新增 reverse 仅多取一列；IC/行业/分位三处均为 O(行数) 的单遍 groupby，无 N+1、无重复取数。
- 前向收益 `fwd_ret_w` 仅在 main 中计算一次并 merge 到因子表，四因子与分位分析共用，避免重复 shift。
- `qcut` 在单截面样本不足（<MIN_CS）或唯一值过少时可能分档数不足，需用 `duplicates="drop"` 并在档数不足时跳过该日；NaN 因子值天然被 `qcut` 排除。

## Implementation Notes

- **复用现有通用函数**：`_rank_ic` / `ic_series` / `report_ic` / `ic_by_industry` 均为因子无关的纯函数，仅调用方入参（列名/label）变化，不修改其内部逻辑。
- **SELECT 改动**：`... size, valuation, volility, reverse, industry ...`，`reverse` 与现有三因子同表同键（ts_code+trade_date），`upsert_stock_factor` 已落库，无需改表结构。
- **industry 兜底**：`factor["industry"] = factor["industry"].fillna("未知")` 已存在，保证 reverse 行即使缺 industry 也能归入「未知」组，不影响行业 IC 运行。
- **布局兼容**：动态 `subplots` 需 `plt.tight_layout()` 与 `figsize` 随因子数调整，避免 4 张图挤在一起；分布图文件名沿用现有 `factor_distribution.png`（覆盖旧图即可）。
- **blast radius**：仅改 `analyze_factor_ic.py`，不动 `cal_reverse_factor` 及其它因子计算、不动 `_rank_ic` 等算法、不新增依赖；向后兼容（原三因子输出文件名/口径不变，仅多 reverse 相关产物）。

## Architecture Design

现有脚本为单文件线性流程（main 内：取数 → 前向收益 → 合并 → 分布 → 全市场 IC → 分行业 IC → 输出）。本改动在数据结构上引入 `FACTORS` 配置驱动，使「取数列、分布、IC、行业 IC、分位收益」五段统一以因子列表为单一数据源；新增的 `report_quintile_ret` 作为与 `report_ic` 平级的独立分析段，复用同一 `fwd_ret_w` 合并 DataFrame，不增加额外取数或耦合。

## Directory Structure

```
src/analyze_factor_ic.py   # [MODIFY]
  - 顶部新增 FACTORS 配置（列名+展示名），并更新文件头 docstring 由「三因子」改为「四因子」+ 分位收益说明。
  - main() 内 SELECT 增加 reverse 列。
  - 数据分布段：因子列遍历 FACTORS，subplots 改为按因子数动态布局（复用 bins/labels）。
  - 全市场 IC 段：循环遍历 FACTORS（label = 展示名+"_12w"）。
  - 分行业 IC 段：循环遍历 FACTORS，汇总 CSV 逻辑不变。
  - 新增 report_quintile_ret(df,fcol,wcol,min_cs,label)：截面 qcut 5 档→各档前向收益均值→柱状图+CSV；main 中调用，遍历 FACTORS。
```

## Key Code Structures

- `FACTORS = [("size", "规模"), ("valuation", "估值"), ("volility", "波动"), ("reverse", "反转")]`（配置项）
- `report_quintile_ret(df, fcol, wcol, min_cs, label) -> None`（新增分析函数，风格对齐 report_ic）