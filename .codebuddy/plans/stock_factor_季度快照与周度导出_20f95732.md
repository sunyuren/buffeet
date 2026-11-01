---
name: stock_factor 季度快照与周度导出
overview: 从 stock_factor 表导出指定区间的因子数据并合并为单个 CSV：2021Q1~2025Q4 全部季度 + 2026Q1~Q3，每个季度取该季度最后一个可用周截面快照（每股一行）；2026 年 10 月按周导出全部周截面（10-09/10-16/10-23）。导出 stock_factor 全部列，并新增 period（季度标签 YYYYQn / 周标签 YYYYWnn）与 freq（quarter/week）两列标识，最终输出到 output/ 下的单个 utf-8-sig CSV。
todos:
  - id: build-exporter
    content: 新建 src/export_stock_factor.py：实现季度末快照与 2026 年 10 月周度选期、参数化取数、period/freq 标注、列顺序与排序落盘
    status: completed
  - id: add-validation
    content: 增加校验与日志：季度数 23、周数 3、无重复主键、各期行数与文件大小，缺季度仅告警不中断
    status: completed
    dependencies:
      - build-exporter
  - id: run-and-verify
    content: 用 .env/Scripts/python.exe 运行导出，核对 CSV 的季度/周度块、列顺序与总行数
    status: completed
    dependencies:
      - add-validation
---

