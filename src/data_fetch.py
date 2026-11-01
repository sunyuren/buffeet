# -*- coding: utf-8 -*-
"""
数据获取模块
基于 Tushare Pro API
"""

import time

from datetime import date, datetime, timedelta

import os
import sys

import pandas as pd

# 兼容多种运行方式：确保项目根目录（config.py 所在）与 src 目录（database.py 所在）
# 均在 sys.path 中，使 `python src/data_fetch.py`（任意 CWD）与在 src 内直接运行
# `python data_fetch.py` 都能正常导入同仓库模块。
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT_DIR = os.path.dirname(_SRC_DIR)
for _p in (_SRC_DIR, _ROOT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from database import get_engine, get_session, init_db, StockList, StockManagers, StockCompany, StockBalancesheet, StockIncome, StockCashflow, StockFinaIndicator, StockWeekly, StockWeeklyIndicator, StockDailyBasic, TradeCal, upsert_stock_list, upsert_stock_managers, upsert_stock_company, upsert_stock_balancesheet, upsert_stock_income, upsert_stock_cashflow, upsert_stock_fina_indicator, upsert_stock_weekly, upsert_stock_weekly_indicator, upsert_stock_daily_basic, upsert_trade_cal
from config import (
    TUSHARE_TOKEN,
    REPORT_START_DATE,
    REPORT_PEAK_MONTHS,
    WEEKLY_UPDATE_DELAY,
    WEEKLY_UPDATE_START_DATE,
)

# ========== Tushare 初始化 ==========
import tushare as ts
ts.set_token(TUSHARE_TOKEN)
_pro = ts.pro_api()


def fetch_stock_list() -> pd.DataFrame:
    """
    从 Tushare stock_basic 接口获取A股股票清单（全量字段）
    返回:
        DataFrame，列名与 StockList ORM 对齐
    """
    print("=" * 50)
    print("fetch_stock_list：正在从 Tushare 获取A股股票清单...")
    print("=" * 50)

    fields = (
        "ts_code,symbol,name,area,industry,market,"
        "exchange,list_status,list_date,delist_date,"
        "is_hs,act_name,act_ent_type"
    )
    try:
        df = _pro.stock_basic(exchange='', list_status='', fields=fields)
        print(f"成功获取 {len(df)} 只股票数据")
    except Exception as e:
        print(f"Tushare 获取失败: {e}")
        return pd.DataFrame()

    # 直接对齐列名（Tushare 返回字段与 StockList 列名一致）
    print("列名:", list(df.columns))

    if not df.empty:
        print("正在写入数据库...")
        upsert_stock_list(df)

    return df


def fetch_daily_basic(
    ts_code: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """
    从 Tushare 获取每日基本面指标（PE/PB/PS等）
    """
    try:
        df = _pro.daily_basic(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields='ts_code,trade_date,pe_ttm,pb,ps_ttm,roe'
        )
        return df
    except Exception as e:
        print(f"获取 daily_basic 失败 ({ts_code}): {e}")
        return pd.DataFrame()


def fetch_stock_managers(batch_size: int = 50, delay: float = 1.0) -> pd.DataFrame:
    """
    批量获取A股公司高管数据并写入数据库
    从 stock_list 表读取所有 ts_code，每 batch_size 个为一组，逐组调用 Tushare stk_managers 接口，组间做适当延时。
    参数:
        batch_size: 每组 ts_code 数量（默认 50）
        delay:      组间延时秒数（默认 1.0）
    返回:
        DataFrame，包含所有批次汇总的高管数据
    """
    print("=" * 50)
    print("fetch_stock_managers：正在批量获取公司高管数据...")
    print("=" * 50)

    # 1. 从数据库获取所有 ts_code
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]

    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()

    print(f"共 {total} 只股票，按每 {batch_size} 只一组分批获取\n")

    all_dfs = []
    batch_count = (total + batch_size - 1) // batch_size

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        chunk = ts_codes[i : i + batch_size]
        chunk_str = ",".join(chunk)

        print(f"[{batch_num}/{batch_count}] 正在获取 ts_code 组 (第 {i+1}-{min(i+batch_size, total)} 个) ...")

        try:
            df = _pro.stk_managers(
                ts_code=chunk_str,
                fields='ts_code,ann_date,name,gender,lev,title,edu,national,birthday,begin_date,end_date,resume'
            )
            if df is not None and not df.empty:
                print(f"  ✓ 获取 {len(df)} 条高管记录")
                all_dfs.append(df)
            else:
                print(f"  - 该组无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        #print(df)
        #break

        # 组间延时（最后一批不需要延时）
        if i + batch_size < total:
            time.sleep(delay)

    if not all_dfs:
        print("\n未获取到任何高管数据。")
        return pd.DataFrame()

    # 汇总所有批次数据
    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：共获取 {len(result)} 条高管记录，正在写入数据库...")

    # 写入数据库
    upsert_stock_managers(result)

    return result


def fetch_stock_company(batch_size: int = 1000, delay: float = 1.0) -> pd.DataFrame:
    """
    批量获取A股上市公司基本信息并写入数据库
    从 stock_list 表读取所有 ts_code，每 batch_size 个为一组，逐组调用 Tushare stock_company 接口，组间做适当延时。
    参数:
        batch_size: 每组 ts_code 数量（默认 1000）
        delay:      组间延时秒数（默认 1.0）
    返回:
        DataFrame，包含所有批次汇总的公司信息
    """
    print("=" * 50)
    print("fetch_stock_company：正在批量获取上市公司基本信息...")
    print("=" * 50)

    # 1. 从数据库获取所有 ts_code
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]

    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()

    print(f"共 {total} 只股票，按每 {batch_size} 只一组分批获取\n")

    all_dfs = []
    batch_count = (total + batch_size - 1) // batch_size

    for i in range(0, total, batch_size):
        batch_num = i // batch_size + 1
        chunk = ts_codes[i : i + batch_size]
        chunk_str = ",".join(chunk)

        print(f"[{batch_num}/{batch_count}] 正在获取 ts_code 组 (第 {i+1}-{min(i+batch_size, total)} 个) ...")

        try:
            df = _pro.stock_company(
                ts_code=chunk_str,
                fields=(
                    "ts_code,com_name,com_id,exchange,chairman,manager,secretary,"
                    "reg_capital,province,city,introduction,"
                    "employees,main_business,business_scope"
                )
            )
            if df is not None and not df.empty:
                print(f"  ✓ 获取 {len(df)} 条公司信息")
                all_dfs.append(df)
            else:
                print(f"  - 该组无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        # 组间延时（最后一批不需要延时）
        if i + batch_size < total:
            time.sleep(delay)

    if not all_dfs:
        print("\n未获取到任何公司信息数据。")
        return pd.DataFrame()

    # 汇总所有批次数据
    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：共获取 {len(result)} 条公司信息，正在写入数据库...")

    # 写入数据库
    upsert_stock_company(result)

    return result


def _generate_report_periods(upto: date) -> set:
    """
    生成从 1990 年到 upto（含）之间所有季报报告期，返回 YYYYMMDD 字符串集合。
    用于判断某只股票是否还「有缺失的报告期」需要补抓。
    """
    periods = set()
    for year in range(1990, upto.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            d = date(year, month, day)
            if d <= upto:
                periods.add(d.strftime("%Y%m%d"))
    return periods


def _latest_week_trade_date(upto: date = None) -> str:
    """
    返回 upto（默认今天）所在周（含）之前最后一个周五的 YYYYMMDD 字符串。
    周线 bars 的 trade_date 为「当周最后一个交易日」，近似取周五，
    用于判断某只股票是否已追平到最新一周（整支跳过优化）。
    """
    if upto is None:
        upto = date.today()
    d = upto
    while d.weekday() != 4:  # 4 = Friday
        d = d - timedelta(days=1)
    return d.strftime("%Y%m%d")


def _latest_open_trade_date(upto: date | None = None) -> str:
    """
    返回交易日历中「不晚于 upto（默认今天）」的最近一个开市日（YYYYMMDD）。

    用于每周增量更新时的「已追平最新交易日」判断。交易日历无数据时，回退为
    upto 本身（不会因缺少日历而跳过应有的增量抓取）。

    说明：此处**不复用** database.get_all_date()，因为后者取
    trade_cal ∩ stock_daily_basic ∩ stock_weekly_indicator 三表交集，
    在数据尚未更新前无法反映最新交易日，用于追平判断会形成死循环依赖。
    """
    if upto is None:
        upto = date.today()
    upto_str = upto.strftime("%Y%m%d")
    with get_session() as session:
        row = (
            session.query(TradeCal.cal_date)
            .filter(TradeCal.is_open == "1", TradeCal.cal_date <= upto_str)
            .order_by(TradeCal.cal_date.desc())
            .first()
        )
    return row[0] if row and row[0] else upto_str


def _is_disclosure_peak(d: date | None = None,
                        months: tuple[int, ...] = REPORT_PEAK_MONTHS) -> bool:
    """
    判断 d（默认今天）是否处于「财报披露高峰期」。

    默认高峰月为 config.REPORT_PEAK_MONTHS（4/8/10 月），对应年报与一季报、
    半年报、三季报的集中披露窗口。仅在高期内才轮询财报类数据，可显著省时。
    """
    if d is None:
        d = date.today()
    return d.month in months


def fetch_stock_balancesheet(delay: float = 0.2, skip_existing: bool = True,
                            start_date: str = REPORT_START_DATE) -> pd.DataFrame:
    """
    逐支股票获取A股公司资产负债表数据并写入数据库（细粒度断点续传）
    从 stock_list 表读取所有 ts_code，按单支股票逐支调用 Tushare balancesheet 接口，调用之间做适当延时。
    由于单次 balancesheet 调用会返回该股票所有报告期数据，采用更细粒度的续传策略：
      - 若某股票已拥有「截至当前最新报告期」的全部数据，则整支跳过，不发起请求；
      - 否则仍发起一次请求，但只在本地过滤出「数据库中缺失的报告期」后才写入，
        实现只补抓缺失报告期、不重复写入已有数据。
    参数:
        delay:         每支股票调用之间的延时秒数（默认 0.3）
        skip_existing: 是否启用续传跳过（默认 True）；设为 False 可强制全量重新抓取
    返回:
        DataFrame，包含本次新写入的资产负债表数据
    """
    print("=" * 50)
    print("fetch_stock_balancesheet：逐支获取公司资产负债表（细粒度续传）...")
    print("=" * 50)

    # 1. 从数据库获取所有 ts_code
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]

    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()

    # 2. 预加载已有的 (ts_code -> {end_date})，用于判断缺失报告期
    existing_map: dict = {}
    if skip_existing:
        with get_session() as session:
            rows = session.query(
                StockBalancesheet.ts_code, StockBalancesheet.end_date
            ).all()
        for code, d in rows:
            ed = str(d).replace("-", "") if d is not None else None
            existing_map.setdefault(code, set()).add(ed)

    # 当前最新报告期（用于判断某股票是否已「追平」到最新）
    latest_period = max(_generate_report_periods(date.today()))

    print(f"共 {total} 只股票，逐支获取（细粒度续传）\n")

    all_dfs = []          # 收集本次新写入记录，用于最终返回
    batch_dfs = []        # 收集待批量 upsert 的记录
    skipped = 0
    fetched = 0

    BATCH = 100

    def _flush(batch: list) -> None:
        if not batch:
            return
        chunk = pd.concat(batch, ignore_index=True)
        upsert_stock_balancesheet(chunk)

    for idx, ts_code in enumerate(ts_codes, start=1):
        existing_periods = existing_map.get(ts_code, set())

        # 续传：若已拥有截至最新的全部报告期，则整支跳过，不发起请求
        if skip_existing and existing_periods and max(existing_periods) >= latest_period:
            skipped += 1
            print(f"[{idx}/{total}] 跳过 {ts_code}：报告期已更新至最新 {latest_period}")
            continue

        print(f"[{idx}/{total}] 正在获取 {ts_code} 的资产负债表 ...")

        try:
            df = _pro.balancesheet(
                ts_code=ts_code,
                start_date=start_date,
                fields=(
                    "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,"
                    "total_assets,money_cap,trad_asset,lt_eqt_invest,invest_real_estate,"
                    "notes_receiv,accounts_receiv,prepayment,oth_receiv,inventories,"
                    "contract_assets,oth_cur_assets,fix_assets,cip,lt_rec,oil_and_gas_assets,"
                    "produc_bio_assets,intan_assets,r_and_d,goodwill,total_liab,"
                    "st_borr,trading_fl,lt_borr,bond_payable,lt_payable,notes_payable,"
                    "acct_payable,adv_receipts,contract_liab,payroll_payable,taxes_payable,"
                    "oth_payable,total_liab_hldr_eqy,minority_int,total_share,cap_rese,"
                    "oth_comp_income,surplus_rese,undistr_porfit"
                )
            )
            if df is not None and not df.empty:
                # 细粒度续传：只保留数据库中缺失的报告期
                if skip_existing and existing_periods:
                    before = len(df)
                    df = df[~df["end_date"].astype(str).isin(existing_periods)]
                    if len(df) < before:
                        print(f"  ✓ 获取 {before} 条，其中 {before - len(df)} 条已存在，"
                              f"补抓 {len(df)} 条缺失报告期")
                    else:
                        print(f"  ✓ 获取 {len(df)} 条，均为缺失报告期")
                else:
                    print(f"  ✓ 获取 {len(df)} 条资产负债表记录")

                if not df.empty:
                    all_dfs.append(df)
                    batch_dfs.append(df)
                    fetched += 1
            else:
                print(f"  - 该股票无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        # 每 100 只股票批量 upsert 一次，便于观察与调试
        if idx % BATCH == 0:
            _flush(batch_dfs)
            batch_dfs = []
            print(f"  -- 已分批写入前 {idx} 只股票的数据 --")

        # 单支调用之间延时（最后一支不需要延时）
        if idx < total:
            time.sleep(delay)

    # 剩余批次 upsert
    _flush(batch_dfs)

    if not all_dfs:
        print("\n没有需要补抓的资产负债表数据。")
        return pd.DataFrame()

    # 汇总所有股票数据
    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：本次补抓 {len(result)} 条资产负债表记录"
          + (f"，跳过 {skipped} 只已追平至最新的股票" if skip_existing else "")
          + "，数据已全部写入数据库")

    return result


def fetch_stock_fina_indicator(delay: float = 0.2, skip_existing: bool = True,
                            start_date: str = REPORT_START_DATE) -> pd.DataFrame:
    """
    逐支股票获取A股公司财务指标数据（Tushare fina_indicator 接口）并写入数据库（细粒度断点续传）
    从 stock_list 表读取所有 ts_code，按单支股票逐支调用 Tushare fina_indicator 接口，
    调用之间做适当延时。采用与 fetch_stock_balancesheet 一致的续传策略：
      - 若某股票已拥有「截至上一轮报告期 last_end_date」的全部数据，则整支跳过，不发起请求；
      - 否则仍发起一次请求，但只在本地过滤出「数据库中缺失的报告期」后才写入，
        实现只补抓缺失报告期、不重复写入已有数据。
    字段三类处理：
      第一类：与 fina_indicator 接口字段完全一致，直接抓取；
      第二类：saleexp_ratio / adminexp_ratio / finaexp_ratio 由接口原字段
              saleexp_to_gr / adminexp_of_gr / finaexp_of_gr 更名得到（fetch 阶段 rename）；
      第三类：total_assets / total_revenue / operate_profit / int_to_assets / gw_to_assets /
              oth_to_assets / fin_assets_ratio / op_assets_ratio / pd_assets_ratio /
              capacity_ratio / rdexp_ratio / daa_to_pdassets 需另行补充取数/计算，本次不抓取（保持 NULL）。
    每累计 100 只股票批量 upsert 一次，便于观察与调试。
    参数:
        delay:         每支股票调用之间的延时秒数（默认 0.3）
        skip_existing: 是否启用续传跳过（默认 True）；设为 False 可强制全量重新抓取
    返回:
        DataFrame，包含本次新写入的财务指标数据
    """
    print("=" * 50)
    print("fetch_stock_fina_indicator：逐支获取公司财务指标（细粒度续传）...")
    print("=" * 50)

    # 1. 查询全市场股票列表，统计共有多少只
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]
    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()
    print(f"全市场股票共 {total} 只")

    # 2. 根据系统当前日期，计算上一轮财务报表报告期 last_end_date（YYYYMMDD 字符串）
    last_end_date = max(_generate_report_periods(date.today()))
    print(f"当前日期 {date.today()}，上一轮报告期截止 last_end_date = {last_end_date}")

    # 3. 预加载已有的 (ts_code -> {end_date})，用于判断缺失报告期
    existing_map: dict = {}
    if skip_existing:
        with get_session() as session:
            rows = session.query(
                StockFinaIndicator.ts_code, StockFinaIndicator.end_date
            ).all()
        for code, d in rows:
            ed = str(d).replace("-", "") if d is not None else None
            existing_map.setdefault(code, set()).add(ed)

    # Tushare fina_indicator 请求字段：
    #   主键(ts_code/ann_date/end_date) + 第一类字段 + 第二类用接口原字段名请求后更名。
    #   第三类字段不在请求范围内（保持 NULL）。
    FINA_TUSHARE_FIELDS = (
        "ts_code,ann_date,end_date,"
        "total_revenue_ps,eps,roe,roic,roe_yearly,q_gsprofit_margin,"
        "grossprofit_margin,netprofit_margin,"
        "saleexp_to_gr,adminexp_of_gr,finaexp_of_gr,"
        "inv_turn,ar_turn,fa_turn,assets_turn,"
        "tr_yoy,q_gr_qoq,or_yoy,op_yoy,dt_netprofit_yoy,ocf_yoy,equity_yoy,"
        "salescash_to_or,opincome_of_ebt,debt_to_assets,int_to_talcap,tax_to_ebt,"
        "daa,rd_exp,interestdebt,interst_income"
    )
    # 第二类更名映射：接口原字段 -> ORM 属性名
    T2_RENAME = {
        "saleexp_to_gr": "saleexp_ratio",
        "adminexp_of_gr": "adminexp_ratio",
        "finaexp_of_gr": "finaexp_ratio",
    }

    BATCH = 100
    all_dfs = []          # 收集本次新写入记录，用于最终返回
    batch_dfs = []        # 收集待批量 upsert 的记录
    skipped = 0
    fetched = 0

    def _flush(batch: list) -> None:
        if not batch:
            return
        chunk = pd.concat(batch, ignore_index=True)
        upsert_stock_fina_indicator(chunk)

    for idx, ts_code in enumerate(ts_codes, start=1):
        existing_periods = existing_map.get(ts_code, set())

        # 续传：若已拥有截至 last_end_date 的全部报告期，则整支跳过，不发起请求
        if skip_existing and existing_periods and max(existing_periods) >= last_end_date:
            skipped += 1
            print(f"[{idx}/{total}] 跳过 {ts_code}：报告期已更新至最新 {last_end_date}")
            continue

        print(f"[{idx}/{total}] 正在获取 {ts_code} 的财务指标 ...")
        try:
            df = _pro.fina_indicator(
                ts_code=ts_code,
                start_date=start_date,
                end_date=last_end_date,
                fields=FINA_TUSHARE_FIELDS,
            )
            if df is not None and not df.empty:
                # 第二类字段更名
                df = df.rename(columns=T2_RENAME)

                # 细粒度续传：只保留数据库中缺失的报告期
                if skip_existing and existing_periods:
                    before = len(df)
                    df = df[~df["end_date"].astype(str).isin(existing_periods)]
                    if len(df) < before:
                        print(f"  ✓ 获取 {before} 条，其中 {before - len(df)} 条已存在，"
                              f"补抓 {len(df)} 条缺失报告期")
                    else:
                        print(f"  ✓ 获取 {len(df)} 条，均为缺失报告期")
                else:
                    print(f"  ✓ 获取 {len(df)} 条财务指标记录")

                if not df.empty:
                    all_dfs.append(df)
                    batch_dfs.append(df)
                    fetched += 1
            else:
                print(f"  - 该股票无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        # 每 100 只股票批量 upsert 一次，便于观察与调试
        if idx % BATCH == 0:
            _flush(batch_dfs)
            batch_dfs = []
            print(f"  -- 已分批写入前 {idx} 只股票的数据 --")

        # 单支调用之间延时（最后一支不需要延时）
        if idx < total:
            time.sleep(delay)

    # 剩余批次 upsert
    _flush(batch_dfs)

    if not all_dfs:
        print("\n没有需要补抓的财务指标数据。")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：本次补抓 {len(result)} 条财务指标记录"
          + (f"，跳过 {skipped} 只已追平至最新的股票" if skip_existing else ""))
    return result


def fetch_stock_fina_indicator_backfill(batch_size: int = 100) -> pd.DataFrame:
    """
    补充计算并回填 fetch_stock_fina_indicator() 预留的第三类字段。

    纯数据库内计算任务（不调用 Tushare 接口）：
      以 StockFinaIndicator 为主表，按 (ts_code, end_date) LEFT JOIN
      StockBalancesheet 与 StockIncome，联查结果转 DataFrame 并 fillna(0)，
      然后向量化计算 11 个第三类字段并批量 upsert 回 StockFinaIndicator。

    计算口径：
      total_assets、total_revenue、operate_profit直接取用，interestdebt/rd_exp/daa 取自 StockFinaIndicator 自身（已由 fina_indicator 接口入库）
      其余比率按用户给定公式，分母为 0 时该比率置空（不写入，避免 inf 落库）。
    参数:
        batch_size: 每批处理的股票数量（默认 100）
    返回:
        DataFrame，包含本次计算回填的第三类字段结果
    """
    print("=" * 50)
    print("fetch_stock_indicator_fina_backfill：补充计算第三类字段...")
    print("=" * 50)

    # 1. 查询全市场股票列表，统计共有多少只
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]
    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()
    print(f"全市场股票共 {total} 只，按每批 {batch_size} 只处理")

    # 组分项列（用于向量化求和）
    fin_assets_cols = ["money_cap", "trad_asset", "lt_eqt_invest", "invest_real_estate"]
    op_assets_cols = ["notes_receiv", "accounts_receiv", "prepayment", "oth_receiv",
                      "inventories", "contract_assets", "oth_cur_assets"]
    pd_assets_cols = ["fix_assets", "cip", "lt_rec", "oil_and_gas_assets",
                      "produc_bio_assets", "intan_assets", "r_and_d", "goodwill"]
    pdassets_denom_cols = ["fix_assets", "cip", "lt_rec", "oil_and_gas_assets",
                           "produc_bio_assets", "intan_assets"]

    # 需要写库的列（仅第三类字段，不覆盖已有 T1/T2 字段）
    upsert_cols = [
        "ts_code", "end_date",
        "total_assets", "total_revenue", "operate_profit", "ap_to_ar",
        "int_to_assets", "gw_to_assets", "oth_to_assets",
        "fin_assets_ratio", "op_assets_ratio", "pd_assets_ratio",
        "capacity_ratio", "rdexp_ratio", "daa_to_pdassets",
    ]

    n_batches = (total + batch_size - 1) // batch_size
    all_dfs = []
    processed = 0

    for i in range(n_batches):
        batch_codes = ts_codes[i * batch_size:(i + 1) * batch_size]
        print(f"\n[批次 {i + 1}/{n_batches}] 处理 {len(batch_codes)} 只股票 ...")
        try:
            with get_session() as session:
                query = (
                    session.query(
                        StockFinaIndicator.ts_code.label("ts_code"),
                        StockFinaIndicator.end_date.label("end_date"),
                        StockFinaIndicator.interestdebt.label("interestdebt"),
                        StockFinaIndicator.rd_exp.label("rd_exp"),
                        StockFinaIndicator.daa.label("daa"),
                        StockBalancesheet.total_assets.label("total_assets"),
                        StockIncome.total_revenue.label("total_revenue"),
                        StockIncome.operate_profit.label("operate_profit"),
                        StockBalancesheet.money_cap.label("money_cap"),
                        StockBalancesheet.trad_asset.label("trad_asset"),
                        StockBalancesheet.lt_eqt_invest.label("lt_eqt_invest"),
                        StockBalancesheet.invest_real_estate.label("invest_real_estate"),
                        StockBalancesheet.notes_receiv.label("notes_receiv"),
                        StockBalancesheet.accounts_receiv.label("accounts_receiv"),
                        StockBalancesheet.prepayment.label("prepayment"),
                        StockBalancesheet.oth_receiv.label("oth_receiv"),
                        StockBalancesheet.notes_payable.label("notes_payable"),
                        StockBalancesheet.acct_payable.label("acct_payable"),
                        StockBalancesheet.acct_payable.label("adv_receipts"),
                        StockBalancesheet.acct_payable.label("contract_liab"),
                        StockBalancesheet.acct_payable.label("oth_payable"),
                        StockBalancesheet.inventories.label("inventories"),
                        StockBalancesheet.contract_assets.label("contract_assets"),
                        StockBalancesheet.oth_cur_assets.label("oth_cur_assets"),
                        StockBalancesheet.fix_assets.label("fix_assets"),
                        StockBalancesheet.cip.label("cip"),
                        StockBalancesheet.lt_rec.label("lt_rec"),
                        StockBalancesheet.oil_and_gas_assets.label("oil_and_gas_assets"),
                        StockBalancesheet.produc_bio_assets.label("produc_bio_assets"),
                        StockBalancesheet.intan_assets.label("intan_assets"),
                        StockBalancesheet.r_and_d.label("r_and_d"),
                        StockBalancesheet.goodwill.label("goodwill"),
                    )
                    .select_from(StockFinaIndicator)
                    .outerjoin(
                        StockBalancesheet,
                        (StockFinaIndicator.ts_code == StockBalancesheet.ts_code)
                        & (StockFinaIndicator.end_date == StockBalancesheet.end_date),
                    )
                    .outerjoin(
                        StockIncome,
                        (StockFinaIndicator.ts_code == StockIncome.ts_code)
                        & (StockFinaIndicator.end_date == StockIncome.end_date),
                    )
                    .filter(StockFinaIndicator.ts_code.in_(batch_codes))
                )
                df = pd.read_sql(query.statement, session.bind)
        except Exception as e:
            print(f"  ✗ 联查失败: {e}")
            continue

        if df.empty:
            print("  - 本批无财务指标记录，跳过")
            continue

        # 所有 NaN/Null 置 0
        df = df.fillna(0)

        ta = df["total_assets"]
        tr = df["total_revenue"]

        # 比率字段（暂算，随后做除零保护）
        df["int_to_assets"] = df["interestdebt"] / ta * 100
        df["gw_to_assets"] = df["goodwill"] / ta * 100
        df["oth_to_assets"] = df["oth_receiv"] / ta * 100
        df["fin_assets_ratio"] = df[fin_assets_cols].sum(axis=1) / ta * 100
        df["op_assets_ratio"] = df[op_assets_cols].sum(axis=1) / ta * 100
        df["pd_assets_ratio"] = df[pd_assets_cols].sum(axis=1) / ta * 100
        df["capacity_ratio"] = df[["fix_assets", "cip"]].sum(axis=1) / tr * 100
        df["rdexp_ratio"] = df["rd_exp"] / tr * 100
        daa_denom = df[pdassets_denom_cols].sum(axis=1)
        df["daa_to_pdassets"] = df["daa"] / daa_denom * 100
        # 应付/应收款 = (应付票据+应付账款+预收款项+合同负债+其他应付款) / (应收票据+应收账款+预付款项+其他应收款)
        ar_sum = df["notes_receiv"] + df["accounts_receiv"] + df["prepayment"] + df["oth_receiv"]
        ap_sum = df["notes_payable"] + df["acct_payable"] + df["adv_receipts"] + df["contract_liab"]+df["oth_payable"]
        df["ap_to_ar"] = ap_sum / ar_sum

        # 除零保护：分母为 0 时比率置空（NaN），由 upsert 的 _has_value 跳过写库
        ratio_denom = {
            "int_to_assets": ta,
            "gw_to_assets": ta,
            "oth_to_assets": ta,
            "fin_assets_ratio": ta,
            "op_assets_ratio": ta,
            "pd_assets_ratio": ta,
            "capacity_ratio": tr,
            "rdexp_ratio": tr,
            "daa_to_pdassets": daa_denom,
            "ap_to_ar": ar_sum,
        }
        for col, denom in ratio_denom.items():
            df[col] = df[col].where(denom != 0, other=None)

        upsert_df = df[upsert_cols].copy()
        upsert_stock_fina_indicator(upsert_df)
        all_dfs.append(upsert_df)
        processed += len(upsert_df)
        print(f"  ✓ 本批计算并回填 {len(upsert_df)} 条记录")

    # 收尾：全量统计 StockFinaIndicator 各字段空值率
    print("\n" + "=" * 50)
    print("StockFinaIndicator 全表字段空值率统计")
    print("=" * 50)
    full = pd.read_sql("SELECT * FROM stock_fina_indicator", get_engine())
    total_rows = len(full)
    print(f"全表总行数：{total_rows}")
    if total_rows > 0:
        null_rate = full.isna().mean() * 100
        for col in full.columns:
            print(f"  {col:32s}: {null_rate[col]:6.2f}%")

    if not all_dfs:
        print("\n没有需要回填的第三类字段数据。")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：本次计算回填 {len(result)} 条第三类字段记录")
    return result


def fetch_stock_income(delay: float = 0.2, skip_existing: bool = True,
                      start_date: str = REPORT_START_DATE) -> pd.DataFrame:
    """
    逐支股票获取A股公司利润表数据并写入数据库（细粒度断点续传）
    从 stock_list 表读取所有 ts_code，按单支股票逐支调用 Tushare income 接口，调用之间做适当延时。
    由于单次 income 调用会返回该股票所有报告期数据，采用更细粒度的续传策略：
      - 若某股票已拥有「截至当前最新报告期」的全部数据，则整支跳过，不发起请求；
      - 否则仍发起一次请求，但只在本地过滤出「数据库中缺失的报告期」后才写入，
        实现只补抓缺失报告期、不重复写入已有数据。
    参数:
        delay:         每支股票调用之间的延时秒数（默认 0.3）
        skip_existing: 是否启用续传跳过（默认 True）；设为 False 可强制全量重新抓取
    返回:
        DataFrame，包含本次新写入的利润表数据
    """
    print("=" * 50)
    print("fetch_stock_income：逐支获取公司利润表（细粒度续传）...")
    print("=" * 50)

    # 1. 从数据库获取所有 ts_code
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]

    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()

    # 2. 预加载已有的 (ts_code -> {end_date})，用于判断缺失报告期
    existing_map: dict = {}
    if skip_existing:
        with get_session() as session:
            rows = session.query(
                StockIncome.ts_code, StockIncome.end_date
            ).all()
        for code, d in rows:
            ed = d if isinstance(d, str) else str(d)
            existing_map.setdefault(code, set()).add(ed)

    # 当前最新报告期（用于判断某股票是否已「追平」到最新）
    latest_period = max(_generate_report_periods(date.today()))

    print(f"共 {total} 只股票，逐支获取（细粒度续传）\n")

    all_dfs = []          # 收集本次新写入记录，用于最终返回
    batch_dfs = []        # 收集待批量 upsert 的记录
    skipped = 0
    fetched = 0

    BATCH = 100

    def _flush(batch: list) -> None:
        if not batch:
            return
        chunk = pd.concat(batch, ignore_index=True)
        upsert_stock_income(chunk)

    for idx, ts_code in enumerate(ts_codes, start=1):
        existing_periods = existing_map.get(ts_code, set())

        # 续传：若已拥有截至最新的全部报告期，则整支跳过，不发起请求
        if skip_existing and existing_periods and max(existing_periods) >= latest_period:
            skipped += 1
            print(f"[{idx}/{total}] 跳过 {ts_code}：报告期已更新至最新 {latest_period}")
            continue

        print(f"[{idx}/{total}] 正在获取 {ts_code} 的利润表 ...")

        try:
            df = _pro.income(
                ts_code=ts_code,
                start_date=start_date,
                fields=(
                    "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,"
                    "basic_eps,diluted_eps,total_revenue,revenue,total_cogs,"
                    "oper_cost,biz_tax_surchg,sell_exp,admin_exp,rd_exp,fin_exp,"
                    "assets_impair_loss,credit_impa_loss,fv_value_chg_gain,invest_income,"
                    "asset_disp_income,oth_income,operate_profit,total_profit,income_tax,"
                    "n_income,n_income_attr_p,oth_compr_income,t_compr_income"
                )
            )
            if df is not None and not df.empty:
                # 细粒度续传：只保留数据库中缺失的报告期
                if skip_existing and existing_periods:
                    before = len(df)
                    df = df[~df["end_date"].astype(str).isin(existing_periods)]
                    if len(df) < before:
                        print(f"  ✓ 获取 {before} 条，其中 {before - len(df)} 条已存在，"
                              f"补抓 {len(df)} 条缺失报告期")
                    else:
                        print(f"  ✓ 获取 {len(df)} 条，均为缺失报告期")
                else:
                    print(f"  ✓ 获取 {len(df)} 条利润表记录")

                if not df.empty:
                    all_dfs.append(df)
                    batch_dfs.append(df)
                    fetched += 1
            else:
                print(f"  - 该股票无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        # 每 100 只股票批量 upsert 一次，便于观察与调试
        if idx % BATCH == 0:
            _flush(batch_dfs)
            batch_dfs = []
            print(f"  -- 已分批写入前 {idx} 只股票的数据 --")

        # 单支调用之间延时（最后一支不需要延时）
        if idx < total:
            time.sleep(delay)

    # 剩余批次 upsert
    _flush(batch_dfs)

    if not all_dfs:
        print("\n没有需要补抓的利润表数据。")
        return pd.DataFrame()

    # 汇总所有股票数据
    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：本次补抓 {len(result)} 条利润表记录"
          + (f"，跳过 {skipped} 只已追平至最新的股票" if skip_existing else "")
          + "，数据已全部写入数据库")

    return result


def fetch_stock_cashflow(delay: float = 0.2, skip_existing: bool = True,
                        start_date: str = REPORT_START_DATE) -> pd.DataFrame:
    """
    逐支股票获取A股公司现金流量表数据并写入数据库（细粒度断点续传）
    从 stock_list 表读取所有 ts_code，按单支股票逐支调用 Tushare cashflow 接口，调用之间做适当延时。
    由于单次 cashflow 调用会返回该股票所有报告期数据，采用更细粒度的续传策略：
      - 若某股票已拥有「截至当前最新报告期」的全部数据，则整支跳过，不发起请求；
      - 否则仍发起一次请求，但只在本地过滤出「数据库中缺失的报告期」后才写入，
        实现只补抓缺失报告期、不重复写入已有数据。
    参数:
        delay:         每支股票调用之间的延时秒数（默认 0.3）
        skip_existing: 是否启用续传跳过（默认 True）；设为 False 可强制全量重新抓取
    返回:
        DataFrame，包含本次新写入的现金流量表数据
    """
    print("=" * 50)
    print("fetch_stock_cashflow：逐支获取公司现金流量表（细粒度续传）...")
    print("=" * 50)

    # 1. 从数据库获取所有 ts_code（即 stocklist 表中的股票数量）
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]

    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()

    # 2. 预加载已有的 (ts_code -> {end_date})，用于判断缺失报告期
    existing_map: dict = {}
    if skip_existing:
        with get_session() as session:
            rows = session.query(
                StockCashflow.ts_code, StockCashflow.end_date
            ).all()
        for code, d in rows:
            ed = d if isinstance(d, str) else str(d)
            existing_map.setdefault(code, set()).add(ed)

    # 当前最新报告期（用于判断某股票是否已「追平」到最新）
    latest_period = max(_generate_report_periods(date.today()))

    print(f"共 {total} 只股票，逐支获取（细粒度续传）\n")

    all_dfs = []          # 收集本次新写入记录，用于最终返回
    batch_dfs = []        # 收集待批量 upsert 的记录
    skipped = 0
    fetched = 0

    BATCH = 100

    def _flush(batch: list) -> None:
        if not batch:
            return
        chunk = pd.concat(batch, ignore_index=True)
        upsert_stock_cashflow(chunk)

    for idx, ts_code in enumerate(ts_codes, start=1):
        existing_periods = existing_map.get(ts_code, set())

        # 续传：若已拥有截至最新的全部报告期，则整支跳过，不发起请求
        if skip_existing and existing_periods and max(existing_periods) >= latest_period:
            skipped += 1
            print(f"[{idx}/{total}] 跳过 {ts_code}：报告期已更新至最新 {latest_period}")
            continue

        print(f"[{idx}/{total}] 正在获取 {ts_code} 的现金流量表 ...")

        try:
            df = _pro.cashflow(
                ts_code=ts_code,
                start_date=start_date,
                fields=(
                    "ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,end_type,"
                    "c_fr_sale_sg,recp_tax_rends,c_fr_oth_operate_a,c_inf_fr_operate_a,"
                    "c_paid_goods_s,c_paid_to_for_empl,c_paid_for_taxes,oth_cash_pay_oper_act,"
                    "st_cash_out_act,n_cashflow_act,c_disp_withdrwl_invest,n_recp_disp_fiolta,"
                    "stot_inflows_inv_act,c_pay_acq_const_fiolta,c_paid_invest,stot_out_inv_act,"
                    "n_cashflow_inv_act,stot_cash_in_fnc_act,stot_cashout_fnc_act,"
                    "n_cash_flows_fnc_act,n_incr_cash_cash_equ,c_cash_equ_end_period"
                )
            )
            if df is not None and not df.empty:
                # 细粒度续传：只保留数据库中缺失的报告期
                if skip_existing and existing_periods:
                    before = len(df)
                    df = df[~df["end_date"].astype(str).isin(existing_periods)]
                    if len(df) < before:
                        print(f"  ✓ 获取 {before} 条，其中 {before - len(df)} 条已存在，"
                              f"补抓 {len(df)} 条缺失报告期")
                    else:
                        print(f"  ✓ 获取 {len(df)} 条，均为缺失报告期")
                else:
                    print(f"  ✓ 获取 {len(df)} 条现金流量表记录")

                if not df.empty:
                    all_dfs.append(df)
                    batch_dfs.append(df)
                    fetched += 1
            else:
                print(f"  - 该股票无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        # 每 100 只股票批量 upsert 一次，便于观察与调试
        if idx % BATCH == 0:
            _flush(batch_dfs)
            batch_dfs = []
            print(f"  -- 已分批写入前 {idx} 只股票的数据 --")

        # 单支调用之间延时（最后一支不需要延时）
        if idx < total:
            time.sleep(delay)

    # 剩余批次 upsert
    _flush(batch_dfs)

    if not all_dfs:
        print("\n没有需要补抓的现金流量表数据。")
        return pd.DataFrame()

    # 汇总所有股票数据
    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：本次补抓 {len(result)} 条现金流量表记录"
          + (f"，跳过 {skipped} 只已追平至最新的股票" if skip_existing else "")
          + "，数据已全部写入数据库")

    return result


def fetch_stock_weekly(delay: float = 0.2, skip_existing: bool = True,
                      start_date: str = "20120101") -> pd.DataFrame:
    """
    逐支股票获取A股周K线（后复权 hfq）数据并写入数据库（细粒度断点续传）
    使用 Tushare pro_bar(freq='W', adj='hfq') 通用行情接口。
    从 stock_list 表读取所有 ts_code，按单支股票逐支调用，调用之间做适当延时。

    续传策略：
      - 若某股票已拥有「截至最近一个周五」的全部周线（已追平到最新周），则整支跳过，不发起请求；
      - 否则从「该股票已存的最大 trade_date」之后开始增量补抓（边界周会在本地被去重过滤），
        只写入数据库中缺失的周，避免重复写入已有数据。

    起始日期优先级：
      - 默认从 20120101 开始抓取（Tushare 免费/普通账号周K线一般自 2012 年起开放）；
      - 若调用时传入 start_date=REPORT_START_DATE，则从财报起始日期（默认 19900101）开始；
      - 若传入任意其它日期字符串（如 "20050101"），则按该日期开始。

    参数:
        delay:         每支股票调用之间的延时秒数（默认 0.3）
        skip_existing: 是否启用续传跳过（默认 True）；设为 False 可强制全量重新抓取
        start_date:    全量抓取时的起始报告期（YYYYMMDD，默认 20120101）；
                       续传时仍从已存最大 trade_date 之后增量，不受此参数影响
    返回:
        DataFrame，包含本次新写入的周K线数据
    """
    print("=" * 50)
    print("fetch_stock_weekly：逐支获取周K线（后复权 hfq，细粒度续传）...")
    print("=" * 50)

    # 1. 从数据库获取所有 ts_code
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]

    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()

    # 2. 预加载已有的 (ts_code -> {trade_date})，用于判断缺失周
    existing_map: dict = {}
    if skip_existing:
        with get_session() as session:
            rows = session.query(
                StockWeekly.ts_code, StockWeekly.trade_date
            ).all()
        for code, d in rows:
            td = d if isinstance(d, str) else str(d)
            existing_map.setdefault(code, set()).add(td)

    # 最近一个周五（周线 trade_date = 当周最后一个交易日，近似取周五），用于判断已追平
    latest_week = _latest_week_trade_date(date.today())

    print(f"共 {total} 只股票，逐支获取（细粒度续传）\n")

    all_dfs = []
    batch_dfs = []
    skipped = 0
    fetched = 0

    BATCH = 100

    def _flush(batch: list) -> None:
        if not batch:
            return
        chunk = pd.concat(batch, ignore_index=True)
        upsert_stock_weekly(chunk)

    for idx, ts_code in enumerate(ts_codes, start=1):
        existing_weeks = existing_map.get(ts_code, set())

        # 续传：若已拥有截至最近周五的全部周线，则整支跳过
        if skip_existing and existing_weeks and max(existing_weeks) >= latest_week:
            skipped += 1
            print(f"[{idx}/{total}] 跳过 {ts_code}：周线已更新至最新周 {latest_week}")
            continue

        # 增量起点：已有数据且启用续传，则从最大 trade_date 起（边界周本地去重过滤）；
        # 否则使用函数入参 start_date 作为全量起点（默认 20120101，可传 REPORT_START_DATE 或任意日期）
        if skip_existing and existing_weeks:
            query_start = max(existing_weeks)
        else:
            query_start = start_date
        end_date = date.today().strftime("%Y%m%d")

        print(f"[{idx}/{total}] 正在获取 {ts_code} 的周K线（{query_start} ~ {end_date}）...")

        try:
            df = ts.pro_bar(
                ts_code=ts_code,
                start_date=query_start,
                end_date=end_date,
                freq="W",
                asset="E",
                adj="hfq",
            )
            if df is not None and not df.empty:
                # pro_bar 默认按 trade_date 降序，回测需升序
                df = df.sort_values("trade_date").reset_index(drop=True)

                # 细粒度续传：只保留数据库中缺失的周（边界周去重过滤）
                if skip_existing and existing_weeks:
                    before = len(df)
                    df = df[~df["trade_date"].astype(str).isin(existing_weeks)]
                    if len(df) < before:
                        print(f"  ✓ 获取 {before} 条，其中 {before - len(df)} 条已存在，"
                              f"补抓 {len(df)} 条缺失周线")
                    else:
                        print(f"  ✓ 获取 {len(df)} 条，均为缺失周线")
                else:
                    print(f"  ✓ 获取 {len(df)} 条周K线记录")

                if not df.empty:
                    all_dfs.append(df)
                    batch_dfs.append(df)
                    fetched += 1
            else:
                print(f"  - 该股票无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        if idx % BATCH == 0:
            _flush(batch_dfs)
            batch_dfs = []
            print(f"  -- 已分批写入前 {idx} 只股票的数据 --")

        if idx < total:
            time.sleep(delay)

    _flush(batch_dfs)

    if not all_dfs:
        print("\n没有需要补抓的周K线数据。")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：本次补抓 {len(result)} 条周K线记录"
          + (f"，跳过 {skipped} 只已追平至最新周的股票" if skip_existing else "")
          + "，数据已全部写入数据库")

    return result


def fetch_stock_daily_basic(delay: float = 0.2, skip_existing: bool = True,
                            start_date: str = "20120101") -> pd.DataFrame:
    """
    逐支股票获取每日指标数据（daily_basic）并写入数据库。

    使用 Tushare daily_basic 接口（支持按 ts_code 查询，自带 ts_code 列）。
    从 stock_list 表读取所有 ts_code，按单支股票逐支调用，调用之间做适当延时。

    取数范围（逐股增量窗口）：
      - 每支股票的请求起点 = 该股已存最大 trade_date（从该日附近向前增量，边界日会被
        本地去重过滤）；对无历史记录的新股，回退为函数入参 start_date（默认 20120101）；
      - 若某股票已追平「最新开市日」（由交易日历判定），则整支跳过，不发起请求；
      - 请求结果仍会在本地按已存交易日过滤，仅写入缺失日，避免重复入库。

    分批策略（daily_basic 单次请求最大返回 6000 条）：
      - 若 start_date ~ 今天 的跨度过大，单股可能超过 6000 个交易日，
        则按日期窗口分段（每段 ≤ MAX_DAYS_PER_REQ 自然日，保守估算 ≤6000 交易日），
        循环请求并合并，防止接口单次超限报错。

    参数:
        delay:         每支股票调用之间的延时秒数（默认 0.2）
        skip_existing: 是否启用本地断点续传（默认 True）；
                       设为 False 则不做已存过滤，全量写入（仍按 start_date 起点）
        start_date:    请求起点（YYYYMMDD，默认 20120101）
    返回:
        DataFrame，包含本次新写入的每日指标数据
    """
    print("=" * 50)
    print("fetch_stock_daily_basic：逐支获取每日指标（daily_basic）...")
    print("=" * 50)

    # 1. 从数据库获取所有 ts_code
    with get_session() as session:
        ts_codes = [
            row[0] for row in session.query(StockList.ts_code).order_by(StockList.ts_code).all()
        ]

    total = len(ts_codes)
    if total == 0:
        print("暂无 ts_code 数据，请先执行 fetch_stock_list。")
        return pd.DataFrame()

    # 2. 预加载已有的 (ts_code -> {trade_date})，用于本地过滤已存交易日
    existing_map: dict = {}
    if skip_existing:
        with get_session() as session:
            rows = session.query(
                StockDailyBasic.ts_code, StockDailyBasic.trade_date
            ).all()
        for code, d in rows:
            td = d if isinstance(d, str) else str(d)
            existing_map.setdefault(code, set()).add(td)

    end_date = date.today().strftime("%Y%m%d")
    # daily_basic 单次请求上限 6000 行；以自然日窗口保守分段（6000 自然日≈16.4 年）
    MAX_DAYS_PER_REQ = 5800

    # 生成分段窗口（每段 [seg_start, seg_end] 均 YYYYMMDD 字符串）
    def _date_windows(start: str, end: str) -> list[tuple[str, str]]:
        s = datetime.strptime(start, "%Y%m%d").date()
        e = datetime.strptime(end, "%Y%m%d").date()
        windows = []
        cur = s
        while cur <= e:
            seg_end = min(cur + timedelta(days=MAX_DAYS_PER_REQ), e)
            windows.append((cur.strftime("%Y%m%d"), seg_end.strftime("%Y%m%d")))
            if seg_end >= e:
                break
            cur = seg_end + timedelta(days=1)
        return windows

    # 最新开市日：用于「已追平则整支跳过」的增量判断
    latest_open = _latest_open_trade_date()
    print(f"共 {total} 只股票，逐股增量请求（新股回退起点 {start_date}）~ {end_date}，"
          f"最新开市日 {latest_open}（每段 ≤{MAX_DAYS_PER_REQ} 自然日）\n")

    all_dfs = []
    batch_dfs = []
    fetched = 0
    written_rows = 0
    skipped = 0

    BATCH = 100

    def _flush(batch: list) -> None:
        if not batch:
            return
        chunk = pd.concat(batch, ignore_index=True)
        upsert_stock_daily_basic(chunk)

    for idx, ts_code in enumerate(ts_codes, start=1):
        existing_days = existing_map.get(ts_code, set())

        # 增量起点：优先从该股已存最大交易日附近增量；无历史的新股回退 start_date
        if skip_existing and existing_days:
            query_start = max(existing_days)
        else:
            query_start = start_date

        # 追平跳过：已拥有截至最新开市日的数据，则整支不发起请求
        if skip_existing and existing_days and max(existing_days) >= latest_open:
            skipped += 1
            print(f"[{idx}/{total}] 跳过 {ts_code}：每日指标已更新至最新 {latest_open}")
            continue

        windows = _date_windows(query_start, end_date)
        print(f"[{idx}/{total}] 正在获取 {ts_code} 的每日指标（{query_start} ~ {end_date}）...")

        try:
            stock_frames = []
            for seg_start, seg_end in windows:
                seg = _pro.daily_basic(
                    ts_code=ts_code,
                    start_date=seg_start,
                    end_date=seg_end,
                )
                if seg is not None and not seg.empty:
                    stock_frames.append(seg)
                time.sleep(delay)
            if stock_frames:
                df = pd.concat(stock_frames, ignore_index=True)
            else:
                df = pd.DataFrame()

            if df is not None and not df.empty:
                # 本地过滤：仅保留缺失交易日（边界日去重过滤，避免重复入库）
                if skip_existing and existing_days:
                    before = len(df)
                    df = df[~df["trade_date"].astype(str).isin(existing_days)]
                    if len(df) < before:
                        print(f"  ✓ 获取 {before} 条，其中 {before - len(df)} 条已存在，"
                              f"补抓 {len(df)} 条缺失日")
                    else:
                        print(f"  ✓ 获取 {len(df)} 条，均为缺失日")
                else:
                    print(f"  ✓ 获取 {len(df)} 条每日指标记录")

                if not df.empty:
                    all_dfs.append(df)
                    batch_dfs.append(df)
                    fetched += 1
                    written_rows += len(df)
            else:
                print(f"  - 该股票无数据或返回为空")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

        if idx % BATCH == 0:
            _flush(batch_dfs)
            batch_dfs = []
            print(f"  -- 已分批写入前 {idx} 只股票的数据 --")

        if idx < total:
            time.sleep(delay)

    _flush(batch_dfs)

    if not all_dfs:
        print(f"\n没有需要写入的每日指标数据"
              + (f"（跳过 {skipped} 只已追平至最新开市日的股票）" if skip_existing else "")
              + "。")
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    print(f"\n汇总：本次写入 {written_rows} 条每日指标记录"
          + (f"，跳过 {skipped} 只已追平至最新的股票" if skip_existing else "")
          + "，数据已全部写入数据库（表 daily_basic）")

    return result


# ========== 周线技术指标计算（自包含，不依赖 indicators.py） ==========

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算单只股票周K线的全部技术指标。
    输入：按 trade_date 升序的周K DataFrame，需包含 close / high / low 列。
    返回：原 df 追加 ma5/ma60/dif/dea/macd_bar/cci/boll_upper/boll_mid/boll_lower 列
          （注意：20周均线仅用于计算 BOLL 中轨，不单独存储）。
    说明：前导滚动窗口不足产生的 NaN 由入库环节的 _has_value 自动跳过（保持 NULL）。
    """
    df = df.copy()
    close = df["close"]

    # 移动均线（MA5 / MA60；MA20 仅用于 BOLL 中轨，不单独落库）
    df["ma5"] = close.rolling(window=5, min_periods=5).mean()
    df["ma60"] = close.rolling(window=60, min_periods=60).mean()

    # MACD（快12/慢26 EMA，信号9 EMA，adjust=False 保证稳定可复现）
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    df["dif"] = dif
    df["dea"] = dea
    df["macd_bar"] = 2.0 * (dif - dea)

    # CCI（14 周）
    # TP = (H + L + C) / 3；SMA = TP 的 14 周期均值；
    # MD = |TP - SMA| 的 14 周期均值；CCI = (TP - SMA) / (0.015 * MD)
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    cci_sma = tp.rolling(window=14, min_periods=14).mean()
    cci_md = (tp - cci_sma).abs().rolling(window=14, min_periods=14).mean()
    df["cci"] = (tp - cci_sma) / (0.015 * cci_md)

    # 布林带 BOLL（周期20，2倍标准差）
    mid = close.rolling(window=20, min_periods=20).mean()  # 中轨 = 20周均线
    std = close.rolling(window=20, min_periods=20).std(ddof=0)
    df["boll_mid"] = mid
    df["boll_upper"] = mid + 2.0 * std
    df["boll_lower"] = mid - 2.0 * std

    return df


def compute_stock_weekly_indicators(delay: float = 0.2, skip_existing: bool = True) -> pd.DataFrame:
    """
    基于 stock_weekly（后复权）一次性计算全市场周K线技术指标并入库（细粒度续传）。
    性能优化：一次性 query(StockWeekly).all() 拉取全部周K后按 ts_code groupby，
    避免逐股多次查询（内存换效率，全市场约 350 万行可接受）。

    续传策略：
      - 若某只股票已拥有截至最近周五的全部指标（已追平到最新周），则整支跳过；
      - 否则读取该股票完整周K历史计算全部指标，仅 upsert 数据库中缺失的周
        （前导滚动窗口不足产生的 NaN 经 _has_value 跳过，保持 NULL）。

    参数:
        delay:         每批 flush 后的延时秒数（默认 0.2，主要缓解写库压力）
        skip_existing: 是否启用续传跳过（默认 True）；设为 False 可强制全量重算
    返回:
        DataFrame，包含本次新写入的指标数据
    """
    print("=" * 50)
    print("compute_stock_weekly_indicators：计算全市场周K线技术指标（细粒度续传）...")
    print("=" * 50)

    # 1. 一次性拉取全部周K行情
    with get_session() as session:
        rows = session.query(StockWeekly).all()

    if not rows:
        print("暂无周K线数据，请先执行 fetch_stock_weekly。")
        return pd.DataFrame()

    # 2. 组装为 DataFrame 并按 ts_code 分组（保持 trade_date 升序）
    all_df = pd.DataFrame([{
        "ts_code": r.ts_code,
        "trade_date": str(r.trade_date),
        "close": r.close,
        "high": r.high,
        "low": r.low,
    } for r in rows])
    all_df = all_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    # 3. 预加载已有的 (ts_code -> {trade_date})，用于判断缺失周
    existing_map: dict = {}
    if skip_existing:
        with get_session() as session:
            erows = session.query(
                StockWeeklyIndicator.ts_code, StockWeeklyIndicator.trade_date
            ).all()
        for code, d in erows:
            td = d if isinstance(d, str) else str(d)
            existing_map.setdefault(code, set()).add(td)

    # 最近一个周五（周线 trade_date = 当周最后一个交易日，近似取周五），用于判断已追平
    latest_week = _latest_week_trade_date(date.today())

    # 4. 按股票分组计算 + 续传过滤 + 分批入库
    groups = list(all_df.groupby("ts_code"))
    total = len(groups)
    print(f"共 {total} 只股票，分组计算（一次性加载后 groupby）\n")

    BATCH = 100
    batch_dfs = []
    skipped = 0
    computed = 0
    all_written = []

    def _flush(batch: list) -> None:
        if not batch:
            return
        chunk = pd.concat(batch, ignore_index=True)
        upsert_stock_weekly_indicator(chunk)

    for idx, (ts_code, g) in enumerate(groups, start=1):
        g = g.sort_values("trade_date").reset_index(drop=True)
        existing_weeks = existing_map.get(ts_code, set())

        # 续传：若已拥有截至最近周五的全部指标，则整支跳过
        if skip_existing and existing_weeks and max(existing_weeks) >= latest_week:
            skipped += 1
            continue

        # 计算该股票全部指标（需完整历史以正确计算滚动窗口）
        g = compute_indicators(g)

        # 细粒度续传：仅保留数据库中缺失的周（前导 NaN 仍由 _has_value 跳过）
        if skip_existing and existing_weeks:
            g = g[~g["trade_date"].astype(str).isin(existing_weeks)]

        if g.empty:
            continue

        g_out = g[[
            "ts_code", "trade_date",
            "ma5", "ma60",
            "dif", "dea", "macd_bar",
            "cci", "boll_upper", "boll_mid", "boll_lower",
        ]].copy()
        batch_dfs.append(g_out)
        all_written.append(g_out)
        computed += 1

        if idx % BATCH == 0:
            _flush(batch_dfs)
            batch_dfs = []
            if delay:
                time.sleep(delay)
            print(f"  -- 已分批计算并写入前 {idx} 只股票 --")

    # 末尾 flush
    _flush(batch_dfs)

    print(
        f"指标计算完成：处理 {computed} 只，跳过 {skipped} 只；"
        f"本次写入指标记录 {sum(len(d) for d in all_written)} 条"
    )
    if all_written:
        return pd.concat(all_written, ignore_index=True)
    return pd.DataFrame()


def fetch_basic_info(symbol):
    """获取股票基本信息"""
    pass


# ===================== 交易日历（trade_cal）数据获取 =====================
def fetch_trade_cal(exchange="SSE"):
    """
    获取指定交易所的交易日历（Tushare trade_cal 接口），并 upsert 写入数据库。

    特点:
        - 单次调用接口、无需请求时延、无需分批写入（数据量极小）
        - 复用 upsert_trade_cal 的"先查已存在主键 -> 合并 -> 写入"逻辑

    参数:
        exchange: 交易所代码，默认 'SSE'（上交所），作为全市场交易日基准。
    """
    print("=" * 50)
    print("测试12: 获取上交所(SSE)交易日历并入库...")
    print("=" * 50)
    df = _pro.trade_cal(exchange=exchange)
    if df is None or df.empty:
        print("交易日历：接口返回为空")
        return

    upsert_trade_cal(df)


# ===================== 数据新鲜度体检 =====================
def report_data_freshness() -> dict:
    """
    数据新鲜度体检：查询各原始表的最新日期，并与「最新开市日」对比后打印。

    返回 dict：{表名: {"latest": 最新日期, "stale": 是否落后于最新开市日}}。
    仅对交易类表（trade_cal / stock_daily_basic / stock_weekly /
    stock_weekly_indicator）判定 stale；财报类表按报告期存储，不做 stale 判定。
    """
    latest_open = _latest_open_trade_date()
    print("=" * 60)
    print("数据新鲜度体检")
    print("=" * 60)
    print(f"最新开市日（交易日历）：{latest_open}\n")

    checks = [
        ("trade_cal", lambda s: s.query(TradeCal.cal_date)
            .filter(TradeCal.is_open == "1",
                    TradeCal.cal_date <= date.today().strftime("%Y%m%d"))
            .order_by(TradeCal.cal_date.desc()).first(), True),
        ("stock_daily_basic", lambda s: s.query(StockDailyBasic.trade_date)
            .filter(StockDailyBasic.trade_date.isnot(None))
            .order_by(StockDailyBasic.trade_date.desc()).first(), True),
        ("stock_weekly", lambda s: s.query(StockWeekly.trade_date)
            .filter(StockWeekly.trade_date.isnot(None))
            .order_by(StockWeekly.trade_date.desc()).first(), True),
        ("stock_weekly_indicator", lambda s: s.query(StockWeeklyIndicator.trade_date)
            .filter(StockWeeklyIndicator.trade_date.isnot(None))
            .order_by(StockWeeklyIndicator.trade_date.desc()).first(), True),
        ("stock_fina_indicator", lambda s: s.query(StockFinaIndicator.end_date)
            .filter(StockFinaIndicator.end_date.isnot(None))
            .order_by(StockFinaIndicator.end_date.desc()).first(), False),
        ("stock_balancesheet", lambda s: s.query(StockBalancesheet.end_date)
            .filter(StockBalancesheet.end_date.isnot(None))
            .order_by(StockBalancesheet.end_date.desc()).first(), False),
        ("stock_income", lambda s: s.query(StockIncome.end_date)
            .filter(StockIncome.end_date.isnot(None))
            .order_by(StockIncome.end_date.desc()).first(), False),
        ("stock_cashflow", lambda s: s.query(StockCashflow.end_date)
            .filter(StockCashflow.end_date.isnot(None))
            .order_by(StockCashflow.end_date.desc()).first(), False),
    ]

    result = {}
    for name, query, is_trade in checks:
        try:
            with get_session() as session:
                row = query(session)
            latest = row[0] if row and row[0] is not None else None
        except Exception as e:
            latest = None
            result[name] = {"latest": None, "stale": False}
            print(f"  - {name:<24} 查询失败：{e}")
            continue

        stale = bool(is_trade and latest is not None and str(latest) < latest_open)
        result[name] = {"latest": latest, "stale": stale}
        tail = ""
        if is_trade:
            tail = "  [落后于最新开市日]" if stale else "  [已追平]"
        print(f"  - {name:<24} 最新: {latest}{tail}")
    print("=" * 60)
    return result


# ===================== 每周动态更新入口 =====================
def _print_update_summary(summary: dict) -> None:
    """打印 update_weekly 的分步汇总（状态 / 耗时 / 写入行数）。"""
    print("\n" + "=" * 60)
    print("每周动态更新 · 汇总")
    print("=" * 60)
    print(f"{'步骤':<38}{'状态':<8}{'耗时(s)':<10}{'写入行数'}")
    print("-" * 60)
    for name, info in summary.items():
        if name.startswith("_"):
            continue
        status = "OK" if info.get("ok") else "FAIL"
        rows = info.get("rows")
        rows = rows if rows is not None else "-"
        print(f"{name:<38}{status:<8}{info.get('elapsed', '-'):<10}{rows}")
    print("-" * 60)
    print(f"财报类是否轮询：{'是' if summary.get('_reports_included') else '否'}")
    print("=" * 60)


def update_weekly(delay: float = WEEKLY_UPDATE_DELAY,
                  include_reports: bool | None = None) -> dict:
    """
    每周动态更新：按依赖顺序增量补齐「因子计算所必需的原始数据」。

    步骤（顺序敏感，trade_cal 必须最先更新）：
      1. trade_cal                —— 交易日历（最新交易日基准）
      2. stock_list               —— 股票清单（新股上市/退市）
      3. stock_daily_basic        —— 每日指标（按各股已存最大交易日增量）
      4. stock_weekly             —— 周K行情（后复权，逐股增量）
      5. stock_weekly_indicator   —— 周K技术指标（派生表，仅补缺失周）
      6. 财报类（仅披露高峰期）    —— fina_indicator 及占位字段回填 +
                                     资产负债表 / 利润表 / 现金流量表

    说明：
      - 只更新原始数据，**不触发因子重算**；
      - 每步独立 try/except，单步失败仅记录并继续（各表相互独立）；
      - include_reports=None 时按当前月份自动判定是否轮询财报类，
        传 True/False 可强制包含/跳过；
      - 结束时打印数据新鲜度体检与分步汇总。

    参数:
        delay:           逐支请求的统一时延（秒），默认取 config.WEEKLY_UPDATE_DELAY
        include_reports: 是否轮询财报类数据；None 表示按披露高峰期自动判定

    返回:
        dict: {step_name: {"ok": bool, "elapsed": float, "rows": int|None, "note": str}}
    """
    print("\n" + "#" * 60)
    print("# 每周动态更新 start")
    print("#" * 60)

    # 0) 确保表结构存在
    init_db()

    summary: dict = {}

    def _run(name: str, fn, note: str = "") -> None:
        tag = f"（{note}）" if note else ""
        print("\n" + "=" * 60)
        print(f"[update_weekly] {name}{tag}")
        print("=" * 60)
        t0 = time.time()
        try:
            out = fn()
            rows = len(out) if out is not None and hasattr(out, "__len__") else None
            summary[name] = {"ok": True, "elapsed": round(time.time() - t0, 2),
                             "rows": rows, "note": note}
        except Exception as e:
            note_txt = f"{note} | 失败: {e}" if note else f"失败: {e}"
            summary[name] = {"ok": False, "elapsed": round(time.time() - t0, 2),
                             "rows": None, "note": note_txt}
            print(f"[update_weekly] {name} 失败（已跳过，继续后续步骤）：{e}")

    # 1) 交易日历（必须最先更新，作为最新交易日基准）
    _run("fetch_trade_cal", lambda: fetch_trade_cal("SSE"), note="最新交易日基准")
    # 2) 股票清单（捕捉新股上市 / 退市）
    _run("fetch_stock_list", fetch_stock_list, note="新股/退市")
    # 3) 每日指标（逐股增量，最耗时但已优化）
    _run("fetch_stock_daily_basic",
         lambda: fetch_stock_daily_basic(delay=delay, skip_existing=True,
                                         start_date=WEEKLY_UPDATE_START_DATE),
         note="逐股增量")
    # 4) 周K行情（后复权）
    _run("fetch_stock_weekly",
         lambda: fetch_stock_weekly(delay=delay, skip_existing=True),
         note="后复权周K增量")
    # 5) 周K技术指标（派生自 stock_weekly）
    _run("compute_stock_weekly_indicators",
         lambda: compute_stock_weekly_indicators(delay=delay, skip_existing=True),
         note="派生指标")

    # 6) 财报类（仅披露高峰期轮询）
    if include_reports is None:
        include_reports = _is_disclosure_peak()
    summary["_reports_included"] = bool(include_reports)
    if include_reports:
        _run("fetch_stock_fina_indicator",
             lambda: fetch_stock_fina_indicator(delay=delay, skip_existing=True))
        _run("fetch_stock_fina_indicator_backfill",
             lambda: fetch_stock_fina_indicator_backfill(batch_size=100),
             note="占位字段回填")
        _run("fetch_stock_balancesheet",
             lambda: fetch_stock_balancesheet(delay=delay, skip_existing=True))
        _run("fetch_stock_income",
             lambda: fetch_stock_income(delay=delay, skip_existing=True))
        _run("fetch_stock_cashflow",
             lambda: fetch_stock_cashflow(delay=delay, skip_existing=True))
    else:
        print("\n[update_weekly] 当前非财报披露高峰期，跳过财报类数据轮询"
              "（如需强制，请传 include_reports=True）。")

    # 7) 新鲜度体检 + 分步汇总
    report_data_freshness()
    _print_update_summary(summary)

    print("#" * 60)
    print("# 每周动态更新 end")
    print("#" * 60 + "\n")
    return summary


if __name__ == "__main__":
    from database import init_db
    
    # 初始化数据库（确保 stock_managers 等新表已创建）
    init_db()
    print("数据库初始化完成\n")

    # ========== 每周动态更新（增量补齐因子计算所必需的原始数据）==========
    update_weekly()

    # ========== 历史参考：旧测试块（保留备查，不再执行）==========
    '''
    # ---- 测试1: Tushare 获取股票清单 ----
    df = fetch_stock_list()
    if not df.empty:
        print(f"成功获取并写入 {len(df)} 条股票记录")
    else:
        print("获取股票清单失败（可能频率超限，1小时后重试）")

    # ---- 测试2: 批量获取公司高管数据 ----
    df_managers = fetch_stock_managers(batch_size=50, delay=1.0)
    if not df_managers.empty:
        print(f"\n成功获取并写入 {len(df_managers)} 条高管记录")
        print(f"数据列: {list(df_managers.columns)}")
        print(f"前5条记录预览:\n{df_managers.head()}")
    else:
        print("获取高管数据失败（可能频率超限，1小时后重试）")

    # ---- 测试3: 批量获取上市公司基本信息 ----
    df_company = fetch_stock_company(batch_size=1000, delay=1.0)
    if not df_company.empty:
        print(f"\n成功获取并写入 {len(df_company)} 条公司信息")
        print(f"数据列: {list(df_company.columns)}")
        print(f"前5条记录预览:\n{df_company.head()}")
    else:
        print("获取公司信息失败（可能频率超限，1小时后重试）")

    # ---- 测试4: 批量获取资产负债表 ----
    df_bs = fetch_stock_balancesheet(delay=0.3)
    if not df_bs.empty:
        print(f"\n成功获取并写入 {len(df_bs)} 条资产负债表记录")
        print(f"数据列: {list(df_bs.columns)}")
        print(f"前5条记录预览:\n{df_bs.head()}")
    else:
        print("获取资产负债表失败（可能频率超限，1小时后重试）")
    
    # ---- 测试5: 批量获取利润表 ----
    df_inc = fetch_stock_income(delay=0.3)
    if not df_inc.empty:
        print(f"\n成功获取并写入 {len(df_inc)} 条利润表记录")
        print(f"数据列: {list(df_inc.columns)}")
        print(f"前5条记录预览:\n{df_inc.head()}")
    else:
        print("获取利润表失败（可能频率超限，1小时后重试）")

    # ---- 测试6: 批量获取现金流量表 ----
    df_cf = fetch_stock_cashflow(delay=0.3)
    if not df_cf.empty:
        print(f"\n成功获取并写入 {len(df_cf)} 条现金流量表记录")
        print(f"数据列: {list(df_cf.columns)}")
        print(f"前5条记录预览:\n{df_cf.head()}")
    else:
        print("获取现金流量表失败（可能频率超限，1小时后重试）")
    
    # ---- 测试7: 批量获取公司财务指标（fina_indicator）----
    df_fina = fetch_stock_fina_indicator(delay=0.3)
    if not df_fina.empty:
        print(f"\n成功获取并写入 {len(df_fina)} 条财务指标记录")
        print(f"数据列: {list(df_fina.columns)}")
        print(f"前5条记录预览:\n{df_fina.head()}")
    else:
        print("获取财务指标失败（可能频率超限，1小时后重试）")
    # ---- 测试8: 补充计算并回填 StockFinaIndicator 第三类字段 ----
    df_fina_backfill = fetch_stock_fina_indicator_backfill(batch_size=100)
    if not df_fina_backfill.empty:
        print(f"\n成功计算并回填 {len(df_fina_backfill)} 条第三类字段记录")
        print(f"数据列: {list(df_fina_backfill.columns)}")
        print(f"前5条记录预览:\n{df_fina_backfill.head()}")
    else:
        print("没有需要回填的第三类字段数据")
    # ---- 测试9: 批量获取周K线（后复权 hfq）----
    df_weekly = fetch_stock_weekly(delay=0.3)
    if not df_weekly.empty:
        print(f"\n成功获取并写入 {len(df_weekly)} 条周K线记录")
        print(f"数据列: {list(df_weekly.columns)}")
        print(f"前5条记录预览:\n{df_weekly.head()}")
    else:
        print("获取周K线失败（可能频率超限，1小时后重试）")
    
    # ---- 测试10: 计算全市场周K线技术指标并入库 ----
    df_weekly_backfill = compute_stock_weekly_indicators()
    if not df_weekly_backfill.empty:
        print(f"\n成功计算并写入 {len(df_weekly_backfill)} 条周K技术指标记录")
        print(f"数据列: {list(df_weekly_backfill.columns)}")
        print(f"前5条记录预览:\n{df_weekly_backfill.head()}")
    else:
        print("周K技术指标计算完成（无新增记录，可能已是最新）")
    
    # ---- 测试11: 逐支获取每日指标（daily_basic）并入库 ----
    df_daily_basic = fetch_stock_daily_basic(delay=0.2, skip_existing=True, start_date="20120101")
    if not df_daily_basic.empty:
        print(f"\n成功获取并写入 {len(df_daily_basic)} 条每日指标记录")
        print(f"数据列: {list(df_daily_basic.columns)}")
        print(f"前5条记录预览:\n{df_daily_basic.head()}")
    else:
        print("获取每日指标失败或无新增数据（可能频率超限，1小时后重试，或已是最新）")
    
    # ---- 测试12: 获取上交所(SSE)交易日历并入库 ----
    try:
        fetch_trade_cal("SSE")
        print(f"测试12，获取交易日历成功")
    except Exception as e:
        print(f"测试12，获取交易日历失败: {e}")
    '''
