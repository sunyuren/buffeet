# 项目长期记忆 (MEMORY.md)

## 环境与运行方式
- 本项目 Python 运行环境：PATH 上的 `python` 是 Windows Store 桩（`C:\Users\yuri_sun\AppData\Local\Microsoft\WindowsApps\python.exe`），直接运行 `.py` 脚本或 `python -c` 会返回退出码 9009。
- 实际可用解释器（二选一）：
  - 项目虚拟环境：`.\.env\Scripts\python.exe`
  - conda 环境 `Buffett`：`C:\Users\yuri_sun\anaconda3\envs\Buffett\python.exe`
- 运行本项目脚本请使用上述真实解释器，例如：`.\.env\Scripts\python.exe src/main.py`。

## 技术栈约定
- SQLAlchemy 2.x ORM（DeclarativeBase / Mapped 风格）+ pandas + SQLite（`data/` 下 .db）。
- 数据库访问通过 `database.py` 的 `get_session()`（上下文管理器）与 `get_engine()`；写库统一走各表 `upsert_*` 函数（仅当字段 `_has_value` 才 setattr，支持部分字段更新）。
- `src/data_fetch.py` 中各 `fetch_*` 函数结构一致：取全量 ts_code → 分批（每批 100）→ 批内处理 → upsert → 汇总打印（`"=" * 50` 风格）。
