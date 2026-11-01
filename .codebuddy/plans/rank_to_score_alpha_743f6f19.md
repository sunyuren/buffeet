---
name: rank_to_score_alpha
overview: 为 src/factor.py 的 rank_to_score 增加可选 alpha 参数，支持自定义比例截断（对称区间 [alpha, 1-alpha]），默认 0.0 保持原全量 min/max 行为，现有调用点无需改动。
todos:
  - id: modify-signature-body
    content: 为 rank_to_score 新增 alpha 参数，截断改为 quantile(alpha)/quantile(1-alpha) 并 clip
    status: completed
  - id: update-docstring
    content: 更新 rank_to_score 文档字符串，说明 alpha 截断语义与默认值
    status: completed
    dependencies:
      - modify-signature-body
  - id: verify-callers-lint
    content: 核对 2 处调用点兼容默认 alpha=0.0，并运行 lint 检查 factor.py
    status: completed
    dependencies:
      - update-docstring
---

## 用户需求

为 `src/factor.py` 中的 `rank_to_score` 函数增加 `alpha` 参数，用于自定义比例截断，与刚完成的 `robust_z_to_score` 接口扩展风格保持一致。

## 核心功能

- 为 `rank_to_score` 新增截断参数 `alpha`（默认 `0.0`），将原本固定使用全量 `pct.min()/pct.max()` 的重映射，改为按 `pct.quantile(alpha)` 与 `pct.quantile(1 - alpha)` 作为对称截断上下界，超出截断区间的百分比排名先 clip 到 `[0,1]` 再线性映射到 `[-100, 100]`，实现自定义尾部比例截断。
- 更新函数文档字符串，说明 `alpha` 控制尾部截断比例（默认 `0.0` 即全量范围，行为与旧实现逐位一致）。
- 核对全部调用点（`cal_valuation_factor` 内 2 处），因 `alpha` 默认 `0.0`，现有调用行为不变，无需改动调用代码；组内 `transform(lambda s: rank_to_score(s))` 仍可正常工作。
- 不改动 `tanh_to_score`、`robust_z_to_score`（上一轮已改）、`database.py`、ORM 及其余因子函数。

## 边界与约束

- 默认 `alpha=0.0` 时，`quantile(0)=min`、`quantile(1)=max`，全市场与按行业组内标准化数值结果与改动前完全一致，不影响已落库因子语义。
- 如需非默认截断，调用方后续可显式传 `alpha=`，本次不指定新值。

## 技术栈

- 语言：Python 3（与现有项目一致）
- 数据处理：pandas + numpy
- 改动范围：仅 `src/factor.py` 的 `rank_to_score` 函数及其文档字符串

## 实现方案

### 总体策略

沿用上一轮 `robust_z_to_score` 的接口扩展模式，做最小化、向后兼容的修改：为 `rank_to_score` 增加带默认值的 `alpha: float = 0.0` 参数，将重映射区间从写死的 `pct.min()/pct.max()` 改为 `pct.quantile(alpha)/pct.quantile(1 - alpha)`，并对重映射结果 clip 到 `[0,1]` 以吸收被截断的尾部。默认值为 `0.0` 保证所有现有调用点零改动且行为不变。

### 关键决策

1. **参数设计与默认值**：签名改为 `def rank_to_score(x: pd.Series, alpha: float = 0.0) -> pd.Series`。

- 采用对称截断 `lo = pct.quantile(alpha)`、`hi = pct.quantile(1 - alpha)`；当 `alpha=0.0` 时 `quantile(0)=min`、`quantile(1)=max`，与原全量 min/max 直接对应，计算结果逐位一致。
- 设默认值 `0.0`（而非必填）是核心：保证 `cal_valuation_factor` 内 2 处调用无需任何修改，避免引入回归与连锁改动。这与 `robust_z_to_score`（默认 `0.01`）的语义一致，只是 `rank` 百分比本就用全量范围，故默认取 `0.0` 以维持原行为。

2. **函数体改动**：

- 原：`lo, hi = pct.min(), pct.max()`
- 改：`lo, hi = pct.quantile(alpha), pct.quantile(1 - alpha)`
- 重映射后增加 `.clip(0, 1)`：`pct = ((pct - lo) / (hi - lo)).clip(0, 1)`。当 `alpha=0.0` 时所有值本就在 `[0,1]`，clip 无副作用；当 `alpha>0` 时，超出截断区间的头部/尾部被夹到 `0/1`，对应触达 `-100/+100` 极值，实现“自定义比例截断”。

3. **文档字符串同步**：将“重映射到 [0, 1]（使唯一最小值对应 0、唯一最大值对应 1）”改为说明 `alpha` 控制尾部截断比例，下限 `quantile(alpha)`、上限 `quantile(1-alpha)`，默认 `0.0` 即原全量范围；补充“不传则行为与原实现一致”。

4. **调用点兼容性验证**：

- `cal_valuation_factor` 行 411：`val_df["ps_ttm_score"] = rank_to_score(val_df["ps_ttm_inv"])`（全市场）
- 行 414：`val_df.groupby("industry")["pb_inv"].transform(lambda s: rank_to_score(s))`（按行业组内，再 ×(-1) 反向）
- 两者均不传 `alpha`，自动取默认 `0.0`，数值不变；组内 transform 的 lambda 仍合法（单参数透传，alpha 取默认）。

### 性能与可靠性

- 仅新增一次 `pct.quantile` 计算（两次，原两次 min/max 同样为 O(n)）与一次 clip，无额外遍历或内存开销，复杂度不变（O(n)）。
- 默认值保证落库因子数值稳定，不影响增量（start_date/end_date）语义与已落库数据可比性。

### 实现注意事项

- 不改动 `tanh_to_score`、`robust_z_to_score` 及 `database.py`、StockFactor ORM、`cal_size_factor`/`cal_valuation_factor` 其余逻辑与兜底处理。
- `lo == hi` 时返回全 0 序列的兜底逻辑保留。
- 改动后运行 lint 检查确认 `factor.py` 无报错。

## 目录结构

```
src/
└── factor.py   # [MODIFY]
    - rank_to_score（行 27-41）：签名新增 alpha: float = 0.0；
      重映射区间改为 quantile(alpha)/quantile(1-alpha)；结果 clip(0,1)；
      更新 docstring
    - 调用点（行 411/414）：无需改动（沿用默认 alpha=0.0）
```