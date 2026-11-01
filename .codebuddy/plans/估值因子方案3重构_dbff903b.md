---
name: 估值因子方案3重构
overview: 按方案3重构 src/factor.py 的 cal_valuation_factor 四个子分口径：dv_ttm 一半行业内robust_z+一半全市场robust_z；pe/ps 取倒数后与行业均值作差（行业中性化）再全市场robust_z（价值方向）；pb 不取倒数、行业内rank_to_score（成长方向）。合成沿用现有四子分加权 2/1/1/1 按有效权重归一，落库逻辑不变。
todos:
  - id: adjust-inv
    content: 调整 3.2 倒数变换，inv_cols 移除 pb 保留原始 pb 列
    status: completed
  - id: rewrite-subscores
    content: 重写 3.3 四子分：dv_ttm 半行业半全市场、pe/ps 行业中性化全市场 robust_z、pb 行业内 rank_to_score
    status: completed
    dependencies:
      - adjust-inv
  - id: docs-lint
    content: 更新 cal_valuation_factor docstring 并 read_lints 检查 src/factor.py
    status: completed
    dependencies:
      - rewrite-subscores
  - id: recompute
    content: 切片重算估值落库验证无 KeyError/除零，再全量重算覆盖
    status: completed
    dependencies:
      - docs-lint
  - id: verify-ic
    content: 跑 analyze_factor_ic 验证 valuation 全市场 IC 显著为正、分位 Q5>Q1
    status: completed
    dependencies:
      - recompute
---

## 用户需求

重构 `src/factor.py` 中 `cal_valuation_factor`（估值因子）的四个子分计算口径（方案3），保持现有四子分加权合成（dv_ttm 权重 2、pe_ttm 权重 2、pb/ps_ttm 各权重 1，按有效权重归一）与落库逻辑不变。

## 核心特性

- **dv_ttm_score**：一半行业内 `robust_z` + 一半全市场 `robust_z`，兼顾行业相对水平与全市场绝对水平。
- **pe / ps**：取倒数，与行业均值作差（行业中性化）后，全市场 `robust_z_to_score`；低估值（高倒数）→ 高分，价值方向。
- **pb**：不取倒数，直接行业内 `rank_to_score`；高 PB → 高分，成长方向，不反向。
- **合成与落库**：四子分加权 2/2/1/1（dv_ttm 2、pe_ttm 2、pb 1、ps_ttm 1）按有效权重归一，向下取整为 int 落库 `StockFactor.valuation`；子分本身不落库。

## 技术栈

- Python 3 + pandas / numpy（项目现有 venv）
- 复用现有归一化函数 `robust_z_to_score`（中位数/MAD 稳健 z，对称重映射至 [-100,100]）、`rank_to_score`（截面排名百分比映射 [-100,100]）
- 数据落库 SQLite 的 `StockFactor.valuation`（经 `upsert_stock_factor`）

## 实现方案

### 总体策略

仅改动 `cal_valuation_factor` 的 3.2（倒数变换）与 3.3（归一化）两段；3.4（合成）、3.5（落库）完全沿用现有逻辑，保证向后兼容与最小改动面。

### 关键技术决策

1. **倒数变换收窄**：`inv_cols` 由 `("pe_ttm","pb","ps_ttm")` 改为 `("pe_ttm","ps_ttm")`，pb 不再取倒数，直接使用 `val_df["pb"]` 原始列（供成长方向打分）。
2. **dv_ttm 混合打分**：`groupby("industry")["dv_ttm"].transform(robust_z_to_score) * 0.5 + robust_z_to_score(val_df["dv_ttm"]) * 0.5`，叠加行业相对与全市场绝对。
3. **pe / ps 行业中性化后全市场 robust_z**：`pe_inv = 1/pe`（>0 才取，否则 NaN），`pe_centered = pe_inv - groupby("industry")["pe_inv"].transform("mean")`，再 `robust_z_to_score(pe_centered)` 全市场；ps 同法。低估值 → 高分（价值方向）。
4. **pb 成长方向**：`groupby("industry")["pb"].transform(rank_to_score)`，不取倒数、不乘 -1 反向，高 PB → 高分（成长方向）。
5. **合成与落库不变**：`weights={dv_ttm:2, pe_ttm:2, pb:1, ps_ttm:1}`，有效权重归一，`valuation` 向下取整 int，`upsert_stock_factor` 落库，仅保留非空记录。

### 性能与可靠性

- 全部为向量化 `groupby.transform` / pandas 运算，单截面 O(股票数)，无逐行 Python 循环。
- `np.errstate` 包裹倒数除零；行业均值 `transform("mean")` 对全 NaN 组返回 NaN，下游合成按有效权重跳过，无除零风险。
- 改动局限于 `cal_valuation_factor` 单函数，不触及 `cal_reverse_factor` / `cal_volatility_factor` 等其它因子，不删除任何函数，不新增依赖。

## 目录结构

```
src/factor.py   # [MODIFY]
  - 3.2 节：inv_cols 改为 ("pe_ttm","ps_ttm")，保留 pb 原始列。
  - 3.3 节：重写 dv_ttm_score（半行业半全市场）、
            pe_ttm_score / ps_ttm_score（行业中性化 + 全市场 robust_z）、
            pb_score（行业内 rank_to_score，不反向）。
  - docstring（335–354 行）：同步 3.3 子分口径说明。
  - 3.4 / 3.5 节：保持不动（合成权重与落库逻辑沿用）。
```

## 验证方式

- 编辑后 `read_lints` 检查 `src/factor.py`，确保无语法/类型告警。
- 先用小日期切片 `cal_valuation_factor(start_date=..., end_date=...)` 验证无 `KeyError` / 除零；再全量重算覆盖 `StockFactor.valuation`。
- 重跑 `python src/analyze_factor_ic.py`（其 `FACTORS` 含 `valuation`、SQL 含 `valuation`），确认 `valuation` 全市场 Rank IC 显著为正、分位收益 Q5（最价值/低估）> Q1（最贵）；抽查分行业 IC 合理。