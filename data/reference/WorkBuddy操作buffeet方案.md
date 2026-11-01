# WorkBuddy × buffeet 操作方案

> 生成时间：2026-10-13 ｜ 目标：让 WorkBuddy 直接读写 buffeet 的 SQLite 库、产出结果，并补齐 supply / moat 两个因子

---

## 一、现状盘点（实测数据）

### 1.1 数据库

| 项目 | 值 |
|---|---|
| 路径 | `C:\Users\yuri_sun\CodeBuddy\buffeet\data\raw\stock.db` |
| 体积 | **7.25 GB** |
| 表数 | 12 |
| 最大表 | `stock_daily_basic` 12,826,541 行 |

| 表 | 行数 | 用途 |
|---|---|---|
| stock_daily_basic | 12,826,541 | 日频市值/估值/换手（**性能瓶颈**） |
| stock_weekly | 2,713,470 | 周K行情 |
| stock_weekly_indicator | 2,713,470 | 周K技术指标（MA/MACD/CCI/BOLL） |
| **stock_factor** | **2,792,791** | **因子表（核心）** |
| stock_fina_indicator | 249,793 | 财务指标（因子主数据源） |
| stock_managers | 396,740 | 高管履历（**无持股数，不可用于 supply**） |
| stock_cashflow / income / balancesheet | 29~32万 | 三大报表 |
| stock_list / company / trade_cal | 5千~1.3万 | 基础信息 |

### 1.2 stock_factor

- 755 个周截面（20120106 ~ 20260930），5573 只股票
- **7 个因子已落地，supply / moat 全空**

| 因子列 | 非空行 | 覆盖率 |
|---|---|---|
| size | 2,705,358 | 96.87% |
| valuation | 2,698,632 | 96.63% |
| volility | 2,698,702 | 96.63% |
| reverse | 2,698,657 | 96.63% |
| profit | 2,749,499 | 98.45% |
| growth | 2,727,137 | 97.65% |
| cash | 2,727,391 | 97.66% |
| **supply** | **0** | **0%** |
| **moat** | **0** | **0%** |

### 1.3 数据新鲜度（实测）

| 表 | 最新日期 | 状态 |
|---|---|---|
| stock_daily_basic | 20260930 | 追平 |
| stock_weekly / weekly_indicator | 20260930 | 追平 |
| stock_fina_indicator | 20260630 | 中报，正常（三季报 10 月底才披露） |
| trade_cal | 20261231 | 日历已铺到年底 |

---

## 二、WorkBuddy 操作项目的运行契约（关键）

buffeet 在 CodeBuddy 下开发，有三个隐式约束，**不满足就报错**：

| 约束 | 原因 | 值 |
|---|---|---|
| 解释器 | 依赖 pandas 3.0.3 / sqlalchemy 2.0.50 | `buffeet\.env\Scripts\python.exe`（Python 3.11.9） |
| cwd | `config.py` 的 `DATABASE_URL = "sqlite:///data/raw/stock.db"` 是**相对路径** | 必须是 `buffeet\` 根目录 |
| PYTHONPATH | `factor.py` 用 flat import `from database import ...` | 必须含 `buffeet\src` |

> ⚠️ WorkBuddy 自带的 managed Python（3.11.9/3.13.12/3.14.3）**没有** pandas/sqlalchemy，不能直接跑项目代码。anaconda3 虽有 pandas 2.2.2，但版本与项目不符（项目 venv 是 pandas 3.0.3），**不要混用**。

已封装成 `buffeet_bridge.py`（本目录），自动完成自举：

```bash
cd C:\Users\yuri_sun\WorkBuddy\2026-10-13-20-04-20
python buffeet_bridge.py info          # 库概览 + 因子覆盖
python buffeet_bridge.py latest 20     # 最新截面综合分 Top N
python buffeet_bridge.py query "SELECT ..." --csv x.csv
python buffeet_bridge.py export 20260930
python buffeet_bridge.py freshness     # 数据新鲜度体检
python buffeet_bridge.py screen        # 调项目 screen_stocks.py
```

**只读连接**（`mode=ro`），不会误写项目库。

---

## 三、三层操作能力

### L1 · 只读查询（已可用）
桥接脚本直接 SQL。适合：查截面、行业画像、个股因子轨迹、缺失诊断。

### L2 · 复用项目模块（已可用）
```bash
cd C:\Users\yuri_sun\CodeBuddy\buffeet
set PYTHONPATH=src
.\.env\Scripts\python.exe -c "import factor; factor.cal_factors_weekly()"
```
可直接调用：`cal_factors_weekly()`（周频增量重算 7 因子）、`data_fetch.update_weekly()`（拉原始数据）、`screen_stocks.py`、`analyze_factor_ic.py`。

### L3 · 自动化任务（待建）
定时跑「拉数据 → 算因子 → 选股 → 出报告」。见第六节。

### 输出结果的链路

| 形态 | 方式 | WorkBuddy 加成 |
|---|---|---|
| CSV / Excel | pandas → `output/` | 直接下载 |
| 图表 PNG | matplotlib | 卡片预览 |
| **HTML 报告** | 自写模板 | **实时预览面板，可交互排序** |
| 对话结论 | 直接给结论 + 关键表 | — |

---

## 四、⚠️ 性能瓶颈（本次最重要的发现）

**所有表主键都是 `(ts_code, trade_date)`，没有任何 `trade_date` 单列索引。**
后果：任何「按日期取横截面」的查询都是**全表扫描**。

| 查询 | 耗时 |
|---|---|
| `stock_factor WHERE trade_date=?` | 0.36 s |
| **`stock_daily_basic WHERE trade_date=?`** | **21.43 s** |

**对 supply/moat 的直接影响**：
supply 若用 `stock_daily_basic`（日频）逐周重算全历史 → 755 周 × 21 s ≈ **4.4 小时仅取数**，加上计算必然超时。

### 三个解法（trade-off）

| 方案 | 做法 | 优点 | 代价 |
|---|---|---|---|
| A. 建索引 | `CREATE INDEX idx_db_td ON stock_daily_basic(trade_date)` | 一行搞定，全项目受益 | 库再涨 300~500MB；写入变慢；7.25GB 库建索引耗时长 |
| **B. 日转周中间表（推荐）** | 一次性把 daily_basic 聚合成周频存 `stock_weekly_basic` | 与项目周频架构对齐；415 万行小表，秒级；supply/moat 都可复用 | 需一次性 ETL（约 30~60 分钟） |
| C. Parquet 快照 | daily_basic 抽成 parquet | 读取最快 | 脱离 SQL 生态，需改代码 |

**推荐 B**：新建 `stock_weekly_basic(ts_code, trade_date, turnover_wk, vol_ratio_wk, free_ratio, float_ratio, share_yoy)`，与现有 `stock_weekly` 同主键同截面，之后 supply 计算走它，秒级。A 可作为辅助（对 `stock_factor` 建 trade_date 索引几乎零成本）。

---

## 五、supply / moat 因子规格

### 5.1 先解决一个设计冲突

`FACTOR_REGISTRY` 中 **volility 已包含「周换手率因子 turnover_rate_f」**，
而 `cal_supply_factor` 的 docstring 写的是「turnover_rate_f / volume_ratio」——**两者会高度共线**，等于把同一个信号算两遍加权两次。

**结论：supply 必须换口径**，否则第 8 个因子是第 3 个因子的复制品。

### 5.2 supply · 推荐口径「筹码供给结构」

衡量**潜在抛压 / 股本稀释**，与现有 7 因子正交。

| 子项 | 计算 | 来源 | 方向 | 归一化 | 权重 |
|---|---|---|---|---|---|
| S1 自由流通占比 | `free_share / total_share` | daily_basic | 正向（供给已释放，解禁压力小） | 全市场 rank | 1 |
| S2 流通占比 | `float_share / total_share` | daily_basic | 正向 | 全市场 rank | 1 |
| S3 股本扩张速度 | `total_share` 同比 52 周 | daily_basic（周聚合） | **负向**（增发/转增 = 稀释抛压） | 全市场 rank 后 ×-1 | 1 |
| S4 资金关注度 | `volume_ratio` 近 12 周均值 | daily_basic（周聚合） | 正向（放量=承接强） | 行业内 rank | 1 |

- `free_share/float_share/total_share` 实测覆盖率 **100%**，`volume_ratio` **99.9%**，数据无缺口。
- S4 与 volility 的区别：volility 是**换手率绝对水平**，S4 是**量比相对放大倍数**，相关性中等，可接受。若不放心，可弃用 S4，退化为 3 子项。

<details>
<summary>备选口径（不推荐）：交易活跃度</summary>

直接用 `turnover_rate_f` / `volume_ratio` 当活跃度。实现最省事，但与 volility 因子相关系数预计 >0.7，会稀释组合有效性。**不建议。**
</details>

### 5.3 moat · 推荐口径「护城河五维」

`cal_moat_factor` docstring 建议 `grossprofit_margin / debt_to_assets`——只有 2 项，太薄，且与 profit 因子重叠（profit 已用 `q_gsprofit_margin`、`netprofit_margin`、`ap_to_ar`）。

| 子项 | 字段 | 来源 | 方向 | 归一化 | 覆盖率 |
|---|---|---|---|---|---|
| M1 投入资本回报率 | `roic` | fina_indicator | 正向 | 全市场 robust_z | 97.2% |
| M2 毛利率 | `grossprofit_margin` | fina_indicator | 正向 | **行业内** rank | 97.1% |
| M3 资产负债率 | `debt_to_assets` | fina_indicator | **负向** | **行业内** rank ×-1 | 96.8% |
| M4 销售费用率 | `saleexp_ratio` | fina_indicator | **负向**（低销售费用=品牌拉力） | **行业内** rank ×-1 | 95.5% |
| M5 研发强度 | `rd_exp / total_revenue` | fina_indicator + income | 正向（技术护城河） | **行业内** rank | **65.5%** |

**trade-off 说明**：
- M2/M3/M4 强制**行业中性化**——毛利率和负债率是强行业属性（银行 vs 白酒不可比），全市场排名会让因子变成「行业选择器」。项目 `cal_cash_factor` 的 R3/R4 已用行业内 rank，照抄即可。
- M5 研发覆盖率仅 65.5%，**按有效权重归一**（缺项不计入分母，与 cash 因子一致），不要填 0（会把非研发型企业错误打入冷宫）。
- 避开 `roe_yearly`/`netprofit_margin`/`ap_to_ar`——profit 因子已用，防止重复。

### 5.4 实现骨架（对齐现有因子函数）

```python
def cal_moat_factor(start_date=None, end_date=None) -> None:
    """护城河因子：与 cal_cash_factor 同构——逐周截面 + upsert_stock_factor 落库。"""
    for td in trade_date:
        fina_df = get_fina_indicator_by_ann_date(   # 复用现成取数，含上市日过滤
            start_ann_date=start_ann, end_ann_date=td,
            fields=["ts_code","end_date","roic","grossprofit_margin",
                    "debt_to_assets","saleexp_ratio","rd_exp"])
        # 子项打分：全市场 / 行业内 分别归一化，缺项按有效权重归一
        ...
        out_df = pd.DataFrame({"ts_code":..., "name":..., "industry":...,
                               "trade_date": td, "moat": moat_int})
        upsert_stock_factor(out_df)   # 幂等，可重复跑
```

落库后注册到 `WEEKLY_FACTORS` 与 `WEEKLY_FACTOR_COLS`，即可被 `cal_factors_weekly()` 自动带走。

> 注意：`cal_all_factors()` 目前是**骨架模式**（返回全空 13 列），`cal_supply_factor` / `cal_moat_factor` 现在还是 `->pd.Series` 的桩签名。真正实现要改成和 `cal_cash_factor` 一样的**自包含流程函数**（自带取数 + 落库），签名 `(start_date, end_date) -> None`。

---

## 六、自动化任务设计

建议一条龙周更（含 supply/moat）：

```
每周六 09:00 触发
  1. data_fetch.update_weekly()      # 增量拉原始数（trade_cal/daily/weekly/财报）
  2. factor.cal_factors_weekly()     # 重算 7 因子（+ 补齐后变 9 因子）
  3. screen_stocks.py                # 出价值型 / 成长型名单 CSV
  4. WorkBuddy 汇总 → HTML 报告       # 因子分布、Top20、行业画像、新鲜度
  5. present_files 推送预览
```

**风险提示**：项目文档记录周更原始数据「总耗时约 5h」。自动化任务必须后台跑，且要有失败断点续跑（`upsert_*` 已幂等，可安全重试）。

---

## 七、其他发现

- **`config.py` 里 Tushare Token 明文硬编码**。若项目要进 git 或外发，建议移到环境变量。
- `stock_managers` 是高管**履历**表（姓名/职务/学历/简历），**没有持股数量**，做不了「内部人增减持」信号。若想要该维度，需新增数据源。
- `main.py` 仍是空壳（全是 TODO），目前实际入口是各脚本独立运行。
- 因子命名 `volility` 是拼写错误（应为 volatility），已落库到列名，改名要动表结构，建议维持现状。

---

## 八、建议的下一步

1. **先做 B（日转周中间表）**——这是 supply/moat 能算得动的前提
2. 拍板 supply 口径（推荐「筹码供给结构」）与 moat 子项清单
3. 实现两个因子函数，小窗口（近 8 周）试跑，核对分值分布
4. 跑 IC 分析验证有效性（`analyze_factor_ic.py`），确认不与其他因子高度相关
5. 通过后全量回算 755 周，建自动化周更任务
