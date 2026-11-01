---
name: cash_factor_ab_improve
overview: 改进 cal_cash_factor（A+B 方案）：R1/R2/R3 由行业内 rank_to_score 改为行业内 robust_z_to_score 以突出龙头相对领先，新增 R4 现金规模子项（StockCashflow.n_cashflow_act，行业内 robust_z_to_score）捕捉龙头绝对体量；四子项等权 1:1:1:1 合成。需在 database.py 新增 get_cashflow_by_ann_date 取数函数。金融降级留作后续可选项（本次不实现）。
todos:
  - id: add-cashflow-getter
    content: 在 database.py 新增 get_cashflow_by_ann_date 取数函数
    status: completed
  - id: wire-cf-data
    content: cal_cash_factor 接入 cf_df 取数并合并 n_cashflow_act
    status: completed
    dependencies:
      - add-cashflow-getter
  - id: revise-normalization
    content: R1~R3 改 robust_z、新增 R4、权重与 score_cols 改 1:1:1:1
    status: completed
    dependencies:
      - wire-cf-data
  - id: verify-ic
    content: 运行 analyze_factor_ic 对比 R1~R4 各自 Rank IC 验证
    status: completed
    dependencies:
      - revise-normalization
---

## 用户需求

改进现有现金因子（cal_cash_factor），解决"比率法体现不出龙头公司优秀现金质量"的痛点。

## 产品概述

在保持逐交易日截面计算与 StockFactor.cash 落库流程不变的前提下，优化现金因子的子项构成与归一化方法，使龙头公司的现金质量与绝对体量能够被有效捕捉。

## 核心特性

- 质量比率子项（R1 现金收入比、R2 净现金利润比、R3 带息债务占比）归一化由行业内 rank_to_score 改为行业内 robust_z_to_score，突出龙头在行业内的相对领先度。
- 新增 R4 现金规模绝对量子项（经营现金流净额 n_cashflow_act，取自 StockCashflow 表），行业内 robust_z_to_score 归一化，捕捉龙头绝对体量壁垒。
- R1 至 R4 四子项权重统一为 1:1:1:1。
- 新增 StockCashflow 按公告日期（ann_date）取数函数，支撑 R4 计算。
- 缺项自动容错：R4 缺失时退化为三质量子项等权，不引入失真。
- 痛点2（因子时序跳跃/稳定性）本次不处理；金融行业口径降级逻辑本次不实现，留作后续。

## Tech Stack Selection

- 语言：Python 3
- 数据访问：SQLAlchemy ORM（现有 StockCashflow / StockFinaIndicator 模型）
- 计算：pandas（groupby.transform 行业内归一化、加权合成）
- 因子框架：沿用现有自包含因子函数（cal_cash_factor）+ 取数层（database.py 函数）+ 落库（upsert_stock_factor）

## Implementation Approach

策略：在现有 cal_cash_factor 自包含流程上做增量修改，新增一张现金流量表取数，将归一化从离散排名升级为行业内稳健 z，并引入绝对量子项。

- 在 database.py 新增 get_cashflow_by_ann_date，仿 get_fina_indicator_by_ann_date 模板，按 ann_date 窗口与 fields 查询 StockCashflow。
- 主循环内仿 fina_df 逻辑取 cf_df（仅年报 1231/中报 0630、每股票最新一期、剔除上市前财报），merge 进 section 的 n_cashflow_act。
- R1/R2/R3 由 rank_to_score(alpha=0.05) 改为 robust_z_to_score(alpha=0.05)，R3 仍翻转；新增 R4 = 行业内 robust_z_to_score(n_cashflow_act)，方向为正。
- weights 改为 {r1_score:1, r2_score:1, r3_score:1, r4_score:1}，score_cols 增加 r4_score。下方 numerator/denom 通用循环自动按 4 项有效权重归一，无需改循环体。
- 落库（floor→int）逻辑不变。

关键技术决策：

- 选用 robust_z_to_score 而非 rank_to_score：连续标准化对行业内排序微小变动不敏感，分数平滑且能表达"相对行业中枢的偏离度"，天然突出龙头持续领先。
- 绝对量子项 n_cashflow_act 行业内比较：跨行业量纲不可比，必须行业内标准化；robust_z 中位数/MAD 对右偏的经营现金流净额稳健。
- 权重 1:1:1:1（用户指定）：四子项等权，避免主观偏好；后续可由 Rank IC 回测再微调。

## Implementation Notes

- cf_df 取数逻辑必须与 fina_df 完全同构（ann_date 窗口 = [td 前一年, td]；仅保留 end_date 末尾为 1231/0630；groupby ts_code tail(1) 取最新一期；用 list_date 剔除报告期早于上市日的行）。
- merge 时仅对 ts_code 合并 n_cashflow_act 单列，避免覆盖 fina_df 字段。
- 缺项容错由现有 numerator/denom 循环保证：R4 为 NaN 时该股票该项权重不计入 denom，合成退化为三质量子项等权（仍 1:1:1），不引入 NaN。
- robust_z_to_score 默认 alpha=0.01，本处显式传 alpha=0.05，与排名法尾部截断比例一致。
- 金融降级本次不做：n_cashflow_act 对银行含客户存款增减，口径异于实体；行业内比较可缓解，若回测异常后续复用 cal_profit_factor 的 PROFIT_FINANCE_KEYWORDS 降级逻辑将 R4 置 0。
- 性能：StockCashflow 全市场按 ann_date 取数，数据量与 fina 同量级，可接受；主循环逐交易日调用，保持与现有一致。
- 日志：沿用现有 print 写入条数即可，无需新增。

## Architecture Design

沿用现有分层：因子计算层（factor.py 自包含函数）→ 取数层（database.py 按 ann_date 查询）→ ORM 模型层（StockCashflow/StockFinaIndicator）→ 落库层（upsert_stock_factor）。本次不引入新架构、新模块，仅扩展取数函数与修改单因子内部计算。数据流：交易日序 → 逐日取两表财务 → 行业内稳健 z 归一化 → 等权合成 → floor 落库。

## Directory Structure

本次仅修改两个既有文件：

- src/database.py  # [MODIFY] 在 get_fina_indicator_by_ann_date 旁新增 get_cashflow_by_ann_date(ts_code, ann_date, start_ann_date, end_ann_date, fields)，照搬模板、数据源换 StockCashflow，支持按 ann_date 窗口与 fields 查询，_empty_df 兜底。
- src/factor.py  # [MODIFY] cal_cash_factor（1368-1530）：①新增 cashflow_fields 常量；②主循环新增 cf_df 取数块（同构 fina_df）；③section 合并 n_cashflow_act；④weights 改 {r1:1,r2:1,r3:1,r4:1}；⑤R1/R2/R3 改 robust_z_to_score、新增 R4；⑥score_cols 扩展 r4_score；⑦落库 floor→int 不变。

## Key Code Structures

关键新增取数函数签名（仿现有模板）：
def get_cashflow_by_ann_date(ts_code=None, ann_date=None, start_ann_date=None, end_ann_date=None, fields=None) -> pd.DataFrame

cal_cash_factor 内部关键常量变更：
weights = {"r1_score":1, "r2_score":1, "r3_score":1, "r4_score":1}
cashflow_fields = ["ts_code", "end_date", "n_cashflow_act"]
score_cols = {"r1_score":"salescash_to_or", "r2_score":"opincome_of_ebt", "r3_score":"int_to_talcap", "r4_score":"n_cashflow_act"}