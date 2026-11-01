# -*- coding: utf-8 -*-
"""
因子计算模块
  - 提供 FACTOR_REGISTRY 因子字典注册表（因子元数据，供上层计算逻辑参考）。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func

from database import (
    StockFactor,
    StockDailyBasic,
    StockWeeklyIndicator,
    upsert_stock_factor,
    get_all_date,
    get_all_stocks,
    get_session,
    get_daily_basic_by_trade_date,
    get_weekly_by_trade_date,
    get_weekly_indicator_by_trade_date,
    get_fina_indicator_by_ann_date,
    get_cashflow_by_ann_date,
    get_balancesheet_by_ann_date,
    get_income_by_ann_date,
)

# ======================================================================
# 1. 截面归一化函数（纯计算，输入 Series -> 输出同索引 Series，值域 [-100,100]）
# ======================================================================

def rank_to_score(x: pd.Series, alpha: float = 0.0) -> pd.Series:
    """
    截面排名百分比映射到 [-100, 100]。

    将输入 Series 在同截面内按 rank(pct=True) 转化为百分比，再按对称截断区间
    [alpha, 1 - alpha] 重映射到 [0, 1]（超出截断区间的尾部被 clip 到 0/1，对应
    触达 -100/+100 极值），最后做线性映射 (pct * 2 - 1) * 100，使得分可触达
    [-100, 100] 极值。排名越高（值越大）得分越高；缺失值保持 NaN。

    alpha 控制尾部截断比例：下限 lo = pct.quantile(alpha)，上限 hi = pct.quantile(1 - alpha)；
    默认 alpha=0.0 对应原全量范围（lo=min、hi=max），不传则行为与旧实现一致。
    """
    pct = x.rank(pct=True, method="average")
    lo, hi = pct.quantile(alpha), pct.quantile(1 - alpha)
    if lo == hi:
        # 退化（有效值全相等 / 整组缺失）：仅对"有值行"给 0，缺失行保持 NaN，
        # 避免把整组（含无数据的股票）都填成 0.0 而凭空造出因子值。
        return pd.Series(0.0, index=x.index).where(x.notna())
    pct = ((pct - lo) / (hi - lo)).clip(0, 1)
    return (pct * 2 - 1) * 100


def tanh_to_score(x: pd.Series) -> pd.Series:
    """
    tanh 映射到 [-100, 100]。

    先对原始值做标准化（减均值除标准差，std 为 0 置 0），再经 tanh 压到 [-1, 1]，
    最后 *100 映射到 [-100, 100]。对极端值较鲁棒、过渡平滑。
    缺失值保持 NaN。
    """
    mean = x.mean()
    std = x.std(ddof=0)
    if std is None or std == 0 or pd.isna(std):
        scaled = pd.Series(0.0, index=x.index)
    else:
        scaled = (x - mean) / std
    return np.tanh(scaled) * 100


def robust_z_to_score(x: pd.Series, alpha: float = 0.01) -> pd.Series:
    """
    稳健 z-score（中位数/MAD 标准化）后按对称分位数**分别**重映射到 [-100, 100]。

    采用正负尾部各自独立缩放（正向用 hi、负向用 |lo|），而非取单侧最大绝对值做
    单边缩放，可避免对市值/资产/收入等右偏数据造成的左尾压缩问题（否则最高易达
    +100、最低只到约 -70），保证极端大/小值在两侧对称触达 ±100。

    alpha 控制尾部截断比例：下限 lo = z.quantile(alpha)，上限 hi = z.quantile(1 - alpha)，
    即对称截断区间 [alpha, 1 - alpha]；默认 alpha=0.01 对应原写死的 [1%, 99%]，不传则
    行为与旧实现一致。

    步骤：
      0. 先把 ±inf 置为 NaN（见下"防御性处理"）；
      1. med = x.median()，mad = (x - med).abs().median()；
      2. z = (x - med) / (1.4826 * mad)；mad 为 0（或整组缺失）时，
         "有值行"记为 0、缺失行保持 NaN（不做整组填充）；
      3. lo, hi = z.quantile(alpha), z.quantile(1 - alpha)；
      4. 正向 clip(0, hi)/hi*100，负向 clip(lo, 0)/(-lo)*100，二者相加。
    缺失值保持 NaN。

    防御性处理：输入中的 ±inf 会先被置为 NaN 再参与统计。否则当 ±inf 的占比达到
    alpha（默认 1%）时，`Series.quantile` 的线性插值会出现 (-inf) - (-inf) = NaN，
    使 lo/hi 为 NaN，进而触发下面的兜底分支把**整列置 0**（曾导致 size 因子值域由
    ±100 塌陷为 ±75）。置 NaN 后该行按缺失处理，不再污染分位数。
    """
    x = x.replace([np.inf, -np.inf], np.nan)
    med = x.median()
    mad = (x - med).abs().median()
    if mad == 0 or pd.isna(mad):
        # 退化（有效值全相等 / 整组缺失）：仅对"有值行"给 0，缺失行保持 NaN，
        # 否则整列全 NaN 时会把全市场股票都填成 0.0，凭空造出因子值。
        return pd.Series(0.0, index=x.index).where(x.notna())
    z = (x - med) / (1.4826 * mad)
    lo, hi = z.quantile(alpha), z.quantile(1 - alpha)
    if pd.isna(lo) or pd.isna(hi):
        return pd.Series(0.0, index=x.index).where(x.notna())
    hi = hi if hi != 0 else 1.0
    lo = lo if lo != 0 else -1.0
    pos = (z.clip(0, hi) / hi * 100).clip(0, 100)
    neg = (z.clip(lo, 0) / (-lo) * 100).clip(-100, 0)
    return pos + neg


# ======================================================================
# 2. 因子字典注册表
# ======================================================================

# 每个元素：(factor_name, factor_field, factor_type, factor_source)
# factor_type: 规模、估值、波动率、反转、盈利、成长、现金
# factor_field 为计算因子所需的对应底层数据表的列名；factor_source 为来源表。
# 注：部分反转因子的 factor_field 为逻辑含义占位（如 "ma5 boll_mid ma60" 表示多字段合成），待具体实现时校准。
FACTOR_REGISTRY = [
    # 规模因子
    ("总市值", "total_mv", "规模", "stock_daily_basic"),
    ("流通市值", "circ_mv", "规模", "stock_daily_basic"),
    ("总收入", "total_revenue", "规模", "stock_fina_indicator"),
    ("营业利润", "operate_profit", "规模", "stock_fina_indicator"),

    # 估值因子（来源 stock_daily_basic）
    ("股息率因子", "dv_ttm", "估值", "stock_daily_basic"),
    ("市盈率因子", "pe_ttm", "估值", "stock_daily_basic"),
    ("市净率因子", "pb", "估值", "stock_daily_basic"),
    ("市销率因子", "ps_ttm", "估值", "stock_daily_basic"),

    # 波动率因子（来源 stock_daily_basic / stock_weekly）
    ("周换手率因子", "turnover_rate_f", "波动率", "stock_daily_basic"),
    ("周涨跌幅因子", "pct_chg", "波动率", "stock_weekly"),
    ("周成交额因子", "amount", "波动率", "stock_weekly"),

    # 反转因子（来源 stock_weekly_indicator；乖离率 / BOLL %B 额外需 stock_weekly.close）
    ("60周均线乖离率", "ma60", "反转", "stock_weekly_indicator"),
    ("MACD深度(水下/水上)", "macd_bar", "反转", "stock_weekly_indicator"),
    ("CCI超卖", "cci", "反转", "stock_weekly_indicator"),
    ("BOLL轨道位置", "boll_lower", "反转", "stock_weekly_indicator"),

    # 盈利因子（来源 stock_fina_indicator）
    ("年化净资产收益率", "roe_yearly", "盈利", "stock_fina_indicator"),
    ("销售毛利率（单季度）", "q_gsprofit_margin", "盈利", "stock_fina_indicator"),
    ("销售净利率", "netprofit_margin", "盈利", "stock_fina_indicator"),
    ("总资产周转率", "assets_turn", "盈利", "stock_fina_indicator"),
    ("应付/应收款", "ap_to_ar", "盈利", "stock_fina_indicator"),

    # 成长因子（来源 stock_fina_indicator）
    ("总收入同比", "tr_yoy", "成长", "stock_fina_indicator"),
    ("营业利润同比", "op_yoy", "成长", "stock_fina_indicator"),
    ("经营现金净流量同比", "ocf_yoy", "成长", "stock_fina_indicator"),

    # 现金因子（来源 stock_fina_indicator）
    ("现金收入比", "salescash_to_or", "现金", "stock_fina_indicator"),
    ("净现金利润比", "opincome_of_ebt", "现金", "stock_fina_indicator"),
    ("带息债务/全部投入资本", "int_to_talcap", "现金", "stock_fina_indicator"),
]


# ======================================================================
# 3. 因子计算框架（仅搭骨架，暂不实现具体计算逻辑）
# ======================================================================
# 约定：
#   - 每个 cal_*_factor 接收截面 DataFrame（df: pd.DataFrame），返回 pd.Series（同索引）。
#   - 子函数内部应先基于底层字段（见 FACTOR_REGISTRY 的 factor_field / factor_source）
#     计算原始值，再调用截面归一化函数（rank_to_score / tanh_to_score /
#     robust_z_to_score，值域 [-100, 100]）得到最终分数。
#   - 框架阶段函数体以 ... 占位，后续逐项填充计算逻辑即可，不影响导入与聚合调用。

def cal_size_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """
    规模因子（自包含流程函数，逐交易日计算）。

    逐交易日截面计算规模因子并落库到 StockFactor.size：
      1. 获取全部交易日序列并升序排序；
      2. 获取全部股票清单（代码 / 名称 / 行业）；
      3. 遍历每个交易日的截面：
         - StockDailyBasic 取 total_mv / circ_mv；
         - stock_fina_indicator 取最新一期年报的 total_revenue / operate_profit；
         - 四项取以 10 为底对数（<= 0 的值先置 NaN，避免 -inf 污染标准化）：
             总市值、总收入       -> 全市场统一稳健标准化；
             流通市值、营业利润   -> 按行业分组、行业内比较后排名百分比归一化
                                   （rank_to_score，alpha=0.1）；
         - 加权合成 size = 4*总市值 + 1*流通市值 + 2*总收入 + 1*营业利润
           （权重和 8，缺项按有效权重归一），结果向下取整为 int 落库。
    start_date / end_date 限定计算范围（如某周），默认 None 时为全量。
    """
    # ---- 1. 交易日序列（升序）----
    trade_date = get_all_date()
    if trade_date is not None and (
        len(trade_date) < 2 or trade_date != sorted(trade_date)
    ):
        trade_date = sorted(trade_date)
    # 按日期范围过滤（增量计算支持）
    if start_date is not None or end_date is not None:
        trade_date = [
            t for t in trade_date
            if (start_date is None or t >= start_date)
            and (end_date is None or t <= end_date)
        ]

    # ---- 2. 股票清单：ts_code -> (name, industry) ----
    stocks = get_all_stocks()
    stock_info = {
        s.ts_code: (s.name, s.industry if s.industry else "未知")
        for s in stocks
    }

    weights = {
        "total_mv": 4,
        "circ_mv": 1,
        "total_revenue": 2,
        "operate_profit": 1,
    }

    for td in trade_date:
        # ---- 3.1 当日市值截面 ----
        mv_df = get_daily_basic_by_trade_date(trade_date=td)
        if mv_df is None or mv_df.empty:
            continue
        mv_df = mv_df[mv_df["ts_code"].isin(stock_info)].copy()

        # 兜底列存在性
        for col in ("total_mv", "circ_mv"):
            if col not in mv_df.columns:
                mv_df[col] = np.nan

        # ---- 3.2 当日及之前最新一期财务截面 ----
        try:
            td_date = datetime.strptime(td, "%Y%m%d")
            start_ann = (td_date.replace(year=td_date.year - 1)).strftime("%Y%m%d")
        except Exception:
            start_ann = None
        fina_df = get_fina_indicator_by_ann_date(
            start_ann_date=start_ann, end_ann_date=td
        )
        if fina_df is not None and not fina_df.empty:
            for col in ("total_revenue", "operate_profit", "end_date"):
                if col not in fina_df.columns:
                    fina_df[col] = np.nan
            fina_df = fina_df[
                fina_df["end_date"].astype(str).str.endswith("1231")
            ].copy()
            fina_df = (
                fina_df.sort_values("end_date")
                .groupby("ts_code", as_index=False)
                .tail(1)
            )
            fina_df = fina_df[fina_df["ts_code"].isin(stock_info)].copy()
        else:
            fina_df = pd.DataFrame(
                columns=["ts_code", "total_revenue", "operate_profit"]
            )

        # ---- 3.3 合并当日截面 + 行业 ----
        section = mv_df[["ts_code", "total_mv", "circ_mv"]].copy()
        section = section.merge(
            fina_df[["ts_code", "total_revenue", "operate_profit"]],
            on="ts_code",
            how="left",
        )
        section["name"] = section["ts_code"].map(lambda c: stock_info[c][0])
        section["industry"] = section["ts_code"].map(lambda c: stock_info[c][1])

        # ---- 3.4 对数变换（底数 10）----
        # 注意：total_revenue / operate_profit 可能为 0 或负值——log10(0) = -inf、
        # log10(负数) = NaN。必须先把 <=0 置 NaN，否则 -inf 会进入后续标准化，
        # 当其占比达到 alpha 时会使 robust_z_to_score 整列归零，进而把 size 的
        # 加权平均稀释（曾导致值域由 ±100 塌陷为 ±75）。
        # 口径与波动率因子对 amount 的处理保持一致：先取 log10，再 .where(> 0)。
        for col in (
            "total_mv",
            "circ_mv",
            "total_revenue",
            "operate_profit",
        ):
            raw = section[col].astype(float)
            with np.errstate(divide="ignore", invalid="ignore"):
                log_val = np.log10(raw)
            section[col + "_log"] = log_val.where(raw > 0)

        # ---- 3.5 稳健标准化 ----
        # 总市值 / 总收入：全市场统一标准化
        section["total_mv_score"] = robust_z_to_score(section["total_mv_log"])
        section["total_revenue_score"] = robust_z_to_score(section["total_revenue_log"])
        # 流通市值 / 营业利润：按行业分组、行业内比较后排名百分比归一化
        section["circ_mv_score"] = section.groupby("industry")["circ_mv_log"].transform(
            lambda s: rank_to_score(s, alpha=0.1)
        )
        section["operate_profit_score"] = section.groupby("industry")[
            "operate_profit_log"
        ].transform(lambda s: rank_to_score(s, alpha=0.1))

        # ---- 3.6 加权合成（缺项按有效权重归一）----
        score_cols = {
            "total_mv_score": "total_mv",
            "circ_mv_score": "circ_mv",
            "total_revenue_score": "total_revenue",
            "operate_profit_score": "operate_profit",
        }
        numerator = pd.Series(0.0, index=section.index)
        denom = pd.Series(0.0, index=section.index)
        for sc, base in score_cols.items():
            w = weights[base]
            valid = section[sc].notna()
            numerator = numerator + np.where(valid, section[sc] * w, 0.0)
            denom = denom + np.where(valid, w, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            size_raw = np.where(denom > 0, numerator / denom, np.nan)
        section["size"] = size_raw

        # 向下取整为 int（对齐 StockFactor.size 的 Integer 类型）
        section["size_int"] = section["size"].apply(
            lambda v: int(np.floor(v)) if pd.notna(v) else None
        )

        # ---- 3.7 组装落库 DataFrame ----
        out_df = pd.DataFrame(
            {
                "ts_code": section["ts_code"],
                "name": section["name"],
                "industry": section["industry"],
                "trade_date": td,
                "size": section["size_int"],
            }
        )
        out_df = out_df[out_df["size"].notna()]
        # 确保 size 为 python int（非 numpy int / float），避免 ORM 类型不匹配
        out_df["size"] = out_df["size"].astype(int)

        if out_df.empty:
            continue
        upsert_stock_factor(out_df)
        print(
            f"[cal_size_factor] trade_date={td} 写入规模因子 {len(out_df)} 条"
        )


def cal_valuation_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """
    估值因子（自包含流程函数，逐交易日计算）。

    逐交易日截面计算估值因子并落库到 StockFactor.valuation（四子项权重 2:2:1:1）：
      1. 获取全部交易日序列并升序排序；
      2. 获取全部股票清单（代码 / 名称 / 行业）；
      3. 遍历每个交易日的截面，查询 StockDailyBasic 的估值底数：
         - dv_ttm（股息率，权重2，不变）：不取倒数，50% 行业内稳健标准化
           + 50% 全市场稳健标准化（robust_z_to_score，alpha=0.1），兼顾行业相对与全市场绝对；
         - pe_ttm（市盈率，权重2）：先取倒数(1/x，非正值转 NaN，价值方向：
           低估值 -> 高分)，再减行业均值（行业中性化），最后全市场稳健标准化
           （robust_z_to_score，alpha=0.05）；
         - pb（市净率，权重1）：取倒数（价值方向），按行业分组、行业内排名
           百分比归一化（rank_to_score，alpha=0.1，行业中性化）；
         - ps_ttm（市销率，权重1）：取倒数（价值方向），按行业分组、行业内排名
           百分比归一化（rank_to_score，alpha=0.1，行业中性化）；
      4. 加权合成 valuation = 2*股息率 + 2*市盈率 + 1*市净率 + 1*市销率
         （权重和 6，缺项按有效权重归一），结果向下取整为 int 落库。
    start_date / end_date 限定计算范围（如某周），默认 None 时为全量。
    """
    # ---- 1. 交易日序列（升序）----
    trade_date = get_all_date()
    if trade_date is not None and (
        len(trade_date) < 2 or trade_date != sorted(trade_date)
    ):
        trade_date = sorted(trade_date)
    # 按日期范围过滤（增量计算支持）
    if start_date is not None or end_date is not None:
        trade_date = [
            t for t in trade_date
            if (start_date is None or t >= start_date)
            and (end_date is None or t <= end_date)
        ]

    # ---- 2. 股票清单：ts_code -> (name, industry) ----
    stocks = get_all_stocks()
    stock_info = {
        s.ts_code: (s.name, s.industry if s.industry else "未知")
        for s in stocks
    }

    weights = {
        "dv_ttm": 2,
        "pe_ttm": 1,
        "pb": 1,
        "ps_ttm": 1,
    }

    for td in trade_date:
        # ---- 3.1 当日估值截面 ----
        val_df = get_daily_basic_by_trade_date(trade_date=td)
        if val_df is None or val_df.empty:
            continue
        val_df = val_df[val_df["ts_code"].isin(stock_info)].copy()

        # 兜底列存在性
        for col in ("dv_ttm", "pe_ttm", "pb", "ps_ttm"):
            if col not in val_df.columns:
                val_df[col] = np.nan

        # ---- 3.2 倒数变换（pe / pb / ps_ttm 取 1/x，非正值转 NaN，价值方向）----
        # dv_ttm 不取倒数；pe_ttm / pb / ps_ttm 取倒数（低估 -> 高分，价值方向）
        inv_cols = ("pe_ttm", "pb", "ps_ttm")
        for col in inv_cols:
            with np.errstate(divide="ignore", invalid="ignore"):
                inv = np.where(
                    val_df[col].astype(float) > 0,
                    1.0 / val_df[col].astype(float),
                    np.nan,
                )
            val_df[col + "_inv"] = inv
        # 行业（用于落库）
        val_df["name"] = val_df["ts_code"].map(lambda c: stock_info[c][0])
        val_df["industry"] = val_df["ts_code"].map(lambda c: stock_info[c][1])

        # ---- 3.3 归一化 ----
        # dv_ttm：50% 行业内稳健标准化 + 50% 全市场稳健标准化（兼顾行业相对与全市场绝对）
        dv_ind = val_df.groupby("industry")["dv_ttm"].transform(
            lambda s: robust_z_to_score(s, alpha=0.05))
        dv_all = robust_z_to_score(val_df["dv_ttm"].astype(float), alpha=0.05)
        val_df["dv_ttm_score"] = 0.5 * dv_ind + 0.5 * dv_all
        # pe_ttm：取倒数(价值方向) -> 减行业均值(行业中性化) -> 全市场稳健标准化
        pe_inv = val_df["pe_ttm_inv"].astype(float)
        pe_centered = pe_inv - val_df.groupby("industry")["pe_ttm_inv"].transform("mean")
        val_df["pe_ttm_score"] = robust_z_to_score(pe_centered, alpha=0.05)
        # pb / ps_ttm：取倒数(价值方向) -> 按行业分组、行业内排名百分比归一化（行业中性化）
        val_df["pb_score"] = val_df.groupby("industry")["pb_inv"].transform(
            lambda s: rank_to_score(s, alpha=0.1))
        val_df["ps_ttm_score"] = val_df.groupby("industry")["ps_ttm_inv"].transform(
            lambda s: rank_to_score(s, alpha=0.1))

        # ---- 3.4 加权合成（缺项按有效权重归一）----
        score_cols = {
            "dv_ttm_score": "dv_ttm",
            "pe_ttm_score": "pe_ttm",
            "pb_score": "pb",
            "ps_ttm_score": "ps_ttm",
        }
        numerator = pd.Series(0.0, index=val_df.index)
        denom = pd.Series(0.0, index=val_df.index)
        for sc, base in score_cols.items():
            w = weights[base]
            valid = val_df[sc].notna()
            numerator = numerator + np.where(valid, val_df[sc] * w, 0.0)
            denom = denom + np.where(valid, w, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            valuation_raw = np.where(denom > 0, numerator / denom, np.nan)
        val_df["valuation"] = valuation_raw

        # 向下取整为 int（对齐 StockFactor.valuation 的 Integer 类型）
        val_df["valuation_int"] = val_df["valuation"].apply(
            lambda v: int(np.floor(v)) if pd.notna(v) else None
        )

        # ---- 3.5 组装落库 DataFrame ----
        out_df = pd.DataFrame(
            {
                "ts_code": val_df["ts_code"],
                "name": val_df["name"],
                "industry": val_df["industry"],
                "trade_date": td,
                "valuation": val_df["valuation_int"],
            }
        )
        # 仅保留有估值分的记录
        out_df = out_df[out_df["valuation"].notna()]
        if out_df.empty:
            continue
        out_df["valuation"] = out_df["valuation"].astype(int)
        upsert_stock_factor(out_df)
        print(
            f"[cal_valuation_factor] trade_date={td} 写入估值因子 {len(out_df)} 条"
        )


# ---- 波动率因子参数 ----
VOL_LOOKBACK_WEEKS = 4   # 取数窗口向前延展周数（覆盖 4 周累计换手率所需的前序窗口）


def cal_volatility_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """
    波动率因子（自包含流程函数，按周频窗口计算）。

    逐周频截面计算波动率因子并落库到 StockFactor.volility：
      1. 获取全市场「完整」交易日序列（已周频对齐，不裁剪），并在其上定位写入窗口
         [start_idx, end_idx]；窗口序号 _wk 与逐截面循环索引均锚定该完整序列，
         以保证 searchsorted 窗口编号与循环下标严格对齐；
      2. 获取全部股票清单（代码 / 名称 / 行业）；
      3. 取数窗口向前延展 VOL_LOOKBACK_WEEKS 周（补齐 4 周累计换手率所需的前序窗口），
         一次区间取数：
         - StockDailyBasic 换手率 turnover_rate_f（日频）；
         - StockWeekly 周频涨跌幅 pct_chg、成交额 amount；
      4. 用 searchsorted 预计算每个 (上一截面, 本截面] 窗口的累计换手率（周累计换手率），
         并基于各窗口累计值滚动 4 窗口求和得到 4 周累计换手率；首个截面因无前序数据跳过；
      5. 逐截面遍历，将股票横向比较、归一化后加权合成波动率因子：
         - 周累计换手率 turnover_1w：窗口 (上一截面, 本截面] 内日换手率之和，
           全市场 robust_z_to_score 反向（低换手高分）；
         - 4 周累计换手率 turnover_4w：截至本截面向前含当周连续 4 个周窗口的日换手率之和，
           全市场 robust_z_to_score 反向（低换手高分）；
         - 周涨跌幅 |pct_chg|：全市场 rank_to_score（alpha=0.1，取绝对值） 反向（低波高分）；
         - 周成交额 amount：先 log10（<=0 与 NaN 转 NaN）再全市场 robust_z_to_score 正向（高流动性高分）；
         - 方向：两份换手率、周涨跌幅(绝对值)均 ×(-1) 反向（低波动高分）；
           周成交额(log10 后) ×(+1) 正向（高成交额高分）；
         - 权重 turnover_1w:1 / turnover_4w:1 / pct_chg:1 / amount:1（总和4，缺项按有效权重归一），
           结果向下取整为 int 落库。
    start_date / end_date 限定「写入/输出」窗口（如某周），默认 None 时为全量；
    取数窗口会向前延展 VOL_LOOKBACK_WEEKS 周用于喂历史窗口，延展周仅参与计算、不落库。
    """
    # ---- 1. 交易日序列（升序，已周频对齐）----
    # 保留「完整」截面序列，不裁剪：searchsorted 生成的窗口序号 _wk 与逐截面循环索引
    # 必须锚定同一份序列，否则滚动窗口会与循环下标错位。
    trade_date = get_all_date()
    if trade_date is not None and (
        len(trade_date) < 2 or trade_date != sorted(trade_date)
    ):
        trade_date = sorted(trade_date)
    if not trade_date:
        return

    # 写入窗口 [start_idx, end_idx]：start_date / end_date 缺省时分别取首 / 末截面
    start_idx = 0
    end_idx = len(trade_date) - 1
    if start_date is not None:
        start_idx = next(
            (i for i, t in enumerate(trade_date) if t >= start_date),
            len(trade_date),
        )
    if end_date is not None:
        end_idx = max(
            (i for i, t in enumerate(trade_date) if t <= end_date),
            default=len(trade_date) - 1,
        )
    if start_idx >= len(trade_date) or start_idx > end_idx:
        print(
            f"[cal_volatility_factor] 窗口内无截面（start={start_date}, "
            f"end={end_date}），跳过"
        )
        return

    # 取数窗口向前延展 VOL_LOOKBACK_WEEKS 周：保证写入窗口首个截面的 turnover_1w
    # （需上一截面）与 turnover_4w（需向前 4 个周窗口）均有前序数据。
    lookback_idx = max(0, start_idx - VOL_LOOKBACK_WEEKS)
    q_start = trade_date[lookback_idx - 1] if lookback_idx > 0 else trade_date[0]
    q_end = trade_date[end_idx]

    # ---- 2. 股票清单：ts_code -> (name, industry) ----
    stocks = get_all_stocks()
    stock_info = {
        s.ts_code: (s.name, s.industry if s.industry else "未知")
        for s in stocks
    }

    # 3.1 日频换手率（用于周换乘累计）
    daily_turnover = get_daily_basic_by_trade_date(
        start_date=q_start, end_date=q_end,
        fields=["ts_code", "trade_date", "turnover_rate_f"],
    )
    if daily_turnover is not None and not daily_turnover.empty:
        if "turnover_rate_f" not in daily_turnover.columns:
            daily_turnover["turnover_rate_f"] = np.nan
        daily_turnover = daily_turnover[
            daily_turnover["ts_code"].isin(stock_info)
        ].copy()
    else:
        daily_turnover = pd.DataFrame(
            columns=["ts_code", "trade_date", "turnover_rate_f"]
        )

    # 3.2 周频涨跌幅 / 成交额
    weekly = get_weekly_by_trade_date(
        start_date=q_start, end_date=q_end,
        fields=["ts_code", "trade_date", "pct_chg", "amount"],
    )
    if weekly is not None and not weekly.empty:
        for col in ("pct_chg", "amount"):
            if col not in weekly.columns:
                weekly[col] = np.nan
        weekly = weekly[weekly["ts_code"].isin(stock_info)].copy()
    else:
        weekly = pd.DataFrame(
            columns=["ts_code", "trade_date", "pct_chg", "amount"]
        )

    # ---- 4. 预计算各 (上一截面, 本截面] 窗口的周换手率 ----
    # 把每个日频交易日映射到其所属窗口序号 i（满足 td_{i-1} < d <= td_i），
    # i 从 1 起算（i==0 表示早于首个截面，丢弃）；再按 (窗口序号, ts_code) 求和。
    # "YYYYMMDD" 为定长零填充字符串，字典序 == 时间序，可直接用 searchsorted。
    weekly_turnover_sum: dict[tuple, float] = {}
    weekly_turnover_sum_4w: dict[tuple, float] = {}
    if not daily_turnover.empty:
        td_arr = np.asarray(trade_date, dtype=object)
        d_dates = daily_turnover["trade_date"].values.astype(object)
        # side="left"：d == td[k] 或 td[k-1] < d < td[k] 均落到窗口 k；
        # d < td[0] 落到 0（丢弃）。即窗口 i 含 (td_{i-1}, td_i]。
        win_idx = np.searchsorted(td_arr, d_dates, side="left")
        dt = daily_turnover.copy()
        dt["_wk"] = win_idx
        dt = dt[dt["_wk"] >= 1]  # 丢弃早于首个截面的样本
        if not dt.empty:
            grp = (
                dt.groupby(["_wk", "ts_code"])["turnover_rate_f"]
                .sum(min_count=1)
            )
            weekly_turnover_sum = {
                (int(wk), code): float(val) for (wk, code), val in grp.items()
            }
            # 4 周累计换手率：在每窗口每股票换手率和基础上，按 ts_code 对窗口序号
            # 做滚动 4 窗口(含当周)求和，得到截至窗口 i 的 (td_{i-4}, td_i] 累计；
            # min_periods=4 保证真正 4 周口径，历史不足 4 周者留 NaN（合成环节跳过）。
            tw_df = grp.reset_index(name="turnover").sort_values(["ts_code", "_wk"])
            tw_df["turnover_4w"] = tw_df.groupby("ts_code")["turnover"].transform(
                lambda s: s.rolling(4, min_periods=4).sum()
            )
            weekly_turnover_sum_4w = {
                (int(wk), code): float(val)
                for wk, code, val in zip(
                    tw_df["_wk"], tw_df["ts_code"], tw_df["turnover_4w"]
                )
                if pd.notna(val)
            }

    # ---- 5. 逐截面遍历 ----
    # 权重（可自行调整）：对应 score_cols 中的权重键
    weights = {
        "turnover_1w": 1,
        "turnover_4w": 1,
        "pct_chg": 1,
        "amount": 1,
    }
    # 从 lookback_idx 起遍历（喂满滚动窗口），但仅对 i >= start_idx 的截面落库
    for i in range(lookback_idx, end_idx + 1):
        td = trade_date[i]
        if i == 0:
            # 首个截面：左开区间 (prev_td, td] 无前序数据，跳过不落库
            continue
        if i < start_idx:
            # 写库守卫：延展周（warm-up）仅用于补齐滚动窗口，不落库
            continue

        # 5.1 当周周频截面（基准样本）
        wk = weekly[weekly["trade_date"] == td].copy()
        if wk.empty:
            continue
        wk = wk[wk["ts_code"].isin(stock_info)].copy()
        if wk.empty:
            continue

        # 5.2 名称 / 行业 / 板块
        wk["name"] = wk["ts_code"].map(lambda c: stock_info[c][0])
        wk["industry"] = wk["ts_code"].map(lambda c: stock_info[c][1])

        # 5.3 周累计换手率：左连接本窗口累计值
        wk["turnover_1w"] = wk["ts_code"].map(
            lambda c: weekly_turnover_sum.get((i, c), np.nan)
        )
        # 5.3b 4 周累计换手率：左连接滚动 4 窗口累计值
        wk["turnover_4w"] = wk["ts_code"].map(
            lambda c: weekly_turnover_sum_4w.get((i, c), np.nan)
        )

        # 5.4 周涨跌幅取绝对值
        wk["pct_chg_abs"] = wk["pct_chg"].astype(float).abs()

        # 5.5 周成交额 log10（<=0 / NaN -> NaN）
        with np.errstate(divide="ignore", invalid="ignore"):
            amount_log = np.log10(wk["amount"].astype(float))
        amount_log = amount_log.where(wk["amount"].astype(float) > 0)

        # ---- 5.6 三子因子归一化（含 NaN 还原与方向）----
        # 方向在此处直接乘 ±1：换手率、涨跌幅(取绝对值)反向（低波动高分，×-1）；
        #           周成交额(log10 后)正向（高成交额高分，×+1）。
        # 周累计换手率：全市场（低换手 -> 高分，反向）
        wk["turnover_1w_score"] = (
            robust_z_to_score(wk["turnover_1w"], alpha=0.05) * -1
        )
        wk["turnover_1w_score"] = wk["turnover_1w_score"].where(
            wk["turnover_1w"].notna()
        )

        # 4 周累计换手率：全市场（低换手 -> 高分，反向）
        wk["turnover_4w_score"] = (
            robust_z_to_score(wk["turnover_4w"], alpha=0.05) * -1
        )
        wk["turnover_4w_score"] = wk["turnover_4w_score"].where(
            wk["turnover_4w"].notna()
        )

        # 周涨跌幅：全市场（rank 百分比归一化，alpha=0.05 截断尾部）
        wk["pct_chg_score"] = rank_to_score(wk["pct_chg_abs"], alpha=0.1) * -1
        wk["pct_chg_score"] = wk["pct_chg_score"].where(
            wk["pct_chg_abs"].notna()
        )

        # 周成交额：全市场（log10 后，正向）
        wk["amount_score"] = robust_z_to_score(amount_log, alpha=0.05)
        wk["amount_score"] = wk["amount_score"].where(amount_log.notna())

        # ---- 5.7 等权合成（缺项按有效权重归一）----
        # score_cols：分数列 -> 权重键（与 size / valuation 等因子结构一致）
        # 方向已在 5.6 归一化时乘入，此处仅按权重加权。
        score_cols = {
            "turnover_1w_score": "turnover_1w",
            "turnover_4w_score": "turnover_4w",
            "pct_chg_score": "pct_chg",
            "amount_score": "amount",
        }
        numerator = pd.Series(0.0, index=wk.index)
        denom = pd.Series(0.0, index=wk.index)
        for sc, base in score_cols.items():
            w = weights[base]
            valid = wk[sc].notna()
            numerator = numerator + np.where(valid, wk[sc] * w, 0.0)
            denom = denom + np.where(valid, w, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            vol_raw = np.where(denom > 0, numerator / denom, np.nan)
        wk["vol_raw"] = vol_raw

        # 向下取整为 int（对齐 StockFactor.volility 的 Integer 类型）
        wk["vol_int"] = wk["vol_raw"].apply(
            lambda v: int(np.floor(v)) if pd.notna(v) else None
        )

        # ---- 5.8 组装落库 DataFrame（列名 volility，库表既定拼写）----
        out_df = pd.DataFrame(
            {
                "ts_code": wk["ts_code"],
                "name": wk["name"],
                "industry": wk["industry"],
                "trade_date": td,
                "volility": wk["vol_int"],
            }
        )
        out_df = out_df[out_df["volility"].notna()]
        # 确保 volility 为 python int（非 numpy int / float），避免 ORM 类型不匹配
        out_df["volility"] = out_df["volility"].astype(int)

        if out_df.empty:
            continue
        upsert_stock_factor(out_df)
        print(
            f"[cal_volatility_factor] trade_date={td} 写入波动率因子 "
            f"{len(out_df)} 条"
        )


# ---- 反转因子"持续性 OR 穿透"双门控参数 ----
REV_LOOKBACK_WEEKS = 60  # 取数窗口向前延展周数（覆盖 60 周均线乖离率所需的历史窗口）
REV_K = 4              # 连续同向周数阈值（K 周封顶 persist=1）
REV_ACT = 20.0         # 子分激活阈值：|原始分| 超此才计入 streak
REV_BIAS_FULL = 0.30   # R1 bias% 穿透满分区（相对 MA60 偏离达 30%）
REV_CCI_FULL = 200.0   # R3 CCI 穿透满分区（|CCI| 达 200）
REV_MACD_FULL = 0.05   # R2 macd_dea_pct 穿透满分区（|macd_dea_pct| 达 5%）
REV_PIERCE = 0.25      # R4 BOLL 刺穿比例（沿用既有口径）


def _smoothstep(t: float) -> float:
    """平滑阶跃：t∈[0,1] -> [0,1]，两端导数为 0，用于持续性因子平滑过渡。"""
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _to_float_array(x) -> np.ndarray:
    """将 Series / ndarray / 标量统一转为 float ndarray，便于向量化门控。"""
    if isinstance(x, pd.Series):
        return x.values.astype(float)
    return np.asarray(x, dtype=float)


def cal_reverse_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """
    反转因子（自包含流程函数，周频截面计算）。

    逐周频截面计算反转（均值回归）因子并落库到 StockFactor.reverse：
      1. 获取全市场周频截面序列（get_all_date，已周频对齐）并按起止日期过滤；
      2. 获取全部股票清单（代码 / 名称 / 行业）；
      3. 循环外一次性区间取数：
         - StockWeeklyIndicator 技术指标：ma5 / ma60 / dif / dea / macd_bar /
           cci / boll_upper / boll_mid / boll_lower；
         - StockWeekly 后复权收盘价 close（乖离率、BOLL %B 及 R2 的 macd_dea_pct 需要）；
      4. 对 indicator 全区间按 ts_code 取紧邻前一周 macd_dea / macd_dea_pct（环比，
         仅紧邻前一周有效，避免停牌/断周伪信号；macd_dea_pct = macd_dea/close）；
      5. 逐截面遍历，计算四个反转子分（方向统一：超卖 / 下跌偏离 -> 高分），
         并对每个子分施加"持续性 OR 穿透"双门控（gate = max(persist, pierce)）：
         - R1 60周均线乖离率：bias=(close-ma60)/ma60，robust_z_to_score(-bias)；
           穿透：|bias| 达 REV_BIAS_FULL(30%) 拿满；
         - R2 MACD（口径）：用 macd_dea_pct = macd_dea/close 替代 macd_bar，
           保留 0.8 水平 + 0.2 收敛/金叉混合；
           穿透：|macd_dea_pct| 达 REV_MACD_FULL(5%) 拿满；
         - R3 CCI（新口径）：截取 [-150,150] 后线性映射到 [-100,100]；
           穿透：|CCI| 达 REV_CCI_FULL(200) 拿满；
         - R4 BOLL（新口径）：贴下轨/上轨仅得 ±80，须大幅刺穿带宽才 ±100（整体居中 [-100,100]），
           沿用 PIERCE 刺穿口径（贴轨±80、刺穿达 PIERCE 封顶 ±100）；
         - 持续性 persist：各子分"同向且 |原始分|>激活阈值"的连胜周数 streak，
           经 smoothstep(streak/REV_K) 平滑，REV_K=4 周封顶；
         - 单周温和偏离被 gate 压低（不再单周满分）；单周巨幅刺穿或连续 REV_K 周同向 -> 满分；
      6. 四子分等权(1:1:1:1)合成（门控后），缺项按有效权重归一，向下取整为 int 落库；
         落库仅对 [start_date, end_date] 内截面执行，其余周(含回溯种子周)仅用于喂 streak。
    start_date / end_date 限定计算范围（如某周），默认 None 时为全量。
    """
    # ---- 1. 交易日序列（升序，已周频对齐）----
    trade_date = get_all_date()
    if trade_date is not None and (
        len(trade_date) < 2 or trade_date != sorted(trade_date)
    ):
        trade_date = sorted(trade_date)
    # 保留完整截面序列用于跨周 streak 种子；起止范围仅用于取数边界与写库守卫，
    # 不再在此裁剪遍历序列（写库守卫在循环内处理）。
    if not trade_date:
        return

    # 计算起止索引（用于取数边界与写库守卫）
    start_idx = 0
    end_idx = len(trade_date) - 1
    if start_date is not None:
        start_idx = next(
            (i for i, t in enumerate(trade_date) if t >= start_date),
            len(trade_date),
        )
    if end_date is not None:
        end_idx = max(
            (i for i, t in enumerate(trade_date) if t <= end_date),
            default=len(trade_date) - 1,
        )

    # ---- 2. 股票清单：ts_code -> (name, industry) ----
    stocks = get_all_stocks()
    stock_info = {
        s.ts_code: (s.name, s.industry if s.industry else "未知")
        for s in stocks
    }

    # ---- 3. 循环外一次性区间取底数 ----
    # 取数边界：q_start 向前扩 REV_LOOKBACK_WEEKS 周，既正确初始化 streak（避免中途起算把
    # 长期超卖误判为第1周），又覆盖 60 周均线乖离率所需的历史窗口；
    # q_end 取至 end_date 对应截面（end_date 为 None 时取全段）。
    lookback_start = max(0, start_idx - REV_LOOKBACK_WEEKS)
    q_start = trade_date[lookback_start]
    q_end = trade_date[end_idx]

    # 3.1 周频技术指标
    ind = get_weekly_indicator_by_trade_date(
        start_date=q_start, end_date=q_end,
        fields=["ts_code", "trade_date", "ma5", "ma60", "dif", "dea",
                "macd_bar", "cci", "boll_upper", "boll_mid", "boll_lower"],
    )
    if ind is not None and not ind.empty:
        for col in ("ma5", "ma60", "dif", "dea", "macd_bar", "cci",
                    "boll_upper", "boll_mid", "boll_lower"):
            if col not in ind.columns:
                ind[col] = np.nan
        ind = ind[ind["ts_code"].isin(stock_info)].copy()
    else:
        ind = pd.DataFrame(columns=["ts_code", "trade_date", "ma5", "ma60",
                                    "dif", "dea", "macd_bar", "cci",
                                    "boll_upper", "boll_mid", "boll_lower"])

    # 3.2 周频收盘价（后复权，乖离率与 BOLL %B 需要）
    wk = get_weekly_by_trade_date(
        start_date=q_start, end_date=q_end,
        fields=["ts_code", "trade_date", "close"],
    )
    if wk is not None and not wk.empty:
        if "close" not in wk.columns:
            wk["close"] = np.nan
        wk = wk[wk["ts_code"].isin(stock_info)].copy()
    else:
        wk = pd.DataFrame(columns=["ts_code", "trade_date", "close"])
    # 合并 close 进 ind：指标层计算 macd_dea_pct 及其环比需要（避免循环内重复合并）
    if not ind.empty and not wk.empty:
        ind = ind.merge(
            wk[["ts_code", "trade_date", "close"]],
            on=["ts_code", "trade_date"], how="left",
        )

    # ---- 4. MACD 环比（收敛/金叉确认项用）：按 ts_code 取紧邻前一周 macd_dea ----
    # 仅当上一 trade_date 严格等于全局序列中紧邻前一周时才有效，否则 diff=NaN，
    # 避免停牌/断周造成的伪信号。
    if not ind.empty:
        ind = ind.sort_values(["ts_code", "trade_date"])
        prev_date = ind.groupby("ts_code")["trade_date"].shift(1)
        # R2 口径：macd_dea_pct = macd_dea / close（按周频标准化，消除大市值量纲）
        with np.errstate(divide="ignore", invalid="ignore"):
            ind["macd_dea_pct"] = ind["dea"] / ind["close"].where(ind["close"] > 0)
        prev_dea_pct = ind.groupby("ts_code")["macd_dea_pct"].shift(1)
        td_index = {d: i for i, d in enumerate(trade_date)}
        cur_idx = ind["trade_date"].map(td_index)
        prev_idx = prev_date.map(td_index)
        adjacent = (
            cur_idx.notna() & prev_idx.notna() & (cur_idx == prev_idx + 1)
        )
        ind["macd_dea_pct_prev"] = np.where(adjacent, prev_dea_pct, np.nan)
    else:
        ind["macd_dea_pct"] = np.nan
        ind["macd_dea_pct_prev"] = np.nan

    # ---- 5. 逐截面遍历 ----
    # 跨周持续性状态（键 ts_code -> {子分项: 连胜计数 / 最近有效符号}），供 streak 门控使用
    streak_state: dict = {}
    streak_sign: dict = {}
    for td in trade_date:
        sub = ind[ind["trade_date"] == td].copy()
        if sub.empty:
            continue
        # close 已在 3.2 节合并进 ind，此处无需再合并 wk
        sub["name"] = sub["ts_code"].map(lambda c: stock_info[c][0])
        sub["industry"] = sub["ts_code"].map(lambda c: stock_info[c][1])

        close = sub["close"].astype(float)
        ma60 = sub["ma60"].astype(float)
        macd_dea_pct = sub["macd_dea_pct"].astype(float)
        macd_dea_pct_prev = sub["macd_dea_pct_prev"].astype(float)
        cci = sub["cci"].astype(float)
        boll_upper = sub["boll_upper"].astype(float)
        boll_lower = sub["boll_lower"].astype(float)

        # ---- 5.1 四子分（方向统一：超卖 / 下跌偏离 -> 高分）----
        # R1 60周均线乖离率
        with np.errstate(divide="ignore", invalid="ignore"):
            bias = (close - ma60) / ma60.where(ma60 > 0)
        r1 = robust_z_to_score(-bias, alpha=0.05)

        # R2 MACD（口径：用 macd_dea_pct = macd_dea/close 替代 macd_bar，
        # 保留 0.8 水平 + 0.2 收敛/金叉混合结构）
        r2_level = robust_z_to_score(-macd_dea_pct, alpha=0.05)        # 纯水平：深度水下→+100、深度水上→-100
        r2_conv = robust_z_to_score(
            -macd_dea_pct + 2.0 * (macd_dea_pct - macd_dea_pct_prev), alpha=0.05)  # 收敛/金叉项
        r2 = 0.8 * r2_level + 0.2 * r2_conv

        # R3 CCI 超卖（新口径：截取 [-150,150] 后线性映射到 [-100,100]，弃用 tanh）
        r3 = -100.0 * np.clip(cci, -150.0, 150.0) / 150.0             # 低 CCI 超卖→+100、高 CCI 超买→-100

        # R4 BOLL（新口径：贴下轨/上轨仅 ±80，须大幅刺穿带宽才 ±100，整体居中 [-100,100]）
        #   pctB=(close-boll_lower)/(boll_upper-boll_lower)：0=下轨、0.5=中轨、1=上轨
        #   带内线性：pctB=0→+80、0.5→0、1→-80；
        #   带外延伸：刺穿达 PIERCE 比例(占带宽)才封顶 ±100（“大比例刺穿”才满分）
        PIERCE = REV_PIERCE  # 刺穿比例阈值(占带宽)：0.25=刺穿约 1 个标准差(下轨下方 σ)才拿满 ±100
        with np.errstate(divide="ignore", invalid="ignore"):
            band = boll_upper - boll_lower
            pctB = (close - boll_lower) / band.where(band > 0)
        r4 = 80.0 - 160.0 * pctB                                   # 带内：下轨+80、中轨0、上轨-80
        r4 = np.where(
            pctB < 0.0,
            np.minimum(80.0 + (20.0 / PIERCE) * (-pctB), 100.0),    # 破下轨：越深越趋近 +100
            np.where(
                pctB > 1.0,
                np.maximum(-80.0 - (20.0 / PIERCE) * (pctB - 1.0), -100.0),  # 破上轨：越深越趋近 -100
                r4,
            ),
        )

        # ---- 5.1b 穿透因子（自然尺度，各指标独立）----
        # R1 bias%：相对 MA60 的偏离幅度
        with np.errstate(divide="ignore", invalid="ignore"):
            bias_abs = np.abs((close - ma60) / ma60.where(ma60 > 0))
        pierce_r1 = _to_float_array(np.clip(bias_abs / REV_BIAS_FULL, 0.0, 1.0))
        # R2 macd_dea_pct 幅度
        pierce_r2 = _to_float_array(np.clip(np.abs(macd_dea_pct) / REV_MACD_FULL, 0.0, 1.0))
        # R3 CCI 幅度
        pierce_r3 = _to_float_array(np.clip(np.abs(cci) / REV_CCI_FULL, 0.0, 1.0))
        # R4 承接现有 PIERCE 刺穿部分：|r4| 超出 ±80 的部分线性到 1
        pierce_r4 = _to_float_array(np.clip((np.abs(r4) - 80.0) / 20.0, 0.0, 1.0))

        # ---- 5.1c 持续性因子（跨周 streak -> persist）----
        # 各子分方向已在 r1..r4（超卖/下跌偏离 -> 正、超买 -> 负）；
        # streak 按"同号且 |raw| 超激活阈值"计连胜，翻转/跌破重置，NaN 不增不减。
        raw_map = {"bias60": r1, "macd": r2, "cci": r3, "boll": r4}
        persist_arr = {}
        codes = sub["ts_code"].values
        for key, raw in raw_map.items():
            arr = _to_float_array(raw)
            p = np.zeros(len(sub), dtype=float)
            for j, code in enumerate(codes):
                val = arr[j]
                st = streak_state.setdefault(code, {}).get(key, 0)
                sign_state = streak_sign.setdefault(code, {})
                if pd.notna(val):
                    if abs(val) > REV_ACT:
                        prev = sign_state.get(key, 0)
                        if prev != 0 and np.sign(val) == prev:
                            st = st + 1 if st > 0 else 1
                        else:
                            st = 1
                        sign_state[key] = int(np.sign(val))
                    else:
                        st = 0
                        sign_state[key] = 0
                # NaN：保持 st / sign 不变（不增不减）
                streak_state[code][key] = st
                p[j] = _smoothstep(min(st / REV_K, 1.0))
            persist_arr[key] = p

        # ---- 5.1d 门控：gate = max(持续性, 穿透)，压低单周温和信号 ----
        gated = {}
        for key, raw, pierce in (
            ("bias60", r1, pierce_r1),
            ("macd", r2, pierce_r2),
            ("cci", r3, pierce_r3),
            ("boll", r4, pierce_r4),
        ):
            arr = _to_float_array(raw)
            gate = np.maximum(persist_arr[key], pierce)
            gated[key] = np.sign(arr) * np.abs(arr) * gate
        r1, r2, r3, r4 = (gated["bias60"], gated["macd"], gated["cci"], gated["boll"])

        # ---- 5.2 等权合成（缺项按有效权重归一）----
        scores = {"bias60": r1, "macd": r2, "cci": r3, "boll": r4}
        weights = {"bias60": 1, "macd": 1, "cci": 1, "boll": 1}
        numerator = pd.Series(0.0, index=sub.index)
        denom = pd.Series(0.0, index=sub.index)
        for base, sc in scores.items():
            w = weights[base]
            valid = pd.notna(sc)
            numerator = numerator + np.where(valid, sc * w, 0.0)
            denom = denom + np.where(valid, w, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            reverse_raw = np.where(denom > 0, numerator / denom, np.nan)
        sub["reverse"] = np.clip(reverse_raw, -100, 100)          # 防御性边界，保证 [-100,100]

        # 对称取整为 int（对齐 StockFactor.reverse 的 Integer 类型）
        sub["reverse_int"] = sub["reverse"].apply(
            lambda v: int(round(v)) if pd.notna(v) else None
        )

        # 写库守卫：回溯种子周(<start_date)与超出 end_date 的周仅喂 streak，不落库
        if (start_date is not None and td < start_date) or (
            end_date is not None and td > end_date
        ):
            continue

        # ---- 5.3 组装落库 DataFrame ----
        out_df = pd.DataFrame(
            {
                "ts_code": sub["ts_code"],
                "name": sub["name"],
                "industry": sub["industry"],
                "trade_date": td,
                "reverse": sub["reverse_int"],
            }
        )
        out_df = out_df[out_df["reverse"].notna()]
        if out_df.empty:
            continue
        out_df["reverse"] = out_df["reverse"].astype(int)
        upsert_stock_factor(out_df)
        print(
            f"[cal_reverse_factor] trade_date={td} 写入反转因子 {len(out_df)} 条"
        )




# ---- 盈利因子：金融行业识别关键字（R2 毛利率 -> 净利率替代）----
PROFIT_FINANCE_KEYWORDS = ("银行", "证券", "保险", "多元金融", "金融", "信托", "期货")


def cal_profit_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """
    盈利因子（自包含流程函数，逐交易日计算）。

    逐交易日截面计算盈利因子并落库到 StockFactor.profit（六子项权重 2:1:1:1:1:1）：
      1. 获取全部交易日序列并升序排序，按起止日期过滤；
      2. 获取全部股票清单（代码 / 名称 / 行业）；
      3. 遍历每个交易日的截面：
         - StockFinaIndicator 取财务底数：ann_date 窗口 [td 前一年, td]，
           保留全部报告期（0331/0630/0930/1231），按 ts_code 取 end_date 最大一期
           （不再剔除季报；仍剔除报告期早于上市日 list_date 的上市前财报）；
        - 额外剔除报告期 end_date 早于个股上市日期 list_date 的财务行，且
          list_date 缺失的股票其报表一并剔除（无上市日即视为未正式上市，
          不进入截面）；
        - 取数字段：roe_yearly / roe / grossprofit_margin / netprofit_margin /
          ap_to_ar；
      4. 六子项归一化（方向统一：越大越好，不翻转）：
        - R1 roe_yearly：线性映射 [-25,25] -> [-100,100]（clip(4*x)），权重 1；
        - R2 roe：全市场 robust_z_to_score(alpha=0.05)，权重 1；
        - R3 行业内毛利率 grossprofit_margin：行业内分组比（groupby industry）
          rank_to_score(alpha=0.01)，权重 1；银保证等金融行业改用净利率
          netprofit_margin 替代毛利率；
        - R4 净利率 netprofit_margin：行业内分组比 rank_to_score
          (alpha=0.05)，权重 0.5；
        - R5 行业内经营杠杆强度 ap_to_ar：行业内分组比 rank_to_score
          (alpha=0.05)，权重 0.5；银保证等金融行业该子项默认输出 0；
        - R6 总资产 total_assets：取自 StockBalancesheet（资产负债表），
          先全截面 log10 平移（log10(total_assets - total_assets.min() + 1)）消除量纲，
          再行业内 robust_z_to_score(alpha=0.05)，权重 1（奖励规模优势）；
      5. 加权合成 profit = 1*roe_yearly + 1*roe + 1*margin + 0.5*netprofit_margin
        + 0.5*ap_to_ar + 1*total_assets（权重和 5，缺项按有效权重归一），
        结果向下取整为 int 落库。
    start_date / end_date 限定计算范围（如某段），默认 None 时为全量。
    """
    # ---- 1. 交易日序列（升序）----
    trade_date = get_all_date()
    if trade_date is not None and (
        len(trade_date) < 2 or trade_date != sorted(trade_date)
    ):
        trade_date = sorted(trade_date)
    if start_date is not None or end_date is not None:
        trade_date = [
            t for t in trade_date
            if (start_date is None or t >= start_date)
            and (end_date is None or t <= end_date)
        ]

    # ---- 2. 股票清单：ts_code -> (name, industry)，并缓存上市日期 ----
    stocks = get_all_stocks()
    stock_info = {
        s.ts_code: (s.name, s.industry if s.industry else "未知")
        for s in stocks
    }
    # list_date 形如 "YYYYMMDD"；缺失为 None（缺失则视为未正式上市，其报表被剔除）
    list_dates = {s.ts_code: s.list_date for s in stocks}

    # 财务取数字段
    fina_fields = [
        "ts_code", "end_date", "roe_yearly", "roe",
        "grossprofit_margin", "netprofit_margin", "ap_to_ar",
    ]

    weights = {
        "roe_yearly": 1,       # R1 线性映射 [-25,25]->[-100,100]
        "roe": 1,              # R2 全市场 robust_z_to_score(alpha=0.05)
        "margin": 1,           # R3 行业内 rank_to_score（金融用 netprofit_margin）
        "netprofit_margin": 0.5, # R4 行业内 rank_to_score(alpha=0.05)
        "ap_to_ar": 0.5,       # R5 行业内 rank_to_score（金融置 0）
        "total_assets": 1,     # R6 总资产（取自 StockBalancesheet）先 log10 平移后行业内 robust_z_to_score(alpha=0.05)
    }

    for td in trade_date:
        # ---- 3.1 财务底数（ann_date 窗口：[td 前一年, td]）----
        try:
            td_date = datetime.strptime(td, "%Y%m%d")
            start_ann = (td_date.replace(year=td_date.year - 1)).strftime("%Y%m%d")
        except Exception:
            start_ann = None
        fina_df = get_fina_indicator_by_ann_date(
            start_ann_date=start_ann, end_ann_date=td, fields=fina_fields,
        )
        if fina_df is not None and not fina_df.empty:
            for col in fina_fields:
                if col not in fina_df.columns:
                    fina_df[col] = np.nan
            # 保留全部报告期（0331/0630/0930/1231），不剔除季报
            # 每股票取 end_date 最大（最新一期）报告
            fina_df = (
                fina_df.sort_values("end_date")
                .groupby("ts_code", as_index=False)
                .tail(1)
            )
            fina_df = fina_df[fina_df["ts_code"].isin(stock_info)].copy()
            # 剔除：① 报告期早于上市日期的财务行（上市前报表，无对应 K 线）；
            #       ② list_date 缺失的股票（视为未正式上市）报表一并剔除。
            # 仅保留 list_date 存在且 end_date >= list_date 的报表。
            ld = fina_df["ts_code"].map(list_dates)
            keep = ld.notna() & (
                fina_df["end_date"].notna()
                & (fina_df["end_date"].astype(str) >= ld.astype(str))
            )
            fina_df = fina_df[keep]
        else:
            fina_df = pd.DataFrame(columns=fina_fields)

        # ---- 3.1b 资产负债表底数（ann_date 窗口：[td 前一年, td]，R6 总资产来源）----
        bs_df = get_balancesheet_by_ann_date(
            start_ann_date=start_ann, end_ann_date=td,
            fields=["ts_code", "end_date", "total_assets"],
        )
        if bs_df is not None and not bs_df.empty:
            for col in ("ts_code", "end_date", "total_assets"):
                if col not in bs_df.columns:
                    bs_df[col] = np.nan
            # 保留全部报告期，每股票取 end_date 最大（最新一期）报告
            bs_df = (
                bs_df.sort_values("end_date")
                .groupby("ts_code", as_index=False)
                .tail(1)
            )
            bs_df = bs_df[bs_df["ts_code"].isin(stock_info)].copy()
            # 剔除上市前报表与 list_date 缺失的股票（口径同 fina_df）
            ld = bs_df["ts_code"].map(list_dates)
            keep = ld.notna() & (
                bs_df["end_date"].notna()
                & (bs_df["end_date"].astype(str) >= ld.astype(str))
            )
            bs_df = bs_df[keep]
        else:
            bs_df = pd.DataFrame(columns=["ts_code", "end_date", "total_assets"])

        # ---- 3.2 合并行业 + 截面（全股票，财务缺失则为 NaN）----
        section = pd.DataFrame({"ts_code": list(stock_info.keys())})
        section = section.merge(fina_df, on="ts_code", how="left")
        section = section.merge(
            bs_df[["ts_code", "total_assets"]], on="ts_code", how="left"
        )
        section["name"] = section["ts_code"].map(lambda c: stock_info[c][0])
        section["industry"] = section["ts_code"].map(lambda c: stock_info[c][1])
        # 兜底列存在性
        for col in ("roe_yearly", "roe", "grossprofit_margin",
                    "netprofit_margin", "ap_to_ar", "total_assets"):
            if col not in section.columns:
                section[col] = np.nan

        # ---- 4.1 R1 roe_yearly：[-25,25] 线性映射至 [-100,100] ----
        section["r1_score"] = np.clip(section["roe_yearly"] * 4.0, -100.0, 100.0)

        # ---- 4.2 R2 roe：全市场 robust_z_to_score（不做行业中性化）----
        section["r2_score"] = robust_z_to_score(section["roe"], alpha=0.05)

        # ---- 4.3 R3 行业内毛利率（金融用净利率）----
        is_finance = section["industry"].apply(
            lambda x: any(k in (x or "") for k in PROFIT_FINANCE_KEYWORDS)
        )
        section["margin"] = np.where(
            is_finance,
            section["netprofit_margin"],
            section["grossprofit_margin"],
        )
        section["r3_score"] = section.groupby("industry")["margin"].transform(
            lambda s: rank_to_score(s, alpha=0.01)
        )

        # ---- 4.4 R4 净利率：行业内 rank_to_score（行业中性化）----
        section["r4_score"] = section.groupby("industry")["netprofit_margin"].transform(
            lambda s: rank_to_score(s, alpha=0.05)
        )

        # ---- 4.5 R5 行业内经营杠杆强度（金融行业默认输出 0）----
        section["r5_score"] = section.groupby("industry")["ap_to_ar"].transform(
            lambda s: rank_to_score(s, alpha=0.05)
        )
        section["r5_score"] = np.where(is_finance, 0.0, section["r5_score"])

        # ---- 4.5b R6 总资产（取自 StockBalancesheet，先 log10 平移，再行业内 robust_z_to_score，权重 1）----
        # 口径：直接取 total_assets；对 total_assets<=0 或缺失的行置 NaN（避免 log10 非正）。
        ta = section["total_assets"].where(
            section["total_assets"].notna() & (section["total_assets"] > 0)
        )
        # 全截面 log10 平移（min 取全截面，组内各自平移会导致跨组不可比）：
        # total_assets_log = log10(total_assets - total_assets.min() + 1)，最小值映射为 0，无 inf。
        total_assets_log = ta.sub(ta.min()).add(1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            total_assets_log = np.where(ta.notna(), np.log10(total_assets_log), np.nan)
        section["total_assets_log"] = total_assets_log
        section["r6_score"] = section.groupby("industry")["total_assets_log"].transform(
            lambda s: robust_z_to_score(s, alpha=0.05)
        )

        # ---- 4.6 加权合成（缺项按有效权重归一）----
        score_cols = {
            "r1_score": "roe_yearly",
            "r2_score": "roe",
            "r3_score": "margin",
            "r4_score": "netprofit_margin",
            "r5_score": "ap_to_ar",
            "r6_score": "total_assets",
        }
        numerator = pd.Series(0.0, index=section.index)
        denom = pd.Series(0.0, index=section.index)
        for sc, base in score_cols.items():
            w = weights[base]
            valid = section[sc].notna()
            numerator = numerator + np.where(valid, section[sc] * w, 0.0)
            denom = denom + np.where(valid, w, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            profit_raw = np.where(denom > 0, numerator / denom, np.nan)
        section["profit"] = profit_raw

        # 向下取整为 int（对齐 StockFactor.profit 的 Integer 类型）
        section["profit_int"] = section["profit"].apply(
            lambda v: int(np.floor(v)) if pd.notna(v) else None
        )

        # ---- 4.7 组装落库 DataFrame ----
        out_df = pd.DataFrame(
            {
                "ts_code": section["ts_code"],
                "name": section["name"],
                "industry": section["industry"],
                "trade_date": td,
                "profit": section["profit_int"],
            }
        )
        out_df = out_df[out_df["profit"].notna()]
        out_df["profit"] = out_df["profit"].astype(int)

        if out_df.empty:
            continue
        upsert_stock_factor(out_df)
        print(
            f"[cal_profit_factor] trade_date={td} 写入盈利因子 {len(out_df)} 条"
        )



def cal_growth_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """
    成长因子（自包含流程函数，逐交易日计算）。

    逐交易日截面计算成长因子并落库到 StockFactor.growth（四子项等权 1:1:1:1）：
      1. 获取全部交易日序列并升序排序，按起止日期过滤；
      2. 获取全部股票清单（代码 / 名称 / 行业）；
      3. 遍历每个交易日的截面：
         - StockFinaIndicator 取财务底数：ann_date 窗口 [td 前一年, td]，
           保留全部报告期（0331/0630/0930/1231），按 ts_code 取 end_date 最大一期
           （不再剔除季报；仍剔除报告期早于上市日 list_date 的上市前财报）；
        - 额外剔除报告期 end_date 早于个股上市日期 list_date 的财务行，且
          list_date 缺失的股票其报表一并剔除（无上市日即视为未正式上市，
          不进入截面）；
        - 取数字段：tr_yoy / op_yoy / ocf_yoy；
      4. 四子项归一化（方向统一：越大越好，不翻转）：
         - R1 总收入同比 tr_yoy：先 log10(1 + yoy/100)（yoy 为百分比，
            x = yoy/100 为比率，如 25% -> 0.25；1+x <= 0 即同比降幅超 100%
            的极端情形置 NaN），再全市场 robust_z_to_score(alpha=0.05)，权重 1；
         - R2 营业利润同比 op_yoy：同 R1 变换与标准化，权重 1；
         - R3 经营现金净流量同比 ocf_yoy：同 R1 变换与标准化，权重 1；
         - R4 总营收 total_revenue：取自 StockIncome（利润表），
           先全截面 log10 平移（log10(x - x.min() + 1)），
           再行业内 robust_z_to_score(alpha=0.05)，权重 1（奖励规模优势，与增速类子项互补）；
         5. 加权合成 growth = 1*tr_yoy + 1*op_yoy + 1*ocf_yoy + 1*total_revenue
         （权重和 4，等权，缺项按有效权重归一），结果向下取整为 int 落库。
    start_date / end_date 限定计算范围（如某段），默认 None 时为全量。
    """
    # ---- 1. 交易日序列（升序）----
    trade_date = get_all_date()
    if trade_date is not None and (
        len(trade_date) < 2 or trade_date != sorted(trade_date)
    ):
        trade_date = sorted(trade_date)
    if start_date is not None or end_date is not None:
        trade_date = [
            t for t in trade_date
            if (start_date is None or t >= start_date)
            and (end_date is None or t <= end_date)
        ]

    # ---- 2. 股票清单：ts_code -> (name, industry)，并缓存上市日期 ----
    stocks = get_all_stocks()
    stock_info = {
        s.ts_code: (s.name, s.industry if s.industry else "未知")
        for s in stocks
    }
    # list_date 形如 "YYYYMMDD"；缺失为 None（缺失则视为未正式上市，其报表被剔除）
    list_dates = {s.ts_code: s.list_date for s in stocks}

    # 财务取数字段
    fina_fields = [
        "ts_code", "end_date", "tr_yoy", "op_yoy", "ocf_yoy",
    ]

    weights = {
        "tr_yoy": 1,        # R1 log10(1+x) 后 全市场 robust_z_to_score(alpha=0.05)
        "op_yoy": 1,        # R2 同上
        "ocf_yoy": 1,       # R3 同上
        "total_revenue": 1, # R4 总营收（取自 StockIncome）先 log10 平移后行业内 robust_z_to_score(alpha=0.05)，权重 1
    }

    for td in trade_date:
        # ---- 3.1 财务底数（ann_date 窗口：[td 前一年, td]）----
        try:
            td_date = datetime.strptime(td, "%Y%m%d")
            start_ann = (td_date.replace(year=td_date.year - 1)).strftime("%Y%m%d")
        except Exception:
            start_ann = None
        fina_df = get_fina_indicator_by_ann_date(
            start_ann_date=start_ann, end_ann_date=td, fields=fina_fields,
        )
        if fina_df is not None and not fina_df.empty:
            for col in fina_fields:
                if col not in fina_df.columns:
                    fina_df[col] = np.nan
            # 保留全部报告期（0331/0630/0930/1231），不剔除季报
            # 每股票取 end_date 最大（最新一期）报告
            fina_df = (
                fina_df.sort_values("end_date")
                .groupby("ts_code", as_index=False)
                .tail(1)
            )
            fina_df = fina_df[fina_df["ts_code"].isin(stock_info)].copy()
            # 剔除：① 报告期早于上市日期的财务行（上市前报表，无对应 K 线）；
            #       ② list_date 缺失的股票（视为未正式上市）报表一并剔除。
            # 仅保留 list_date 存在且 end_date >= list_date 的报表。
            ld = fina_df["ts_code"].map(list_dates)
            keep = ld.notna() & (
                fina_df["end_date"].notna()
                & (fina_df["end_date"].astype(str) >= ld.astype(str))
            )
            fina_df = fina_df[keep]
        else:
            fina_df = pd.DataFrame(columns=fina_fields)

        # ---- 3.1b 利润表底数（ann_date 窗口：[td 前一年, td]，R4 总营收来源）----
        inc_df = get_income_by_ann_date(
            start_ann_date=start_ann, end_ann_date=td,
            fields=["ts_code", "end_date", "total_revenue"],
        )
        if inc_df is not None and not inc_df.empty:
            for col in ("ts_code", "end_date", "total_revenue"):
                if col not in inc_df.columns:
                    inc_df[col] = np.nan
            # 保留全部报告期，每股票取 end_date 最大（最新一期）报告
            inc_df = (
                inc_df.sort_values("end_date")
                .groupby("ts_code", as_index=False)
                .tail(1)
            )
            inc_df = inc_df[inc_df["ts_code"].isin(stock_info)].copy()
            # 剔除上市前报表与 list_date 缺失的股票（口径同 fina_df）
            ld = inc_df["ts_code"].map(list_dates)
            keep = ld.notna() & (
                inc_df["end_date"].notna()
                & (inc_df["end_date"].astype(str) >= ld.astype(str))
            )
            inc_df = inc_df[keep]
        else:
            inc_df = pd.DataFrame(columns=["ts_code", "end_date", "total_revenue"])

        # ---- 3.2 合并行业 + 截面（全股票，财务缺失则为 NaN）----
        section = pd.DataFrame({"ts_code": list(stock_info.keys())})
        section = section.merge(fina_df, on="ts_code", how="left")
        section = section.merge(
            inc_df[["ts_code", "total_revenue"]], on="ts_code", how="left"
        )
        section["name"] = section["ts_code"].map(lambda c: stock_info[c][0])
        section["industry"] = section["ts_code"].map(lambda c: stock_info[c][1])
        # 兜底列存在性
        for col in ("tr_yoy", "op_yoy", "ocf_yoy", "total_revenue"):
            if col not in section.columns:
                section[col] = np.nan

        # ---- 4. 三子项：log10(1+x) 变换（x = yoy/100）后全市场 robust_z_to_score ----
        for col, sc in (("tr_yoy", "r1_score"), ("op_yoy", "r2_score"),
                        ("ocf_yoy", "r3_score")):
            with np.errstate(divide="ignore", invalid="ignore"):
                base = 1.0 + section[col].astype(float) / 100.0
                log_val = np.log10(base)
            log_val = log_val.where(base > 0)  # 1+x<=0（同比降幅>=100%）置 NaN
            section[sc] = robust_z_to_score(log_val, alpha=0.05)

        # ---- 4.0 R4 总营收：先全截面 log10 平移（min 取全截面，组内各自平移会跨组不可比），
        #          再行业内 robust_z_to_score（奖励规模优势，权重 1）----
        tr_log = section["total_revenue"].sub(section["total_revenue"].min()).add(1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            tr_log = np.where(section["total_revenue"].notna(), np.log10(tr_log), np.nan)
        section["tr_log"] = tr_log
        section["r4_score"] = section.groupby("industry")["tr_log"].transform(
            lambda s: robust_z_to_score(s, alpha=0.05)
        )

        # ---- 4.1 加权合成（缺项按有效权重归一）----
        score_cols = {
            "r1_score": "tr_yoy",
            "r2_score": "op_yoy",
            "r3_score": "ocf_yoy",
            "r4_score": "total_revenue",
        }
        numerator = pd.Series(0.0, index=section.index)
        denom = pd.Series(0.0, index=section.index)
        for sc, base in score_cols.items():
            w = weights[base]
            valid = section[sc].notna()
            numerator = numerator + np.where(valid, section[sc] * w, 0.0)
            denom = denom + np.where(valid, w, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            growth_raw = np.where(denom > 0, numerator / denom, np.nan)
        section["growth"] = growth_raw

        # 向下取整为 int（对齐 StockFactor.growth 的 Integer 类型）
        section["growth_int"] = section["growth"].apply(
            lambda v: int(np.floor(v)) if pd.notna(v) else None
        )

        # ---- 4.2 组装落库 DataFrame ----
        out_df = pd.DataFrame(
            {
                "ts_code": section["ts_code"],
                "name": section["name"],
                "industry": section["industry"],
                "trade_date": td,
                "growth": section["growth_int"],
            }
        )
        out_df = out_df[out_df["growth"].notna()]
        out_df["growth"] = out_df["growth"].astype(int)

        if out_df.empty:
            continue
        upsert_stock_factor(out_df)
        print(
            f"[cal_growth_factor] trade_date={td} 写入成长因子 {len(out_df)} 条"
        )


def cal_cash_factor(
    start_date: str | None = None, end_date: str | None = None
) -> None:
    """
    现金因子（自包含流程函数，逐交易日计算）。

    逐交易日计算现金因子并落库到 StockFactor.cash（R1/R2 全市场比较、R3/R4 行业内，四子项等权 1:1:1:1）：
      1. 获取全部交易日序列并升序排序，按起止日期过滤；
      2. 获取全部股票清单（代码 / 名称 / 行业 / 上市日期）；
      3. 遍历每个交易日的截面：
         - StockFinaIndicator 取财务底数：ann_date 窗口 [td 前一年, td]，
           保留全部报告期（0331/0630/0930/1231），按 ts_code 取 end_date 最大一期
           （不再剔除季报；仍剔除报告期早于上市日 list_date 的上市前财报）；
        - 额外剔除报告期 end_date 早于个股上市日期 list_date 的财务行，且
          list_date 缺失的股票其报表一并剔除（无上市日即视为未正式上市，
          不进入截面）；
        - 取数字段：salescash_to_or / opincome_of_ebt / int_to_talcap；
      4. 子项归一化（R1/R2 全市场比较、R3/R4 行业内中性化，方向统一：变现质量越大越好、杠杆越小越好）：
         - R1 现金收入比 salescash_to_or：全市场 robust_z_to_score(alpha=0.05)，权重 1；
         - R2 净现金利润比 opincome_of_ebt：全市场 robust_z_to_score(alpha=0.05)，权重 1；
         - R3 带息债务/全部投入资本 int_to_talcap：行业内 rank_to_score(alpha=0.05)
           后翻转（×-1，越小越好），权重 1；
         - R4 现金规模：经营现金流净额 n_cashflow_act，先全截面 log10 平移
          （log10(x - x.min() + 1)），再行业内 robust_z_to_score(alpha=0.05)，权重 1；
      5. 加权合成 cash = 2*R1 + 2*R2 + 1*R3（权重和 5，缺项按有效权重归一），
         结果向下取整为 int 落库。
    start_date / end_date 限定计算范围（如某段），默认 None 时为全量。
    """
    # ---- 1. 交易日序列（升序）----
    trade_date = get_all_date()
    if trade_date is not None and (
        len(trade_date) < 2 or trade_date != sorted(trade_date)
    ):
        trade_date = sorted(trade_date)
    if start_date is not None or end_date is not None:
        trade_date = [
            t for t in trade_date
            if (start_date is None or t >= start_date)
            and (end_date is None or t <= end_date)
        ]

    # ---- 2. 股票清单：ts_code -> (name, industry)，并缓存上市日期 ----
    stocks = get_all_stocks()
    stock_info = {
        s.ts_code: (s.name, s.industry if s.industry else "未知")
        for s in stocks
    }
    # list_date 形如 "YYYYMMDD"；缺失为 None（缺失则视为未正式上市，其报表被剔除）
    list_dates = {s.ts_code: s.list_date for s in stocks}

    # 财务取数字段
    fina_fields = [
        "ts_code", "end_date", "salescash_to_or", "opincome_of_ebt", "int_to_talcap",
    ]

    cashflow_fields = ["ts_code", "end_date", "n_cashflow_act"]
    weights = {
        "r1_score": 1,       # R1 现金收入比：行业内 robust_z_to_score(alpha=0.05)，权重 1
        "r2_score": 1,       # R2 净现金利润比：行业内 robust_z_to_score(alpha=0.05)，权重 1
        "r3_score": 1,       # R3 带息债务占比：行业内 robust_z_to_score 后翻转，权重 1
        "r4_score": 1,       # R4 现金规模：经营现金流净额，行业内 robust_z_to_score，权重 1
    }

    for td in trade_date:
        # ---- 3.1 财务底数（ann_date 窗口：[td 前一年, td]）----
        try:
            td_date = datetime.strptime(td, "%Y%m%d")
            start_ann = (td_date.replace(year=td_date.year - 1)).strftime("%Y%m%d")
        except Exception:
            start_ann = None
        fina_df = get_fina_indicator_by_ann_date(
            start_ann_date=start_ann, end_ann_date=td, fields=fina_fields,
        )
        if fina_df is not None and not fina_df.empty:
            for col in fina_fields:
                if col not in fina_df.columns:
                    fina_df[col] = np.nan
            # 保留全部报告期（0331/0630/0930/1231），不剔除季报
            # 每股票取 end_date 最大（最新一期）报告
            fina_df = (
                fina_df.sort_values("end_date")
                .groupby("ts_code", as_index=False)
                .tail(1)
            )
            fina_df = fina_df[fina_df["ts_code"].isin(stock_info)].copy()
            # 剔除：① 报告期早于上市日期的财务行（上市前报表，无对应 K 线）；
            #       ② list_date 缺失的股票（视为未正式上市）报表一并剔除。
            # 仅保留 list_date 存在且 end_date >= list_date 的报表。
            ld = fina_df["ts_code"].map(list_dates)
            keep = ld.notna() & (
                fina_df["end_date"].notna()
                & (fina_df["end_date"].astype(str) >= ld.astype(str))
            )
            fina_df = fina_df[keep]
        else:
            fina_df = pd.DataFrame(columns=fina_fields)

        # ---- 3.1b 现金流量表底数（ann_date 窗口：[td 前一年, td]）----
        cf_df = get_cashflow_by_ann_date(
            start_ann_date=start_ann, end_ann_date=td, fields=cashflow_fields,
        )
        if cf_df is not None and not cf_df.empty:
            for col in cashflow_fields:
                if col not in cf_df.columns:
                    cf_df[col] = np.nan
            # 保留全部报告期（0331/0630/0930/1231），不剔除季报
            # 每股票取 end_date 最大（最新一期）报告
            cf_df = (
                cf_df.sort_values("end_date")
                .groupby("ts_code", as_index=False)
                .tail(1)
            )
            cf_df = cf_df[cf_df["ts_code"].isin(stock_info)].copy()
            # 剔除：① 报告期早于上市日期的财务行（上市前报表，无对应 K 线）；
            #       ② list_date 缺失的股票（视为未正式上市）报表一并剔除。
            # 仅保留 list_date 存在且 end_date >= list_date 的报表。
            ld = cf_df["ts_code"].map(list_dates)
            keep = ld.notna() & (
                cf_df["end_date"].notna()
                & (cf_df["end_date"].astype(str) >= ld.astype(str))
            )
            cf_df = cf_df[keep]
        else:
            cf_df = pd.DataFrame(columns=cashflow_fields)

        # ---- 3.2 合并行业 + 截面（全股票，财务缺失则为 NaN）----
        section = pd.DataFrame({"ts_code": list(stock_info.keys())})
        section = section.merge(fina_df, on="ts_code", how="left")
        section = section.merge(
            cf_df[["ts_code", "n_cashflow_act"]], on="ts_code", how="left"
        )
        section["name"] = section["ts_code"].map(lambda c: stock_info[c][0])
        section["industry"] = section["ts_code"].map(lambda c: stock_info[c][1])
        # 兜底列存在性
        for col in ("salescash_to_or", "opincome_of_ebt", "int_to_talcap", "n_cashflow_act"):
            if col not in section.columns:
                section[col] = np.nan

        # ---- 4.1 R1 现金收入比：全市场 robust_z_to_score（方向 +）----
        section["r1_score"] = robust_z_to_score(section["salescash_to_or"], alpha=0.05)

        # ---- 4.2 R2 净现金利润比：全市场 robust_z_to_score（方向 +）----
        section["r2_score"] = robust_z_to_score(section["opincome_of_ebt"], alpha=0.05)

        # ---- 4.3 R3 带息债务占比：行业内 robust_z_to_score 后翻转（方向 -，越小越好）----
        r3 = section.groupby("industry")["int_to_talcap"].transform(
            lambda s: robust_z_to_score(s, alpha=0.05)
        )
        section["r3_score"] = (-r3).where(section["int_to_talcap"].notna())

        # ---- 4.4 R4 现金规模：经营现金流净额，先全截面 log10 平移（min 取全截面），
        #          再行业内 robust_z_to_score（方向 +）----
        cf_log = section["n_cashflow_act"].sub(section["n_cashflow_act"].min()).add(1.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            cf_log = np.where(section["n_cashflow_act"].notna(), np.log10(cf_log), np.nan)
        section["cf_log"] = cf_log
        section["r4_score"] = section.groupby("industry")["cf_log"].transform(
            lambda s: robust_z_to_score(s, alpha=0.05)
        )

        # ---- 加权合成（缺项按有效权重归一，四子项等权 1:1:1:1）----
        score_cols = {
            "r1_score": "salescash_to_or",
            "r2_score": "opincome_of_ebt",
            "r3_score": "int_to_talcap",
            "r4_score": "n_cashflow_act",
        }
        numerator = pd.Series(0.0, index=section.index)
        denom = pd.Series(0.0, index=section.index)
        for sc, base in score_cols.items():
            w = weights[sc]
            valid = section[sc].notna()
            numerator = numerator + np.where(valid, section[sc] * w, 0.0)
            denom = denom + np.where(valid, w, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            cash_raw = np.where(denom > 0, numerator / denom, np.nan)
        section["cash"] = cash_raw

        # 向下取整为 int（对齐 StockFactor.cash 的 Integer 类型）
        section["cash_int"] = section["cash"].apply(
            lambda v: int(np.floor(v)) if pd.notna(v) else None
        )

        # ---- 4.5 组装落库 DataFrame ----
        out_df = pd.DataFrame(
            {
                "ts_code": section["ts_code"],
                "name": section["name"],
                "industry": section["industry"],
                "trade_date": td,
                "cash": section["cash_int"],
            }
        )
        out_df = out_df[out_df["cash"].notna()]
        out_df["cash"] = out_df["cash"].astype(int)

        if out_df.empty:
            continue
        upsert_stock_factor(out_df)
        print(
            f"[cal_cash_factor] trade_date={td} 写入现金因子 {len(out_df)} 条"
        )


def cal_supply_factor(df: pd.DataFrame) -> pd.Series:
    """
    供需因子。

    基于供需/活跃度类字段（如 turnover_rate_f / volume_ratio，来源 stock_daily_basic）计算
    原始供需值，经截面归一化映射到 [-100, 100]。交投活跃度（方向待定）得分更高。
    TODO: 实现具体计算逻辑（取字段 -> 归一化 -> 返回 Series）。
    """
    ...


def cal_moat_factor(df: pd.DataFrame) -> pd.Series:
    """
    护城河因子。

    基于护城河类财务字段（如 grossprofit_margin / debt_to_assets，来源 stock_fina_indicator）
    计算原始护城河值，经截面归一化映射到 [-100, 100]。毛利率高、负债率低得分更高。
    TODO: 实现具体计算逻辑（多字段合成 -> 归一化 -> 返回 Series）。
    """
    ...


# ======================================================================
# 4. 因子聚合入口
# ======================================================================

def cal_all_factors(df: pd.DataFrame) -> pd.DataFrame:
    """
    因子聚合入口（骨架版）。

    各因子由各自的流程函数（如 cal_size_factor）独立计算并落库 StockFactor，
    不再以"接收单截面 df、返回 Series"的形式在此处被调用。本函数仅保留 13 列
    占位结构，便于核对与上层引用，不会触发尚未实现的单截面计算逻辑。

    参数
    ----
    df : pd.DataFrame
        仅用于确定截面行数 / 主键列（ts_code / name / trade_date），
        不再驱动因子计算。

    返回
    ----
    pd.DataFrame
        含 13 列、因子列全为空的因子表骨架：
        ts_code, name, trade_date,
        size, valuation, volility, reverse,
        profit, growth, cash, supply, moat。
    """
    expected_cols = [
        "ts_code", "name", "trade_date",
        "size", "valuation", "volility", "reverse",
        "profit", "growth", "cash", "supply", "moat",
    ]
    skeleton = pd.DataFrame(
        {c: df[c] if c in df.columns else np.nan for c in expected_cols[:3]},
        index=df.index if hasattr(df, "index") else None,
    )
    for c in expected_cols[3:]:
        skeleton[c] = np.nan
    # 严格对齐 13 列顺序
    skeleton = skeleton[expected_cols]
    print(
        "[cal_all_factors] 骨架模式：各因子由各自流程函数独立落库，"
        "本函数仅返回 13 列占位结构。"
    )
    return skeleton


# ======================================================================
# 4.5 每周增量重算入口（对应「每周动态更新因子」）
# ======================================================================

# 每周增量重算的因子清单：(名称, 流程函数)。因子间无依赖，顺序固定仅为日志稳定。
WEEKLY_FACTORS = [
    ("size", cal_size_factor),
    ("valuation", cal_valuation_factor),
    ("volatility", cal_volatility_factor),
    ("reverse", cal_reverse_factor),
    ("profit", cal_profit_factor),
    ("growth", cal_growth_factor),
    ("cash", cal_cash_factor),
]

# 参与覆盖率统计的 7 个因子列
WEEKLY_FACTOR_COLS = ("size", "valuation", "volility", "reverse",
                      "profit", "growth", "cash")

# 因子覆盖率下限：若窗口起点「上一周」的因子覆盖率低于此值，
# 则把窗口起点向前顺延至上一周（连续不足时持续顺延），避免漏算不完整的周。
WEEKLY_COVERAGE_MIN = 0.90


def _stock_factor_row_count() -> int:
    """stock_factor 当前行数（用于增量行数差分统计）。"""
    with get_session() as session:
        return int(session.query(StockFactor).count())


def _stock_factor_max_date():
    """stock_factor 当前最大 trade_date（无数据时返回 None）。"""
    with get_session() as session:
        row = (
            session.query(StockFactor.trade_date)
            .order_by(StockFactor.trade_date.desc())
            .first()
        )
    return row[0] if row and row[0] is not None else None


def _cross_section_coverage(trade_date: str) -> dict:
    """
    统计指定截面（trade_date）各因子列的覆盖率。

    覆盖率口径：该截面下，每个因子列的「非空股票数 / 该截面股票行数」；
    另给出最小值 min_ratio 及覆盖最差的因子 worst_factor。
    截面无任何行时 n=0、min_ratio=0（视为完全未覆盖）。
    """
    with get_session() as session:
        row = session.query(
            func.count().label("n"),
            *[func.count(getattr(StockFactor, c)).label(c)
              for c in WEEKLY_FACTOR_COLS],
        ).filter(StockFactor.trade_date == trade_date).one()

    n = int(row[0] or 0)
    if n == 0:
        return {"n": 0, "ratios": {c: 0.0 for c in WEEKLY_FACTOR_COLS},
                "min_ratio": 0.0, "worst_factor": None}
    ratios = {c: (row[i + 1] or 0) / n for i, c in enumerate(WEEKLY_FACTOR_COLS)}
    worst = min(ratios, key=ratios.get)
    return {"n": n, "ratios": ratios,
            "min_ratio": ratios[worst], "worst_factor": worst}


def _extend_start_by_coverage(start_date: str,
                              available: list,
                              threshold: float = WEEKLY_COVERAGE_MIN) -> tuple:
    """
    覆盖率守卫：若窗口起点「上一周（上一个可用截面）」的因子覆盖率不足 threshold，
    则把起点向前顺延至该周；连续不足时持续顺延，直到某周达标或已到可用序列开头。

    目的：避免把「只写了部分因子 / 只写了部分股票」的周当作已完成，导致漏周。

    返回 (新的 start_date, 顺延记录列表)；记录元素含被纳入的周、最小覆盖率与最差因子。
    """
    extended = []
    while True:
        prevs = [t for t in available if t < start_date]
        if not prevs:
            break
        prev = prevs[-1]
        cov = _cross_section_coverage(prev)
        if cov["min_ratio"] >= threshold:
            break
        worst = cov["worst_factor"]
        extended.append({
            "date": prev,
            "min_ratio": round(cov["min_ratio"], 4),
            "rows": cov["n"],
            "worst_factor": worst,
            "worst_ratio": round(cov["ratios"].get(worst, 0.0), 4) if worst else 0.0,
        })
        start_date = prev
    return start_date, extended


def _last_week_end(upto: str) -> str:
    """返回 upto（YYYYMMDD）所在周（含）之前最后一个周五，作为「最新周」参照。"""
    d = datetime.strptime(upto, "%Y%m%d").date()
    while d.weekday() != 4:  # 4 = Friday
        d = d - timedelta(days=1)
    return d.strftime("%Y%m%d")


def _check_factor_dependencies(end_date: str) -> dict:
    """
    因子依赖预检：打印基础数据最新日期与可用截面末值，判断是否就绪。

    就绪判定：可用截面（get_all_date 末值）应 >= 最新周（end_date 所在周的最后一个周五）。
    落后时仅告警、不中断，提示先执行基础数据周更（data_fetch.update_weekly）。
    """
    available = get_all_date() or []
    available_last = available[-1] if available else None

    with get_session() as session:
        db_row = (
            session.query(StockDailyBasic.trade_date)
            .filter(StockDailyBasic.trade_date.isnot(None))
            .order_by(StockDailyBasic.trade_date.desc())
            .first()
        )
        wi_row = (
            session.query(StockWeeklyIndicator.trade_date)
            .filter(StockWeeklyIndicator.trade_date.isnot(None))
            .order_by(StockWeeklyIndicator.trade_date.desc())
            .first()
        )
    db_max = db_row[0] if db_row else None
    wi_max = wi_row[0] if wi_row else None

    expected = _last_week_end(end_date)
    ready = bool(available_last and available_last >= expected)

    print("-" * 66)
    print("因子依赖预检")
    print("-" * 66)
    print(f"  stock_daily_basic       最新: {db_max}")
    print(f"  stock_weekly_indicator  最新: {wi_max}")
    print(f"  可用因子截面末值        最新: {available_last}（期望 >= {expected}）")
    if available_last is None:
        print("  [告警] 无可用截面：请先执行基础数据周更 data_fetch.update_weekly()")
    elif not ready:
        print("  [告警] 可用截面落后于最新周：建议先执行基础数据周更 data_fetch.update_weekly()")
    elif db_max and wi_max and available_last < min(db_max, wi_max):
        print("  [告警] 三表最新日期不一致（交集被滞后表限制）：建议先补齐基础数据")
    else:
        print("  [就绪] 依赖数据已更新至最新周")
    print("-" * 66)
    return {
        "expected_week_end": expected,
        "available_last": available_last,
        "daily_basic_max": db_max,
        "weekly_indicator_max": wi_max,
        "ready": ready,
    }


def cal_factors_weekly(start_date: str | None = None,
                       end_date: str | None = None) -> dict:
    """
    每周增量重算已实现的 7 个因子，使 stock_factor 随基础数据同步推进。

    窗口：
      - start_date 缺省取 stock_factor 现有 max(trade_date)（含边界，重算无害）；
      - end_date   缺省取今天；两者均可显式传入以覆盖（便于小窗口试跑）。

    历史依赖延展（关键）：
      - 波动率因子需向前延展 VOL_LOOKBACK_WEEKS 周（4 周累计换手率），
        反转因子需向前延展 REV_LOOKBACK_WEEKS 周（60 周均线乖离率）；
      - 延展一律在**因子函数内部**完成，本驱动**不**在窗口层面前移 start，
        从而保证所有因子的落库窗口严格保持 [start_date, end_date]、不改写历史存量。

    覆盖率守卫（仅当 start_date 缺省、由函数自动推导时生效）：
      - 若「上一周（上一个可用截面）」的 7 因子覆盖率不足 WEEKLY_COVERAGE_MIN
        （默认 90%；口径：该截面下每个因子列的非空股票数 / 该截面股票行数），
        即 7 个因子未覆盖该截面 90% 的股票时，把窗口起点向前顺延至该周；
      - 连续不足时持续向前顺延，直到某周达标或已到可用序列开头；
      - 显式传入 start_date 时不启用该守卫，保持调用者意图。

    其他：
      - 调用前做依赖预检（每日指标 / 周K技术指标 / 可用截面末值），落后仅告警不中断；
      - 窗口内无可用截面时直接返回；
      - 每个因子独立 try/except，单因子失败不阻断其余因子；
      - 落库沿用 upsert_stock_factor，幂等可重复执行。

    返回：
      {
        "start": str, "end": str, "window_dates": int,
        "dependencies": {...},
        "factors": {name: {"ok": bool, "elapsed": float, "rows_delta": int}},
        "factor_max_date": str | None,
        "coverage_extended": [{date, min_ratio, rows, worst_factor, worst_ratio}],
      }
    """
    print("\n" + "#" * 66)
    print("# 每周因子增量更新 start")
    print("#" * 66)

    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    # ---- 窗口起点解析：缺省取因子表现有最大日期（含边界），并做覆盖率守卫 ----
    available_all = get_all_date() or []
    coverage_extended: list = []
    if start_date is None:
        start_date = _stock_factor_max_date()
        if start_date is None:
            start_date = available_all[0] if available_all else None
            if start_date is not None:
                print(f"[cal_factors_weekly] stock_factor 无数据，"
                      f"从最早可用截面 {start_date} 起全量计算。")
        else:
            start_date, coverage_extended = _extend_start_by_coverage(
                start_date, available_all, WEEKLY_COVERAGE_MIN
            )
            if coverage_extended:
                detail = "、".join(
                    f"{e['date']}(最差={e['worst_factor']} {e['worst_ratio']:.1%})"
                    for e in coverage_extended
                )
                print(f"[cal_factors_weekly] 上一周因子覆盖率不足 "
                      f"{WEEKLY_COVERAGE_MIN:.0%}，窗口起点向前顺延至 {start_date}；"
                      f"顺延纳入: {detail}")

    if not start_date:
        print("[cal_factors_weekly] 无可用截面，退出。")
        return {"start": start_date, "end": end_date, "window_dates": 0,
                "dependencies": {}, "factors": {}, "factor_max_date": None,
                "coverage_extended": []}

    print(f"[cal_factors_weekly] 增量窗口（落库）: {start_date} ~ {end_date}")

    # ---- 依赖预检 ----
    deps = _check_factor_dependencies(end_date)

    # ---- 无新周短路 ----
    window_dates = [t for t in available_all if start_date <= t <= end_date]
    if not window_dates:
        print("[cal_factors_weekly] 窗口内无可用截面，无需重算（基础数据可能未更新）。")
        return {"start": start_date, "end": end_date, "window_dates": 0,
                "dependencies": deps, "factors": {},
                "factor_max_date": _stock_factor_max_date(),
                "coverage_extended": coverage_extended}
    print(f"[cal_factors_weekly] 窗口内可用截面 {len(window_dates)} 个"
          f"（{window_dates[0]} ~ {window_dates[-1]}）")

    # ---- 依次重算 7 个因子 ----
    results: dict = {}
    for name, fn in WEEKLY_FACTORS:
        print("\n" + "=" * 66)
        print(f"[cal_factors_weekly] 计算因子：{name}")
        print("=" * 66)
        t0 = time.time()
        c0 = _stock_factor_row_count()
        try:
            fn(start_date, end_date)
            c1 = _stock_factor_row_count()
            results[name] = {"ok": True, "elapsed": round(time.time() - t0, 2),
                             "rows_delta": c1 - c0}
        except Exception as e:
            results[name] = {"ok": False, "elapsed": round(time.time() - t0, 2),
                             "rows_delta": 0, "error": str(e)}
            print(f"[cal_factors_weekly] 因子 {name} 失败（已跳过，继续后续因子）：{e}")

    new_max = _stock_factor_max_date()

    # ---- 汇总 ----
    print("\n" + "=" * 66)
    print("每周因子增量更新 · 汇总")
    print("=" * 66)
    print(f"窗口: {start_date} ~ {end_date}（可用截面 {len(window_dates)} 个）")
    print(f"{'因子':<12}{'状态':<8}{'耗时(s)':<12}{'新增行数'}")
    print("-" * 66)
    for name, info in results.items():
        status = "OK" if info["ok"] else "FAIL"
        print(f"{name:<12}{status:<8}{info['elapsed']:<12}{info['rows_delta']}")
    print("-" * 66)
    expected = deps.get("expected_week_end")
    print(f"stock_factor.max(trade_date): {new_max}"
          + (f"（期望 >= {expected}）" if expected else ""))
    print("=" * 66)
    print("# 每周因子增量更新 end")
    print("#" * 66 + "\n")

    return {"start": start_date, "end": end_date, "window_dates": len(window_dates),
            "dependencies": deps, "factors": results, "factor_max_date": new_max,
            "coverage_extended": coverage_extended}


# ======================================================================
# 5. 本地测试入口（仅用于调试，直接 `python factor.py` 运行）
#    - 测试0：构造假截面数据，验证 cal_all_factors 骨架聚合与 13 列对齐。
#    - 测试1：调用真实 cal_size_factor()，逐交易日计算并落库规模因子。
#    - 测试2：调用真实 cal_valuation_factor()，逐交易日计算并落库估值因子。
#    - 测试3：调用真实 cal_volatility_factor()，逐周频截面计算并落库波动率因子。
#    - 测试4：调用真实 cal_reverse_factor()，逐周频截面计算并落库反转因子。
#    - 测试5：调用真实 cal_profit_factor()，逐交易日计算并落库盈利因子。
#    - 测试6：调用真实 cal_growth_factor()，逐交易日计算并落库成长因子。
#    - 测试7：调用真实 cal_cash_factor()，逐交易日计算并落库现金因子。
# ======================================================================
if __name__ == "__main__":
    # 每周增量重算因子：自动解析窗口 → 依次调用 7 个因子 → 汇总耗时/行数
    cal_factors_weekly()

    # ===================== 历史参考：旧测试块（保留备查，不再执行）=====================
    '''
    # ===================== 测试1：真实规模因子计算 =====================
    print("\n" + "=" * 70)
    print("测试1：调用真实 cal_size_factor() 逐交易日计算并落库")
    print("=" * 70)
    cal_size_factor()
    #cal_size_factor("20180601","20211231")
    print("测试1 完成：规模因子已写入 StockFactor 表。")
    
    # ===================== 测试2：真实估值因子计算 =====================
    print("\n" + "=" * 70)
    print("测试2：调用真实 cal_valuation_factor() 逐交易日计算并落库")
    print("=" * 70)
    cal_valuation_factor()
    #cal_valuation_factor("20180601","20211231")
    print("测试2 完成：估值因子已写入 StockFactor 表。")
    
    # ===================== 测试3：真实波动率因子计算 =====================
    print("\n" + "=" * 70)
    print("测试3：调用真实 cal_volatility_factor() 逐周频截面计算并落库")
    print("=" * 70)
    cal_volatility_factor()
    #cal_volatility_factor("20180601","20211231")
    print("测试3 完成：波动率因子已写入 StockFactor 表。")
    
    # ===================== 测试4：真实反转因子计算 =====================
    print("\n" + "=" * 70)
    print("测试4：调用真实 cal_reverse_factor() 逐周频截面计算并落库反转因子")
    print("=" * 70)
    cal_reverse_factor()
    #cal_reverse_factor("20180601","20211231")
    print("测试4 完成：反转因子已写入 StockFactor 表。")
    # ===================== 测试5：真实盈利因子计算 =====================
    print("\n" + "=" * 70)
    print("测试5：调用真实 cal_profit_factor() 逐交易日计算并落库盈利因子")
    print("=" * 70)
    cal_profit_factor()
    #cal_profit_factor("20180601","20211231")
    print("测试5 完成：盈利因子已写入 StockFactor 表。")
    
    # ===================== 测试6：真实成长因子计算 =====================
    print("\n" + "=" * 70)
    print("测试6：调用真实 cal_growth_factor() 逐交易日计算并落库成长因子")
    print("=" * 70)
    cal_growth_factor()
    #cal_growth_factor("20180601","20211231")
    print("测试6 完成：成长因子已写入 StockFactor 表。")
    
    # ===================== 测试7：真实现金因子计算 =====================
    print("\n" + "=" * 70)
    print("测试7：调用真实 cal_cash_factor() 逐交易日计算并落库现金因子")
    print("=" * 70)
    cal_cash_factor()
    #cal_cash_factor("20180601","20211231")
    print("测试7 完成：现金因子已写入 StockFactor 表。")
    '''
    

    
    
    
