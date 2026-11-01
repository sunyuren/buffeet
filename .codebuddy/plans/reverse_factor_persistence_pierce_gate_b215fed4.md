---
name: reverse_factor_persistence_pierce_gate
overview: 优化反转因子 cal_reverse_factor：在 R1-R4 四个子分上引入"持续性 OR 穿透"双门控，使满分反转信号仅在不满足"连续 K=4 周同向超卖/超买"或"大幅刺穿波动区间"时才出现，过滤单周噪声尖峰。R4 在保留现有 PIERCE 穿透基础上叠加 streak 门控。落库仍为 StockFactor.reverse 单列，不改 ORM/表结构。
todos:
  - id: add-helpers-constants
    content: 新增模块级 _smoothstep 与阈值常量(K/ACT/BIAS_FULL/CCI_FULL/MACD_FULL)
    status: completed
  - id: extend-lookback-guard
    content: 扩展 q_start 回溯 K+2 周并加写库守卫，停止写前过滤 trade_date
    status: completed
    dependencies:
      - add-helpers-constants
  - id: compute-pierce
    content: 循环内计算 R1/R2/R3/R4 自然尺度穿透因子 pierce
    status: completed
    dependencies:
      - add-helpers-constants
  - id: streak-gate-synthesis
    content: 维护跨周 streak 算 persist，gate=max 后门控子分并替换 scores 合成
    status: completed
    dependencies:
      - extend-lookback-guard
      - compute-pierce
  - id: docstring-lint
    content: 同步 docstring 并 read_lints 校验，提示全量重算
    status: completed
    dependencies:
      - streak-gate-synthesis
---

## 用户需求

优化反转因子 `cal_reverse_factor` 的 R1–R4 子项，使"满分反转信号"只在以下两种情形之一出现（OR 关系）：

1. 同一反转方向（超卖/超买）**连续 K 周（默认 K=4）** 持续出现；
2. 单周**大幅刺穿波动区间**（自然尺度极端值），即便只出现 1 周也能满分。

澄清结论：K=4；R4 在保留现有 PIERCE 穿透基础上**叠加持续性门控**（四个子分统一口径）；门控粒度默认按"每子分独立门控"（用户原话提及 R1-R4 子项）。

## 核心特性

- 每个子分最终得分 = 方向 × |原始分| × gate，gate = max(持续性因子, 穿透因子) ∈ [0,1]。
- 持续性因子 `persist = smoothstep(clip(streak/K,0,1))`：1 周≈0.25，4 周封顶 1.0；streak 为各子分"同向且超过激活阈值(如 |raw|>20)"的连胜计数，翻转/跌破阈值重置为 1，NaN 不增不减。
- 穿透因子各指标自然尺度：R1 用 |bias%|（BIAS_FULL≈0.3）、R3 用 |CCI|（CCI_FULL≈200）、R2 用 |macd_dea_pct|（MACD_FULL≈0.05）、R4 复用现有 PIERCE 逻辑（仅对刺穿 ±80 的部分计穿透）。
- 单周温和偏离被 gate 压低（不再单周满分）；单周巨幅刺穿或连续 4 周同向 → 满分。
- 落库仍为单列 `StockFactor.reverse`（向下取整 int），不改动 ORM / 表结构；需全量重算对齐新口径。

## 技术栈

- 现有项目：Python + pandas + SQLAlchemy ORM，沿用 `robust_z_to_score` / `rank_to_score` 归一化范式与既有逐周截面合成循环。**无新增依赖、无新增表/类/模块**。

## 实现方案

采用"**循环内 + 跨周状态字典**"的最小侵入式改造，复用现有 per-week 截面计算（robust_z 在循环内逐截面调用），仅在原合成前插入 1) 穿透因子、2) 持续性因子、3) gate、4) 子分门控；并在取数/循环层加入"回溯种子 + 写库守卫"以保证 streak 初值正确且不影响落库范围。

- **关键决策 1（不向量化重构）**：`r1..r4` 依赖当周截面分布，无法脱离当周在 `ind` 上纯预计算；保留循环内计算，仅用 dict 维护 `streak[code][key]` 跨周状态，diff 最小、blast radius 可控，与现有 `pd.notna` 合成范式完全兼容。
- **关键决策 2（回溯种子）**：现有 `q_start` 仅等于 `start_date`，会导致中途起算把长期超卖误判为"第 1 周"而压低。改为把 `q_start` 向前扩 `K+2` 周取数，且**不**对 `trade_date` 做写库前过滤（仍遍历全序列），在合成后加写库守卫 `if start_date and td < start_date: continue`（仍更新 streak）。
- **关键决策 3（gate=max 的 OR 语义）**：`gate = np.maximum(persist, pierce)`，保证"连续数周"与"大幅刺穿"任一满足即满分，不满足双条件，避免过度严格。
- **R4 双门控**：R4 原始映射已含 PIERCE 穿透（`PIERCE=0.25`，贴轨仅 ±80），新增 `pierce_r4 = clip((|r4|-80)/20, 0, 1)` 承接其刺穿部分，再与 persist 取 max，四个子分口径统一。

## 性能与可靠性

- 额外取数仅 `K+2≈6` 周周频指标，数据量可忽略；streak 字典为 O(股票数) 内存，逐周更新开销极低；gate/合成均为当周向量化（ndarray/Series）运算，无 N+1、无循环内重复遍历。
- 沿用 `pd.notna(sc)`（非 `sc.notna()`）兼容 R3(`np.clip`)/R4(`np.where`) 为 numpy ndarray 的既有坑；NaN 周 streak 不增不减，避免停牌伪信号污染。
- 落库单列 `reverse` 不变；建议重跑全量以对齐新口径。

## 实现注意

- 新增模块级 `_smoothstep(t)=t*t*(3-2*t)` 小工具（与现有归一化函数同区），避免重复造轮子。
- 阈值常量集中定义于函数顶部：`K=4, ACT=20.0, BIAS_FULL=0.3, CCI_FULL=200.0, MACD_FULL=0.05, PIERCE` 沿用既有（保持 R4 不变）。
- streak 更新顺序：先取 `prev_sign/prev_count` → 计算 `active = notna(raw) & (|raw|>ACT)` → 同号且 active 则 `count+1`，否则 active 则 `count=1` 否则 `0` → 写回 dict。
- 写库守卫必须位于"计算 r1..r4、更新 streak、合成"之后、组装 `out_df` 之前，确保回溯周只喂 streak 不落库。

## 架构设计

单函数内部扩展，数据流保持：`区间取数(扩回溯) → 逐周截面计算 r1..r4 → 计算 pierce 因子 → 更新 streak 算 persist → gate=max → 门控子分 → 等权合成 → upsert 单列 reverse`；与现有架构完全对齐，不新增模块。

```mermaid
flowchart TD
    A[周频截面: r1..r4 原始分 方向+幅度] --> B[穿透因子 pierce: R1 bias%/R3 CCI/R2 macd%/R4 刺穿部分]
    A --> C[跨周 streak → 持续性因子 persist=smoothstep streak/K]
    B --> G[gate = max persist, pierce  in 0..1]
    C --> G
    G --> F[门控子分 = 方向 × |原始| × gate]
    F --> S[等权 1:1:1:1 合成 → reverse 单列落库]
    L[回溯 K+2 周取数 + 写库守卫] -->|种子 streak| C
```

## 目录结构

```
src/
└── factor.py   # [MODIFY] cal_reverse_factor
                #  - 顶部新增 _smoothstep 工具 + 阈值常量(K/ACT/BIAS_FULL/CCI_FULL/MACD_FULL)；
                #  - 取数: q_start 向前扩 K+2 周；trade_date 不再写前过滤，改在循环末加写库守卫；
                #  - 循环内: 计算 pierce_r1/r2/r3/r4(自然尺度)；维护 streak[code][key] 跨周状态算 persist；
                #    gate=max(persist,pierce)；用门控后 r1_g..r4_g 替换 scores 字典；
                #  - docstring 同步"连续 K 周 OR 大幅刺穿"新口径与权重。
```

## 关键代码结构

```python
# 模块级（与 robust_z_to_score 同区）
def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)

# 循环内单周门控核心（示意，r 为当周某子分原始 Series/ndarray，raw_ind 为自然尺度列）
persist = _smoothstep(min(streak_val / K, 1.0))
pierce  = np.clip(np.abs(raw_ind) / FULL, 0.0, 1.0)   # R1 FULL=0.3 / R3 FULL=200 / R2 FULL=0.05 / R4 用 (|r4|-80)/20
gate    = np.maximum(persist, pierce)
r_gated = np.sign(r) * np.abs(r) * gate               # 压低单周温和信号
```