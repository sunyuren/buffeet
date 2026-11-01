---
name: cal_reverse_factor 改进计划
overview: 改进 src/factor.py 的 cal_reverse_factor，使反转因子具备稳定的"双向反转性"：底部超跌接近+100（向上反转）、顶部超买接近-100（向下反转）。核心改动：R2 改为"水平为主+金叉为辅"的 0.8/0.2 混合信号；R4 中性点对齐 BOLL 中轨 0.5；合成后 clip(-100,100) 并改用对称 round 取整；同步更新 docstring 与 FACTOR_REGISTRY 注释。符号方向已正确（超跌→正、超买→负），保持不变。
todos:
  - id: modify-r2-mix
    content: 将 R2 改为 0.8 水平项 + 0.2 收敛项的混合信号（约 797–800 行）
    status: completed
  - id: modify-r4-center
    content: 将 R4 的 -pctB 改为 0.5 - pctB，中性点对齐 BOLL 中轨（约 805–809 行）
    status: completed
  - id: modify-composite-clip-round
    content: 合成后增加 clip(-100,100) 并将 floor 改为 round 对称取整（约 822–829 行）
    status: completed
    dependencies:
      - modify-r2-mix
      - modify-r4-center
  - id: sync-doc-and-verify
    content: 更新 docstring 与 FACTOR_REGISTRY 注释，运行测试4 验证极值触达 ±100
    status: in_progress
    dependencies:
      - modify-r2-mix
      - modify-r4-center
      - modify-composite-clip-round
---

## 用户需求

改进 `src/factor.py` 中的 `cal_reverse_factor`，使反转因子具备稳定的「双向反转性」：

- 底部超跌时，因子分数接近 +100，预期向上反转；
- 顶部超买时，因子分数接近 -100，预期向下反转。

## 已确认决策

1. **R2（MACD）口径** = 水平为主 + 金叉为辅：`r2 = 0.8 * 水平项 + 0.2 * 收敛项`（兼顾极值可达与反转确认，极限略低于纯水平但更稳健）。
2. **符号方向保持不变**：当前超跌→正分、超买→负分已符合需求，不翻转。
3. **范围**：仅改进 `cal_reverse_factor`，不动其它因子、不新增依赖。

## 核心特性

- R1/R3/R4 子分维持原有方向（超跌高分、超买低分），仅修正 R2 的混合方式与 R4 中性点。
- 合成后做边界裁剪与对称取整，保证分数严格落在 [-100, 100] 且正负极值对称可达。
- 同步更新文档与因子注册表注释，保持实现与描述一致。

## 技术栈

- Python 3 + pandas / numpy（项目现有 venv `.env`），数据落库 SQLite 的 `StockFactor.reverse` 列。
- 归一化函数 `rank_to_score` / `tanh_to_score` / `robust_z_to_score` 值域本就是 `[-100, 100]`，无需修改。

## 改动文件与位置

- 文件：`src/factor.py`
- 函数：`cal_reverse_factor`（def 在第 674 行），仅修改第 5.1 节子分（约 797–809 行）、第 5.2 节合成与取整（约 822–829 行）、docstring（约 690–691 行）、`FACTOR_REGISTRY`（约 128 行）。

## 实现方案（4 步）

### 步骤 1：R2 改为「水平为主 + 金叉为辅」混合（约 797–800 行）

将原单一收敛项拆分为水平项与收敛项，按 0.8 : 0.2 加权，确保深度水下/水上可达 ±100：

```python
# R2 MACD：深度水下/水上（水平）为主 + 收敛/金叉确认为辅（0.8 : 0.2）
r2_level = robust_z_to_score(-macd_bar, alpha=0.05)            # 纯水平：深度水下→+100、深度水上→-100
r2_conv  = robust_z_to_score(
    -macd_bar + 2.0 * (macd_bar - macd_bar_prev), alpha=0.05)   # 原收敛/金叉项
r2 = 0.8 * r2_level + 0.2 * r2_conv
```

### 步骤 2：R4 中性点对齐 BOLL 中轨 0.5（约 805–809 行）

将 `-pctB` 改为 `0.5 - pctB`，把中性精确钉在中轨（pctB=0.5），使上下轨对称对应 ±100：

```python
# R4 BOLL %B（band<=0 时 pctB 置 NaN）；中性精确钉在中轨 pctB=0.5
with np.errstate(divide="ignore", invalid="ignore"):
    band = boll_upper - boll_lower
    pctB = (close - boll_lower) / band.where(band > 0)
r4 = robust_z_to_score(0.5 - pctB, alpha=0.05)
```

### 步骤 3：合成后 clip + 对称取整（约 822–829 行）

合成均值增加 `clip(-100, 100)` 防御边界；将 `np.floor` 改为 `round`，消除正负极值取整不对称（floor(99.9)=99 而 floor(-99.9)=-100）：

```python
with np.errstate(divide="ignore", invalid="ignore"):
    reverse_raw = np.where(denom > 0, numerator / denom, np.nan)
sub["reverse"] = np.clip(reverse_raw, -100, 100)          # 防御性边界，保证 [-100,100]
# 对称取整为 int（对齐 StockFactor.reverse 的 Integer 类型）
sub["reverse_int"] = sub["reverse"].apply(
    lambda v: int(round(v)) if pd.notna(v) else None
)
```

### 步骤 4：文档同步

- 更新 `cal_reverse_factor` docstring（约 690–691 行）的 R2 描述，改为「水平为主 + 收敛确认为辅（0.8 : 0.2）」。
- 更新 `FACTOR_REGISTRY`（约 128 行）中「MACD水下收敛金叉」为「MACD深度(水下/水上)」。

## 设计理由

- **极值可达性**：真实底部时 R1(bias)、R3(CCI)、R4(pctB) 会同时触达 +100；原 R2 因混入环比动量，在「仍在创新低」的底部掉队，导致等权合成达不到接近 +100。改为以水平项为主（0.8）后，四者齐 +100，合成自然触达 ±100。
- **对称性**：`robust_z_to_score` 以中位数/MAD 做正负双向独立缩放；R4 改用 `0.5 - pctB` 把中性点从「截面中位数」精确钉在「中轨 0.5」。
- **取整对称**：`round` 替代 `floor`，正负极值同权处理，避免负向更易吃满 -100。
- **防御边界**：`clip(-100, 100)` 防止浮点误差导致越界。

## 不改动范围

- 不翻转符号方向（已符合需求）。
- 不动 `cal_size_factor` / `cal_valuation_factor` / `cal_volatility_factor` 及其它函数。
- 不新增第三方依赖。

## 验证方式

- 运行 `python src/factor.py`（venv，UTF-8）触发测试4（`cal_reverse_factor()`）重新落库反转因子。
- 抽查 `StockFactor.reverse` 极值：真实底部截面最超跌个股应接近 +100、顶部最超买接近 -100。
- （可选）复用 `analyze_factor_ic` 思路对 `reverse` 列做前向 12 周 Rank IC，确认高分组未来收益为正、低分组为负（双向反转成立）。