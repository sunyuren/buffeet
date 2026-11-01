---
name: 估值因子trimmed-mean改造
overview: 改造 cal_valuation_factor,将 pe/pb/ps 三个估值倍数改为 trimmed-mean 聚合(丢弃每行最低分、保留高分两项平均),pb 改回全市场截面且价值方向,dv_ttm 作为独立维度(权重4),三选二选出项各权重3。仅改 src/factor.py,不改动表结构与 FACTOR_REGISTRY。
todos:
  - id: update-docstring
    content: 更新 cal_valuation_factor 的 docstring 权重口径说明
    status: completed
  - id: rewrite-normalize
    content: 重写 3.3 归一化:pb 改全市场价值方向,pe/pb/ps 统一 robust_z_to_score
    status: completed
  - id: rewrite-synthesis
    content: 重写 3.4 合成:trimmed 选高分两项并与 dv_ttm(权重4)缺失自适应合成
    status: completed
    dependencies:
      - rewrite-normalize
  - id: remove-obsolete
    content: 删除旧 weights 字典与旧 score_cols 权重循环
    status: completed
    dependencies:
      - rewrite-synthesis
  - id: lint-verify
    content: 运行 lint 校验 factor.py 无新增错误
    status: completed
    dependencies:
      - remove-obsolete
---

## 用户需求

将估值因子 `cal_valuation_factor` 的聚合方式从「固定权重合成」改造为经典的 **trimmed-mean(截尾均值)** 聚合,降低单一失真估值指标对合成分的拖累。

## 核心口径(用户确认)

1. `pe_ttm`、`pb`、`ps_ttm` 三个估值倍数各自归一化后,逐行比较:丢弃得分最低的一项,保留高分的两项求平均 → `mult_score`。
2. `pb` 改回**价值方向**(去掉原 `-1`,即低 PB→高分),并改回**全市场截面**比较(不再按行业 `groupby`)。
3. `dv_ttm`(股息率)保留为**独立维度**,权重 4;三选二选出的两项各赋权 3(即倍数块合计权重 6)。
4. 最终 `valuation = (mult_score * Wm + dv_ttm_score * 4) / (Wm + 4)`,其中 `Wm` 按有效倍数个数自适应(≥2 项时=6,仅 1 项时=3,0 项时=0),分母为 0 时置 NaN。

## 功能效果

- 当某股票因一次性损益导致 PE 暴增(→低估值分)等异常时,该异常项作为三项的「最低分」被丢弃,不再拉低合成估值分,提升价值信号的稳健性。
- 不改变 `StockFactor.valuation` 的落库列与 `[-100,100]` int 值域,不影响其他因子与 `FACTOR_REGISTRY`。

## 技术栈

- 语言/运行时:Python 3 + pandas + numpy(与现有 `factor.py` 一致)
- 复用既有工具:`robust_z_to_score`(截面稳健 z 标准化,映射到 `[-100,100]`)、`get_daily_basic_by_trade_date`、`upsert_stock_factor`
- 无需新增依赖、无需改表结构(`StockFactor.valuation` 为 Integer 列,`StockDailyBasic` 已含 `pe_ttm/pb/ps_ttm/dv_ttm`)

## 实现方案

在 `src/factor.py` 的 `cal_valuation_factor` 内做局部改造,保持函数整体流程(交易日循环、取数、落库)不变,仅替换「归一化(3.3)」与「合成(3.4)」两段,并同步更新 docstring。

### 关键决策与理由

1. **归一化一致性**:为让 top-2 选择更可比,将 `pe/pb/ps` 三项统一为**全市场 `robust_z_to_score`**(`pe` 已是;`pb`、`ps` 由 `rank_to_score` 切换)。两者单调保序映射到 `[-100,100]`,不影响 trimmed 选择,且 `robust_z` 对右偏的 PE/PS 更稳健。
2. **pb 方向修正**:去掉 `groupby("industry")` 与 `-1`,改为 `robust_z_to_score(pb_inv)`,实现全市场、低 PB→高分(价值方向),与 pe/ps 语义一致。
3. **trimmed 聚合**:用 `np.sort(arr, axis=1)` 将 NaN 排至行末;`cnt==3` 时减去最小有效值(`s[:,0]`)即丢弃最低分,`cnt<3` 时保留全部有效项求平均。该向量化写法避免逐行 Python 循环,性能与现有截面计算同量级。
4. **缺失自适应**:有效倍数个数 `cnt` 决定 `Wm`(≥2→6,==1→3,==0→0);`dv_ttm` 有效则权重 4。最终合成分母可能为 0(如全部缺失),此时置 NaN,由下游 `out_df = out_df[out_df["valuation"].notna()]` 自然剔除。

### 实现注意事项

- 旧 `weights` 字典(374–379 行)与旧 `score_cols` 固定权重循环(419–436 行)将被新逻辑取代,需整段删除,避免遗留无效代码。
- `mult_score` 与 `dv_ttm_score` 均为 `[-100,100]`,加权后 `valuation` 自然落在同区间,沿用现有 `np.floor` 取整 + `astype(int)` 落库即可。
- 复用 `np.errstate(divide="ignore", invalid="ignore")` 包裹除法,避免 NaN/0 告警。
- docstring 中 349 行旧权重描述("3\*股息率+3\*市盈率+2\*市销率+2\*市净率")需同步改写为 trimmed-mean + 独立股息率权重 4 的口径。

## 架构设计

本次为纯函数内部逻辑改造,不引入新表/新模块,不改动 `StockFactor` 其他列与 `FACTOR_REGISTRY`。数据流保持不变:
`get_all_date() → 逐交易日 get_daily_basic_by_trade_date → 倒数变换 → 三项倍数归一化(全市场 robust_z) → trimmed 选高分两项 → 与 dv_ttm(权重4)缺失自适应合成 → floor int → upsert_stock_factor`。
`mult_score` 作为内部中间量,不单独落库(保持 `StockFactor` 表结构稳定)。

## 目录结构(仅改动文件)

```
src/
└── factor.py   # [MODIFY] cal_valuation_factor
                #  - 删除旧 weights 字典(374-379)
                #  - 重写 3.3 归一化:pb 改全市场价值方向;pe/pb/ps 统一 robust_z_to_score
                #  - 重写 3.4 合成:trimmed 选高分两项 + dv_ttm 权重4 缺失自适应合成
                #  - 同步更新 docstring 权重说明(约349行)
                #  - 落库逻辑(438-462)保持不变
```

## 关键代码结构(trimmed 聚合核心片段)

```python
mult_cols = ["pe_ttm_score", "pb_score", "ps_ttm_score"]
arr = val_df[mult_cols].to_numpy(dtype=float)
s = np.sort(arr, axis=1)                       # 行内升序,NaN 落末尾
cnt = np.nansum(~np.isnan(arr), axis=1).astype(int)
valid_sum = np.nansum(arr, axis=1)
min_valid = s[:, 0]                            # 行内最小有效值(cnt==0 时为 NaN)
adj_sum = np.where(cnt == 3, valid_sum - min_valid, valid_sum)
mult_score = np.where(cnt >= 2, adj_sum / np.where(cnt == 3, 2, cnt),
                      np.where(cnt == 1, valid_sum, np.nan))

Wm = np.where(cnt >= 2, 6, np.where(cnt == 1, 3, 0))
Wdv = val_df["dv_ttm_score"].notna().astype(float) * 4
numerator = mult_score.fillna(0) * Wm + val_df["dv_ttm_score"].fillna(0) * Wdv
den = Wm + Wdv
with np.errstate(divide="ignore", invalid="ignore"):
    val_df["valuation"] = np.where(den > 0, numerator / den, np.nan)
```