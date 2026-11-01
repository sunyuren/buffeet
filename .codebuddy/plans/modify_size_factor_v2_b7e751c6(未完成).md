---
name: modify_size_factor_v2
overview: 调整规模因子 cal_size_factor：移除总资产(total_assets)，新增营业利润(operate_profit)，权重改为 总市值5/流通市值1/总收入2/营业利润2；流通市值与总收入在 log10 后改为**按行业分组**标准化（行业内比较），再与总市值、营业利润一起做稳健标准化合成。database.py 无需改动（operate_profit 字段已存在且被 get_fina_indicator_by_ann_date 默认返回）。
todos:
  - id: update-registry
    content: 修改 FACTOR_REGISTRY：移除总资产项，新增营业利润项
    status: pending
  - id: update-size-docstring
    content: 更新 cal_size_factor 文档字符串（分项与 5:1:2:2 权重、组内标准化）
    status: pending
    dependencies:
      - update-registry
  - id: update-fina-merge
    content: 调整 3.2/3.3 财务兜底列与 merge 为 total_revenue/operate_profit
    status: pending
    dependencies:
      - update-size-docstring
  - id: update-log-std
    content: 调整 3.4 对数列，3.5 中 circ_mv/total_revenue 改按行业组内标准化
    status: pending
    dependencies:
      - update-fina-merge
  - id: update-weights
    content: 调整 3.6 weights 为 5:1:2:2 并映射新四项合成
    status: pending
    dependencies:
      - update-log-std
---

## 用户需求

调整规模因子 cal_size_factor 的构成与标准化方式，以及 factor.py 中相关注册表与文档。

## 核心功能

- 移除规模因子中的【总资产 total_assets】分项。
- 在营业总收入之后新增【营业利润 operate_profit】分项（数据库字段已存在，无需改 database.py）。
- 权重分布改为：总市值 5、流通市值 1、总收入 2、营业利润 2（权重和 10，缺项按有效权重归一）。
- 流通市值、总收入两项取 log10 后改为按行业分组、行业内比较，再与其他分项一同执行稳健标准化（robust_z_to_score）；总市值、营业利润仍全市场标准化。
- 同步更新 FACTOR_REGISTRY 中规模因子注册项（移除总资产项，新增营业利润项）、cal_size_factor 文档字符串与权重描述。
- cal_valuation_factor 与其他占位函数、upsert/ORM 均不改动。

## 技术栈

- 语言：Python 3（与现有项目一致）
- 数据处理：pandas + numpy
- 数据访问：复用 src/database.py 现有 get_daily_basic_by_trade_date、get_fina_indicator_by_ann_date（operate_profit 已包含于返回列，无需改 database.py）
- 归一化：复用 factor.py 现有 robust_z_to_score（单序列，不改动其实现）

## 实现方案

### 总体策略

仅修改 src/factor.py 的 cal_size_factor 与其文档、FACTOR_REGISTRY 注册项。将分项由 4 项（含 total_assets）调整为 4 项（total_mv / circ_mv / total_revenue / operate_profit），权重 5:1:2:2；对 circ_mv_log、total_revenue_log 增加「按 industry 分组后组内 robust_z_to_score」的步骤，其余两项保持全市场标准化，最后统一加权合成。

### 关键决策

1. **database.py 无需改动**：StockFinaIndicator.operate_profit 已定义（728 行），get_fina_indicator_by_ann_date 默认返回全部列，operate_profit 自动包含。
2. **组内标准化实现**：robust_z_to_score 仅接受单序列。对 circ_mv_log、total_revenue_log 使用
`section.groupby("industry")[col + "_log"].transform(lambda s: robust_z_to_score(s))`
得到行业内比较的分数；transform 保证返回与原索引对齐的 Series，缺失组不报错。total_mv_log、operate_profit_log 仍直接 `robust_z_to_score(section[col+"_log"])`（全市场）。
3. **兜底与空 DataFrame 列调整**：fina_df 兜底列集合改为 ("total_revenue","operate_profit","end_date")；空兜底 DataFrame columns 改为 ["ts_code","total_revenue","operate_profit"]，避免 merge 时 KeyError。
4. **权重与 total_w**：weights={total_mv:5, circ_mv:1, total_revenue:2, operate_profit:2}，total_w=10；复用现有加权合成循环（score_cols 映射新四项），缺项按有效权重归一逻辑不变。
5. **FACTOR_REGISTRY**：移除 ("总资产","total_assets","规模","stock_fina_indicator")，新增 ("营业利润","operate_profit","规模","stock_fina_indicator")，保持注册表与计算逻辑一致（便于后续聚合/展示）。

### 性能与可靠性

- 组内 transform 在每个交易日截面执行一次 groupby，截面规模（全市场数千只）开销可忽略，不改变整体 O(n) 逐日循环复杂度。
- 边界：某行业样本不足时 robust_z_to_score 内部 mad==0 或分位数为 NaN 会返回 0 序列，安全；缺失值保持 NaN，加权时按有效权重跳过。
- 不影响增量（start_date/end_date）语义，落库仍按 (ts_code, trade_date) 主键 upsert。

## 实现注意事项

- 不改 robust_z_to_score 签名与实现。
- 不改 upsert_stock_factor、StockFactor ORM、cal_valuation_factor 及其他占位函数。
- 仅修正 cal_size_factor 内列名、兜底列、对数循环、标准化步骤、加权映射、docstring；以及 FACTOR_REGISTRY 对应两行。
- 保持代码风格与现有回滚版本一致（逐交易日循环、print 日志）。

## 架构设计

```mermaid
flowchart TD
    A[cal_size_factor 入口] --> B[get_all_date 取交易日 + start_date/end_date 过滤]
    B --> C[遍历交易日 td]
    C --> D[get_daily_basic_by_trade_date 取 total_mv/circ_mv]
    C --> E[get_fina_indicator_by_ann_date 取 total_revenue/operate_profit]
    D --> F[合并 + industry 列]
    E --> F
    F --> G[log10 变换四项]
    G --> H1[total_mv/operate_profit 全市场 robust_z_to_score]
    G --> H2[circ_mv/total_revenue 按 industry 组内 robust_z_to_score]
    H1 --> I[加权合成 5:1:2:2]
    H2 --> I
    I --> J[apply 转 int 落库 upsert]
```

## 目录结构

```
src/
└── factor.py   # [MODIFY]
    - FACTOR_REGISTRY：移除总资产项，新增营业利润项（行 99-104 附近）
    - cal_size_factor docstring：更新分项与权重 5:1:2:2、组内标准化说明
    - cal_size_factor 3.2：fina_df 兜底列改为 total_revenue/operate_profit/end_date；空兜底 columns 改为 ts_code/total_revenue/operate_profit
    - cal_size_factor 3.3：merge 使用 fina_df[["ts_code","total_revenue","operate_profit"]]
    - cal_size_factor 3.4：对数循环列改为 total_mv/circ_mv/total_revenue/operate_profit
    - cal_size_factor 3.5：total_mv/operate_profit 全市场标准化；circ_mv/total_revenue 按 industry 组内标准化
    - cal_size_factor 3.6：weights 改 5:1:2:2，score_cols 映射新四项
```