---
name: task6_factorization
overview: 基于 8 张基础表建立量化因子构建方案：本次在 database.py 新增 FactorLibrary 因子字典模型与 FactorValue 通用纵表模型（ts_code/f_date/f_code/f_name/f_value）及 upsert_factor_value 入库函数；新建 src/factor.py 实现 3 个归一化函数（rank_to_score / z_to_score / tanh_to_score）、因子字典种子与 build_all_factors 主流程（因子原始值由主流程内计算，三粒度取数函数后续再做）。
todos:
  - id: add-orm-models
    content: 在 database.py 新增 FactorLibrary 与 FactorValue（ts_code/f_date/f_code/f_name/f_value）两个 ORM 模型
    status: completed
  - id: add-upsert-factor-value
    content: 在 database.py 实现 upsert_factor_value 批量入库函数
    status: completed
    dependencies:
      - add-orm-models
  - id: add-normalize-funcs
    content: 在 factor.py 实现 rank_to_score、z_to_score、tanh_to_score 三个归一化函数
    status: completed
    dependencies:
      - add-orm-models
  - id: add-factor-registry
    content: 在 factor.py 定义因子字典种子 FACTOR_REGISTRY 与 seed_factor_library 写入函数
    status: completed
    dependencies:
      - add-orm-models
  - id: add-build-flow
    content: 在 factor.py 实现 build_all_factors 主流程，内联三粒度取数并计算覆盖各类型示例因子
    status: completed
    dependencies:
      - add-upsert-factor-value
      - add-normalize-funcs
      - add-factor-registry
---

## 用户需求

基于现有 8 张数据表，建立一套完整的量化因子构建方案（纵向因子表结构）。

## 产品概述

新增因子字典表与因子值通用纵表，提供跨多时间粒度（日频/周频/报告期）的因子计算、归一化与入库能力，使后续策略可统一从纵表读取因子值。

## 核心功能

- 在 database.py 中新建 FactorLibrary 因子字典 ORM 模型（因子代码、名称、字段、类型、来源）。
- 在 database.py 中新建 FactorValue 因子值通用纵表 ORM 模型（ts_code / f_date / f_code / f_name / f_value），支持日/周/报告期多粒度存储，唯一约束 (ts_code, f_date, f_code)，f_name 冗余存储因子名称便于查询。
- 在 database.py 中实现 upsert_factor_value 批量入库函数（跳过 NaN，按唯一约束去重更新或插入）。
- 在 src/factor.py 中提供 3 个截面归一化函数：rank_to_score（排名百分比映射到 [-100,100]）、z_to_score（z-score 三倍标准差截断后映射 [-100,100]）、tanh_to_score（tanh 映射到 [-100,100]）。
- 在 factor.py 中定义因子字典种子 FACTOR_REGISTRY 与 seed_factor_library 写入函数，并提供 build_all_factors 主流程（主流程内联从 ORM 模型取数并计算因子原始值，再调用 database.upsert_factor_value 入库），覆盖各因子类型（规模/估值/波动率/盈利/成长/现金/反转/趋势/供需/护城河）与多粒度示例。

## 范围说明

本次取消三粒度取数函数（fetch_daily_factors / fetch_weekly_factors / fetch_report_factors），相关取数逻辑后续再做；本次因子原始值的取数/计算统一放在 factor.py 的 build_all_factors 主流程内联实现，不单独拆分取数函数。

## 技术栈

- 语言/运行时：Python 3（与现有项目一致）
- ORM：SQLAlchemy 2.0（DeclarativeBase / Mapped / mapped_column）
- 数据处理：pandas、numpy
- 数据库：SQLite（DATABASE_URL，已配置）
- 复用：现有 database.py 的 Base、get_session()、init_db()、各表 ORM 模型

## 实现方案

### 总体策略

在现有 ORM 体系内新增两张表（字典表 FactorLibrary、值表 FactorValue），数据访问与入库逻辑放在 database.py（贴近 ORM 与会话），因子算法与主流程放在新建的 factor.py（贴近业务逻辑）。归一化函数以 pandas Series 为输入，按"同一截面（同 f_date）"做跨股票标准化，输出 [-100,100] 的 float 分数。因子计算按粒度分流：

- 日频（f_date=trade_date）：从 stock_daily_basic 取估值/规模类（pe_ttm、pb、ps_ttm、total_mv、circ_mv、turnover_rate_f 等）
- 周频（f_date=trade_date）：从 stock_weekly + StockWeeklyIndicator 取波动率/反转/趋势类（pct_chg 滚动波动、近 N 周收益反转、MA 多空、MACD 等）
- 报告期（f_date=end_date）：从 stock_fina_indicator + stock_balancesheet 取盈利/成长/现金/供需/护城河类（roe、roic、tr_yoy、ap_to_ar、毛利率等）

### 关键技术决策

1. FactorValue 采用通用纵表（ts_code, f_date, f_code, f_name, f_value），去掉 freq 单列、新增 f_name 冗余列。唯一约束 (ts_code, f_date, f_code) 保证同截面同因子唯一。新增因子无需改表结构，因子字典与因子值解耦，扩展性最强。
2. 取数与入库放在 database.py：贴近 ORM 与 get_session，契合项目既有 upsert_stock_fina_indicator 的"存在则更新、否则插入"模式，由唯一约束去重；upsert_factor_value 接收含 ts_code/f_date/f_code/f_name/f_value 的长表 DataFrame，批量写入，跳过 f_value 为 NaN 的行。
3. 三粒度取数函数本轮取消，因子原始值取数在 factor.py 的 build_all_factors 主流程内联实现（用 get_session 查询 ORM 模型并转 DataFrame 计算），保持职责清晰，后续可平滑抽出独立取数函数。
4. 归一化函数独立无副作用，便于单测与复用：输入 Series、返回同索引 Series，处理 NaN/零分母（z-score 分母为 0 置 0，rank 百分比用 pct=True 默认 method='average'，三倍标准差截断用 np.clip）。
5. 因子计算以"主流程内取数→算原始值 DataFrame→按截面 groupby(f_date) 归一化→整理为 ts_code/f_date/f_code/f_name/f_value 长表→调用 database.upsert_factor_value"的流程。
6. 因子字典种子数据由 factor.py 的 seed_factor_library() 写入（通过 database 的会话），factor_source 标注取数表组合，factor_type 限定 10 类枚举。

### 性能与可靠性

- 因子计算在 pandas 内向量化（groupby+transform），避免逐行 Python 循环；截面归一化 O(n) 每行。
- 入库采用批量 upsert（按唯一键查后更新/插入或 merge），避免逐条 commit；参考 data_fetch.py 既有 _flush 分块模式控制内存。
- 截面内股票数不足（如单只）时归一化退化为中性值（rank 置 0、z 置 0），由调用方保证截面有合理样本。
- NaN 保护：计算与归一化全程保留 NaN，入库时跳过 NaN。

## 实现要点（防止回归）

- FactorLibrary / FactorValue 直接继承 Base，沿用 Mapped[...] = mapped_column(...) 风格与 comment 注释，无需改 init_db（create_all 自动建表）。
- factor.py 导入 database.py 模型、get_session、upsert_factor_value，沿用现有会话上下文，不引入新连接模式。
- 归一化函数签名与返回类型明确（pd.Series -> pd.Series），不在函数内做 IO。
- 因子计算示例必须覆盖三种粒度，且只用已存在的表字段，避免引用未抓取占位字段（ap_to_ar 已由 backfill 计算可放心用）。

## 架构设计

```mermaid
flowchart TD
    A[8张源表 ORM] -->|factor.py 主流程内联查询| B[factor.py 计算原始因子]
    B --> C[原始因子 DataFrame]
    C -->|groupby 截面| D[归一化函数 rank/z/tanh]
    D --> E[标准化分数 -100~100]
    E -->|整理长表| F[database.upsert_factor_value]
    F --> G[FactorValue 纵表 ts_code/f_date/f_code/f_name/f_value]
    H[FactorLibrary 字典表] -.|f_code 关联| G
```

## 目录结构

```
src/
├── database.py   # [MODIFY] 新增 FactorLibrary、FactorValue 两个 ORM 模型；新增 upsert_factor_value 批量入库函数
└── factor.py     # [NEW] 3 个归一化函数 + FACTOR_REGISTRY 因子字典种子 + seed_factor_library 写入函数 + build_all_factors 主流程（主流程内联三粒度取数与因子计算）
```

### database.py 修改说明

- FactorLibrary：__tablename__="factor_library"，字段 factor_code(PK,String)、factor_name(String)、factor_field(String)、factor_type(String)、factor_source(String)。
- FactorValue：__tablename__="factor_value"，唯一约束 (ts_code, f_date, f_code)，字段 ts_code(String)、f_date(String)、f_code(String)、f_name(String)、f_value(Float)，建索引加速按因子/日期查询。
- 新增 upsert_factor_value(df)：接收含 ts_code/f_date/f_code/f_name/f_value 的长表 DataFrame，批量写入 FactorValue，跳过 f_value 为 NaN 的行，按唯一约束 (ts_code, f_date, f_code) 更新或插入。

### factor.py 新建说明

- 3 个归一化函数：rank_to_score / z_to_score / tanh_to_score（pd.Series -> pd.Series）。
- FACTOR_REGISTRY：因子字典种子列表（factor_code/name/field/type/source）与 seed_factor_library() 写入函数。
- 计算辅助：按 f_date 分组调用对应归一化函数，将原始因子列整理为 ts_code/f_date/f_code/f_name/f_value 长表。
- 主流程 build_all_factors()：内联从 ORM 模型取数→计算原始因子→截面归一化→调用 database.upsert_factor_value 入库，覆盖三粒度与各类型示例因子。

## 关键代码结构

```python
# factor.py 归一化函数签名（仅接口级）
def rank_to_score(x: "pd.Series") -> "pd.Series":
    """截面排名百分比映射到 [-100,100]：pct=rank(pct=True); return (pct*2-1)*100"""

def z_to_score(x: "pd.Series") -> "pd.Series":
    """z-score 三倍标准差截断后映射到 [-100,100]"""

def tanh_to_score(x: "pd.Series") -> "pd.Series":
    """tanh 映射到 [-1,1] 后 *100 到 [-100,100]"""

# FactorValue ORM 关键字段
# ts_code: str, f_date: str, f_code: str, f_name: str, f_value: float
# 唯一约束: (ts_code, f_date, f_code)
```