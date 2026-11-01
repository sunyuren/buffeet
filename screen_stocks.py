# -*- coding: utf-8 -*-
"""
临时脚本：基于 stock_factor 最新一期截面，筛选两类建仓候选公司。

第一类（价值型）：中大盘 + 低估值/高股息 + 盈利强 + 低波动 + 原始股息率达标；
                「反转(超卖)」作为综合分权重（软条件/选时机），不做硬性过滤。
第二类（成长型）：中小盘 + 估值尚可 + 高增长

因子方向（已核对实现）：7 个因子均为「分越高越好」——
  size     分越高 = 市值/收入/利润越大；
  valuation 分越高 = 低估值 + 高股息（PE/PB/PS 取倒数 + 股息率正向）；
  volility 分越高 = 低换手/低振幅；reverse 分越高 = 超卖（向下偏离）；
  profit / growth / cash 分越高 = 盈利 / 成长 / 现金质量越好。

输出：output/screen_value_<date>.csv、output/screen_growth_<date>.csv（utf-8-sig）。
说明：一次性选股用途，确认结果后可删除；所有阈值/权重集中在下方 CONFIG 区。
"""
import os
import sqlite3

import pandas as pd

# ================================ CONFIG ================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "raw", "stock.db")
OUT_DIR = os.path.join(BASE_DIR, "output")

EXCLUDE_KEYWORDS = ("ST", "退")   # 名称含这些关键字即从股票池剔除
TOP_N_PRINT = 30                  # 控制台各打印前 N 只

# ---- 第一类：价值型 ----
VALUE = {
    # 硬条件（选公司）
    "size_min": 0,        # 规模：中大盘（横截面中位以上）
    "valuation_min": 50,  # 低估值（已含高股息）
    "profit_min": 50,     # 盈利能力强
    "volility_min": 50,   # 低波动（低换手/低振幅）
    "dv_ttm_min": 2.0,    # 原始股息率下限（%，来自 stock_daily_basic.dv_ttm）
    # 软条件（选时机）：反转不做硬过滤，改为综合分权重（C 方案，权重和 = 1.0）
    "score_weights": {"reverse": 0.20, "valuation": 0.25, "profit": 0.25,
                      "volility": 0.15, "size": 0.15},
    "csv": "screen_value",
}

# ---- 第二类：成长型 ----
GROWTH = {
    "size_max": 0,        # 规模：中小盘（横截面中位以下）
    "valuation_min": 0,   # 估值尚可（不低于横截面中位，即未被高估太离谱）
    "growth_min": 50,     # 高增长
    "score_weights": {"growth": 0.60, "valuation": 0.40},
    "csv": "screen_growth",
}
# =======================================================================

FACTOR_COLS = ["size", "valuation", "volility", "reverse",
               "profit", "growth", "cash"]
OUT_COLS = ["ts_code", "name", "industry", "score",
            "size", "valuation", "volility", "reverse",
            "profit", "growth", "cash", "dv_ttm"]


def _composite(df: pd.DataFrame, weights: dict) -> pd.Series:
    """按权重对指定因子列加权求和，作为名单排序用的综合分。"""
    return sum(df[k] * w for k, w in weights.items())


def _report(tag: str, res: pd.DataFrame, cfg: dict, date: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"{tag}：命中 {len(res)} 只")
    print(f"{'=' * 70}")
    if res.empty:
        print("（无满足条件的公司）")
        return
    path = os.path.join(OUT_DIR, f"{cfg['csv']}_{date}.csv")
    res[OUT_COLS].to_csv(path, index=False, encoding="utf-8-sig")
    print(f"[已保存] {path}")
    show = res[OUT_COLS].head(TOP_N_PRINT)
    print(show.to_string(index=False))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)

    latest = pd.read_sql("SELECT MAX(trade_date) m FROM stock_factor", con).iloc[0, 0]
    print(f"筛选截面（最新一期）: {latest}")
    print(f"第一类阈值: {VALUE}\n第二类阈值: {GROWTH}")

    fac = pd.read_sql(
        "SELECT ts_code, name, industry, trade_date, " + ", ".join(FACTOR_COLS)
        + " FROM stock_factor WHERE trade_date = ?", con, params=(latest,))
    dv = pd.read_sql(
        "SELECT ts_code, dv_ttm FROM stock_daily_basic WHERE trade_date = ?",
        con, params=(latest,))
    con.close()

    df = fac.merge(dv, on="ts_code", how="left")
    print(f"\n全市场截面: {len(df)} 只；dv_ttm 覆盖 {df['dv_ttm'].notna().sum()} 只")

    # 剔除 ST / 退
    pattern = "|".join(EXCLUDE_KEYWORDS)
    keep = ~df["name"].fillna("").str.contains(pattern, regex=True)
    df = df[keep].copy()
    print(f"剔除含『{pattern}』后: {len(df)} 只")

    # ---------------- 第一类：价值型 ----------------
    c = VALUE
    v = df.dropna(subset=["size", "valuation", "profit",
                          "volility", "reverse", "dv_ttm"]).copy()
    v = v[(v["size"] >= c["size_min"])
          & (v["valuation"] >= c["valuation_min"])
          & (v["profit"] >= c["profit_min"])
          & (v["volility"] >= c["volility_min"])
          & (v["dv_ttm"] >= c["dv_ttm_min"])]
    v["score"] = _composite(v, c["score_weights"]).round(2)
    v = v.sort_values("score", ascending=False)

    # ---------------- 第二类：成长型 ----------------
    c2 = GROWTH
    g = df.dropna(subset=["size", "valuation", "growth"]).copy()
    g = g[(g["size"] <= c2["size_max"])
          & (g["valuation"] >= c2["valuation_min"])
          & (g["growth"] >= c2["growth_min"])]
    g["score"] = _composite(g, c2["score_weights"]).round(2)
    g = g.sort_values("score", ascending=False)

    _report("第一类 · 价值型（中大盘/低估值/高分红/盈利强/低波动；反转计入打分）",
            v, VALUE, latest)
    _report("第二类 · 成长型（中小盘/估值尚可/高增长）", g, GROWTH, latest)


if __name__ == "__main__":
    main()
