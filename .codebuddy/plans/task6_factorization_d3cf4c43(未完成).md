---
name: task6_factorization
overview: 基于 8 张基础表建立量化因子构建方案：新增 FactorLibrary 因子字典表与 FactorValue 通用纵表 ORM 模型（ts_code/f_date/f_code/f_name/f_value，支持日/周/报告期多粒度），新建 src/factor.py 存放因子计算代码及 3 个归一化函数（rank_to_score / z_to_score / tanh_to_score），并搭好可落地的因子定义与计算/入库框架（多粒度并存：日/周/报告期）。
todos:
  - id: add-orm-models
    content: 在 database.py 新增 FactorLibrary 与 FactorValue（ts_code/f_date/f_code/f_name/f_value）两个 ORM 模型
    status: pending
  - id: add-normalize-funcs
    content: 在 factor.py 实现 rank_to_score、z_to_score、tanh_to_score 三个归一化函数
    status: pending
    dependencies:
      - add-orm-models
  - id: add-factor-registry
    content: 在 factor.py 定义因子字典种子 FACTOR_REGISTRY 与 seed_factor_library 写入函数
    status: pending
    dependencies:
      - add-orm-models
  - id: add-factor-compute
    content: 在 factor.py 实现三粒度取数、截面归一化与 upsert_factor_value 入库
    status: pending
    dependencies:
      - add-normalize-funcs
      - add-factor-registry
  - id: add-build-flow
    content: 在 factor.py 实现 build_all_factors 主流程，覆盖各类型多粒度示例因子
    status: pending
    dependencies:
      - add-factor-compute
---

## 用户需求

基于现有 8 张数据表（stock_list / stock_company / stock_balancesheet / stock_income / stock_cashflow / stock_fina_indicator / stock_weekly / stock_daily_basic），建立一套完整、可直接落地的量化因子构建方案（纵向因子表结构）。

## 产品概述

建立量化因子基础框架：定义因子字典表与因子值通用纵表，提供跨多时间粒度（日频/周频/报告期）的因子计算、归一化与入库能力，使后续策略可统一从纵表读取因子值。

## 核心功能

- 新建 FactorLibrary 因子字典 ORM 模型（因子代码、名称、字段、类型、来源），并写入各类因子种子数据。
- 新建 FactorValue 因子值通用纵表 ORM 模型（ts_code / f_date / f_code / f_name / f_value），支持日/周/报告期多粒度存储，唯一约束 (ts_code, f_date, f_code)，f_name 冗余存储因子名称便于查询。
- 新建 src/factor.py，提供 3 个截面归一化函数：rank_to_score（排名百分比映射到 [-100,100]）、z_to_score（z-score 三倍标准差截断后映射 [-100,100]）、tanh_to_score（tanh 映射到 [-100,100]）。
- 在 factor.py 中提供因子计算框架：从 8 张表按多粒度取数、计算因子原始值、按截面归一化、批量写入 FactorValue 纵表。
- 提供覆盖各因子类型（规模/估值/波动率/盈利/成长/现金/反转/趋势/供需/护城河）与多粒度的因子计算示例，验证流程可落地。

## 技术栈

- 语言/运行时：Python 3（与现有项目一致）
- ORM：SQLAlchemy 2.0（DeclarativeBase / Mapped / mapped_column）
- 数据处理：pandas、numpy
- 数据库：SQLite（DATABASE_URL，已配置）
- 复用：现有 database.py 的 Base、get_session()、init_db()、各表 ORM 模型

## 实现方案

### 总体策略

在现有 ORM 体系内新增两张表（字典表 FactorLibrary、值表 FactorValue），并在新建的 factor.py 中集中实现因子计算与归一化逻辑。归一化函数以 pandas Series 为输入，按"同一截面（同 f_date）"做跨股票标准化，输出 [-100,100] 的 float 分数。因子计算按粒度分流：

- 日频（f_date=trade_date）：从 stock_daily_basic 取估值/规模类（pe_ttm、pb、ps_ttm、total_mv、circ_mv、turnover_rate_f 等）
- 周频（f_date=trade_date）：从 stock_weekly + StockWeeklyIndicator 取波动率/反转/趋势类（pct_chg 滚动波动、近 N 周收益反转、MA 多空、MACD 等）
- 报告期（f_date=end_date）：从 stock_fina_indicator + stock_balancesheet 取盈利/成长/现金/供需/护城河类（roe、roic、tr_yoy、ap_to_ar、毛利率等）

### 关键技术决策

1. FactorValue 采用通用纵表（ts_code, f_date, f_code, f_name, f_value），去掉 freq 单列、新增 f_name 冗余列，符合用户本轮修改。唯一约束 (ts_code, f_date, f_code) 保证同截面同因子唯一。新增因子无需改表结构，因子字典与因子值解耦，扩展性最强。
2. 归一化函数独立无副作用，便于单测与复用：输入 Series、返回同索引 Series，处理 NaN/零分母（z-score 分母为0置0，rank 百分比用 pct=True 默认 method='average'，三倍标准差截断用 np.clip）。
3. 因子计算以"先算原始值 DataFrame → 按截面 groupby(f_date) 归一化 → 整理为 ts_code/f_date/f_code/f_name/f_value 长表 → upsert FactorValue"的流程，复用现有 upsert 模式（参考 database.py 中 upsert_stock_fina_indicator 的"存在则更新、否则插入"思路，用 (ts_code, f_date, f_code) 唯一约束去重）。
4. 因子字典种子数据由独立 seed 函数写入，factor_source 标注取数表组合，factor_type 限定 10 类枚举（规模、估值、波动率、盈利、成长、现金、反转、趋势、供需、护城河）。

### 性能与可靠性

- 因子计算在 pandas 内向量化（groupby+transform），避免逐行 Python 循环；截面归一化 O(n) 每行。
- 入库采用批量 upsert（先查后更新/插入或 merge），避免逐条 commit；大数据量时分块（参考 data_fetch.py 既有 _flush 分块模式）。
- 截面内股票数不足（如单只）时归一化退化为中性值（如 rank 置 0、z 置 0），由调用方保证截面有合理样本。
- NaN 保护：计算与归一化全程保留 NaN，入库时跳过 NaN（对齐 _has_value 思路）。

## 实现要点（防止回归）

- FactorLibrary / FactorValue 直接继承 Base，沿用 Mapped[...] = mapped_column(...) 风格与 comment 注释，无需改 init_db（create_all 自动建表）。
- factor.py 导入 database.py 模型与 get_session，沿用现有会话上下文，不引入新连接模式。
- 归一化函数签名与返回类型明确（pd.Series -> pd.Series），不在函数内做 IO。
- 因子计算示例必须覆盖三种粒度，且只用已存在的表字段，避免引用未抓取占位字段（ap_to_ar 已由 backfill 计算可放心用）。

## 架构设计

```mermaid
flowchart TD
    A[8张源表] -->|按粒度取数| B(factor.py 因子计算)
    B --> C[原始因子 DataFrame]
    C -->|groupby 截面| D[归一化函数 rank/z/tanh]
    D --> E[标准化分数 -100~100]
    E -->|整理长表| F[FactorValue 纵表 ts_code/f_date/f_code/f_name/f_value]
    G[FactorLibrary 字典表] -.|f_code 关联| F
```

## 目录结构

```
src/
├── database.py              # [MODIFY] 新增 FactorLibrary、FactorValue 两个 ORM 模型（继承 Base，沿用现有风格）；init_db 自动建表无需改
└── factor.py                # [NEW] 因子计算框架：3 个归一化函数 + 因子字典种子 + 多粒度因子计算与入库
```

### database.py 修改说明

- FactorLibrary：__tablename__="factor_library"，字段 factor_code(PK,String)、factor_name(String)、factor_field(String)、factor_type(String)、factor_source(String)。
- FactorValue：__tablename__="factor_value"，唯一约束 (ts_code, f_date, f_code)，字段 ts_code(String)、f_date(String)、f_code(String)、f_name(String)、f_value(Float)，建索引加速按因子/日期查询。

### factor.py 新建说明

- 3 个归一化函数：rank_to_score / z_to_score / tanh_to_score。
- FACTOR_REGISTRY：因子字典种子列表（factor_code/name/field/type/source），含 seed_factor_library() 写入函数。
- 取数函数：fetch_daily_factors() / fetch_weekly_factors() / fetch_report_factors()，返回原始值 DataFrame。
- 归一化入口：normalize_cross_section(df, method)，按 f_date 分组调用对应函数。
- 入库函数：upsert_factor_value(df)，批量写入 FactorValue，跳过 NaN。
- 主流程 build_all_factors()：串联取数→计算→归一化→入库，覆盖三粒度与各类型示例因子。

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