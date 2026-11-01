---
name: sqlite-stock-list-setup
overview: 在 data/raw/ 下创建 SQLite 数据库文件，新建 stock_list 表（code/name/market/industry/general_value/is_st/created_at/updated_at），并在 src/ 下创建 database.py 使用 SQLAlchemy 构建 ORM 映射。
todos:
  - id: add-sqlalchemy-dep
    content: 更新 requirements.txt，添加 sqlalchemy>=2.0.0 依赖
    status: completed
  - id: add-db-config
    content: 更新 config.py，新增 DATABASE_URL 数据库连接配置
    status: completed
  - id: create-database-module
    content: 创建 src/database.py，实现 StockList ORM 模型、引擎创建、建表及会话管理
    status: completed
    dependencies:
      - add-db-config
---

## 用户需求

在现有股票量化项目（Buffeet）中集成 SQLite 数据库，使用 SQLAlchemy ORM 管理股票清单数据。

## 核心功能

- 在 `data/raw/` 目录下创建 SQLite 数据库文件 `stock.db`
- 建立 `stock_list` 表，包含字段：code（主键）、name、market、industry、general_value（总市值）、is_st、created_at、updated_at
- 在 `src/database.py` 中实现 SQLAlchemy ORM 模型映射及数据库会话管理
- 将数据库连接配置集成到 `config.py` 中，统一管理

## 技术栈

- **数据库**：SQLite（Python 标准库自带，零配置）
- **ORM 框架**：SQLAlchemy 2.0+（声明式映射，`Mapped` + `mapped_column` 风格）
- **数据库驱动**：sqlite3（Python 内置，无需额外安装 pymysql）

## 实现方案

### 核心策略

采用 SQLAlchemy 2.0 的现代声明式 ORM 风格（`DeclarativeBase` + `Mapped` 注解），创建独立的数据库模块 `src/database.py`，通过 `config.py` 集中管理数据库连接字符串，实现与 `data_fetch.py` 的完全解耦。

### 关键设计决策

1. **数据库文件位置**：`data/raw/stock.db`，与现有 CSV 数据文件放在同一目录下，便于统一管理数据资源。

2. **ORM 风格选择**：使用 SQLAlchemy 2.0 新式 API（`sqlalchemy.orm.DeclarativeBase` + `Mapped` 类型注解），代码更简洁、类型安全更好，且是官方推荐的未来方向。

3. **日期字段设计**：`created_at` 和 `updated_at` 使用 TEXT 类型存储 ISO 格式字符串（如 `2026-05-24 21:41:00`），通过 Python 的 `datetime.now().isoformat()` 生成，确保与 MySQL 兼容。

4. **is_st 字段**：使用 `Boolean` 类型，默认值 `False`，在 SQLite 中映射为 INTEGER（0/1）。

5. **会话管理**：提供 `get_session()` 上下文管理器和全局 `init_db()` 函数，确保建表和会话生命周期管理便捷可靠。

6. **扩展性预留**：`DatabaseManager` 类预留了 `save_dataframe()` 和 `load_dataframe()` 等通用方法接口，方便后续其他模块（如日线行情表）复用数据库操作模式。

### 架构设计

```
config.py  ──(DATABASE_URL)──>  src/database.py
                                      │
                          ┌───────────┼───────────┐
                          │           │           │
                     ORM 模型     init_db()   get_session()
                    (StockList)   建表函数    会话管理器
                          │
                          ▼
                   data/raw/stock.db
                   ┌─────────────────┐
                   │  stock_list 表  │
                   │  code (PK)      │
                   │  name           │
                   │  market         │
                   │  industry       │
                   │  general_value  │
                   │  is_st          │
                   │  created_at     │
                   │  updated_at     │
                   └─────────────────┘
```

### 目录结构

```
c:\Users\yuri_sun\CodeBuddy\buffeet\
├── config.py                    # [MODIFY] 新增 DATABASE_URL 配置项
├── requirements.txt             # [MODIFY] 新增 sqlalchemy>=2.0.0 依赖
├── data/
│   └── raw/
│       └── stock.db             # [NEW] SQLite 数据库文件（首次运行时自动创建）
└── src/
    └── database.py              # [NEW] SQLAlchemy ORM 映射与数据库操作模块
```

### 代码结构说明

**config.py 新增内容**：

- `DATABASE_URL`：SQLite 连接字符串 `"sqlite:///data/raw/stock.db"`，后续切换 CloudBase MySQL 只需修改此变量。

**src/database.py 模块结构**：

- `Base`：SQLAlchemy 声明式基类
- `StockList`：ORM 模型类，映射 `stock_list` 表
- `get_engine()`：创建数据库引擎（单例模式）
- `init_db()`：建表函数（项目中首次调用时执行）
- `get_session()`：上下文管理器，自动 commit/rollback/close

### 关键代码结构

```python
from sqlalchemy import create_engine, String, Float, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from contextlib import contextmanager

class Base(DeclarativeBase):
    pass

class StockList(Base):
    __tablename__ = "stock_list"
    code: Mapped[str] = mapped_column(String(20), primary_key=True, comment="股票代码")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="股票名称")
    market: Mapped[str | None] = mapped_column(String(10), comment="市场")
    industry: Mapped[str | None] = mapped_column(String(50), comment="所属行业")
    general_value: Mapped[float | None] = mapped_column(Float, comment="总市值")
    is_st: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否ST")
    created_at: Mapped[str] = mapped_column(String(30), comment="创建时间")
    updated_at: Mapped[str | None] = mapped_column(String(30), comment="更新时间")
```