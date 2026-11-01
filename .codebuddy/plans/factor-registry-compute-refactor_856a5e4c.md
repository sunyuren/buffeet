---
name: factor-registry-compute-refactor
overview: 整体替换 FACTOR_REGISTRY 为 30 个新因子，并新增 compute_factor_library() 统一计算调度函数（框架+注释+留白，暂不实现精确计算）。
todos:
  - id: replace-registry
    content: 替换 FACTOR_REGISTRY 为 30 个新因子（含分组注释、字段映射修正）
    status: completed
  - id: add-compute-function
    content: 在 factor.py 中新增 compute_factor_library() 及按数据源分发的辅助函数框架（_group_by_source、_dispatch_compute、_compute_daily_basic_factors、_compute_weekly_factors、_compute_weekly_indicator_factors、_compute_fina_factors）
    status: completed
    dependencies:
      - replace-registry
  - id: add-calc-placeholders
    content: 添加 30 个 _calc_{code} 占位函数，含注释说明计算逻辑和 TODO 标记
    status: completed
    dependencies:
      - add-compute-function
  - id: verify-seed-compat
    content: 验证 seed_factor_library() 与新 FACTOR_REGISTRY 的兼容性，确认无需修改
    status: completed
    dependencies:
      - replace-registry
---

## 用户需求

### 1. 替换 FACTOR_REGISTRY

将 `src/factor.py` 中的 `FACTOR_REGISTRY` 从现有的 21 个因子整体替换为 30 个新因子，保持现有的五元组格式 `(factor_code, factor_name, factor_field, factor_type, factor_source)`。

### 2. 新增 compute_factor_library() 函数

在 `factor.py` 中新增 `compute_factor_library()` 函数，作为因子计算的统一入口。该函数遍历 `FACTOR_REGISTRY` 中所有因子，按数据源分组计算原始因子值并写入 `factor_value` 表。本期只做整体框架、注释和留白，暂不实现每个因子的精确计算逻辑。

### 核心功能

- 30 个因子覆盖 6 大类：规模(SIZE)、估值(VAL)、波动(VOL)、技术(TECH)、盈利(PRF)、成长(GRT)、现金(CAF)
- 数据源覆盖 4 张表：`stock_daily_basic`(日频)、`stock_weekly`(周频)、`stock_weekly_indicator`(周频)、`stock_fina_indicator`(报告期)
- `seed_factor_library()` 自动适配新的 FACTOR_REGISTRY，无需修改
- `compute_factor_library()` 按因子类型分 6 组处理，每组内部再按数据源进一步拆分

## 技术栈

- 语言：Python 3
- 核心库：pandas、numpy、SQLAlchemy 2.0 ORM
- 数据库：SQLite (通过现有 `database.py` 管理)

## 实现方案

### 1. FACTOR_REGISTRY 替换

直接替换 `factor.py` 第 101-142 行的整个列表，按因子类型分组排列。保留原有注释风格和分组注释。

**关键字段映射处理**：

- `VOL01` 的 `factor_field` 用户写为 `turnover_rate`，但 ORM 列名为 `turnover_rate_f`，注册表中统一使用 ORM 实际列名 `turnover_rate_f`
- `TECH03` 用户写为 `macd`，ORM 中为 `macd_bar`，注册表使用 `macd_bar`
- `TECH05` 用户写为 `boll`，ORM 中拆分为 `boll_upper/boll_mid/boll_lower` 三列。考虑到注册表 `factor_field` 是单字段，暂用 `boll_mid` 占位，在 `compute_factor_library()` 注释中说明需要计算 (close - boll_mid) / (boll_upper - boll_lower) 偏离度

**因子类型枚举**：用户使用 `"波动"` 和 `"技术"` 替代原有的 `"波动率"` 和 `"趋势"`，按用户给定值写入。`factor_library` 表的 `factor_type` 字段注释说明是"限定 10 类枚举"，但实际无 CHECK 约束，写入新值不影响功能。

### 2. compute_factor_library() 函数设计

**整体架构**：

```
compute_factor_library()
├── 按 factor_source 分组因子
│   ├── stock_daily_basic → _compute_daily_basic_factors()
│   ├── stock_weekly → _compute_weekly_factors()
│   ├── stock_weekly_indicator → _compute_weekly_indicator_factors()
│   └── stock_fina_indicator → _compute_fina_factors()
└── 每组内部遍历因子列表，逐个计算并入库
```

**设计决策**：

- 复用现有 `_to_long()` + `upsert_factor_value()` 管道，保持与现有因子写入一致的流程
- 按数据源分组一次查询数据库，避免每个因子单独查库（N+1 问题）
- 每个因子函数返回 `(ts_code, factor_date, raw_value)` 三列 DataFrame，再由 `normalize_by_date` 统一做截面归一化
- 函数名采用 `_calc_{factor_code}` 约定（如 `_calc_SIZE01`），便于后续逐因子实现

**compute_factor_library() 函数签名**：

```python
def compute_factor_library(
    start_date: str | None = None,
    end_date: str | None = None,
    ts_codes: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """
    计算 FACTOR_REGISTRY 中所有因子并写入 factor_value 表。
    
    start_date / end_date: 可选日期范围过滤（YYYYMMDD）
    ts_codes: 可选股票列表过滤
    dry_run: True 时只打印计算计划，不实际写库
    
    返回：{"新增": int, "更新": int, "跳过": int} 或 dry_run 时返回因子清单
    """
```

**性能考虑**：

- 同数据源的因子合并一次 SQL 查询，减少数据库往返
- 波动率因子 (VOL02-VOL05) 需要窗口计算（rolling std），在 pandas 层面完成，不额外查库
- 报告期因子按 `end_date` 截面分组归一化，与日频/周频的 `trade_date` 截面分开处理

### 3. 对现有代码的影响

- `FACTOR_REGISTRY`：直接替换，现有 `seed_factor_library()` 无需修改
- `seed_factor_library()`：无需改动，自动适配新注册表（基于 `factor_code` 去重）
- `normalize_by_date()`、`_to_long()`、`rank_to_score()`、`robust_z_to_score()`、`tanh_to_score()`：无需改动，保持不变
- 数据库 ORM 模型：无需修改

## 目录结构

```
buffeet/
├── src/
│   └── factor.py    # [MODIFY] 替换 FACTOR_REGISTRY + 新增 compute_factor_library() 及辅助函数
```

仅修改 `src/factor.py` 一个文件，无需新建或修改其他文件。

## 关键代码结构

### compute_factor_library() 内部结构

```python
def compute_factor_library(start_date=None, end_date=None, ts_codes=None, dry_run=False):
    """统一因子计算入口"""
    # 1. 按 factor_source 分组
    groups = _group_by_source()
    
    # 2. 依次处理每个数据源
    total_new, total_update, total_skip = 0, 0, 0
    for source, factors in groups.items():
        new, update, skip = _dispatch_compute(source, factors, ...)
        total_new += new; total_update += update; total_skip += skip
    
    return {"新增": total_new, "更新": total_update, "跳过": total_skip}


def _group_by_source():
    """将 FACTOR_REGISTRY 按 factor_source 分组"""
    ...


def _dispatch_compute(source, factors, start_date, end_date, ts_codes):
    """根据 source 分发到对应的计算函数"""
    dispatcher = {
        "stock_daily_basic": _compute_daily_basic_factors,
        "stock_weekly": _compute_weekly_factors,
        "stock_weekly_indicator": _compute_weekly_indicator_factors,
        "stock_fina_indicator": _compute_fina_factors,
    }
    ...


def _compute_daily_basic_factors(factors, ...):
    """计算 stock_daily_basic 来源的因子 (SIZE01-02, VAL01-04, VOL01)"""
    # 一次查询 StockDailyBasic 表，提取所需字段
    # 遍历 factors，逐个调用 _calc_{code} 计算原始值
    # normalize_by_date → _to_long → upsert_factor_value
    ...


# 类似地定义 _compute_weekly_factors / _compute_weekly_indicator_factors / _compute_fina_factors
```

### 各因子计算函数占位约定

每个 `_calc_{code}` 函数内部格式：

```python
def _calc_SIZE01(df: pd.DataFrame) -> pd.DataFrame:
    """总市值因子：取 total_mv，做 log 变换"""
    # TODO: 实现 log 变换 + 99% 截断 + robust_z 归一化
    result = df[["ts_code", "trade_date"]].copy()
    result["factor_date"] = result["trade_date"]
    result["raw"] = df["total_mv"]  # 占位：暂取原始值
    return result[["ts_code", "factor_date", "raw"]]
```