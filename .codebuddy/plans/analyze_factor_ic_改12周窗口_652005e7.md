---
name: analyze_factor_ic_改12周窗口
overview: 将 analyze_factor_ic.py 中 size/valuation/volility 三个因子的 IC 计算统一改为基于 stock_weekly 的前向 12 周收益(H_WEEKLY=12),移除原有日频 20 交易日收益路径,更新因子标签与 docstring;本次不新增回测逻辑,仅调整 IC 窗口口径。
todos:
  - id: adjust-config-and-returns
    content: 配置改为 H_WEEKLY=12,删除 H_DAILY 与日频 fwd_ret_d 计算/合并
    status: completed
  - id: unify-ic-12w
    content: 三因子 IC 统一改用 fwd_ret_w 并更新标签为 *_12w(全市场+分行业)
    status: completed
    dependencies:
      - adjust-config-and-returns
  - id: doc-and-verify
    content: 更新 docstring 并重跑脚本验证无中文乱码、输出 *_12w 图与 CSV
    status: completed
    dependencies:
      - unify-ic-12w
---

## 用户需求

将 `analyze_factor_ic.py` 的 IC 计算口径统一调整为 **3 个月（12 周）** 前向收益,并重新输出有效性指标。

## 产品概述

调整因子有效性分析脚本的时间窗口:规模(size)、估值(valuation)、波动(volility) 三个因子统一基于 `stock_weekly` 的**前向 12 周收益**计算 Rank IC / ICIR / 正率及分行业 IC;不再使用日频收益。不新增分组多空回测逻辑,仅调整 IC 计算窗口。

## 核心特性

- 三因子 IC 统一使用周频前向 12 周收益(`fwd_ret_w`,`H_WEEKLY=12`),替代原先 size/valuation 的日频 20 交易日收益。
- 输出标签由 `*_20d` / `volility_4w` 改为 `*_12w`(size_12w、valuation_12w、volility_12w),图片与 CSV 文件名同步反映新窗口。
- 全市场 IC 指标(均值 IC / ICIR / 正率 / t 值)与分行业 IC(行业均值 IC / ICIR / 正率)按 12 周窗口重算。
- 保留已修复的中文字体渲染与分行业 CSV 导出(`ic_industry_*.csv`、`ic_industry_all.csv`)能力不变。

## 技术栈

- 语言:Python 3(项目 venv `\.env`)
- 依赖:pandas、numpy、matplotlib(与现有脚本一致,无新增依赖)
- 数据源:SQLite `data/raw/stock.db` 中的 `stock_factor`、`stock_weekly` 表

## 实现方案

### 总体策略

仅修改 `analyze_factor_ic.py` 的 CONFIG 与 `main()` 中收益计算和 IC 输出部分,使三因子统一采用周频前向 12 周收益。IC 核心函数(`_rank_ic`、`ic_series`、`report_ic`、`ic_by_industry`)与窗口无关,保持不变;中文字体修复 `_setup_cjk_font` 与分行业 CSV 导出保持不变。

### 关键技术决策

1. **移除日频收益链路**:删除 `H_DAILY=20` 配置项与 `main` 第 2 节(stock_daily_basic 计算 `fwd_ret_d`、shift(-20)),以及第 4 节中对 `fwd_ret_d` 的 merge。原因:用户明确"全部统一 12 周",size/valuation 改为周频 12 周,日频收益不再被引用,保留会造成死代码与混淆。
2. **统一为周频 12 周**:`H_WEEKLY` 由 `4` 改为 `12`;三个因子 IC 均使用 `fwd_ret_w`(由 stock_weekly close 的 `shift(-12)/close-1` 得到)。volility 原为周频 4w,现直接改为 12w,逻辑一致。
3. **标签与产物命名**:全市场与分行业输出的 `name` 参数改为 `size_12w` / `valuation_12w` / `volility_12w`,使 PNG(`ic_{label}.png`、`ic_industry_{label}.png`)与 CSV(`ic_industry_{label}.csv`)文件名正确反映新窗口,避免与历史产物混淆。

### 性能与可靠性

- 仅改变 `shift` 的偏移量(4→12)与合并字段,数据读取行数与截面数不变,运行开销持平。
- 删除日频收益计算与一次 merge,反而减少一次内存 join,略有收益。
- `MIN_CS`(全市场截面最小股票数)与 `MIN_CS_I`(行业内最小股票数)阈值沿用,无需调整;12 周窗口下有效截面数会减少(因 shift 需未来 12 周数据),属预期行为。

## 实现注意

- 删除日频相关代码后,需同步清理对 `fwd_ret_d` 列的所有引用(`dropna(subset=[col, "fwd_ret_d"])` 改为 `fwd_ret_w`),避免 KeyError。
- 顶部 docstring 需更新为"三因子均基于 stock_weekly 前向 12 周收益计算 Rank IC",保持文档与实现一致。
- 重跑验证:日志应无 `Glyph ... missing` 中文乱码警告;产物文件名含 `12w`;分行业 CSV 正常生成。

## 架构设计

本任务为单文件局部修改,不涉及架构调整。数据流保持:stock_factor + stock_weekly → 计算前向 12 周收益 → merge → 全市场截面 IC → 分行业截面 IC → 指标输出 + 图表 + CSV。

## 目录结构

```
src/
└── analyze_factor_ic.py   # [MODIFY] 因子有效性分析脚本。
                            #  - CONFIG: 删除 H_DAILY=20;H_WEEKLY 由 4 改为 12。
                            #  - main 第2节: 删除 stock_daily_basic 的 fwd_ret_d 计算。
                            #  - main 第4节: 删除 fwd_ret_d 的 merge,仅保留 fwd_ret_w。
                            #  - 全市场 IC / 分行业 IC: size/valuation/volility 统一用
                            #    fwd_ret_w,标签改为 *_12w。
                            #  - 顶部 docstring: 更新为周频 12 周口径。
                            #  - _setup_cjk_font、ic_by_industry 的 CSV 导出保持不变。
```

## 关键代码结构(改动示意)

- CONFIG 变更:
- 删除 `H_DAILY = 20`
- `H_WEEKLY = 12`
- 收益计算(原第3节改为唯一收益来源):

```python
weekly["fwd_ret"] = weekly.groupby("ts_code")["close"].transform(
lambda s: s.shift(-H_WEEKLY) / s - 1.0)
```

- 三因子 IC 调用统一:

```python
report_ic(ic_series(f.dropna(subset=[col, "fwd_ret_w"]), col, "fwd_ret_w", MIN_CS), "size_12w")
ic_by_industry(f.dropna(subset=[col, "fwd_ret_w"]), col, "fwd_ret_w", MIN_CS_I, "size_12w")
```