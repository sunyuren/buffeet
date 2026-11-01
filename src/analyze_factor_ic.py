#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
因子有效性分析：规模(size) / 估值(valuation) / 波动(volility) / 反转(reverse) / 盈利(profit) / 成长(growth) / 现金(cash)
- 数据分布：覆盖度、min/max/mean/median/std、分桶直方图
- 有效性：Rank IC / ICIR / 正率 / t 值（分日期截面 Spearman 相关）
    * 六因子统一：基于 stock_weekly 的前向两档窗口收益（12周≈3个月、60周≈约1年）分别分析
- 分行业 IC：在每个行业内做截面 Rank IC，再按行业汇总均值/ICIR/正率（仅展示与汇总，
  不再输出每因子单独的 ic_industry_{label}.csv）
- 因子 IR 汇总：IR = IC 均值 / IC 标准差（即 ICIR），横向比较各因子有效性
依赖：pandas, numpy, matplotlib（无需 scipy，用 rank+pearson 实现 Spearman）
用法：改 CONFIG / FACTORS 后 `python src/analyze_factor_ic.py`
"""
import sqlite3
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


def _setup_cjk_font():
    """设置中文字体，避免图表中文显示为方框（豆腐块）。

    优先使用 matplotlib 自动发现（启动时已扫描系统字体目录）的 CJK 字体；
    仅在未发现时，才兜底手动加载常见中文字体文件并用 fontManager.addfont 注册。
    """
    available = {f.name for f in fm.fontManager.ttflist}
    preferred = ["Microsoft YaHei", "SimHei", "SimSun", "PingFang SC",
                 "Noto Sans CJK SC", "WenQuanYi Micro Hei"]
    chosen = [n for n in preferred if n in available]

    # 兜底：扫描系统字体目录，手动注册常见中文字体文件
    if not chosen:
        font_dirs = [r"C:\Windows\Fonts", "/usr/share/fonts", "/System/Library/Fonts"]
        files = ["msyh.ttc", "simhei.ttf", "simsun.ttc", "msyh.ttf", "simsun.ttf"]
        for d in font_dirs:
            if not os.path.isdir(d):
                continue
            for fname in files:
                p = os.path.join(d, fname)
                if os.path.exists(p):
                    try:
                        fm.fontManager.addfont(p)
                        chosen.append(fm.FontProperties(fname=p).get_name())
                    except Exception:
                        pass
            if chosen:
                break

    if chosen:
        # 去重并保留顺序，最后回退到 DejaVu Sans
        seen, uniq = set(), []
        for n in chosen + ["DejaVu Sans"]:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        plt.rcParams["font.sans-serif"] = uniq
    plt.rcParams["axes.unicode_minus"] = False  # 让负号正常显示


_setup_cjk_font()

# ----------------------------- CONFIG -----------------------------
DB_PATH  = r"data/raw/stock.db"   # 相对项目根；如不符请改绝对路径
START    = "20180101"             # 分析起始日 YYYYMMDD
END      = "20251231"             # 分析结束日
H_WEEKLY_LIST = [12, 60]          # 前向持有周数：12周(约3个月) 与 60周(约1年) 两档
MIN_CS   = 30                     # 全市场单截面最少股票数（低于则跳过该日）
MIN_CS_I = 10                     # 行业内单截面最少股票数（分行业 IC 用）
OUT_DIR  = "output"               # 图片输出目录
# ------------------------------------------------------------------

# 因子列表：(数据库列名, 展示名)；新增/调整因子只需在此追加一行
FACTORS = [
    ("size",      "规模"),
    ("valuation", "估值"),
    ("volility",  "波动"),
    ("reverse",   "反转"),
    ("profit",    "盈利"),
    ("growth",    "成长"),
    ("cash",      "现金"),

]


def _rank_ic(sub_f, sub_w):
    """对一组 (因子值, 前向收益) 计算 Spearman 秩相关（返回 NaN 表示无效）。"""
    m = sub_f.notna() & sub_w.notna()
    if m.sum() < 2:
        return np.nan
    r1, r2 = sub_f[m].rank(), sub_w[m].rank()
    if r1.nunique() < 2 or r2.nunique() < 2:
        return np.nan
    return np.corrcoef(r1, r2)[0, 1]


def ic_series(df, fcol, wcol, min_cs):
    """逐 trade_date 截面计算 Rank IC，返回 (trade_date -> ic) 的 Series。"""
    res = {}
    for td, sub in df.groupby("trade_date"):
        s1, s2 = sub[fcol], sub[wcol]
        if s1.notna().sum() < min_cs or s2.notna().sum() < min_cs:
            continue
        ic = _rank_ic(s1, s2)
        if pd.notna(ic):
            res[td] = ic
    return pd.Series(res).sort_index()


def report_ic(ic, label):
    if ic.empty:
        print(f"{label}: 无有效截面（检查日期区间/收益表）")
        return
    mean_ic, std_ic = ic.mean(), ic.std()
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    pos = (ic > 0).mean()
    t = mean_ic / (std_ic / np.sqrt(len(ic))) if std_ic > 0 else np.nan
    print(f"\n--- {label} ---")
    print(f"截面数={len(ic)}  均值IC={mean_ic:.4f}  标准差={std_ic:.4f}  "
          f"ICIR={icir:.4f}  正率={pos:.3f}  t={t:.2f}")
    fig, ax = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    ax[0].plot(ic.index, ic.values, color="#C44E52", lw=0.8, label="IC")
    ax[0].axhline(mean_ic, color="k", ls="--", lw=1, label=f"均值={mean_ic:.3f}")
    ax[0].set_title(f"{label} Rank IC 时序"); ax[0].legend()
    cum = ic.cumsum()
    ax[1].plot(cum.index, cum.values, color="#55A868", lw=1, label="累计IC")
    ax[1].axhline(0, color="k", lw=0.5); ax[1].legend()
    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, f"ic_{label}.png"), dpi=120)
    print(f"[已保存] {OUT_DIR}/ic_{label}.png")


def ic_by_industry(df, fcol, wcol, min_cs, label):
    """在每个行业内做截面 Rank IC，再按行业汇总。返回 DataFrame。"""
    recs = []
    for ind, g in df.groupby("industry"):
        if g[fcol].notna().sum() < min_cs:
            continue
        per_date = {}
        for td, sub in g.groupby("trade_date"):
            s1, s2 = sub[fcol], sub[wcol]
            if s1.notna().sum() < min_cs or s2.notna().sum() < min_cs:
                continue
            ic = _rank_ic(s1, s2)
            if pd.notna(ic):
                per_date[td] = ic
        if not per_date:
            continue
        ic = pd.Series(per_date)
        std_ic = ic.std()
        recs.append({
            "industry": ind,
            "n_dates": len(ic),
            "mean_ic": round(ic.mean(), 4),
            "std_ic": round(std_ic, 4) if std_ic == std_ic else np.nan,
            "icir": round(ic.mean() / std_ic, 4) if std_ic and std_ic > 0 else np.nan,
            "pos_ratio": round((ic > 0).mean(), 3),
        })
    res = pd.DataFrame(recs).sort_values("mean_ic", ascending=False)
    print(f"\n--- {label} 分行业 IC（按均值IC降序）---")
    if res.empty:
        print("无足够样本的行业")
    else:
        print(res.to_string(index=False))
        fig, ax = plt.subplots(figsize=(12, max(4, 0.4 * len(res))))
        ax.barh(res["industry"][::-1], res["mean_ic"][::-1], color="#4C72B0")
        ax.axvline(0, color="k", lw=0.6)
        ax.set_title(f"{label} 分行业 Rank IC（均值）")
        plt.tight_layout()
        fig.savefig(os.path.join(OUT_DIR, f"ic_industry_{label}.png"), dpi=120)
        print(f"[已保存] {OUT_DIR}/ic_industry_{label}.png")
    return res


def report_ic_summary(ic_map, label="全因子 IR 汇总", h=None):
    """汇总所有因子的 IC 与 IR（横向比较有效性）。

    IR（信息比率）= IC 序列均值 / 标准差，等价于 ICIR；另给出均值 IC、IC 标准差、
    正率与 t 值。按 IR 降序排列，并打印 / 保存 CSV。
    """
    rows = []
    for name, ic in ic_map.items():
        if ic is None or ic.empty:
            continue
        mean_ic, std_ic = ic.mean(), ic.std()
        ir = mean_ic / std_ic if std_ic > 0 else np.nan
        pos = (ic > 0).mean()
        t = mean_ic / (std_ic / np.sqrt(len(ic))) if std_ic > 0 else np.nan
        rows.append({
            "factor": name, "n": len(ic),
            "mean_ic": round(mean_ic, 4), "std_ic": round(std_ic, 4),
            "IR": round(ir, 4), "pos_ratio": round(pos, 3), "t": round(t, 2),
        })
    res = pd.DataFrame(rows).sort_values("IR", ascending=False)
    print(f"\n--- {label} ---")
    if res.empty:
        print("无有效因子")
    else:
        print(res.to_string(index=False))
        csv_path = os.path.join(OUT_DIR, f"ic_ir_summary_{h}w.csv")
        res.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"[已保存] {csv_path}")
    return res


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)

    # 1) 因子表（仅取分析区间内，含前向收益所需的截面）
    factor = pd.read_sql(
        f"SELECT ts_code, trade_date, size, valuation, volility, reverse, profit, growth, cash, industry "
        f"FROM stock_factor WHERE trade_date BETWEEN '{START}' AND '{END}'", con)
    factor["industry"] = factor["industry"].fillna("未知")

    # 2) 周频收盘价 -> 向前多档窗口收益（12周≈3个月、60周≈约1年）
    weekly = pd.read_sql(
        f"SELECT ts_code, trade_date, close FROM stock_weekly "
        f"WHERE trade_date BETWEEN '{START}' AND '{END}' AND close IS NOT NULL", con)
    weekly = weekly.sort_values(["ts_code", "trade_date"])
    for h in H_WEEKLY_LIST:
        weekly[f"fwd_ret_{h}w"] = weekly.groupby("ts_code")["close"].transform(
            lambda s: s.shift(-h) / s - 1.0)

    # 3) 合并前向多档窗口收益到因子表
    f = factor.copy()
    f = f.merge(weekly[["ts_code", "trade_date"] + [f"fwd_ret_{h}w" for h in H_WEEKLY_LIST]],
                on=["ts_code", "trade_date"], how="left")

    # ----------------------- 数据分布 -----------------------
    print("=" * 60); print("1) 数据分布"); print("=" * 60)
    cols = [c for c, _ in FACTORS]
    rows = []
    for col in cols:
        s = f[col].dropna(); total = len(f)
        rows.append({
            "factor": col, "total_rows": total, "non_null": len(s),
            "coverage_%": round(100 * len(s) / total, 2),
            "min": int(s.min()), "max": int(s.max()),
            "mean": round(s.mean(), 3), "median": round(s.median(), 3),
            "std": round(s.std(), 3),
        })
    print(pd.DataFrame(rows).to_string(index=False))

    bins = [-101, -70, -40, -10, 20, 50, 80, 101]
    labels = ["[-100,-70)", "[-70,-40)", "[-40,-10)", "[-10,20)",
              "[20,50)", "[50,80)", "[80,100]"]
    n = len(cols)
    ncols = min(n, 4); nrows = (n + ncols - 1) // ncols
    fig, axes = plt.subplots(nrows, ncols, figsize=(6 * ncols, 5),
                             squeeze=False)
    for ax, col in zip(axes.flat, cols):
        s = f[col].dropna().clip(-100, 100)
        vc = pd.cut(s, bins=bins, labels=labels, include_lowest=True).value_counts().reindex(labels).fillna(0)
        print(f"\n--- {col} 分桶 ---\n{vc.to_string()}")
        ax.bar(range(len(vc)), vc.values, color="#4C72B0")
        ax.set_xticks(range(len(vc))); ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_title(f"{col} 分布")
    plt.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "factor_distribution.png"), dpi=120)
    print(f"\n[已保存] {OUT_DIR}/factor_distribution.png")

    # ----------------------- 全市场 IC（两档窗口：12周 / 60周） -----------------------
    for h in H_WEEKLY_LIST:
        wcol = f"fwd_ret_{h}w"
        print("\n" + "=" * 60); print(f"2) 全市场 Rank IC 等有效性指标（前向 {h} 周）"); print("=" * 60)
        ic_map = {}
        for col, name in [(c, f"{n}_{h}w") for c, n in FACTORS]:
            ic = ic_series(f.dropna(subset=[col, wcol]), col, wcol, MIN_CS)
            ic_map[name] = ic
            report_ic(ic, name)
        # 各因子 IR 汇总（IR = IC 均值 / IC 标准差，即 ICIR，横向比较有效性）
        report_ic_summary(ic_map, label=f"全因子 IR 汇总（前向 {h} 周）", h=h)

    # ----------------------- 分行业 IC（两档窗口，仅展示与汇总，不再输出单因子行业的csv） -----------------------
    for h in H_WEEKLY_LIST:
        wcol = f"fwd_ret_{h}w"
        print("\n" + "=" * 60); print(f"3) 分行业 Rank IC（前向 {h} 周）"); print("=" * 60)
        ind_frames = []
        for col, name in [(c, f"{n}_{h}w") for c, n in FACTORS]:
            r = ic_by_industry(f.dropna(subset=[col, wcol]), col, wcol, MIN_CS_I, name)
            if r is not None and not r.empty:
                r = r.copy(); r.insert(0, "factor", name); ind_frames.append(r)
        if ind_frames:
            all_ind = pd.concat(ind_frames, ignore_index=True)
            all_path = os.path.join(OUT_DIR, f"ic_industry_all_{h}w.csv")
            all_ind.to_csv(all_path, index=False, encoding="utf-8-sig")
            print(f"[已保存] {all_path}（共 {len(all_ind)} 行行业记录）")

    con.close()
    print("\n完成。")


if __name__ == "__main__":
    main()
