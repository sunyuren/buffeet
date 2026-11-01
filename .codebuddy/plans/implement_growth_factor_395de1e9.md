---
name: implement_growth_factor
overview: 在 src/factor.py 中完成成长因子计算：将现有占位 cal_growth_factor(df) 重写为 (start_date, end_date) 自包含流程函数，参照 cal_profit_factor 的取数/剔除上市前财报/落库范式，三子项 tr_yoy/op_yoy/ocf_yoy 经 log10(1+x) 变换后全市场 robust_z_to_score，等权合成后向下取整落库到 StockFactor.growth。
todos:
  - id: rewrite-skeleton
    content: 重写 cal_growth_factor 为 (start_date,end_date) 流程函数：替换占位签名/docstring，定义 fina_fields=[ts_code,end_date,tr_yoy,op_yoy,ocf_yoy]，grep 核对无旧签名引用
    status: completed
  - id: fetch-filter
    content: 实现交易日循环取数：get_fina_indicator_by_ann_date(start_ann,td,fields) + 仅1231/0630 + groupby tail(1) + 按 list_date 剔除上市前财报（复用 profit 范式）
    status: completed
    dependencies:
      - rewrite-skeleton
  - id: transform-synth
    content: 实现 log10(1+x) 变换(1+x≤0置NaN) 与 R1/R2/R3 robust_z_to_score(alpha=0.05) 及三子等权合成 floor 落 growth
    status: completed
    dependencies:
      - fetch-filter
  - id: upsert-verify
    content: 组装 out_df 经 upsert_stock_factor 落库；py_compile + read_lints，并以窄区间(如20190101-20190331)试运行核对落库条数
    status: completed
    dependencies:
      - transform-synth
---

## 用户需求

完成任务15：在 `src/factor.py` 中实现成长因子（growth）计算逻辑，参照既有规模/估值/盈利因子的自包含流程函数范式。

## 产品概述

成长因子从财务指标表 `StockFinaIndicator` 取同比增长率，逐交易日截面计算并落库到 `StockFactor.growth`（该列已存在，Integer 可空）。因子由三个等权子项合成，衡量企业收入、利润、经营现金流的成长性。

## 核心功能

- 函数签名改为 `cal_growth_factor(start_date=None, end_date=None)`，替换原 `df` 占位签名；输入日期区间，内部通过 `get_all_date()` 生成交易日序列。
- 取数：每个交易日截面以 `end_ann_date=td`、`start_ann_date=td前一年` 调用 `get_fina_indicator_by_ann_date`，仅保留年报(1231)/中报(0630)，按 `ts_code` 取 `end_date` 最新一期；剔除报告期早于个股上市日期 `list_date` 的上市前财报（`list_date` 缺失则不过滤）。
- 三个子项（均正向越大越好，等权权重 1:1:1，和 3）：
- R1 总收入同比 `tr_yoy`：先 `log10(1+x)`（**x 为 yoy 除以 100 后的比率浮点值，如 25%→0.25**；`1+x≤0` 即同比下降超 100% 置 NaN），再全市场 `robust_z_to_score(alpha=0.05)`。
- R2 营业利润同比 `op_yoy`：同 R1 变换与标准化（x 同样为比率 yoy/100）。
- R3 经营现金净流量同比 `ocf_yoy`：同 R1 变换与标准化（x 同样为比率 yoy/100）。
- 加权合成（缺项按有效权重归一），结果 `np.floor` 向下取整为 int，落库 `growth` 列（沿用 `upsert_stock_factor` 联合主键 ts_code+trade_date）。

## 技术栈

- 语言/运行：Python 3，pandas + numpy（项目既有因子计算栈）。
- 数据源：复用 `database` 模块已导入的 `get_all_date`、`get_all_stocks`、`get_fina_indicator_by_ann_date`、`upsert_stock_factor` 与 `StockFactor` 模型；无需新增依赖或建表（`growth` 列已存在）。

## 实现方案

整体**镜像 `cal_profit_factor` 的自包含流程函数骨架**（已确认其范式：交易日排序/过滤 → `stock_info` 构建与 `list_date` 缓存 → `fina_fields` 取数 → 仅 1231/0630 + `groupby("ts_code").tail(1)` 取最新 → 按 `list_date` 剔除上市前财报 → `section` 合并 name/industry 与列兜底 → 子项归一化 → numerator/denom 有效权重归一合成 → `np.floor` 转 int → `out_df` 落库）。差异仅在取数字段、子项变换与落库列名。

关键决策：

1. **log10(1+x) 变换**：依用户澄清，`x` 为 yoy 除以 100 后的比率浮点值（如 25% → 0.25），直接计算 `log10(1+x)`；用 `np.errstate(divide="ignore", invalid="ignore")` 抑制告警，并以 `.where(base > 0)` 将 `1+x≤0`（同比降幅 ≥100% 的极端情形）置 NaN，与 `cal_valuation_factor` 的 amount log10 处理一致。该变换使下滑（负增长）仍得负分、保留方向信息。
2. **标准化 alpha**：用户未指定。`robust_z_to_score` 默认 `alpha=0.01`，但最近实现的 profit/valuation 均显式用 `alpha=0.05`；为保持一致采用 `alpha=0.05`（集中定义，便于后续统一调整）。
3. **等权合成**：三子项权重 1:1:1（和 3），沿用 profit 的 numerator/denom 有效权重归一逻辑，避免单一子项缺失拖累整体。
4. **落库列**：`out_df` 输出 `ts_code/name/industry/trade_date/growth`，过滤 `growth` 非空后 `astype(int)` 再 `upsert_stock_factor`，与 profit 尾部完全一致。

## 实现要点（防回归）

- 严格复用既有范式，不引入新架构/新工具函数；`log10` 的 NaN 兜底与 valuation 因子保持一致，避免负增长静默丢失。
- `section` 列兜底：对 `tr_yoy/op_yoy/ocf_yoy` 缺失列补 `np.nan`，保证 `get_fina_indicator_by_ann_date` 缺列时不报错。
- 性能与 profit 同级：逐 td 循环 + pandas `groupby.transform/tail`，数据量可控；避免在循环外重复查询。
- 兼容性：已确认全文仅 1 处 `cal_growth_factor` 定义、无调用方，`cal_all_factors` 为骨架版不调用；实施时 grep 核对 `FACTOR_REGISTRY`/其它引用，确保无旧签名依赖。

## 架构设计

沿用因子模块现有分层：`cal_growth_factor` 作为独立流程函数，直接取数→截面归一化→落库，与 `cal_profit_factor` 并列，不改动聚合入口或 ORM。无新模块/新表，改动收敛在单文件单函数。

## 目录结构

```
src/
└── factor.py   # [MODIFY] 替换 line~1210 的 `cal_growth_factor(df)` 占位为流程函数：
                #   1) 签名改为 (start_date, end_date)->None，写 docstring；
                #   2) fina_fields=[ts_code,end_date,tr_yoy,op_yoy,ocf_yoy]；
                #   3) 交易日循环取数+剔除上市前财报（复用 profit 范式）；
                #   4) log10(1+x) 变换（x=yoy/100）+ R1/R2/R3 robust_z_to_score(alpha=0.05)；
                #   5) 等权合成 floor 落 growth，upsert 落库。
                #   顺带 grep 确认 FACTOR_REGISTRY 等无旧签名引用（无需改动则跳过）。
```

## 关键代码结构

```python
def cal_growth_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    ...

# 核心变换（每个 yoy 子项通用，x 为比率 = yoy/100）
with np.errstate(divide="ignore", invalid="ignore"):
    base = 1.0 + section[col].astype(float) / 100.0   # col ∈ {tr_yoy, op_yoy, ocf_yoy}
    log_val = np.log10(base)
log_val = log_val.where(base > 0)                     # 1+x ≤ 0（同比降幅≥100%）置 NaN
score = robust_z_to_score(log_val, alpha=0.05)
```