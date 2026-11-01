# -*- coding: utf-8 -*-
"""
配置文件
集中管理 API 密钥、参数等
"""

# ========== 数据库配置 ==========
DATABASE_URL = "sqlite:///data/raw/stock.db"

# ========== 数据源配置 ==========
# Tushare Token（注册地址: https://tushare.pro）
TUSHARE_TOKEN = "513019732446567de0011457f7dfdee19167b4e09711c903eddfc966"

# 财报抓取起始报告期（格式 YYYYMMDD）。
# 注意：Tushare 免费/普通账号（120 积分）服务端仅开放 2012 年及以后的财报，
# 即使设为更早日期也会被平台截断；需 5000 积分以上账号方可拉取更早历史。
# 此处默认 "19900101" 表示「请求全部历史」，实际返回范围由账号权限决定。
REPORT_START_DATE = "19900101"

# ========== 回测参数 ==========
INITIAL_CAPITAL = 100_000          # 初始资金
COMMISSION_RATE = 0.0003           # 佣金费率
SLIPPAGE = 0.001                   # 滑点

# ========== 策略参数 ==========
FAST_MA_WINDOW = 5                 # 快均线窗口
SLOW_MA_WINDOW = 20                # 慢均线窗口

# ========== 每周动态更新参数 ==========
# 财报披露高峰期月份：仅在这些月份的每周更新中轮询财报类数据
# （年报/一季报集中在 4 月，半年报 8 月，三季报 10 月）
REPORT_PEAK_MONTHS = (4, 8, 10)

# 每周更新时逐支请求的统一时延（秒）
WEEKLY_UPDATE_DELAY = 0.2

# 每周更新时，无历史数据的新股回退使用的全量起点（YYYYMMDD）
WEEKLY_UPDATE_START_DATE = "20120101"

# ========== 其他 ==========
OUTPUT_DIR = "./output"
