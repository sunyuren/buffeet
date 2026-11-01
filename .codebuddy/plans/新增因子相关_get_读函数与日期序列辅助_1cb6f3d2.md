---
name: 新增因子相关 get 读函数与日期序列辅助
overview: 在 database.py 为 4 张因子表新增带日期截面语义的 get_*_by_date 读函数（统一返回 DataFrame），并新增 get_all_date() 辅助函数输出统一日期序列（日频/周频/报告期），供因子最后统一到周频。
todos:
  - id: add-pandas-import
    content: 在 database.py 顶部新增 import pandas as pd
    status: completed
  - id: add-query-layer
    content: 在 database.py 末尾新增四个 get_*_by_date 读函数与 get_all_date 辅助函数
    status: completed
    dependencies:
      - add-pandas-import
  - id: verify-imports
    content: 运行导入冒烟测试并 grep 确认无错误引用
    status: completed
    dependencies:
      - add-query-layer
---

## 用户需求

在 database.py 中为因子计算涉及的 4 张 ORM 表新增统一返回 pd.DataFrame 的日期截面读函数，并新增一个统一日期序列辅助函数，供 factor.py 等上层模块调用，避免在各业务文件中裸写 SQL/ORM 查询。

## 产品概述

建立统一的数据访问层（DAL）查询函数，对因子计算所需的财务、日频、周频行情及周频技术指标四类数据，提供一致、可复用的按日期截面取数能力，返回 pandas DataFrame；并新增 get_all_date() 输出统一截面日期序列，使各维度数据最终可对齐到周频。

## 核心特性

- 为 StockFinaIndicator 新增 get_fina_indicator_by_ann_date（规模/盈利/成长/现金），按公告日期 ann_date 截面取数（该表无 trade_date 字段）。
- 为 StockDailyBasic 新增 get_daily_basic_by_trade_date（规模/估值/波动，日频），按 trade_date 截面取数。
- 为 StockWeekly 新增 get_weekly_by_trade_date（波动，周频），按 trade_date 截面取数。
- 为 StockWeeklyIndicator 新增 get_weekly_indicator_by_trade_date（技术），按 trade_date 截面取数。
- 四个函数统一签名：支持可选 ts_code（单只或列表）、可选日期单值或区间、可选 fields 限制返回列，统一返回 pd.DataFrame（空结果返回含 ORM 列的空 DataFrame，不返回 None）。
- 新增 get_all_date() 辅助函数：第一步取 TradeCal 中 is_open='1' 的所有 cal_date；第二步 distinct 取 StockDailyBasic 的全部日频 trade_date；第三步 distinct 取 StockWeeklyIndicator 的全部周频 trade_date；三者取并集（去重升序）返回 list[str]，作为统一截面日期序列（因子最终统一为周频）。

## 技术栈

- 语言：Python 3（项目现有）
- ORM：SQLAlchemy 2.0（DeclarativeBase / Mapped / mapped_column）
- 数据处理：pandas / numpy
- 数据库：SQLite（通过 config.DATABASE_URL 配置）

## 实现方案

### 总体策略

在 database.py 末尾（TradeCal 区块之后，约第 2490 行后）新增「统一查询层」区块，为四张因子相关表各实现一个带日期截面语义的 get_*_by_date 读函数，并新增 get_all_date() 辅助函数。所有函数复用现有 get_session() 上下文管理器，通过 SQLAlchemy ORM 查询后在 session 关闭前转为 pd.DataFrame 返回。保持与现有 upsert_* 函数一致的分层与风格，不改动任何原有写入逻辑与 ORM 定义。

### 关键技术决策

1. **读函数集中在 database.py（DAL 单一职责）**：database.py 已是所有 ORM 表与 upsert_* 写函数的唯一归宿，读函数放在此处可避免 factor.py 或其他模块裸写 session.query，保证数据访问入口唯一、可复用、可测试。
2. **统一返回 pd.DataFrame**：贴合 factor.py 现有「DataFrame 进、DataFrame 出」的因子计算流程；空结果返回含 ORM 列名的空 DataFrame（非 None），避免调用方做 None 判断。
3. **在 with 块内用 pd.read_sql(query.statement, session.bind) 取数**：get_session() 使用 expire_on_commit=False 且 finally 中 session.close()，若先 .all() 取出 ORM 对象再在 with 块外访问属性会触发懒加载失败。最稳妥做法是在 session 未关闭前用 pd.read_sql 直接基于 query statement 读取，避免对象过期问题。
4. **日期维度差异处理（重要）**：

- StockFinaIndicator 无 trade_date 字段，含 ann_date（公告日期）与 end_date（报告期）。按用户要求以 ann_date 作为截面筛选参数（支持 ann_date 单值或 start_ann_date / end_ann_date 区间）。
- StockDailyBasic / StockWeekly / StockWeeklyIndicator 均含 trade_date，以 trade_date 作为截面参数（支持 trade_date 单值或 start_date / end_date 区间），保持与各自主键一致。

5. **函数命名体现日期截面**：按用户要求统一采用 get_*_by_date 形式（get_fina_indicator_by_ann_date / get_daily_basic_by_trade_date / get_weekly_by_trade_date / get_weekly_indicator_by_trade_date），使调用方一眼可知取数维度。
6. **fields 参数控制返回列**：默认返回全列；传入字段名列表时用 session.query(*[getattr(Model, f) for f in fields]) 限制查询列，减少 I/O 与内存（截面全市场查询可能数千行，限制列有实际收益）。
7. **ts_code 支持单值或列表**：传入列表时用 Model.ts_code.in_(ts_code)，便于按股票子集取数。
8. **get_all_date() 合并策略**：三步分别查询后取并集（set union）并升序排序返回 list[str]。采用 union 而非 intersection，确保不漏掉任一维度可用的截面日期，因子后续对齐周频时可自行筛选；此策略在代码注释中标注，若需交集可后续调整。

### 实现要点

- **database.py 顶部新增导入**：当前仅局部 from pandas import isna，需在文件顶部（约第 13 行后）增加 import pandas as pd，供查询层使用。
- **函数位置**：放在文件末尾 TradeCal 区块之后，新增注释分隔块 `# ===================== 统一查询层（供 factor.py 等调用，返回 DataFrame） =====================`。
- **空 DataFrame 构造**：用 pd.DataFrame(columns=[c.name for c in Model.**table**.columns]) 保证列名与 ORM 一致。
- **get_all_date() 实现细节**：
- 第一步：session.query(TradeCal.cal_date).filter(TradeCal.is_open == '1')，收集 cal_date；
- 第二步：session.query(StockDailyBasic.trade_date.distinct())，收集日频 trade_date；
- 第三步：session.query(StockWeeklyIndicator.trade_date.distinct())，收集周频 trade_date；
- 合并：sorted(set(cal_dates) | set(daily_dates) | set(weekly_dates))，返回 list[str]。
- **blast radius 控制**：不修改任何 upsert_* 函数、不修改 ORM 表定义、不修改 factor.py（本次仅新增读函数与辅助函数；factor.py 的实际调用改造留待后续独立任务）。不改动 StockFactor / upsert_stock_factor（复合因子结果表，保持不变）。

### 性能与可靠性

- 截面查询（单 trade_date 全市场）通常在数千行量级，一次性 pd.read_sql 足够；联合主键已建索引，trade_date 过滤走索引，无额外建索引需求。
- get_all_date() 三步均为单列查询 + distinct，数据量小、开销低；union 为内存 set 操作，可忽略。
- 风险极低：纯新增函数，无外部引用依赖，删除/修改零影响。

## 架构设计

保持现有扁平模块结构，不引入新架构模式。

```mermaid
graph TD
    factor[factor.py 因子计算] -->|调用 get_*_by_date / get_all_date| DAL[database.py 统一查询层]
    DAL -->|get_session| DB[(SQLite)]
    DAL -->|pd.DataFrame / list[str]| factor
```

新增后模块职责：

- database.py：行情/基本面/日历等表的 ORM + upsert_ *写函数 + 新增 get_*_by_date 读函数与 get_all_date() 辅助函数（统一返回 DataFrame / 日期序列）。
- factor.py：纯计算模块（归一化函数 + FACTOR_REGISTRY），后续可从 database 导入 get_*_by_date 与 get_all_date 取数，本次不改动其调用。

## 目录结构

```
src/
└── database.py   # [MODIFY] 顶部新增 import pandas as pd；
                 #          末尾 TradeCal 区块之后新增统一查询层区块，
                 #          实现 get_fina_indicator_by_ann_date /
                 #          get_daily_basic_by_trade_date /
                 #          get_weekly_by_trade_date /
                 #          get_weekly_indicator_by_trade_date 四个读函数
                 #          （均返回 pd.DataFrame，支持 ts_code/日期/fields 过滤），
                 #          以及 get_all_date() 统一日期序列辅助函数。
```

## 关键代码结构

四个读函数统一签名范式（以 StockDailyBasic 为例）：

```python
def get_daily_basic_by_trade_date(
    ts_code: str | list[str] | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """按 trade_date 截面（或区间）查询每日指标，返回 DataFrame。"""

# get_fina_indicator_by_ann_date 用 ann_date / start_ann_date / end_ann_date 替代 trade_date 参数
# get_weekly_by_trade_date / get_weekly_indicator_by_trade_date 同 get_daily_basic_by_trade_date 使用 trade_date 参数
```

get_all_date() 签名：

```python
def get_all_date() -> list[str]:
    """返回统一截面日期序列（TradeCal 开市日 ∪ 日频 trade_date ∪ 周频 trade_date，升序去重）。"""
```