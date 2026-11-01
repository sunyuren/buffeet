---
name: cal_valuation_factor
overview: 完成任务11：实现估值因子 cal_valuation_factor 自包含计算流程（遍历 trade_date、查四类估值底数、倒数+全市场稳健标准化、加权、落库 StockFactor.valuation），并新增测试2 入口。
todos:
  - id: impl-valuation
    content: 重写 cal_valuation_factor 为自包含流程：遍历交易日、查四类估值底数、倒数+全市场稳健标准化、加权落库
    status: completed
  - id: add-test2
    content: 在 __main__ 测试1 之后新增测试2 调用真实 cal_valuation_factor 并打印摘要
    status: completed
    dependencies:
      - impl-valuation
  - id: verify-valuation
    content: 用小批量脚本验证 valuation 与 industry 落库后清理验证数据
    status: completed
    dependencies:
      - impl-valuation
      - add-test2
---

## 用户需求

完成任务11：在 factor.py 中实现估值因子（valuation）的完整计算与落库逻辑，框架参照已有的规模因子 cal_size_factor。

## 产品概述

估值因子衡量股票估值高低（价值属性），由股息率、市盈率倒数、市净率倒数、市销率倒数四类底数经稳健标准化（robust_z_to_score，映射至[-100,100]）后按权重加权得到，逐交易日截面计算并写入 StockFactor 表。

## 核心功能

- 获取全部交易日序列并升序排序。
- 获取全部股票清单（代码、名称、行业）。
- 逐交易日截面循环：查询该日 StockDailyBasic 的 dv_ttm、pe_ttm、pb、ps_ttm。
- 股息率 dv_ttm 直接稳健标准化；市盈率 pe_ttm、市净率 pb、市销率 ps_ttm 先取倒数（1/x，非正值转 NaN）再稳健标准化；四个分数均为全市场标准化。
- 加权合成估值因子（权重：股息率3、市盈率3、市净率2、市销率2），缺项按有效权重归一。
- 结果向下取整为 int，与 name/industry/trade_date 一并写入 StockFactor 表的 valuation 列。
- 在 factor.py 的 **main** 新增"测试2"，调用真实 cal_valuation_factor 并打印摘要，保留既有测试1。

## 技术栈

- 语言：Python 3（与现有项目一致）
- 数据处理：pandas + numpy
- 数据访问：复用 src/database.py 现有接口（get_all_date / get_all_stocks / get_daily_basic_by_trade_date / upsert_stock_factor）
- 归一化：复用 factor.py 现有 robust_z_to_score（对称版，值域 [-100,100]）

## 实现方案

### 总体策略

将 cal_valuation_factor 重构为无参自包含流程函数，内部结构完全对齐已验证的 cal_size_factor：获取交易日 -> 获取股票清单 -> 遍历交易日截面查 daily_basic -> 倒数/标准化/加权 -> 组装含 industry 的 DataFrame -> upsert 落库。估值字段全部来自 StockDailyBasic，无需财务表，因此比规模因子更简洁（无 fina_indicator 分支）。

### 关键决策

1. **股票清单**：复用 get_all_stocks() 构建 {ts_code: (name, industry or "未知")} 映射，与规模因子一致；industry 为 None 归"未知"，保证落库 industry 非空。
2. **底数来源**：四个估值字段（dv_ttm/pe_ttm/pb/ps_ttm）直接来自 get_daily_basic_by_trade_date(trade_date=td) 返回的 DataFrame，过滤 ts_code∈stock_info，并对缺失列做 NaN 兜底。
3. **倒数处理**：pe_ttm/pb/ps_ttm 先用 section[col].where(section[col] > 0) 将非正值（<=0、负值、NaN）转为 NaN，再取 1/x；dv_ttm 不取倒数。这样避免 1/负数、1/0 产生污染值（robust_z_to_score 对 NaN 保持缺失，加权时按有效权重归一）。
4. **标准化范围**：四个分数均全市场 robust_z_to_score（任务未要求行业分组），与规模因子中 total_mv/total_revenue 的处理口径一致。
5. **加权合成**：valuation = (3*dv + 3*pe + 2*pb + 2*ps)；分母取实际参与权重之和，缺项按有效权重归一，避免除零；权重和=10。
6. **落库格式**：StockFactor.valuation 为 Integer，结果向下取整为 python int 后落入 out_df（含 ts_code/name/industry/trade_date/valuation）；upsert_stock_factor 自动写入 valuation 列，industry 按 _has_value 透传。

### 性能与可靠性

- 遍历 trade_date 为 O(N)，每次循环一次 daily_basic 查询 + 内存计算，无 N+1 风险。
- 缺失值：robust_z_to_score 保留 NaN；倒数非正转 NaN；加权阶段显式处理全 NaN 分项（denom>0 判断），不抛异常。
- 落库复用既有 upsert_stock_factor 分批/去重逻辑。

### 对 **main** 的修改

在测试1（调用 cal_size_factor）之后新增"测试2"：调用 cal_valuation_factor() 并打印写入摘要，与测试1 并列、互不干扰。

## 实现注意事项

- 函数签名由占位 `cal_valuation_factor(df: pd.DataFrame)` 改为无参 `cal_valuation_factor() -> None`（与 cal_size_factor 一致）；cal_all_factors 已是骨架模式不再调用它，无需改动。
- 倒数计算统一用 `np.where(col>0, 1.0/col, np.nan)` 或 `.where(col>0).rdiv(1)`，避免 inf/警告。
- 不改动 database.py（valuation 列、upsert 逻辑、industry 透传均已具备）。
- 不改动其他 cal_*_factor 占位函数与 FACTOR_REGISTRY。

## 架构设计

```mermaid
flowchart TD
    A[cal_valuation_factor 自包含流程] --> B[get_all_date 升序交易日]
    A --> C[get_all_stocks 股票清单+行业]
    A --> D{遍历 trade_date}
    D --> E[get_daily_basic_by_trade_date: dv_ttm/pe_ttm/pb/ps_ttm]
    E --> F[pe/pb/ps 取倒数(>0); dv 不取倒数]
    F --> G[四底数全市场 robust_z_to_score]
    G --> H[加权合成 valuation 分数]
    H --> I[组装 DataFrame ts_code,name,industry,trade_date,valuation]
    I --> J[upsert_stock_factor 落库]
```

## 目录结构

```
src/
└── factor.py   # [MODIFY]
    - 重写 cal_valuation_factor()：改为无参自包含流程，遍历交易日、查四类估值底数、倒数/稳健标准化、加权、向下取整为 int、含 industry 落库
    - __main__ 测试1 之后新增"测试2"：调用真实 cal_valuation_factor() 并打印摘要
```

## 关键代码结构

```python
def cal_valuation_factor() -> None:
    """
    估值因子自包含计算流程：遍历交易日截面，查四类估值底数，
    倒数(pe/pb/ps) + 稳健标准化 + 加权合成，落库 StockFactor.valuation。
    """
```