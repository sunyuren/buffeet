---
name: robust_z_alpha_param_v1
overview: 为 robust_z_to_score 增加截断值参数 alpha（默认 0.01，等价于原写死的 1%/99% 对称截断），将函数体内写死的 0.01/0.99 改为 alpha/1-alpha，并同步更新文档字符串。所有现有调用点因默认值保持 0.01 而行为不变、无需实质改动（含 cal_size_factor 与 cal_valuation_factor 的组内 transform lambda），仅确保调用兼容。
todos:
  - id: modify-signature-body
    content: 修改 robust_z_to_score 签名新增 alpha 参数，并将截断改为 quantile(alpha)/quantile(1-alpha)
    status: completed
  - id: update-docstring
    content: 更新 robust_z_to_score 文档字符串，说明 alpha 截断语义与默认值
    status: completed
    dependencies:
      - modify-signature-body
  - id: verify-callers-lint
    content: 核对 6 处调用点兼容默认 alpha=0.01，并运行 lint 检查 factor.py 确认无报错
    status: completed
    dependencies:
      - update-docstring
---

## 用户需求

修改 `src/factor.py` 中的 `robust_z_to_score` 归一化函数，将其写死的对称截断区间 `[1%, 99%]` 中的下限 `0.01` 抽离为可输入参数，并提供配套调整，使其他代码能正确适配。

## 核心功能

- 为 `robust_z_to_score` 新增截断值参数 `alpha`（默认 `0.01`），把原写死的 `z.quantile(0.01), z.quantile(0.99)` 改为 `z.quantile(alpha), z.quantile(1 - alpha)`，保持对称截断语义。
- 更新函数文档字符串，说明 `alpha` 控制尾部截断比例（默认即原 `[1%, 99%]`）。
- 核对全部调用点（`cal_size_factor` 4 处、`cal_valuation_factor` 2 处），因 `alpha` 有默认值 `0.01`，现有调用行为逐位不变，无需改动调用代码；组内 `transform(lambda s: robust_z_to_score(s))` 仍可正常工作。
- 不改动 `rank_to_score` / `tanh_to_score`、不改动 `database.py`、ORM 及其余因子函数。

## 边界与约束

- 默认 `alpha=0.01` 时，全市场与按行业组内标准化数值结果与改动前完全一致，不影响已落库因子语义。
- 如需对特定截面使用不同截断，调用方后续可显式传 `alpha=`，本次不指定新值。

## 技术栈

- 语言：Python 3（与现有项目一致）
- 数据处理：pandas + numpy
- 改动范围：仅 `src/factor.py` 的 `robust_z_to_score` 函数及其文档字符串

## 实现方案

### 总体策略

仅做最小化、向后兼容的接口扩展：为 `robust_z_to_score` 增加带默认值的 `alpha: float = 0.01` 参数，将截断区间改为 `quantile(alpha)` 与 `quantile(1 - alpha)`。由于默认值为 `0.01`，所有现有调用点零改动且行为不变；后续如需非默认截断，调用方显式传参即可。

### 关键决策

1. **参数设计与默认值**：签名改为 `def robust_z_to_score(x: pd.Series, alpha: float = 0.01) -> pd.Series`。

- 采用对称截断 `lo = quantile(alpha)`、`hi = quantile(1 - alpha)`，与原 `[1%, 99%]` 直接对应，`alpha=0.01` 时计算结果逐位一致。
- 设默认值（而非必填）是核心：保证 `cal_size_factor` / `cal_valuation_factor` 内 6 处调用无需任何修改，避免引入回归与连锁改动。

2. **函数体改动**：

- 原函数体：`lo, hi = z.quantile(0.01), z.quantile(0.99)`
- 改为：`lo, hi = z.quantile(alpha), z.quantile(1 - alpha)`
- 其余逻辑（median/MAD 计算、mad==0 置 0、hi/lo 为 0 时的兜底、正负尾部分别缩放至 [-100,100]）完全不变。

3. **文档字符串同步**：将“按 [1%, 99%] 分位数分别重映射”改为说明 `alpha` 控制尾部截断比例，下限 `quantile(alpha)`、上限 `quantile(1-alpha)`，默认 `0.01` 即原 `[1%, 99%]`；缺省说明“不传则行为与原实现一致”。

4. **调用点兼容性验证**：

- `cal_size_factor`：269/270 全市场调用、273/277 组内 `transform(lambda s: robust_z_to_score(s))` 均不传 `alpha`，自动取默认 `0.01`，数值不变。
- `cal_valuation_factor`：404/405 全市场调用同理。
- 组内 transform 的 lambda 仍合法（单参数透传，alpha 取默认）。

### 性能与可靠性

- 仅新增一个浮点参数与一次 `1 - alpha` 减法，无额外遍历或内存开销，复杂度不变（O(n)）。
- 默认值保证落库因子数值稳定，不影响增量（start_date/end_date）语义与已落库数据可比性。

### 实现注意事项

- 不改动 `rank_to_score`、`tanh_to_score` 及其他归一化函数。
- 不改动 `database.py`、StockFactor ORM、`cal_size_factor`/`cal_valuation_factor` 其余逻辑与兜底处理。
- 改动后运行 lint 检查确认 `factor.py` 无报错。

## 目录结构

```
src/
└── factor.py   # [MODIFY]
    - robust_z_to_score（行 61-88）：签名新增 alpha: float = 0.01；
      函数体截断改为 quantile(alpha)/quantile(1-alpha)；更新 docstring
    - 调用点（行 269/270/273/277/404/405）：无需改动（沿用默认 alpha=0.01）
```