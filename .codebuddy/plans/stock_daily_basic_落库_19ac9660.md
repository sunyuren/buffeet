---
name: stock_daily_basic_落库
overview: 在 stock.db 中新增 daily_basic 表（对应 Tushare daily_basic 接口），实现 upsert 函数与逐股取数（固定从20120101起、单股超6000条分批、本地过滤已存交易日续传、每100只分批写入）的 fetch 逻辑，并补测试11。
todos:
  - id: add-orm-model
    content: 在 database.py 新增 StockDailyBasic ORM 类与字段定义
    status: completed
  - id: add-upsert-fn
    content: 在 database.py 新增 upsert_stock_daily_basic 函数复用合并模式
    status: completed
    dependencies:
      - add-orm-model
  - id: add-fetch-fn
    content: 在 data_fetch.py 增加 import 并实现 fetch_stock_daily_basic 固定起点分批续传逻辑
    status: completed
    dependencies:
      - add-upsert-fn
  - id: add-test11
    content: 在 data_fetch.py __main__ 新增测试11 调用并打印预览
    status: completed
    dependencies:
      - add-fetch-fn
---

## 产品概述

在现有 buffeet 项目中新增"每日指标（daily_basic）"数据表的取数与落库能力，对接 Tushare `daily_basic` 接口，实现全市场股票每日估值/股本/换手/涨跌停状态等指标的批量抓取、本地断点续传与入库。

## 核心功能

- 新增 ORM 模型 `StockDailyBasic`（表名 `daily_basic`），含复合主键 (ts_code, trade_date) 及 13 个指标字段 + 时间戳字段，与现有 SQLAlchemy 2.0 模型风格一致。
- 新增 `upsert_stock_daily_basic` 批量写入函数，复用现有"先查已存在主键 → 合并 → 写入"模式（复合主键）。
- 新增 `fetch_stock_daily_basic` 取数函数：读取 `stock_list` 全部 ts_code，逐支调用 Tushare `daily_basic`（请求起点固定为 start_date，默认 20120101），单支超 6000 交易日按日期段分批请求合并，按已存交易日本地过滤实现断点续传，每 100 只批量 flush 写入，默认时延 0.2s。
- 在 `data_fetch.py` 的 `__main__` 中新增测试11，调用 `fetch_stock_daily_basic` 并打印预览。

## Tech Stack

- 沿用现有栈：Python + SQLAlchemy 2.0 ORM + Tushare Pro SDK + pandas
- 数据库：SQLite（`data/raw/stock.db`，通过 `config.DATABASE_URL` 连接）
- 复用：`database.py`（`get_session`、`_has_value`、`_td_to_str`、upsert 范式）、`data_fetch.py`（`fetch_stock_weekly` 续传范式、`_pro` 实例）

## Implementation Approach

整体采用与 `fetch_stock_weekly` 一致的"逐股续传 + 分批 flush"范式，并按用户最新调整改写续传语义：

1. **ORM 层**：仿 `StockWeekly` 定义 `StockDailyBasic`，复合主键 `ts_code(String(20))` + `trade_date(String(20))`，数值字段用 `Float`（除 `limit_status` 用 `Integer`），补充 `created_time/updated_time` 时间戳列。所有 Tushare 返回列名与 ORM 属性名完全一致，无需 rename。
2. **upsert 层**：仿 `upsert_stock_weekly` —— 先 `session.query(ts_code, trade_date).all()` 构建 existing set，逐行判存：存在则 `setattr` 更新、不存在则构造新对象 `add_all`，结尾打印并返回 `(new, updated)`。复用 `_has_value` 跳过 Tushare 返回的 None（如亏损 PE 为空）。
3. **fetch 层（按调整改）**：仿 `fetch_stock_weekly` 结构，但续传语义调整：

- 预加载 `daily_basic` 已有 `{ts_code: {trade_date}}`。
- **请求起点固定**：每次调用 `_pro.daily_basic` 的 `start_date` 固定为函数入参 `start_date`（默认 "20120101"），不再改为已存 max(trade_date)。
- **分批预判**：计算自 start_date 至今天的交易日窗口，若单股预计超过 6000 条（约 23.5 年，老股需保留），按每段 ≤6000 交易日的日期段循环请求并 concat，防接口单次超 6000 报错。
- **本地过滤续传**：拉回后 `~df["trade_date"].astype(str).isin(existing_periods)` 过滤已存交易日，仅写入缺失日，避免重复写库且不中断流程。
- **移除整支跳过**：不再用 max(trade_date) >= 今天 判断整支跳过（因起点固定）。
- 每 100 只 `_flush`（`pd.concat` + `upsert_stock_daily_basic`）；`time.sleep(delay)`（末只不 sleep）；单支异常 try/except 打印继续。

## Implementation Notes

- **import 同步**：`database.py` 新增 `StockDailyBasic` 后，必须在 `data_fetch.py` 顶部 `from database import ...` 行追加 `StockDailyBasic, upsert_stock_daily_basic`，否则 fetch 无法引用（现有导入为整批列出，非 `*`）。
- **性能**：续传预加载 existing set 为内存集合，O(1) 判存；分批 flush 避免长事务与内存峰值；本地过滤避免重复写库。全市场体量极大，单股请求起点固定可能重复拉历史，但本地过滤保证不重复入库。
- **健壮性**：`delay=0.2` 在用户要求内；分批逻辑保留以防后续超 6000 报错；单支异常不中断整体流程。
- **向后兼容**：现有所有 upsert/fetch 函数与表结构不变，仅新增。物理表由 `init_db()`（`Base.metadata.create_all`）在下次运行时自动创建，无需手写 DDL。

## Architecture Design

```mermaid
flowchart TD
    A[fetch_stock_daily_basic] --> B[读 stock_list 全部 ts_code]
    B --> C[预加载 daily_basic 已有 ts_code->trade_date 集合]
    C --> D{逐支循环}
    D --> E[按 start_date(20120101)~今天 切段, 每段<=6000交易日]
    E --> F[循环请求 _pro.daily_basic 并 concat]
    F --> G[过滤已存交易日 仅留缺失日]
    G --> H[加入 batch_dfs]
    H --> I{idx % 100 == 0?}
    I -- 是 --> K[_flush: upsert_stock_daily_basic]
    I -- 否 --> D
    K --> D
    D --> L[末尾 _flush 剩余]
    L --> M[输出汇总]
```

## Directory Structure

本次仅改动 `src/database.py` 与 `src/data_fetch.py` 两个文件，新增 ORM 模型、upsert 函数、fetch 函数与测试11，不改变现有模块划分。

- `src/database.py`  # [MODIFY] 在 `StockWeeklyIndicator` 类之后新增 `StockDailyBasic` ORM 类（__tablename__="daily_basic"，复合主键 ts_code+trade_date，13 指标字段 + created/updated 时间戳）；在文件末尾新增 `upsert_stock_daily_basic(df)` 函数，复用 `_has_value`/`_td_to_str` 与现有"先查 existing → 合并 → add_all"模式。
- `src/data_fetch.py`  # [MODIFY] 顶部 import 行追加 `StockDailyBasic, upsert_stock_daily_basic`；在 `fetch_stock_weekly` 之后新增 `fetch_stock_daily_basic(delay=0.2, skip_existing=True, start_date="20120101")` 函数（读 ts_code → 预加载 existing_map → 固定起点分段分批请求 → 本地过滤已存日 → 每 100 只 _flush → time.sleep）；在 `__main__` 测试10 之后新增测试11 调用并打印预览。

## Key Code Structures

```python
# src/database.py 新增 ORM 模型（示意接口）
class StockDailyBasic(Base):
    __tablename__ = "daily_basic"
    ts_code: Mapped[str] = mapped_column(String(20), primary_key=True, comment="TS股票代码")
    trade_date: Mapped[str] = mapped_column(String(20), primary_key=True, comment="交易日期 YYYYMMDD")
    close: Mapped[float | None] = mapped_column(Float, comment="当日收盘价")
    turnover_rate_f: Mapped[float | None] = mapped_column(Float, comment="换手率(自由流通股)")
    volume_ratio: Mapped[float | None] = mapped_column(Float, comment="量比")
    pe_ttm: Mapped[float | None] = mapped_column(Float, comment="市盈率TTM")
    pb: Mapped[float | None] = mapped_column(Float, comment="市净率")
    ps_ttm: Mapped[float | None] = mapped_column(Float, comment="市销率TTM")
    dv_ttm: Mapped[float | None] = mapped_column(Float, comment="股息率TTM(%)")
    total_share: Mapped[float | None] = mapped_column(Float, comment="总股本(万股)")
    float_share: Mapped[float | None] = mapped_column(Float, comment="流通股本(万股)")
    free_share: Mapped[float | None] = mapped_column(Float, comment="自由流通股本(万)")
    total_mv: Mapped[float | None] = mapped_column(Float, comment="总市值(万元)")
    circ_mv: Mapped[float | None] = mapped_column(Float, comment="流通市值(万元)")
    limit_status: Mapped[int | None] = mapped_column(Integer, comment="收盘涨跌状态 0-6")
    created_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    updated_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")
```