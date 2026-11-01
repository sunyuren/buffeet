---
name: weekly-factor-update-plan
overview: 在 src/factor.py 新增 cal_factors_weekly() 驱动（窗口 start=stock_factor 现有 max(trade_date)、end=今天，依次调用 7 个因子）；并按「内部向前延展取数、写库窗口仍严格为 [start,end]」的统一范式改造两个因子：波动率向前延展 4 周（4周累计换手率）、反转因子向前延展 60 周（60周均线乖离率）。
todos:
  - id: explore-vol-window
    content: 使用 [subagent:code-explorer] 定位 cal_volatility_factor 的 _wk 窗口编号与写库边界，并记录改造前历史周因子值基线
    status: in_progress
  - id: vol-refactor
    content: 新增 VOL_LOOKBACK_WEEKS=4 并改造 cal_volatility_factor：完整序列对齐窗口序号、向前延展 4 周、仅 [start,end] 写库
    status: completed
    dependencies:
      - explore-vol-window
  - id: rev-refactor
    content: 新增 REV_LOOKBACK_WEEKS=60 并将 cal_reverse_factor 取数延展改为 60 周，写库守卫保持不变
    status: completed
    dependencies:
      - explore-vol-window
  - id: weekly-driver
    content: 新增 cal_factors_weekly：窗口解析、依赖预检、无新周短路、依次调用 7 因子并汇总耗时与行数
    status: completed
    dependencies:
      - vol-refactor
      - rev-refactor
  - id: main-hook
    content: 在 factor.py 顶部补 get_session 导入，并在 __main__ 接入 cal_factors_weekly，保留既有测试块为注释
    status: completed
    dependencies:
      - weekly-driver
  - id: verify-factor
    content: 小窗口试跑校验：因子表推进至最新周、旧日期波动与反转因子值不变、同窗口重跑幂等
    status: in_progress
    dependencies:
      - main-hook
---

## 产品概述

在基础数据（交易日历、股票清单、每日指标、周K、周K技术指标、财报三表与财务指标）已完成每周更新至最新的前提下，为因子库补齐「每周增量重算」能力：新增一个一键驱动入口，自动解析增量窗口并依次重算已实现的 7 个因子，使因子结果随基础数据同步推进到最新周。

## 核心功能

- **一键周更因子**：自动解析窗口（起点取因子表现有最大日期、含边界，终点取今天），依次重算 7 个因子，并打印各因子状态、耗时与写入行数。
- **覆盖范围**：规模、估值、波动、反转、盈利、成长、现金共 7 个因子；供需、护城河两个尚未实现的因子跳过。
- **历史依赖的前向延展**：波动因子需向前延伸 4 周（4 周累计换手率）；反转因子需向前延伸 60 周（60 周均线乖离率）。延展仅用于喂给计算所需的历史上下文。
- **输出窗口不扩大**：所有因子计算完成后，输出与落库窗口严格保持为「起点、终点」范围，延展周仅参与计算、不落库，避免改写历史存量因子值。
- **依赖预检**：运行前检查每日指标、周K技术指标与可用截面序列的最新日期是否就绪，落后时给出告警并提示先做基础数据周更。
- **结果校验与幂等**：结束后报告因子表最新日期是否推进到最新周、各因子增量行数；同一窗口重复执行结果一致。

## 边界与约束

- 仅做因子增量重算，不改动基础数据更新链路。
- 保持各因子函数对外的调用方式与入参不变，仅修正波动、反转两个因子的内部取数窗口语义。
- 不引入新的外部依赖。

## 技术栈

- 语言与运行环境：Python 3.11（现有 .env 环境），Windows / PowerShell。
- 计算与数据访问：pandas、numpy、SQLAlchemy + SQLite（data/raw/stock.db）；全部沿用现有依赖，无需新增。
- 复用模块：src/factor.py（因子计算与 upsert_stock_factor）、src/database.py（get_all_date、get_daily_basic_by_trade_date、get_weekly_by_trade_date、get_weekly_indicator_by_trade_date、StockFactor 等）。
- 改动面：仅 src/factor.py 一个文件。

## 前置事实（已核实）

- get_all_date() 取 交易日历开市日 与 每日指标日期 与 周K技术指标日期 三者交集；因技术指标仅有周频日期，交集即每周最后交易日，故因子表为周频表，7 个因子函数遍历的都是周频截面。
- 7 个因子签名统一为 cal_xxx_factor(start_date=None, end_date=None)，落库统一走 upsert_stock_factor（幂等）。
- 因子表计数字段：size / valuation / volility / reverse / profit / growth / cash。

## 因子历史依赖与延展口径

| 因子 | 数据依赖形态 | 是否延展 | 延展周数 |
| --- | --- | --- | --- |
| size | 逐截面自包含（当日每日指标 + 财报公告窗口） | 否 | 0 |
| valuation | 逐截面自包含（当日每日指标，仅截面归一化） | 否 | 0 |
| volatility | 跨截面滚动：本周换手率窗口 + 向前连续 4 周窗口滚动求和 | 是 | 4 |
| reverse | 跨截面滚动：持续性连胜 + 60 周均线乖离率 | 是 | 60 |
| profit | 逐截面自包含（财报公告窗口） | 否 | 0 |
| growth | 逐截面自包含（财报公告窗口） | 否 | 0 |
| cash | 逐截面自包含（财报公告窗口） | 否 | 0 |


## 实现方案

采用「新增统一驱动函数 + 两个因子单点改造」的最小侵入式方案。

### 关键决策与理由

1. 延展只在因子函数内部进行，绝不在驱动层前移起点。若在驱动层把起点往前挪，波动/反转会把延展周的（降级）因子值一并 upsert，覆盖掉这些历史周原本正确的存量值。因此遵循反转因子既有范式：取数窗口延展、写库窗口守卫。

2. 新增模块级常量（与既有 REV_ 参数块风格一致）：VOL_LOOKBACK_WEEKS = 4、REV_LOOKBACK_WEEKS = 60。

3. 写库守卫统一为「td 不小于起点日期才落库」；起点为 None（全量调用）时不设守卫，行为与改造前一致。

### volatility 改造（重点：窗口序号必须与循环索引对齐）

现状：函数先把截面序列裁剪为 [start, end]，再用 searchsorted 把日频交易日映射到窗口序号 _wk，然后用 enumerate 的索引 i 去 weekly_turnover_sum[(i, ts_code)] 查值。即 _wk 是「当前序列索引」，循环索引 i 也是同一序列索引，二者必须指向同一份序列。

风险：若直接裁剪序列，首个截面 i=0 被跳过、且 4 周滚动因缺少前序窗口而留空，导致起点当周及后若干周因子降级。

正确改法（保持「同一份完整序列」不变）：

- 使用完整 get_all_date() 序列（不裁剪）用于 searchsorted 与循环索引，保证 _wk 与循环下标严格一致；
- 在完整序列上定位 start_idx 与 end_idx（end_date 为 None 时取末值）；
- lookback_idx = max(0, start_idx - VOL_LOOKBACK_WEEKS)；
- 取数下界 q_start = trade_date[max(0, lookback_idx - 1)]（保证「上一截面, 本截面」的日频窗口有前序），取数上界 q_end = trade_date[end_idx]；
- 遍历改为 for i in range(lookback_idx, end_idx + 1) 且 td = trade_date[i]，窗口查值仍用 (i, ts_code)，从而与 _wk 对齐；
- 保留 i == 0 的原有跳过分支（仅影响全量调用）；
- 新增写库守卫：当 i 小于 start_idx（等价 td 小于起点日期）时 continue，不落库；
- 同步更新文档字符串。

### reverse 改造（一行延展，守卫不变）

- 将 lookback_start = max(0, start_idx - (REV_K + 2)) 改为 lookback_start = max(0, start_idx - REV_LOOKBACK_WEEKS)（即 60），q_start = trade_date[lookback_start] 自动随之更新；
- 现有遍历与写库守卫保持不变（仍仅对 [start, end] 内截面落库）；
- 同步更新文档字符串中关于延展周数的说明。
- 技术注记：60 周均线指标已在基础数据阶段预计算入库，且持续性由 REV_K = 4 封顶，因此延展 6 周改为 60 周不改变因子取值，仅满足明确要求并提升语义一致性。

### 驱动函数 cal_factors_weekly

- 窗口解析：起点缺省取因子表现有最大日期（含边界，重算无害），终点缺省取今天；
- 依赖预检：打印每日指标最新日期、周K技术指标最新日期与可用截面序列末值；落后于期望最新周时告警并提示先执行基础数据周更（默认告警不中断）；
- 无新周短路：起点晚于终点或窗口内无截面时打印提示并返回；
- 依次调用（固定顺序便于日志稳定）：size、valuation、volatility、reverse、profit、growth、cash；每个因子 try/except 包裹，记录调用前后因子表行数差与耗时；
- 汇总打印：窗口、每因子状态/耗时/新增行数，以及结束后因子表最新日期是否推进到最新周；返回结构化结果字典。

### 导入与入口

- 顶部导入补充 get_session（用于查询因子表现有最大日期）；
- 主入口新增调用 cal_factors_weekly()，既有测试块保留为注释。

### 性能考量

- 增量窗口通常为 1 周；波动因子实际遍历截面数约为 4 加窗口周数，反转因子遍历仍沿用既有全序列循环但仅对范围内截面做重活，属分钟级，远小于全量重算。
- 因子表计数采用 COUNT(*) 前后差，避免全表加载。
- 波动因子沿用 searchsorted 加 groupby 加 rolling 的向量化实现，延展仅体现为索引下界平移，不增加量级开销。

## 架构设计

```mermaid
flowchart TB
    A["cal_factors_weekly(start, end)"] --&gt; B["窗口解析 start=因子表max日期, end=今天"]
    B --&gt; C["依赖预检 daily_basic / weekly_indicator / get_all_date 末值"]
    C --&gt; D{"窗口内有新截面"}
    D --&gt;|否| Z["打印提示并返回"]
    D --&gt;|是| E["依次调用 7 因子"]
    E --&gt; F1["size / valuation / profit / growth / cash 逐截面自包含"]
    E --&gt; F2["volatility 内部延展4周 仅start起落库"]
    E --&gt; F3["reverse 内部延展60周 仅start起落库"]
    F1 --&gt; G["upsert_stock_factor 幂等落库"]
    F2 --&gt; G
    F3 --&gt; G
    G --&gt; H["汇总各因子耗时与行数 校验最新日期是否推进"]

    style A fill:#1f6feb,color:#fff
    style B fill:#2ea043,color:#fff
    style C fill:#2ea043,color:#fff
    style F2 fill:#cf222e,color:#fff
    style F3 fill:#cf222e,color:#fff
    style G fill:#8250df,color:#fff
    style H fill:#0969da,color:#fff
```

## 目录结构

```
buffeet/
└── src/
    └── factor.py   # [MODIFY] 本计划唯一改动文件，共四处：
                    #   1) 新增模块级常量 VOL_LOOKBACK_WEEKS = 4 与 REV_LOOKBACK_WEEKS = 60，
                    #      置于既有 REV_ 参数块附近，保持模块级参数风格一致。
                    #   2) 改造 cal_volatility_factor：以完整截面序列对齐 searchsorted 窗口序号与循环索引；
                    #      lookback_idx = max(0, start_idx - VOL_LOOKBACK_WEEKS)；
                    #      q_start = trade_date[max(0, lookback_idx-1)]，q_end = trade_date[end_idx]；
                    #      遍历 for i in range(lookback_idx, end_idx+1)，td = trade_date[i]；
                    #      新增写库守卫（i 小于 start_idx 时不落库）；全量调用行为保持不变；更新文档字符串。
                    #   3) 改造 cal_reverse_factor：延展由 REV_K+2 改为 REV_LOOKBACK_WEEKS(60)，
                    #      q_start 随之更新；写库守卫保持不变；更新文档字符串。
                    #   4) 新增驱动函数 cal_factors_weekly(start_date=None, end_date=None)：
                    #      窗口解析、依赖预检、无新周短路、依次调用 7 因子（try/except 加计时加行数差分）、
                    #      汇总打印并返回结果字典；顶部导入补 get_session；主入口接入该函数，既有测试块保留为注释。
```

## 关键代码结构

```python
# factor.py 新增模块级常量
VOL_LOOKBACK_WEEKS = 4    # 波动率向前延展周数，对应 4 周累计换手率
REV_LOOKBACK_WEEKS = 60   # 反转因子向前延展周数，对应 60 周均线乖离率

# factor.py 新增驱动函数（返回 dict）
def cal_factors_weekly(start_date: str | None = None,
                       end_date: str | None = None) -> dict:
    """
    每周增量重算已实现的 7 个因子。
    窗口：start_date 缺省取因子表现有最大日期（含边界）；end_date 缺省取今天。
    顺序：size、valuation、volatility、reverse、profit、growth、cash。
    延展：波动因子内部延展 4 周、反转因子内部延展 60 周，写库均严格守卫在 [start, end]。
    返回：{factor_name: {"ok": bool, "elapsed": float, "rows_delta": int, "note": str}}
    """

# factor.py 改造后 cal_volatility_factor 的核心索引对齐（示意）
trade_date = sorted(get_all_date())              # 完整序列，不裁剪
start_idx = ...  # 首个不小于 start_date 的索引，缺省为 0
end_idx = ...    # 最后一个不大于 end_date 的索引，缺省为末位
lookback_idx = max(0, start_idx - VOL_LOOKBACK_WEEKS)
q_start = trade_date[max(0, lookback_idx - 1)]
q_end = trade_date[end_idx]
# searchsorted 使用同一份完整 trade_date，得到窗口序号 _wk
# 遍历改用 range(lookback_idx, end_idx + 1)，td = trade_date[i]，查值仍用 (i, ts_code)
# 写库守卫：i 小于 start_idx 时 continue
```

## 验证要点

- 小窗口试跑：以最近 2 到 3 周为窗口调用驱动函数，确认无报错、日志正常。
- 推进校验：因子表最新日期推进到最新周；抽查新增周各因子列的非空覆盖率。
- 写库守卫校验（关键）：改造前后，起点之前的历史周波动因子与反转因子取值应完全一致，确认未被改写或降级。
- 延展有效性校验：起点当周的波动因子应与全量重算结果一致；若因周数取 4 存在边界偏差，可将常量上调至 5 到 6 作为安全余量。
- 幂等校验：同一窗口连续执行两次，结果一致。

## Agent Extensions

### SubAgent

- **code-explorer**
- Purpose：在改造波动因子前，精确定位并复核 cal_volatility_factor 中 searchsorted 窗口序号 _wk 的生成逻辑（约 factor.py 第 559 至 600 行）与写库点边界（约第 694 至 714 行），明确「窗口序号与循环索引同源」的对齐关系；同时确认全仓库无其他调用点依赖其旧窗口行为，并记录改造前的历史周因子值基线用于回归比对。
- Expected outcome：产出 _wk 编号与滚动 4 窗口对齐关系的关键行号与结构摘要、延展起点的位移方式，以及一份改造前基线（历史周波动/反转因子取值快照），确保改造为局部安全编辑、不产生索引错位或历史值回归。