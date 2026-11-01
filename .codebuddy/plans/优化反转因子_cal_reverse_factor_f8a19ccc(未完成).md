---
name: 优化反转因子 cal_reverse_factor
overview: 按用户的四子分新规改造 src/factor.py 的 cal_reverse_factor：R1(60周乖离率)保持不变；R2 改用 macd_bar_pct=macd_bar/close（保留既有 0.8水平/0.2收敛金叉混合）；R3 改为 CCI 截取[-200,200]后÷2 线性映射到[-100,100]（弃用 tanh_to_score）；R4 改为「贴/破 BOLL 轨」得分成居中[-100,100]（下轨+100/上轨-100，按方案A）。合成(等权1:1:1:1)与落库逻辑不变；并把 close 合并进 ind 以在指标层计算 macd_bar_pct 及其环比、移除循环内重复的 wk 合并。
todos:
  - id: refactor-fetch
    content: 在 3.2 节把 close 合并进 ind，并在第 4 节补 macd_bar_pct / macd_bar_pct_prev 计算
    status: completed
  - id: rewrite-r2
    content: 改写 R2：改用 macd_bar_pct 的 0.8/0.2 水平+收敛混合
    status: completed
    dependencies:
      - refactor-fetch
  - id: rewrite-r3
    content: 改写 R3：CCI 截取[-200,200]后÷2 线性映射到[-100,100]，弃用 tanh_to_score
    status: completed
  - id: rewrite-r4
    content: 改写 R4：BOLL 轨接触/刺穿得分成居中[-100,100]
    status: completed
  - id: docs-and-lint
    content: 移除循环内重复 wk 合并，更新 docstring，read_lints 检查 src/factor.py
    status: completed
    dependencies:
      - rewrite-r2
      - rewrite-r3
      - rewrite-r4
  - id: verify-recompute
    content: 重算 reverse 落库并跑 analyze_factor_ic 验证 IC 与分位单调性
    status: in_progress
    dependencies:
      - docs-and-lint
---

## 用户需求

优化 `src/factor.py` 的 `cal_reverse_factor`，按四个子分的新口径重构，使反转因子保持「双向反转」特性（底部超跌接近 +100、顶部超买接近 -100）。

## 核心特性

- **R1（60 周均线乖离率）**：保持不变，`bias=(close-ma60)/ma60`，`robust_z_to_score(-bias)`。
- **R2（MACD）**：用 `macd_bar_pct = macd_bar / close` 替代 `macd_bar`；保留现有「0.8 水平 + 0.2 收敛/金叉」混合结构，仅替换底层变量（含其紧邻前一周环比）。
- **R3（CCI）**：不再使用 `tanh_to_score`；改为 `CCI` 截取至 `[-200, 200]` 后除以 2，线性映射到 `[-100, 100]`（低 CCI 超卖→高分，高 CCI 超买→低分）。
- **R4（BOLL 轨）**：`close` 接触/连续接触/大幅刺穿 `boll_lower` → 高分（极值 100）；接触/连续接触/大幅刺穿 `boll_upper` → 低分（极值对应 -100）。按已确认方案 A 将其居中到 `[-100, 100]`（下轨→+100、上轨→-100），与 R1/R2/R3 同量表，保证等权合成对称、顶部可达 -100。
- **合成与落库**：四个子分仍按等权 1:1:1:1 合成（有效权重归一），`clip(-100,100)` 后 `round` 取整落库到 `StockFactor.reverse`；子分本身不落库。

## 技术栈

- Python 3 + pandas / numpy（项目现有 venv `.env`），数据落库 SQLite 的 `StockFactor.reverse`。
- 复用现有归一化函数 `robust_z_to_score`；`tanh_to_score` 在本函数内弃用但**不删除**（若别处仍使用则保留）。

## 实现方案

### 总体策略

仅改动 `cal_reverse_factor` 内部：R1 不动；R2 变量替换（`macd_bar`→`macd_bar_pct`）；R3 改为线性裁剪映射；R4 改为基于 `pctB` 的接触/刺穿打分并居中。由于 `macd_bar_pct` 及其环比需在指标层（`ind`）计算，必须把 `close` 合并进 `ind`，并相应移除循环内重复的 `wk` close 合并（否则会产生 `close_x/close_y` 导致 `sub["close"]` KeyError）。

### 关键技术决策

1. **R2 变量替换 + 保留混合权重**：用户仅要求用 `macd_bar_pct` 替代 `macd_bar`，未提改权重，故沿用 0.8 水平 / 0.2 收敛金叉结构：`r2 = 0.8*robust_z_to_score(-macd_bar_pct) + 0.2*robust_z_to_score(-macd_bar_pct + 2*(macd_bar_pct - macd_bar_pct_prev))`。
2. **指标层引入 close**：在 3.2 节加载 `wk` 后，将 `close` 以 left join 合并进 `ind`；第 4 节在相邻守卫（adjacent）逻辑内，用 `groupby(ts_code).shift(1)` 计算 `macd_bar_pct_prev`（与 `macd_bar_prev` 并列），非相邻周置 NaN，避免停牌/断周伪信号。
3. **R3 线性映射**：`r3 = -np.clip(cci, -200.0, 200.0) / 2.0`。`clip` 对 NaN 返回 NaN，方向为超卖（低 CCI）→ 正分，与全因子「超卖/偏离→高分」一致。
4. **R4 居中打分（方案 A）**：`r4 = np.clip(100.0*(1.0 - pctB), 0.0, 100.0)*2.0 - 100.0`，其中 `pctB=(close-boll_lower)/(boll_upper-boll_lower)`、`band<=0` 时 `pctB` 置 NaN。覆盖四类描述：贴下轨(pctB=0)→+100；破下轨(pctB<0)→clip100→+100；贴上轨(pctB=1)→-100；破上轨(pctB>1)→clip0→-100。因已居中，合成对称、双向可达 ±100。
5. **合成不变**：等权 1:1:1:1、按有效权重归一、`clip` + `round`，落库逻辑保持原样，向后兼容。

### 性能与可靠性

- `macd_bar_pct` 与 `macd_bar_pct_prev` 在指标层一次性向量化计算（O(行数)），无逐行循环、无重复取数；循环内仅做标量向量运算。
- `np.errstate` 包裹除零/无效值；`band<=0`、`close<=0`、`cci` NaN 均被安全处理为 NaN，下游合成按有效权重跳过。
- 改动局限于单函数，不改 `cal_volatility_factor` 等其它因子，不新增依赖；`tanh_to_score` 不删除。

## 关键改动（src/factor.py）

### 3.2 节：合并 close 进 ind

```python
    # 3.2 周频收盘价（后复权）：合并进 ind，供乖离率/BOLL %B 及 R2 的 macd_bar_pct 使用
    wk = get_weekly_by_trade_date(start_date=q_start, end_date=q_end,
                                  fields=["ts_code", "trade_date", "close"])
    if wk is not None and not wk.empty:
        if "close" not in wk.columns:
            wk["close"] = np.nan
        wk = wk[wk["ts_code"].isin(stock_info)].copy()
    else:
        wk = pd.DataFrame(columns=["ts_code", "trade_date", "close"])
    # 合并 close 进 ind（指标层计算 macd_bar_pct 及其环比需要）
    if not ind.empty and not wk.empty:
        ind = ind.merge(wk[["ts_code", "trade_date", "close"]],
                        on=["ts_code", "trade_date"], how="left")
```

### 第 4 节：新增 macd_bar_pct / macd_bar_pct_prev

```python
    if not ind.empty:
        ind = ind.sort_values(["ts_code", "trade_date"])
        prev_date = ind.groupby("ts_code")["trade_date"].shift(1)
        prev_bar = ind.groupby("ts_code")["macd_bar"].shift(1)
        # R2 新口径：macd_bar_pct = macd_bar / close（按周频标准化）
        with np.errstate(divide="ignore", invalid="ignore"):
            ind["macd_bar_pct"] = ind["macd_bar"] / ind["close"].where(ind["close"] > 0)
        prev_pct = ind.groupby("ts_code")["macd_bar_pct"].shift(1)
        td_index = {d: i for i, d in enumerate(trade_date)}
        cur_idx = ind["trade_date"].map(td_index)
        prev_idx = prev_date.map(td_index)
        adjacent = (cur_idx.notna() & prev_idx.notna() & (cur_idx == prev_idx + 1))
        ind["macd_bar_prev"] = np.where(adjacent, prev_bar, np.nan)
        ind["macd_bar_pct_prev"] = np.where(adjacent, prev_pct, np.nan)
    else:
        ind["macd_bar_prev"] = np.nan
        ind["macd_bar_pct"] = np.nan
        ind["macd_bar_pct_prev"] = np.nan
```

### 循环第 5 节：本地变量 + 移除重复合并

- 删除 `sub = sub.merge(wk[["ts_code","trade_date","close"]], ...)`，改为从 `ind`（已含 close）取数；本地变量补充：

```python
        macd_bar = sub["macd_bar"].astype(float)
        macd_bar_prev = sub["macd_bar_prev"].astype(float)
        macd_bar_pct = sub["macd_bar_pct"].astype(float)
        macd_bar_pct_prev = sub["macd_bar_pct_prev"].astype(float)
```

### R2 / R3 / R4 子分替换

```python
        # R2 MACD（新口径：用 macd_bar_pct = macd_bar/close 替代 macd_bar）
        r2_level = robust_z_to_score(-macd_bar_pct, alpha=0.05)
        r2_conv = robust_z_to_score(
            -macd_bar_pct + 2.0 * (macd_bar_pct - macd_bar_pct_prev), alpha=0.05)
        r2 = 0.8 * r2_level + 0.2 * r2_conv

        # R3 CCI 超卖（新口径：截取 [-200,200] 后 /2 线性映射到 [-100,100]，不再用 tanh）
        r3 = -np.clip(cci, -200.0, 200.0) / 2.0

        # R4 BOLL（新口径：贴/破下轨→+100、贴/破上轨→-100，居中到 [-100,100]）
        with np.errstate(divide="ignore", invalid="ignore"):
            band = boll_upper - boll_lower
            pctB = (close - boll_lower) / band.where(band > 0)
        r4 = np.clip(100.0 * (1.0 - pctB), 0.0, 100.0) * 2.0 - 100.0
```

### docstring 同步

更新 `cal_reverse_factor` 文档（约 677–697 行）中 R2/R3/R4 的描述，注明 R2 用 `macd_bar_pct`、R3 为 CCI 线性裁剪、R4 居中 `[-100,100]` 及合成对称性。

## 目录结构

```
src/factor.py   # [MODIFY]
  - 3.2 节：加载 wk 后将 close 合并进 ind。
  - 第 4 节：新增 macd_bar_pct / macd_bar_pct_prev 计算（含 adjacent 守卫）。
  - 循环第 5 节：本地变量补充 macd_bar_pct(_prev)，移除重复 wk close 合并。
  - R2：基于 macd_bar_pct 的 0.8/0.2 混合。
  - R3：-np.clip(cci,-200,200)/2.0。
  - R4：clip(100*(1-pctB),0,100)*2-100 居中打分。
  - docstring：同步 R2/R3/R4 新口径。
```

## 验证方式

- 编辑后 `read_lints` 检查 `src/factor.py`，确保无语法/类型告警。
- 重算反转因子落库：运行 `cal_reverse_factor()`（或先用日期切片小范围验证），确认每周正常 upsert、无 `KeyError`、无除零异常。
- 重跑 `python src/analyze_factor_ic.py`，确认 `reverse` 全市场 Rank IC 仍显著为正、分位收益 Q5（最超跌）> Q1（最超买）；抽查分布与分行业 IC 合理。
- 重算会覆盖全量 `reverse` 行（逐周频截面 + `robust_z`），耗时较 IC 分析更长，属预期。

## 不改动范围

- 不改 R1、不改合成权重与落库逻辑；不改 `cal_volatility_factor` 等其它因子；不删除 `tanh_to_score`（若别处仍用）；不新增依赖。