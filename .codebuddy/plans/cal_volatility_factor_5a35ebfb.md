---
name: cal_volatility_factor
overview: 实现 src/factor.py 中预留的 cal_volatility_factor：以周频截面遍历，用窗口汇总的周换手率、板块内周涨跌幅绝对值、对数化周成交额三项等权合成波动率因子，统一反向后落库到 StockFactor.volility 列。
todos:
  - id: add-import-and-board-helper
    content: 在 factor.py 导入 get_weekly_by_trade_date，新增 _get_board 板块分类函数并同步注册表换手率字段名
    status: completed
  - id: build-flow-skeleton
    content: 重写 cal_volatility_factor 主流程前半：日期序列、股票清单、日频与周频区间取数
    status: completed
    dependencies:
      - add-import-and-board-helper
  - id: vectorize-window-turnover
    content: 用 searchsorted 预计算 (上一截面, 本截面] 窗口的周换手率求和，首个截面跳过
    status: completed
    dependencies:
      - build-flow-skeleton
  - id: implement-subfactors-and-synthesis
    content: 实现三子因子归一化（板块分组/全市场/log10）、NaN 还原、×(-1) 反向与等权加权合成
    status: completed
    dependencies:
      - vectorize-window-turnover
  - id: implement-upsert-and-verify
    content: 实现 volility 取整落库与日志，运行 lint 检查并小批量冒烟验证
    status: completed
    dependencies:
      - implement-subfactors-and-synthesis
---

## 产品概述

在因子计算模块中补齐「波动率因子」的计算与落库逻辑。该因子不做单日截面比较，而是以**周频窗口**为单位：将日频换手率按周汇总、结合周频涨跌幅与成交额，在每个截面把全部股票横向比较后归一化、加权合成一个波动率分数。

## 核心功能

1. **日期与标的**：按输入的起止日期确定计算区间，取全市场交易日序列（已周频对齐）作为截面；取全部股票的代码、名称、行业。
2. **底数取数**：批量取区间内的日频换手率，以及周频的涨跌幅、成交额。
3. **周换手率**：把日频换手率按窗口汇总为周换手率（相邻两个截面之间的交易日求和），首个截面因缺少前序数据不计算。
4. **周涨跌幅**：取涨跌幅绝对值，按板块（上证主板、深证主板、科创板、创业板、北交所）分组后组内比较。
5. **周成交额**：全市场比较（先做对数变换缓解右偏）。
6. **合成与落库**：三项等权合成，方向统一为「低波动得分更高」，结果取整后按交易日写入因子库；缺项按有效权重归一，缺失值不写入。

## 技术栈

- 语言：Python 3（与现有项目一致）
- 数据处理：pandas + numpy
- 持久化：SQLAlchemy ORM + 现有 `upsert_stock_factor` 批量写入
- 改动范围：**仅 `src/factor.py`**（用户明确选择不改 `database.py`、不动表结构）

## 实现方案

### 总体策略

把行 464-472 的占位函数（`def cal_volatility_factor(df) -> pd.Series`，函数体为 `...`）整体替换为**自包含流程函数**，签名与编码风格完全对齐同文件已有的 `cal_size_factor` / `cal_valuation_factor`（入参 `start_date`/`end_date`，无返回值，循环内自行落库）。底数在循环外一次性区间查询，循环内只做切片与向量化计算，避免逐日重复查库。

### 关键技术决策

1. **签名与定位**：改为 `def cal_volatility_factor(start_date: str | None = None, end_date: str | None = None) -> None`。
全仓搜索确认无任何外部调用点（`cal_all_factors` 仅是骨架、未调用它），改签名零影响。落库列名必须用 **`volility`**（`StockFactor` / `upsert_stock_factor` 字段映射中的既有拼写，非 `volatility`）。

2. **取数范围收敛（避免全表加载）**：

- 日频换手率：`get_daily_basic_by_trade_date(start_date=..., end_date=..., fields=["ts_code","trade_date","turnover_rate_f"])`。
- 周频：`get_weekly_by_trade_date(start_date=..., end_date=..., fields=["ts_code","trade_date","pct_chg","amount"])`。
- 当 `start_date`/`end_date` 为 None 时，用 `trade_date[0]` / `trade_date[-1]` 作为有效边界，避免一次性拉全表。
- 字段来源按已确认口径：**`turnover_rate_f`**（库中无 `turnover_rate` 列）。沿用 `cal_size_factor` 的「兜底列存在性」写法，缺列则补 NaN 列。

3. **窗口聚合向量化（性能核心）**：
朴素做法（每次循环对全量日频表做布尔过滤）复杂度为 O(截面数 × 日频行数)，全历史约数十亿次扫描，不可接受。改用 `np.searchsorted(td_arr, daily_dates, side="left")` 一次性把每个日频日期映射到其所属窗口序号 `i`（满足 `td_{i-1} < d <= td_i`），丢弃 `i==0`（早于首个截面），再 `groupby(["_wk","ts_code"]).sum(min_count=1)` 一次算出全部窗口的周换手率，循环内按 `i` 直接取用。总复杂度降为 O(n log n)。`min_count=1` 保证全 NaN 组仍为 NaN 而非 0。

4. **板块分类辅助函数**：新增模块内私有函数 `_get_board(ts_code)`，按代码前缀返回 5 组之一：

| 板块 | 判定规则（ts_code） |
| --- | --- |
| 科创板 | `.SH` 且以 `688` 开头 |
| 上证主板 | `.SH` 且非 `688`（`600/601/603/605` 等） |
| 创业板 | `.SZ` 且以 `300`/`301` 开头 |
| 深证主板 | `.SZ` 且以 `000/001/002/003` 开头 |
| 北交所 | `.BJ`（`43/83/87/88/920` 等） |
| 其他 | 兜底分组，保证不丢样本 |


5. **三子因子归一化（含 NaN 还原）**：

- 周涨跌幅：`pct_chg.abs()` → `groupby("board").transform(lambda s: robust_z_to_score(s))`。
- 周成交额：`amount` 先 `log10`（`<=0` 与 NaN 转 NaN）→ 全市场 `robust_z_to_score`。
- 周换手率：周汇总值 → 全市场 `robust_z_to_score`。
- **必须做 NaN 还原**：`robust_z_to_score` 在 MAD 为 0/NaN 时返回**全 0 序列**而非 NaN，因此须用原始值的 `notna()` 掩码把缺失样本分数重置为 NaN，否则缺失会被误判为「中性 0 分」并混入加权。

6. **反向与等权合成**：三项均 `×(-1)`（低波动高分），权重 1:1:1。沿用 `cal_size_factor` 的加权范式：`numerator/denominator` 累加，缺失项不计入分母（按有效权重归一），`den>0` 才计算结果否则 NaN。`upsert_stock_factor` 前用 `int(np.floor(v))` 取整、`astype(int)`、剔除 NaN、空则 `continue`。

### 关键代码结构

```python
# 板块划分（私有辅助，供按板块分组比较使用）
def _get_board(ts_code: str) -> str: ...   # -> 上证主板 / 深证主板 / 科创板 / 创业板 / 北交所 / 其他

# 合成配置（等权、统一反向）
weights = {"turnover_week": 1, "pct_chg": 1, "amount": 1}
score_cols = {
    "turnover_score": "turnover_week",  # 全市场 robust_z
    "pct_chg_score":  "pct_chg",        # 取绝对值 + 按 board 组内 robust_z
    "amount_score":   "amount",         # log10 + 全市场 robust_z
}
# 落库列名：volility（StockFactor 既有拼写）
```

### 性能与可靠性

- 取数：每类底数各 1 次区间查询（原范式为每截面 1 次，改为 1 次，I/O 从 O(m) 降为 O(1)）。
- 窗口聚合：O(n log n) 一次性完成，循环内仅为 O(当周股票数) 的字典取值。
- 分组标准化：`groupby.transform` 单次遍历，与规模因子的行业内比较写法一致。
- 可靠性：区间为空 / 底数为空 / 单截面无数据 / 板块组样本过少（MAD=0 → 组内中性 0 分再被掩码还原）均有兜底，不抛异常。

### 实现注意事项

- 循环用 `enumerate`，`i == 0` 直接 `continue`（首个截面左开区间无前序数据，按确认口径不落库）。
- `trade_date` 为 `YYYYMMDD` 字符串，可直接使用字典序比较（与 `cal_size_factor` 一致）。
- 截面样本基准取「该周有周频记录的股票」，再左连接周换手率；无周频记录的截面 `continue`。
- 同步把 `FACTOR_REGISTRY` 中「周换手率因子」的 `factor_field` 由 `turnover_rate` 改为 `turnover_rate_f`，避免与实际取数列名不一致（1 行，可按需否决）。
- 不改 `database.py`、不改表结构、不动其余 `cal_*_factor` 与 `cal_all_factors`。
- 完成后运行 lint 检查；用小范围 `start_date/end_date` 冒烟验证落库行数与分数区间。

## 目录结构

```
src/
└── factor.py   # [MODIFY] 唯一改动文件
    - 行 14-21 导入块：新增 get_weekly_by_trade_date
    - 行 119-122 FACTOR_REGISTRY：周换手率因子 factor_field 改为 turnover_rate_f
    - 行 464-472（原占位）：整体替换为完整的 cal_volatility_factor 流程函数
        · _get_board：板块分类私有辅助函数（5 组 + 其他兜底）
        · cal_volatility_factor：
            1) get_all_date() 升序 + 按 start_date/end_date 过滤
            2) get_all_stocks() -> stock_info{ts_code: (name, industry)}
            3) 循环外一次性区间取数（日频换手率 / 周频 pct_chg、amount）
            4) searchsorted 预计算各窗口周换手率
            5) 逐截面：取数合并 -> 三子因子归一化（NaN 掩码还原）
                      -> ×(-1) 反向 -> 等权加权（缺项按有效权重归一）
            6) 取整 -> 组装 out_df(ts_code/name/industry/trade_date/volility)
                      -> upsert_stock_factor -> print 日志
```