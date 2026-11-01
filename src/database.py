# -*- coding: utf-8 -*-
"""
数据库管理模块
使用 SQLAlchemy 2.0 ORM 管理 SQLite 数据库
"""

import sys
import os
from contextlib import contextmanager
from datetime import datetime, date

import pandas as pd
from sqlalchemy import create_engine, String, Float, Boolean, Text, Integer, DateTime, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DATABASE_URL


# ========== 声明式基类 ==========
class Base(DeclarativeBase):
    pass


# ========== ORM 模型 ==========
class StockList(Base):
    """
    股票清单表（对应 Tushare stock_basic 接口）
    https://tushare.pro/document/2?doc_id=25
    """

    __tablename__ = "stock_list"

    # ---- 主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="Tushare 代码，如 600000.SH"
    )

    # ---- 标识 ----
    symbol: Mapped[str] = mapped_column(
        String(10), nullable=False, comment="股票代码，如 600000"
    )
    name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="股票名称"
    )

    # ---- 市场 / 地域 ----
    area: Mapped[str | None] = mapped_column(
        String(50), comment="所在地域"
    )
    industry: Mapped[str | None] = mapped_column(
        String(50), comment="所属行业"
    )
    market: Mapped[str | None] = mapped_column(
        String(20), comment="市场类型：主板/创业板/科创板/北交所"
    )
    exchange: Mapped[str | None] = mapped_column(
        String(10), comment="交易所代码：SSE/SZSE/BSE"
    )

    # ---- 上市状态 ----
    list_status: Mapped[str | None] = mapped_column(
        String(4), comment="上市状态：L上市/D退市/G过会未交易/P暂停上市"
    )
    list_date: Mapped[str | None] = mapped_column(
        String(20), comment="上市日期"
    )
    delist_date: Mapped[str | None] = mapped_column(
        String(20), comment="退市日期"
    )
    is_hs: Mapped[str | None] = mapped_column(
        String(4), comment="沪深港通标的：N/H/S"
    )

    # ---- 实控人 ----
    act_name: Mapped[str | None] = mapped_column(
        String(100), comment="实控人名称"
    )
    act_ent_type: Mapped[str | None] = mapped_column(
        String(50), comment="实控人企业类型"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return f"<StockList(ts_code={self.ts_code}, name={self.name})>"


class StockManagers(Base):
    """
    公司高管信息表（对应 Tushare stk_managers 接口）
    https://tushare.pro/document/2?doc_id=208

    联合主键：ts_code + ann_date + name + title
    """

    __tablename__ = "stock_managers"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    ann_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="公告日期"
    )
    name: Mapped[str] = mapped_column(
        String(100), primary_key=True, comment="姓名"
    )
    title: Mapped[str] = mapped_column(
        String(100), primary_key=True, default="", comment="岗位"
    )

    # ---- 基本信息 ----
    gender: Mapped[str | None] = mapped_column(
        String(10), comment="性别"
    )
    lev: Mapped[str | None] = mapped_column(
        String(50), comment="岗位类别"
    )
    edu: Mapped[str | None] = mapped_column(
        String(50), comment="学历"
    )
    national: Mapped[str | None] = mapped_column(
        String(50), comment="国籍"
    )

    # ---- 日期 ----
    birthday: Mapped[str | None] = mapped_column(
        String(20), comment="出生年月日"
    )
    begin_date: Mapped[str | None] = mapped_column(
        String(20), comment="上任日期"
    )
    end_date: Mapped[str | None] = mapped_column(
        String(20), comment="离任日期"
    )

    # ---- 简历 ----
    resume: Mapped[str | None] = mapped_column(
        Text, comment="个人简历"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return (
            f"<StockManagers(ts_code={self.ts_code}, "
            f"ann_date={self.ann_date}, name={self.name}, title={self.title})>"
        )


class StockCompany(Base):
    """
    上市公司基本信息表（对应 Tushare stock_company 接口）
    https://tushare.pro/document/2?doc_id=25

    主键：ts_code（每只股票唯一）
    """

    __tablename__ = "stock_company"

    # ---- 主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )

    # ---- 基本信息 ----
    com_name: Mapped[str | None] = mapped_column(
        String(200), comment="公司全称"
    )
    com_id: Mapped[str | None] = mapped_column(
        String(50), comment="统一社会信用代码"
    )
    exchange: Mapped[str | None] = mapped_column(
        String(10), comment="交易所代码"
    )

    # ---- 高管 ----
    chairman: Mapped[str | None] = mapped_column(
        String(100), comment="法人代表"
    )
    manager: Mapped[str | None] = mapped_column(
        String(100), comment="总经理"
    )
    secretary: Mapped[str | None] = mapped_column(
        String(100), comment="董秘"
    )

    # ---- 注册资本 ----
    reg_capital: Mapped[float | None] = mapped_column(
        Float, comment="注册资本(万元)"
    )

    # ---- 地域 ----
    province: Mapped[str | None] = mapped_column(
        String(50), comment="所在省份"
    )
    city: Mapped[str | None] = mapped_column(
        String(100), comment="所在城市"
    )

    # ---- 公司详情 ----
    introduction: Mapped[str | None] = mapped_column(
        Text, comment="公司介绍"
    )
    employees: Mapped[int | None] = mapped_column(
        Integer, comment="员工人数"
    )
    main_business: Mapped[str | None] = mapped_column(
        Text, comment="主要业务及产品"
    )
    business_scope: Mapped[str | None] = mapped_column(
        Text, comment="经营范围"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return f"<StockCompany(ts_code={self.ts_code}, com_name={self.com_name})>"


class StockBalancesheet(Base):
    """
    资产负债表（对应 Tushare balancesheet 接口）
    https://tushare.pro/document/2?doc_id=36

    联合主键：ts_code + end_date
    （一只股票每个报告期对应一条记录）
    """

    __tablename__ = "stock_balancesheet"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    end_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="报告期"
    )

    # ---- 基础字段 ----
    ann_date: Mapped[str | None] = mapped_column(
        String(20), comment="公告日期"
    )
    f_ann_date: Mapped[str | None] = mapped_column(
        String(20), comment="实际公告日期"
    )
    report_type: Mapped[str | None] = mapped_column(
        String(20), comment="报表类型(1一般工商业2银行3保险4证券)"
    )
    comp_type: Mapped[str | None] = mapped_column(
        String(10), comment="公司类型(1一般工商业2银行3保险4证券)"
    )
    end_type: Mapped[str | None] = mapped_column(
        String(10), comment="报告期类型"
    )

    # ---- 资产总计 ----
    total_assets: Mapped[float | None] = mapped_column(
        Float, comment="资产总计"
    )

    # ---- 金融资产 ----
    money_cap: Mapped[float | None] = mapped_column(
        Float, comment="货币资金"
    )
    trad_asset: Mapped[float | None] = mapped_column(
        Float, comment="交易性金融资产"
    )
    lt_eqt_invest: Mapped[float | None] = mapped_column(
        Float, comment="长期股权投资"
    )
    invest_real_estate: Mapped[float | None] = mapped_column(
        Float, comment="投资性房地产"
    )

    # ---- 经营性资产 ----
    notes_receiv: Mapped[float | None] = mapped_column(
        Float, comment="应收票据"
    )
    accounts_receiv: Mapped[float | None] = mapped_column(
        Float, comment="应收账款"
    )
    prepayment: Mapped[float | None] = mapped_column(
        Float, comment="预付款项"
    )
    oth_receiv: Mapped[float | None] = mapped_column(
        Float, comment="其他应收款"
    )
    inventories: Mapped[float | None] = mapped_column(
        Float, comment="存货"
    )
    contract_assets: Mapped[float | None] = mapped_column(
        Float, comment="合同资产"
    )
    oth_cur_assets: Mapped[float | None] = mapped_column(
        Float, comment="其他流动资产"
    )

    # ---- 生产性资产 ----
    fix_assets: Mapped[float | None] = mapped_column(
        Float, comment="固定资产"
    )
    cip: Mapped[float | None] = mapped_column(
        Float, comment="在建工程"
    )
    lt_rec: Mapped[float | None] = mapped_column(
        Float, comment="长期应收款"
    )
    oil_and_gas_assets: Mapped[float | None] = mapped_column(
        Float, comment="油气资产"
    )
    produc_bio_assets: Mapped[float | None] = mapped_column(
        Float, comment="生产性生物资产"
    )
    intan_assets: Mapped[float | None] = mapped_column(
        Float, comment="无形资产"
    )
    r_and_d: Mapped[float | None] = mapped_column(
        Float, comment="开发支出（研发支出）"
    )
    goodwill: Mapped[float | None] = mapped_column(
        Float, comment="商誉"
    )

    # ---- 负债合计 ----
    total_liab: Mapped[float | None] = mapped_column(
        Float, comment="负债合计"
    )

    # ---- 带息负债 ----
    st_borr: Mapped[float | None] = mapped_column(
        Float, comment="短期借款"
    )
    trading_fl: Mapped[float | None] = mapped_column(
        Float, comment="交易性金融负债"
    )
    lt_borr: Mapped[float | None] = mapped_column(
        Float, comment="长期借款"
    )
    bond_payable: Mapped[float | None] = mapped_column(
        Float, comment="应付债券"
    )
    lt_payable: Mapped[float | None] = mapped_column(
        Float, comment="长期应付款"
    )

    # ---- 经营负债 ----
    notes_payable: Mapped[float | None] = mapped_column(
        Float, comment="应付票据"
    )
    acct_payable: Mapped[float | None] = mapped_column(
        Float, comment="应付账款"
    )
    adv_receipts: Mapped[float | None] = mapped_column(
        Float, comment="预收款项"
    )
    contract_liab: Mapped[float | None] = mapped_column(
        Float, comment="合同负债"
    )
    payroll_payable: Mapped[float | None] = mapped_column(
        Float, comment="应付职工薪酬"
    )
    taxes_payable: Mapped[float | None] = mapped_column(
        Float, comment="应交税费"
    )
    oth_payable: Mapped[float | None] = mapped_column(
        Float, comment="其他应付款"
    )

    # ---- 权益合计 ----
    total_liab_hldr_eqy: Mapped[float | None] = mapped_column(
        Float, comment="负债及股东权益总计"
    )
    minority_int: Mapped[float | None] = mapped_column(
        Float, comment="少数股东权益"
    )
    
    # ---- 股东投入 ----
    total_share: Mapped[float | None] = mapped_column(
        Float, comment="期末总股本"
    )
    cap_rese: Mapped[float | None] = mapped_column(
        Float, comment="资本公积金"
    )
    
    # ---- 资本累积 ----
    oth_comp_income: Mapped[float | None] = mapped_column(
        Float, comment="其他综合收益"
    )
    surplus_rese: Mapped[float | None] = mapped_column(
        Float, comment="盈余公积金"
    )
    undistr_porfit: Mapped[float | None] = mapped_column(
        Float, comment="未分配利润"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return (
            f"<StockBalancesheet(ts_code={self.ts_code}, "
            f"end_date={self.end_date})>"
        )


class StockIncome(Base):
    """
    利润表（对应 Tushare income 接口）
    https://tushare.pro/document/2?doc_id=44

    联合主键：ts_code + end_date
    （一只股票每个报告期对应一条记录）
    """

    __tablename__ = "stock_income"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    end_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="报告期"
    )

    # ---- 基础字段 ----
    ann_date: Mapped[str | None] = mapped_column(
        String(20), comment="公告日期"
    )
    f_ann_date: Mapped[str | None] = mapped_column(
        String(20), comment="实际公告日期"
    )
    report_type: Mapped[str | None] = mapped_column(
        String(20), comment="报表类型"
    )
    comp_type: Mapped[str | None] = mapped_column(
        String(10), comment="公司类型(1一般工商业2银行3保险4证券)"
    )
    end_type: Mapped[str | None] = mapped_column(
        String(10), comment="报告期类型"
    )

    # ---- 每股收益 ----
    basic_eps: Mapped[float | None] = mapped_column(
        Float, comment="基本每股收益"
    )
    diluted_eps: Mapped[float | None] = mapped_column(
        Float, comment="稀释每股收益"
    )

    # ---- 营收与成本 ----
    total_revenue: Mapped[float | None] = mapped_column(
        Float, comment="营业总收入"
    )
    revenue: Mapped[float | None] = mapped_column(
        Float, comment="营业收入"
    )
    total_cogs: Mapped[float | None] = mapped_column(
        Float, comment="营业总成本"
    )
    oper_cost: Mapped[float | None] = mapped_column(
        Float, comment="其中：营业成本"
    )
    biz_tax_surchg: Mapped[float | None] = mapped_column(
        Float, comment="营业税金及附加"
    )
    sell_exp: Mapped[float | None] = mapped_column(
        Float, comment="销售费用"
    )
    admin_exp: Mapped[float | None] = mapped_column(
        Float, comment="管理费用"
    )
    rd_exp: Mapped[float | None] = mapped_column(
        Float, comment="研发费用"
    )
    fin_exp: Mapped[float | None] = mapped_column(
        Float, comment="财务费用"
    )
    assets_impair_loss: Mapped[float | None] = mapped_column(
        Float, comment="资产减值损失"
    )
    credit_impa_loss: Mapped[float | None] = mapped_column(
        Float, comment="信用减值损失"
    )

    # ---- 收益类 ----
    fv_value_chg_gain: Mapped[float | None] = mapped_column(
        Float, comment="加:公允价值变动收益"
    )
    invest_income: Mapped[float | None] = mapped_column(
        Float, comment="投资收益"
    )
    asset_disp_income: Mapped[float | None] = mapped_column(
        Float, comment="资产处置收益"
    )
    oth_income: Mapped[float | None] = mapped_column(
        Float, comment="其他收益"
    )

    # ---- 利润 ----
    operate_profit: Mapped[float | None] = mapped_column(
        Float, comment="营业利润"
    )
    total_profit: Mapped[float | None] = mapped_column(
        Float, comment="利润总额"
    )
    income_tax: Mapped[float | None] = mapped_column(
        Float, comment="所得税费用"
    )
    n_income: Mapped[float | None] = mapped_column(
        Float, comment="净利润(含少数股东损益)"
    )
    n_income_attr_p: Mapped[float | None] = mapped_column(
        Float, comment="净利润(不含少数股东损益)"
    )
    oth_compr_income: Mapped[float | None] = mapped_column(
        Float, comment="其他综合收益"
    )
    t_compr_income: Mapped[float | None] = mapped_column(
        Float, comment="综合收益总额"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return (
            f"<StockIncome(ts_code={self.ts_code}, "
            f"end_date={self.end_date})>"
        )


class StockCashflow(Base):
    """
    现金流量表（对应 Tushare cashflow 接口）
    https://tushare.pro/document/2?doc_id=45

    联合主键：ts_code + end_date
    （一只股票每个报告期对应一条记录）
    日期类字段（ann_date/f_ann_date/end_date）按需求统一使用字符串存储，
    便于与 Tushare 原始返回及 fetch 续传逻辑保持一致。
    """

    __tablename__ = "stock_cashflow"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    end_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="报告期"
    )

    # ---- 基础字段 ----
    ann_date: Mapped[str | None] = mapped_column(
        String(20), comment="公告日期"
    )
    f_ann_date: Mapped[str | None] = mapped_column(
        String(20), comment="实际公告日期"
    )
    report_type: Mapped[str | None] = mapped_column(
        String(20), comment="报表类型"
    )
    comp_type: Mapped[str | None] = mapped_column(
        String(10), comment="公司类型(1一般工商业2银行3保险4证券)"
    )
    end_type: Mapped[str | None] = mapped_column(
        String(10), comment="报告期类型"
    )

    # ---- 经营活动现金流量 ----
    c_fr_sale_sg: Mapped[float | None] = mapped_column(
        Float, comment="销售商品、提供劳务收到的现金"
    )
    recp_tax_rends: Mapped[float | None] = mapped_column(
        Float, comment="收到的税费返还"
    )
    c_fr_oth_operate_a: Mapped[float | None] = mapped_column(
        Float, comment="收到其他与经营活动有关的现金"
    )
    c_inf_fr_operate_a: Mapped[float | None] = mapped_column(
        Float, comment="经营活动现金流入小计"
    )
    c_paid_goods_s: Mapped[float | None] = mapped_column(
        Float, comment="购买商品、接受劳务支付的现金"
    )
    c_paid_to_for_empl: Mapped[float | None] = mapped_column(
        Float, comment="支付给职工以及为职工支付的现金"
    )
    c_paid_for_taxes: Mapped[float | None] = mapped_column(
        Float, comment="支付的各项税费"
    )
    oth_cash_pay_oper_act: Mapped[float | None] = mapped_column(
        Float, comment="支付其他与经营活动有关的现金"
    )
    st_cash_out_act: Mapped[float | None] = mapped_column(
        Float, comment="经营活动现金流出小计"
    )
    n_cashflow_act: Mapped[float | None] = mapped_column(
        Float, comment="经营活动产生的现金流量净额"
    )

    # ---- 投资活动现金流量 ----
    c_disp_withdrwl_invest: Mapped[float | None] = mapped_column(
        Float, comment="收回投资收到的现金"
    )
    n_recp_disp_fiolta: Mapped[float | None] = mapped_column(
        Float, comment="处置固定资产、无形资产和其他长期资产收回的现金净额"
    )
    stot_inflows_inv_act: Mapped[float | None] = mapped_column(
        Float, comment="投资活动现金流入小计"
    )
    c_pay_acq_const_fiolta: Mapped[float | None] = mapped_column(
        Float, comment="购建固定资产、无形资产和其他长期资产支付的现金"
    )
    c_paid_invest: Mapped[float | None] = mapped_column(
        Float, comment="投资支付的现金"
    )
    stot_out_inv_act: Mapped[float | None] = mapped_column(
        Float, comment="投资活动现金流出小计"
    )
    n_cashflow_inv_act: Mapped[float | None] = mapped_column(
        Float, comment="投资活动产生的现金流量净额"
    )

    # ---- 筹资活动现金流量 ----
    stot_cash_in_fnc_act: Mapped[float | None] = mapped_column(
        Float, comment="筹资活动现金流入小计"
    )
    stot_cashout_fnc_act: Mapped[float | None] = mapped_column(
        Float, comment="筹资活动现金流出小计"
    )
    n_cash_flows_fnc_act: Mapped[float | None] = mapped_column(
        Float, comment="筹资活动产生的现金流量净额"
    )

    # ---- 现金及等价物 ----
    n_incr_cash_cash_equ: Mapped[float | None] = mapped_column(
        Float, comment="现金及现金等价物净增加额"
    )
    c_cash_equ_end_period: Mapped[float | None] = mapped_column(
        Float, comment="期末现金及现金等价物余额"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return (
            f"<StockCashflow(ts_code={self.ts_code}, "
            f"end_date={self.end_date})>"
        )


class StockFinaIndicator(Base):
    """
    财务指标表（对应 Tushare fina_indicator 接口）
    https://tushare.pro/document/2?doc_id=79

    联合主键：ts_code + end_date
    （一只股票每个报告期对应一条记录）
    日期类字段（ann_date/end_date）统一使用字符串存储，
    便于与 Tushare 原始返回及 fetch 续传逻辑保持一致。

    字段分三类处理：
      第一类：与 fina_indicator 接口字段完全一致（直接抓取）
      第二类：接口原字段更名（saleexp_to_gr→saleexp_ratio 等）
      第三类：需另行补充取数或计算，本次不抓取（预留占位，保持 NULL）
    """

    __tablename__ = "stock_fina_indicator"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    end_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="报告期"
    )

    # ---- 基础字段 ----
    ann_date: Mapped[str | None] = mapped_column(
        String(20), comment="公告日期"
    )

    # ---- 第三类占位字段（本次不抓取，留待后续补充取数/计算），按用户字段顺序置于基础指标前 ----
    total_assets: Mapped[float | None] = mapped_column(
        Float, comment="资产总计（占位：后续从资产负债表补充）"
    )
    total_revenue: Mapped[float | None] = mapped_column(
        Float, comment="营业总收入（占位：后续从利润表补充）"
    )
    operate_profit: Mapped[float | None] = mapped_column(
        Float, comment="营业利润（占位：后续从利润表补充）"
    )

    # ---- 基础指标 ----
    total_revenue_ps: Mapped[float | None] = mapped_column(
        Float, comment="每股营业总收入"
    )
    eps: Mapped[float | None] = mapped_column(
        Float, comment="基本每股收益"
    )

    # ---- 盈利能力 ----
    roe: Mapped[float | None] = mapped_column(
        Float, comment="净资产收益率"
    )
    roic: Mapped[float | None] = mapped_column(
        Float, comment="投入资本回报率"
    )
    roe_yearly: Mapped[float | None] = mapped_column(
        Float, comment="年化净资产收益率"
    )
    q_gsprofit_margin: Mapped[float | None] = mapped_column(
        Float, comment="销售毛利率（单季度）"
    )
    grossprofit_margin: Mapped[float | None] = mapped_column(
        Float, comment="销售毛利率"
    )
    netprofit_margin: Mapped[float | None] = mapped_column(
        Float, comment="销售净利率"
    )

    # ---- 第二类更名字段：原接口 saleexp_to_gr / adminexp_of_gr / finaexp_of_gr ----
    saleexp_ratio: Mapped[float | None] = mapped_column(
        Float, comment="销售费用率（销售费用/营业总收入）"
    )
    adminexp_ratio: Mapped[float | None] = mapped_column(
        Float, comment="管理费用率（管理费用/营业总收入）"
    )
    finaexp_ratio: Mapped[float | None] = mapped_column(
        Float, comment="财务费用率（财务费用/营业总收入）"
    )

    # ---- 运营能力 ----
    inv_turn: Mapped[float | None] = mapped_column(
        Float, comment="存货周转率"
    )
    ar_turn: Mapped[float | None] = mapped_column(
        Float, comment="应收账款周转率"
    )
    fa_turn: Mapped[float | None] = mapped_column(
        Float, comment="固定资产周转率"
    )
    assets_turn: Mapped[float | None] = mapped_column(
        Float, comment="总资产周转率"
    )
    ap_to_ar: Mapped[float | None] = mapped_column(
        Float, comment="应付/应收款（占位：后续计算）"
    )

    # ---- 成长能力 ----
    tr_yoy: Mapped[float | None] = mapped_column(
        Float, comment="营业总收入同比增长率(%)"
    )
    q_gr_qoq: Mapped[float | None] = mapped_column(
        Float, comment="营业总收入环比增长率(%)(单季度)"
    )
    or_yoy: Mapped[float | None] = mapped_column(
        Float, comment="营业收入同比增长率(%)"
    )
    op_yoy: Mapped[float | None] = mapped_column(
        Float, comment="营业利润同比增长率(%)"
    )
    dt_netprofit_yoy: Mapped[float | None] = mapped_column(
        Float, comment="归属母公司股东的净利润-扣除非经常损益同比增长率(%)"
    )
    ocf_yoy: Mapped[float | None] = mapped_column(
        Float, comment="经营活动产生的现金流量净额同比增长率(%)"
    )
    equity_yoy: Mapped[float | None] = mapped_column(
        Float, comment="净资产同比增长率(%)"
    )

    # ---- 安全性 ----
    salescash_to_or: Mapped[float | None] = mapped_column(
        Float, comment="销售商品提供劳务收到的现金/营业收入"
    )
    opincome_of_ebt: Mapped[float | None] = mapped_column(
        Float, comment="经营活动净收益/利润总额"
    )
    debt_to_assets: Mapped[float | None] = mapped_column(
        Float, comment="资产负债率"
    )

    # ---- 第三类占位字段：带息债务率（后续计算 = interestdebt / total_assets）----
    int_to_assets: Mapped[float | None] = mapped_column(
        Float, comment="带息债务率（占位：后续计算）"
    )
    int_to_talcap: Mapped[float | None] = mapped_column(
        Float, comment="带息债务/全部投入资本"
    )
    tax_to_ebt: Mapped[float | None] = mapped_column(
        Float, comment="所得税/利润总额"
    )

    # ---- 第三类占位字段：商誉/总资产、其他款/总资产（后续计算）----
    gw_to_assets: Mapped[float | None] = mapped_column(
        Float, comment="商誉/总资产（占位：后续计算）"
    )
    oth_to_assets: Mapped[float | None] = mapped_column(
        Float, comment="其他款/总资产（占位：后续计算）"
    )

    # ---- 第三类占位字段：资产结构比率（非 fina_indicator 原生字段，预留占位，后续联查计算补充）----
    fin_assets_ratio: Mapped[float | None] = mapped_column(
        Float, comment="金融资产占比（占位：后续计算）"
    )
    op_assets_ratio: Mapped[float | None] = mapped_column(
        Float, comment="经营性资产占比（占位：后续计算）"
    )
    pd_assets_ratio: Mapped[float | None] = mapped_column(
        Float, comment="生产性资产占比（占位：后续计算）"
    )
    capacity_ratio: Mapped[float | None] = mapped_column(
        Float, comment="产能占比（占位：后续计算）"
    )

    # ---- 第三类占位字段：研发费用率（后续计算 = rd_exp / total_revenue）----
    rdexp_ratio: Mapped[float | None] = mapped_column(
        Float, comment="研发费用率（占位：后续计算）"
    )

    # ---- 第三类占位字段：折旧摊销占生产性资产比（后续计算 = daa / 生产性资产）----
    daa_to_pdassets: Mapped[float | None] = mapped_column(
        Float, comment="折旧摊销占生产性资产比（占位：后续计算）"
    )

    # ---- 补充字段（报表补充）----
    rd_exp: Mapped[float | None] = mapped_column(
        Float, comment="研发投入合计"
    )
    daa: Mapped[float | None] = mapped_column(
        Float, comment="折旧与摊销"
    )
    interestdebt: Mapped[float | None] = mapped_column(
        Float, comment="带息债务"
    )
    interst_income: Mapped[float | None] = mapped_column(
        Float, comment="利息费用"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return (
            f"<StockFinaIndicator(ts_code={self.ts_code}, "
            f"end_date={self.end_date})>"
        )


class StockWeekly(Base):
    """
    周K线行情表（对应 Tushare pro_bar(freq='W', adj='hfq') 接口）
    https://tushare.pro/document/2?doc_id=109

    联合主键：ts_code + trade_date
    （一只股票每个交易周对应一条记录，trade_date 为当周最后一个交易日，YYYYMMDD 字符串）
    注：本表固定存储后复权(hfq)数据，用于长期真实收益 / 估值 / 价格分位测算。
    """

    __tablename__ = "stock_weekly"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    trade_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="交易日期（周线为当周最后交易日，YYYYMMDD）"
    )

    # ---- 行情字段（后复权）----
    close: Mapped[float | None] = mapped_column(
        Float, comment="收盘价（后复权）"
    )
    open: Mapped[float | None] = mapped_column(
        Float, comment="开盘价（后复权）"
    )
    high: Mapped[float | None] = mapped_column(
        Float, comment="最高价（后复权）"
    )
    low: Mapped[float | None] = mapped_column(
        Float, comment="最低价（后复权）"
    )
    pre_close: Mapped[float | None] = mapped_column(
        Float, comment="昨收价（后复权，作为涨跌幅计算基准）"
    )
    change: Mapped[float | None] = mapped_column(
        Float, comment="涨跌额（后复权）"
    )
    pct_chg: Mapped[float | None] = mapped_column(
        Float, comment="涨跌幅（基于除权后的昨收计算）"
    )
    vol: Mapped[float | None] = mapped_column(
        Float, comment="成交量（手）"
    )
    amount: Mapped[float | None] = mapped_column(
        Float, comment="成交额（千元）"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return (
            f"<StockWeekly(ts_code={self.ts_code}, "
            f"trade_date={self.trade_date})>"
        )


class StockWeeklyIndicator(Base):
    """
    周K线技术指标表（派生数据，由 stock_weekly 后复权数据计算得出）

    联合主键：ts_code + trade_date（与 StockWeekly 完全一致，便于按周对齐）
    指标说明：
      - MA5/MA60：5/60 周移动均线（基于后复权收盘价 close）
      - MACD：DIF（快12/慢26 EMA 差）、DEA（DIF 的 9 周 EMA）、MACD柱（2*(DIF-DEA)）
      - CCI：顺势指标（默认 14 周，TP=(H+L+C)/3）
      - BOLL：布林带（周期 20 周、2 倍标准差；中轨=20周均线，但 20周均线不单独存储）
    注：前导窗口不足产生的 NaN 不写入（保持 NULL）。
    """

    __tablename__ = "stock_weekly_indicator"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    trade_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="交易日期（周线为当周最后交易日，YYYYMMDD）"
    )

    # ---- 移动均线 ----
    ma5: Mapped[float | None] = mapped_column(Float, comment="5周均线")
    ma60: Mapped[float | None] = mapped_column(Float, comment="60周均线")

    # ---- MACD ----
    dif: Mapped[float | None] = mapped_column(Float, comment="MACD DIF（快12-慢26 EMA差）")
    dea: Mapped[float | None] = mapped_column(Float, comment="MACD DEA（DIF的9周EMA）")
    macd_bar: Mapped[float | None] = mapped_column(Float, comment="MACD柱 2*(DIF-DEA)")

    # ---- CCI ----
    cci: Mapped[float | None] = mapped_column(Float, comment="CCI（14周）")

    # ---- 布林带 BOLL ----
    boll_upper: Mapped[float | None] = mapped_column(Float, comment="布林带上轨")
    boll_mid: Mapped[float | None] = mapped_column(Float, comment="布林带中轨（MA20）")
    boll_lower: Mapped[float | None] = mapped_column(Float, comment="布林带下轨")

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    updated_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")

    def __repr__(self):
        return (
            f"<StockWeeklyIndicator(ts_code={self.ts_code}, "
            f"trade_date={self.trade_date})>"
        )


class StockDailyBasic(Base):
    """
    每日指标表（对应 Tushare daily_basic 接口）
    https://tushare.pro/document/2?doc_id=32

    联合主键：ts_code + trade_date（一只股票每个交易日对应一条记录）
    字段名与 Tushare daily_basic 返回列名完全一致，无需 rename。
    """

    __tablename__ = "stock_daily_basic"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    trade_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="交易日期（YYYYMMDD）"
    )

    # ---- 行情与估值指标 ----
    close: Mapped[float | None] = mapped_column(Float, comment="当日收盘价")
    turnover_rate_f: Mapped[float | None] = mapped_column(
        Float, comment="换手率（自由流通股）(成交量/自由流通股数)"
    )
    volume_ratio: Mapped[float | None] = mapped_column(Float, comment="量比 VOL/MA")
    pe_ttm: Mapped[float | None] = mapped_column(
        Float, comment="市盈率（总市值/净利润TTM，亏损的PE为空）"
    )
    pb: Mapped[float | None] = mapped_column(
        Float, comment="市净率（总市值/(净资产-其他权益工具)）"
    )
    ps_ttm: Mapped[float | None] = mapped_column(
        Float, comment="市销率（TTM）(总市值/营业收入TTM)"
    )
    dv_ttm: Mapped[float | None] = mapped_column(
        Float, comment="股息率（TTM）（%），除息日在近12个月且分红报告期在12个月以内"
    )

    # ---- 股本 ----
    total_share: Mapped[float | None] = mapped_column(Float, comment="总股本（万股）")
    float_share: Mapped[float | None] = mapped_column(Float, comment="流通股本（万股）")
    free_share: Mapped[float | None] = mapped_column(
        Float, comment="自由流通股本（万）"
    )

    # ---- 市值 ----
    total_mv: Mapped[float | None] = mapped_column(Float, comment="总市值（万元）")
    circ_mv: Mapped[float | None] = mapped_column(Float, comment="流通市值（万元）")

    # ---- 涨跌停状态 ----
    limit_status: Mapped[int | None] = mapped_column(
        Integer,
        comment="收盘涨跌状态：0-平盘，1-上涨(不含涨停)，2-涨停(不含一字涨停)，"
                "3-一字涨停，4-下跌(不含跌停)，5-跌停(不含一字跌停)，6-一字跌停",
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    updated_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")

    def __repr__(self):
        return (
            f"<StockDailyBasic(ts_code={self.ts_code}, "
            f"trade_date={self.trade_date})>"
        )


class StockFactor(Base):
    """
    因子库表（复合因子）

    联合主键：ts_code + trade_date（一只股票每个交易日对应一条复合因子记录）
    各因子列存储归一化后的分数（int 类型），由上层 factor.py 计算后写入。
    说明：
      - size / valuation / volility / reverse 为规模、估值、波动率、反转因子；
      - profit / growth / cash / supply / moat 为盈利、成长、现金、供需、护城河因子。
      - 动量已测试长期收益为负，弃用动量仅用「反转因子（reverse）」。
    """

    __tablename__ = "stock_factor"

    # ---- 联合主键 ----
    ts_code: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="TS股票代码"
    )
    name: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="股票名称"
    )
    industry: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="所属行业"
    )
    trade_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="交易日期（YYYYMMDD）"
    )

    # ---- 复合因子分数（int）----
    size: Mapped[int | None] = mapped_column(
        Integer, comment="规模因子"
    )
    valuation: Mapped[int | None] = mapped_column(
        Integer, comment="估值因子"
    )
    volility: Mapped[int | None] = mapped_column(
        Integer, comment="波动率因子"
    )
    reverse: Mapped[int | None] = mapped_column(
        Integer, comment="反转因子"
    )

    profit: Mapped[int | None] = mapped_column(
        Integer, comment="盈利因子"
    )
    growth: Mapped[int | None] = mapped_column(
        Integer, comment="成长因子"
    )
    cash: Mapped[int | None] = mapped_column(
        Integer, comment="现金因子"
    )
    supply: Mapped[int | None] = mapped_column(
        Integer, comment="供需因子"
    )
    moat: Mapped[int | None] = mapped_column(
        Integer, comment="护城河因子"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="创建时间"
    )
    updated_time: Mapped[datetime | None] = mapped_column(
        DateTime, comment="更新时间"
    )

    def __repr__(self):
        return (
            f"<StockFactor(ts_code={self.ts_code}, "
            f"trade_date={self.trade_date})>"
        )


# ========== 引擎（单例） ==========
_engine = None


def get_engine():
    """获取数据库引擎（单例模式）"""
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            echo=False,          # 设为 True 可查看 SQL 日志
            future=True,
        )
    return _engine


# ========== 数据库初始化 ==========
def init_db():
    """创建所有表（首次运行时调用）"""
    engine = get_engine()
    Base.metadata.create_all(engine)


# ========== 会话管理 ==========
@contextmanager
def get_session():
    """获取数据库会话（上下文管理器，自动 commit/rollback/close）"""
    engine = get_engine()
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ========== 便捷函数 ==========
def add_stock(
    ts_code: str, name: str,
    symbol: str | None = None, area: str | None = None,
    industry: str | None = None, market: str | None = None,
    exchange: str | None = None, list_status: str | None = None,
    list_date: str | None = None, delist_date: str | None = None,
    is_hs: str | None = None, act_name: str | None = None,
    act_ent_type: str | None = None,
) -> StockList:
    """添加一只股票到清单"""
    def _parse_date(s: str | None):
        return _td_to_str(s)

    with get_session() as session:
        now = datetime.now()
        stock = StockList(
            ts_code=ts_code, name=name,
            symbol=symbol, area=area,
            industry=industry, market=market,
            exchange=exchange, list_status=list_status,
            list_date=_parse_date(list_date),
            delist_date=_parse_date(delist_date),
            is_hs=is_hs, act_name=act_name,
            act_ent_type=act_ent_type,
            created_time=now, updated_time=now,
        )
        session.add(stock)
    return stock


def get_all_stocks() -> list[StockList]:
    """获取全部股票清单"""
    with get_session() as session:
        return session.query(StockList).all()


def update_one_stock(ts_code: str, **kwargs) -> StockList | None:
    """
    更新股票信息。通过 ts_code 查找记录，仅更新传入的字段。
    返回更新后的 StockList 对象，找不到记录则返回 None。
    """
    with get_session() as session:
        stock = session.query(StockList).filter(StockList.ts_code == ts_code).first()
        if not stock:
            print(f"警告: 找不到 ts_code={ts_code}")
            return None

        for key, value in kwargs.items():
            if value is not None and hasattr(stock, key):
                if key in ("list_date", "delist_date"):
                    value = _td_to_str(value)
                setattr(stock, key, value)
        stock.updated_time = datetime.now()
        return stock


# ---- upsert 字段映射 (DataFrame列名 → StockList属性) ----
_STOCK_FIELDS = [
    ("ts_code", str),
    ("symbol", str),
    ("name", str),
    ("area", str),
    ("industry", str),
    ("market", str),
    ("exchange", str),
    ("list_status", str),
    ("list_date", "str"),
    ("delist_date", "str"),
    ("is_hs", str),
    ("act_name", str),
    ("act_ent_type", str),
]


def upsert_stock_list(df) -> tuple:
    """
    批量 upsert 股票清单数据（主键 = ts_code）

    参数:
        df: 包含股票数据的 DataFrame，必须包含 'ts_code' 列
    返回:
        tuple: (新增数量, 更新数量)
    """
    if "ts_code" not in df.columns:
        print("错误: DataFrame 必须包含 'ts_code' 列")
        return (0, 0)

    with get_session() as session:
        existing = {s for s, in session.query(StockList.ts_code).all()}
        new_stocks, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]

            if ts_code in existing:
                stock = session.query(StockList).filter(StockList.ts_code == ts_code).first()
                if stock:
                    for df_col, _type in _STOCK_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            val = row[df_col]

                            setattr(stock, df_col, val)
                    stock.updated_time = now
                    updated_count += 1
            else:
                kwargs = {"ts_code": ts_code, "created_time": now, "updated_time": now}
                for df_col, _type in _STOCK_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        val = row[df_col]

                        if df_col != "ts_code":
                            kwargs[df_col] = val
                new_stocks.append(StockList(**kwargs))

        if new_stocks:
            session.add_all(new_stocks)

        print(f"数据库写入完成：新增 {len(new_stocks)} 条，更新 {updated_count} 条")
        return (len(new_stocks), updated_count)


def _has_value(v):
    """检查值是否非空（兼容 None / np.nan / pd.NA / NaT 等缺失值）"""
    if v is None:
        return False
    try:
        from pandas import isna
        if isna(v):
            return False
    except Exception:
        # 无 pandas 环境下退化为 float NaN 判断
        if isinstance(v, float) and v != v:
            return False
    return True


def _td_to_str(s):
    """将 YYYYMMDD 或 YYYY-MM-DD 字符串/date 归一化为 YYYYMMDD 字符串，无效返回 None"""
    if s is None:
        return None
    if isinstance(s, date):
        return s.strftime("%Y%m%d")
    s = str(s).replace("-", "")
    return s if s.isdigit() else None


# ---- upsert 字段映射 (DataFrame列名 → StockManagers属性) ----
_MANAGER_FIELDS = [
    ("ts_code", str),
    ("ann_date", "str"),
    ("name", str),
    ("gender", str),
    ("lev", str),
    ("title", str),
    ("edu", str),
    ("national", str),
    ("birthday", "str"),
    ("begin_date", "str"),
    ("end_date", "str"),
    ("resume", str),
]


def upsert_stock_managers(df) -> tuple:
    """
    批量 upsert 公司高管数据（联合主键 = ts_code + ann_date + name + title）

    参数:
        df: 包含高管数据的 DataFrame，必须包含 'ts_code', 'ann_date', 'name', 'title' 列
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"ts_code", "ann_date", "name", "title"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "ann_date", "name", "title"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的联合主键
        existing_rows = session.query(
            StockManagers.ts_code, StockManagers.ann_date,
            StockManagers.name, StockManagers.title,
        ).all()
        existing = {
            (r[0], _td_to_str(r[1]), r[2], r[3]) for r in existing_rows
        }

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            ann_date = _td_to_str(row["ann_date"])
            name = row["name"]
            title_val = row["title"] if _has_value(row["title"]) else ""
            key = (ts_code, ann_date, name, title_val)

            if key in existing:
                # 更新路径
                manager = session.query(StockManagers).filter(
                    StockManagers.ts_code == ts_code,
                    StockManagers.ann_date == ann_date,
                    StockManagers.name == name,
                    StockManagers.title == title_val,
                ).first()
                if manager:
                    for df_col, _type in _MANAGER_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            val = row[df_col]

                            setattr(manager, df_col, val)
                    manager.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "ts_code": ts_code,
                    "ann_date": ann_date,
                    "name": name,
                    "title": title_val,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _MANAGER_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        val = row[df_col]

                        if df_col not in ("ts_code", "ann_date", "name", "title"):
                            kwargs[df_col] = val
                new_list.append(StockManagers(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ---- upsert 字段映射 (DataFrame列名 → StockCompany属性) ----
_COMPANY_FIELDS = [
    ("ts_code", str),
    ("com_name", str),
    ("com_id", str),
    ("exchange", str),
    ("chairman", str),
    ("manager", str),
    ("secretary", str),
    ("reg_capital", float),
    ("province", str),
    ("city", str),
    ("introduction", str),
    ("employees", int),
    ("main_business", str),
    ("business_scope", str),
]


def upsert_stock_company(df) -> tuple:
    """
    批量 upsert 上市公司基本信息数据（主键 = ts_code）

    参数:
        df: 包含公司数据的 DataFrame，必须包含 'ts_code' 列
    返回:
        tuple: (新增数量, 更新数量)
    """
    if "ts_code" not in df.columns:
        print("错误: DataFrame 必须包含 'ts_code' 列")
        return (0, 0)

    # 按主键去重
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有已有记录的 ts_code
        existing = {s for s, in session.query(StockCompany.ts_code).all()}

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]

            if ts_code in existing:
                # 更新路径
                company = session.query(StockCompany).filter(
                    StockCompany.ts_code == ts_code
                ).first()
                if company:
                    for df_col, _type in _COMPANY_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            val = row[df_col]
                            if _type == int and isinstance(val, float):
                                val = int(val)
                            setattr(company, df_col, val)
                    company.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {"ts_code": ts_code, "created_time": now, "updated_time": now}
                for df_col, _type in _COMPANY_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        val = row[df_col]
                        if _type == int and isinstance(val, float):
                            val = int(val)
                        if df_col != "ts_code":
                            kwargs[df_col] = val
                new_list.append(StockCompany(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ---- upsert 字段映射 (DataFrame列名 → StockBalancesheet属性) ----
_BALANCESHEET_FIELDS = [
    ("ts_code", str),
    ("ann_date", "str"),
    ("f_ann_date", "str"),
    ("end_date", "str"),
    ("report_type", str),
    ("comp_type", str),
    ("end_type", str),
    ("total_assets", float),
    ("money_cap", float),
    ("trad_asset", float),
    ("lt_eqt_invest", float),
    ("invest_real_estate", float),
    ("notes_receiv", float),
    ("accounts_receiv", float),
    ("prepayment", float),
    ("oth_receiv", float),
    ("inventories", float),
    ("contract_assets", float),
    ("oth_cur_assets", float),
    ("fix_assets", float),
    ("cip", float),
    ("lt_rec", float),
    ("oil_and_gas_assets", float),
    ("produc_bio_assets", float),
    ("intan_assets", float),
    ("r_and_d", float),
    ("goodwill", float),
    ("total_liab", float),
    ("st_borr", float),
    ("trading_fl", float),
    ("lt_borr", float),
    ("bond_payable", float),
    ("lt_payable", float),
    ("notes_payable", float),
    ("acct_payable", float),
    ("adv_receipts", float),
    ("contract_liab", float),
    ("payroll_payable", float),
    ("taxes_payable", float),
    ("oth_payable", float),
    ("total_liab_hldr_eqy", float),
    ("minority_int", float),
    ("total_share", float),
    ("cap_rese", float),
    ("oth_comp_income", float),
    ("surplus_rese", float),
    ("undistr_porfit", float),
]


def upsert_stock_balancesheet(df) -> tuple:
    """
    批量 upsert 资产负债表数据（联合主键 = ts_code + end_date）

    参数:
        df: 包含资产负债表数据的 DataFrame，必须包含 'ts_code', 'end_date' 列
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"ts_code", "end_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "end_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的联合主键
        existing_rows = session.query(
            StockBalancesheet.ts_code, StockBalancesheet.end_date,
        ).all()
        existing = {tuple(row) for row in existing_rows}

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            end_date = str(row["end_date"])
            key = (ts_code, end_date)

            if key in existing:
                # 更新路径
                bs = session.query(StockBalancesheet).filter(
                    StockBalancesheet.ts_code == ts_code,
                    StockBalancesheet.end_date == end_date,
                ).first()
                if bs:
                    for df_col, _type in _BALANCESHEET_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            val = row[df_col]

                            setattr(bs, df_col, val)
                    bs.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "ts_code": ts_code,
                    "end_date": end_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _BALANCESHEET_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        val = row[df_col]

                        if df_col not in ("ts_code", "end_date"):
                            kwargs[df_col] = val
                new_list.append(StockBalancesheet(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ---- upsert 字段映射 (DataFrame列名 → StockIncome属性) ----
_INCOME_FIELDS = [
    ("ts_code", str),
    ("ann_date", str),
    ("f_ann_date", str),
    ("end_date", str),
    ("report_type", str),
    ("comp_type", str),
    ("end_type", str),
    ("basic_eps", float),
    ("diluted_eps", float),
    ("total_revenue", float),
    ("revenue", float),
    ("total_cogs", float),
    ("oper_cost", float),
    ("biz_tax_surchg", float),
    ("sell_exp", float),
    ("admin_exp", float),
    ("rd_exp", float),
    ("fin_exp", float),
    ("assets_impair_loss", float),
    ("credit_impa_loss", float),
    ("fv_value_chg_gain", float),
    ("invest_income", float),
    ("asset_disp_income", float),
    ("oth_income", float),
    ("operate_profit", float),
    ("total_profit", float),
    ("income_tax", float),
    ("n_income", float),
    ("n_income_attr_p", float),
    ("oth_compr_income", float),
    ("t_compr_income", float),
]


def upsert_stock_income(df) -> tuple:
    """
    批量 upsert 利润表数据（联合主键 = ts_code + end_date）

    参数:
        df: 包含利润表数据的 DataFrame，必须包含 'ts_code', 'end_date' 列
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"ts_code", "end_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "end_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的联合主键
        existing_rows = session.query(
            StockIncome.ts_code, StockIncome.end_date,
        ).all()
        existing = {tuple(row) for row in existing_rows}

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            end_date = row["end_date"]
            key = (ts_code, end_date)

            if key in existing:
                # 更新路径
                inc = session.query(StockIncome).filter(
                    StockIncome.ts_code == ts_code,
                    StockIncome.end_date == end_date,
                ).first()
                if inc:
                    for df_col, _type in _INCOME_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            setattr(inc, df_col, row[df_col])
                    inc.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "ts_code": ts_code,
                    "end_date": end_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _INCOME_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        if df_col not in ("ts_code", "end_date"):
                            kwargs[df_col] = row[df_col]
                new_list.append(StockIncome(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ---- upsert 字段映射 (DataFrame列名 → StockCashflow属性) ----
_CASHFLOW_FIELDS = [
    ("ts_code", str),
    ("ann_date", str),
    ("f_ann_date", str),
    ("end_date", str),
    ("report_type", str),
    ("comp_type", str),
    ("end_type", str),
    ("c_fr_sale_sg", float),
    ("recp_tax_rends", float),
    ("c_fr_oth_operate_a", float),
    ("c_inf_fr_operate_a", float),
    ("c_paid_goods_s", float),
    ("c_paid_to_for_empl", float),
    ("c_paid_for_taxes", float),
    ("oth_cash_pay_oper_act", float),
    ("st_cash_out_act", float),
    ("n_cashflow_act", float),
    ("c_disp_withdrwl_invest", float),
    ("n_recp_disp_fiolta", float),
    ("stot_inflows_inv_act", float),
    ("c_pay_acq_const_fiolta", float),
    ("c_paid_invest", float),
    ("stot_out_inv_act", float),
    ("n_cashflow_inv_act", float),
    ("stot_cash_in_fnc_act", float),
    ("stot_cashout_fnc_act", float),
    ("n_cash_flows_fnc_act", float),
    ("n_incr_cash_cash_equ", float),
    ("c_cash_equ_end_period", float),
]


def upsert_stock_cashflow(df) -> tuple:
    """
    批量 upsert 现金流量表数据（联合主键 = ts_code + end_date）

    参数:
        df: 包含现金流量表数据的 DataFrame，必须包含 'ts_code', 'end_date' 列
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"ts_code", "end_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "end_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的联合主键
        existing_rows = session.query(
            StockCashflow.ts_code, StockCashflow.end_date,
        ).all()
        existing = {tuple(row) for row in existing_rows}

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            end_date = str(row["end_date"])
            key = (ts_code, end_date)

            if key in existing:
                # 更新路径
                cf = session.query(StockCashflow).filter(
                    StockCashflow.ts_code == ts_code,
                    StockCashflow.end_date == end_date,
                ).first()
                if cf:
                    for df_col, _type in _CASHFLOW_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            setattr(cf, df_col, row[df_col])
                    cf.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "ts_code": ts_code,
                    "end_date": end_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _CASHFLOW_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        if df_col not in ("ts_code", "end_date"):
                            kwargs[df_col] = row[df_col]
                new_list.append(StockCashflow(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ===================== 财务指标（fina_indicator）字段映射与批量 upsert =====================
# 字段分三类处理：
#   第一类（T1）：与 fina_indicator 接口字段完全一致，df 列名 = ORM 属性名，直接抓取
#   第二类（T2）：接口原字段更名，fetch 阶段已将 df 列名 rename 为 ORM 属性名
#   第三类（T3）：需另行补充取数或计算，本次不抓取（保持 NULL 占位）
# 说明：fin_assets_ratio / op_assets_ratio / pd_assets_ratio / capacity_ratio 非 fina_indicator 原生字段，
#       归入 T3 占位（不在 Tushare 请求 fields 中），避免接口报错。

# 第一类：与 fina_indicator 接口字段完全一致（df 列名 = ORM 属性名）
_FINA_FIELDS_T1 = [
    ("ts_code", str),
    ("ann_date", str),
    ("end_date", str),
    # 基础指标
    ("total_revenue_ps", float),
    ("eps", float),
    # 盈利能力
    ("roe", float),
    ("roic", float),
    ("roe_yearly", float),
    ("q_gsprofit_margin", float),
    ("grossprofit_margin", float),
    ("netprofit_margin", float),
    # 运营能力
    ("inv_turn", float),
    ("ar_turn", float),
    ("fa_turn", float),
    ("assets_turn", float),
    # 成长能力
    ("tr_yoy", float),
    ("q_gr_qoq", float),
    ("or_yoy", float),
    ("op_yoy", float),
    ("dt_netprofit_yoy", float),
    ("ocf_yoy", float),
    ("equity_yoy", float),
    # 安全性
    ("salescash_to_or", float),
    ("opincome_of_ebt", float),
    ("debt_to_assets", float),
    ("int_to_talcap", float),
    ("tax_to_ebt", float),
    # 补充字段
    ("daa", float),
    ("rd_exp", float),
    ("interestdebt", float),
    ("interst_income", float),
]

# 第二类：接口原字段更名（fetch 阶段已完成 rename，此处使用更名后的 ORM 属性名）
_FINA_FIELDS_T2 = [
    ("saleexp_ratio", float),
    ("adminexp_ratio", float),
    ("finaexp_ratio", float),
]

# 第三类：需联查资产负债表/利润表或计算，本次不抓取，预留占位（保持 NULL）
_FINA_FIELDS_T3 = [
    # 占位：直接取用（联查自资产负债表/利润表）
    ("total_assets", float),
    ("total_revenue", float),
    ("operate_profit", float),
    # 占位：应付比应收（= 多种应付款 / 应收款）
    ("ap_to_ar", float),
    # 占位：研发费用率（= rd_exp / total_revenue * 100）
    ("rdexp_ratio", float),
    # 占位：带息债务率（= interestdebt / total_assets * 100）
    ("int_to_assets", float),
    # 占位：商誉/总资产（= goodwill / total_assets * 100）
    ("gw_to_assets", float),
    # 占位：其他款/总资产（= oth_receiv / total_assets * 100）
    ("oth_to_assets", float),
    # 占位：金融资产占比 / 经营性资产占比 / 生产性资产占比 / 产能占比（第三类资产结构比率，后续计算）
    ("fin_assets_ratio", float),
    ("op_assets_ratio", float),
    ("pd_assets_ratio", float),
    ("capacity_ratio", float),
    # 占位：折旧摊销占生产性资产比（= daa / 生产性资产 * 100）
    ("daa_to_pdassets", float),
]

# 全量字段映射（upsert 使用）
_FINA_FIELDS = _FINA_FIELDS_T1 + _FINA_FIELDS_T2 + _FINA_FIELDS_T3


def _fina_field_names() -> str:
    """返回全量字段名列表（不含主键），便于调试/排查。"""
    return ", ".join(name for name, _ in _FINA_FIELDS)


def upsert_stock_fina_indicator(df: "pd.DataFrame") -> tuple:
    """
    批量插入或更新财务指标数据（stock_fina_indicator）。

    约定：
      - 联合主键为 (ts_code, end_date)，end_date 为字符串。
      - df 的列名应与 ORM 属性名对齐（第二类字段由 fetch 阶段 rename 完成）。
      - 第三类占位字段若不在 df 中，则保持数据库 NULL（不处理）。

    返回：(新增数量, 更新数量)
    """
    required_cols = {"ts_code", "end_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 防御性去重：同一 (ts_code, end_date) 只保留最后一条
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "end_date"], keep="last")
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        existing_rows = session.query(
            StockFinaIndicator.ts_code, StockFinaIndicator.end_date
        ).all()
        existing = {(code, ed if isinstance(ed, str) else str(ed))
                    for code, ed in existing_rows}

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            end_date = str(row["end_date"])
            key = (ts_code, end_date)

            if key in existing:
                obj = session.query(StockFinaIndicator).filter(
                    StockFinaIndicator.ts_code == ts_code,
                    StockFinaIndicator.end_date == end_date,
                ).first()
                if obj:
                    for df_col, _type in _FINA_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            setattr(obj, df_col, row[df_col])
                    obj.updated_time = now
                    updated_count += 1
            else:
                kwargs = {
                    "ts_code": ts_code,
                    "end_date": end_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _FINA_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        if df_col not in ("ts_code", "end_date"):
                            kwargs[df_col] = row[df_col]
                new_list.append(StockFinaIndicator(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(
            f"数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条"
        )
        return (len(new_list), updated_count)


def upsert_stock_indicator_fina_row(ts_code: str, end_date: str, **fields) -> tuple:
    """
    单行 / 部分字段 更新插入的便捷封装（满足「支持部分记录更新或单行记录更新」）。

    内部将单条记录构造成 1 行 DataFrame 后复用 upsert_stock_fina_indicator：
      - 仅传入需要更新的字段（**fields）即可实现「部分字段更新」；
      - 单行调用即等价于「单行记录更新」；
      - 若该 (ts_code, end_date) 已存在则走 UPDATE 分支，否则 INSERT。

    返回：upsert_stock_fina_indicator 的结果 (新增数量, 更新数量)
    """
    df = pd.DataFrame([{"ts_code": ts_code, "end_date": end_date, **fields}])
    return upsert_stock_fina_indicator(df)


# ---- upsert 字段映射 (DataFrame列名 → StockWeekly属性) ----
_WEEKLY_FIELDS = [
    ("ts_code", str),
    ("trade_date", "str"),
    ("close", float),
    ("open", float),
    ("high", float),
    ("low", float),
    ("pre_close", float),
    ("change", float),
    ("pct_chg", float),
    ("vol", float),
    ("amount", float),
]


def upsert_stock_weekly(df) -> tuple:
    """
    批量 upsert 周K线行情数据（联合主键 = ts_code + trade_date，后复权 hfq）

    参数:
        df: 包含周K线数据的 DataFrame，必须包含 'ts_code', 'trade_date' 列
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"ts_code", "trade_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的联合主键
        existing_rows = session.query(
            StockWeekly.ts_code, StockWeekly.trade_date,
        ).all()
        existing = {
            (code, td if isinstance(td, str) else str(td))
            for code, td in existing_rows
        }

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            trade_date = str(row["trade_date"])
            key = (ts_code, trade_date)

            if key in existing:
                # 更新路径
                wk = session.query(StockWeekly).filter(
                    StockWeekly.ts_code == ts_code,
                    StockWeekly.trade_date == trade_date,
                ).first()
                if wk:
                    for df_col, _type in _WEEKLY_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            setattr(wk, df_col, row[df_col])
                    wk.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _WEEKLY_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        if df_col not in ("ts_code", "trade_date"):
                            kwargs[df_col] = row[df_col]
                new_list.append(StockWeekly(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ---- upsert 字段映射 (DataFrame列名 → StockWeeklyIndicator属性) ----
_WEEKLY_INDICATOR_FIELDS = [
    ("ma5", float),
    ("ma60", float),
    ("dif", float),
    ("dea", float),
    ("macd_bar", float),
    ("cci", float),
    ("boll_upper", float),
    ("boll_mid", float),
    ("boll_lower", float),
]


def upsert_stock_weekly_indicator(df) -> tuple:
    """
    批量 upsert 周K线技术指标数据（联合主键 = ts_code + trade_date）

    参数:
        df: 包含周K线指标数据的 DataFrame，必须包含 'ts_code', 'trade_date' 列
            （其余指标列缺失时该列保持 NULL，不强制要求齐全）
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"ts_code", "trade_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的联合主键
        existing_rows = session.query(
            StockWeeklyIndicator.ts_code, StockWeeklyIndicator.trade_date,
        ).all()
        existing = {
            (code, td if isinstance(td, str) else str(td))
            for code, td in existing_rows
        }

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            trade_date = str(row["trade_date"])
            key = (ts_code, trade_date)

            if key in existing:
                # 更新路径
                wk = session.query(StockWeeklyIndicator).filter(
                    StockWeeklyIndicator.ts_code == ts_code,
                    StockWeeklyIndicator.trade_date == trade_date,
                ).first()
                if wk:
                    for df_col, _type in _WEEKLY_INDICATOR_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            setattr(wk, df_col, row[df_col])
                    wk.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _WEEKLY_INDICATOR_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        if df_col not in ("ts_code", "trade_date"):
                            kwargs[df_col] = row[df_col]
                new_list.append(StockWeeklyIndicator(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"指标数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ---- upsert 字段映射 (DataFrame列名 → StockDailyBasic属性) ----
_DAILY_BASIC_FIELDS = [
    ("close", float),
    ("turnover_rate_f", float),
    ("volume_ratio", float),
    ("pe_ttm", float),
    ("pb", float),
    ("ps_ttm", float),
    ("dv_ttm", float),
    ("total_share", float),
    ("float_share", float),
    ("free_share", float),
    ("total_mv", float),
    ("circ_mv", float),
    ("limit_status", int),
]


def upsert_stock_daily_basic(df) -> tuple:
    """
    批量 upsert 每日指标数据（联合主键 = ts_code + trade_date）

    参数:
        df: 包含每日指标数据的 DataFrame，必须包含 'ts_code', 'trade_date' 列
            （其余指标列缺失时该列保持 NULL，不强制要求齐全）
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"ts_code", "trade_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的联合主键
        existing_rows = session.query(
            StockDailyBasic.ts_code, StockDailyBasic.trade_date,
        ).all()
        existing = {
            (code, td if isinstance(td, str) else str(td))
            for code, td in existing_rows
        }

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            trade_date = str(row["trade_date"])
            key = (ts_code, trade_date)

            if key in existing:
                # 更新路径
                db = session.query(StockDailyBasic).filter(
                    StockDailyBasic.ts_code == ts_code,
                    StockDailyBasic.trade_date == trade_date,
                ).first()
                if db:
                    for df_col, _type in _DAILY_BASIC_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            setattr(db, df_col, row[df_col])
                    db.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "ts_code": ts_code,
                    "trade_date": trade_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _DAILY_BASIC_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        if df_col not in ("ts_code", "trade_date"):
                            kwargs[df_col] = row[df_col]
                new_list.append(StockDailyBasic(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"每日指标数据库写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ===================== 因子库（factor_library）ORM 与批量 upsert =====================
# StockFactor 类定义见上文 ORM 章节（__tablename__ = "factor_library"）

# 因子库各因子列名（用于 upsert 时按列写值，name 视为总是更新的字段）
_FACTOR_FIELDS = (
    "size",
    "valuation",
    "volility",
    "reverse",
    "profit",
    "growth",
    "cash",
    "supply",
    "moat",
)


def upsert_stock_factor(df, chunk_size: int = 5000) -> tuple:
    """
    批量 upsert 因子库数据（联合主键 = ts_code + trade_date）

    支持分批写入（默认每批 5000 条）与更新插入（已存在则更新，不存在则新增）。

    参数:
        df: 包含因子数据的 DataFrame，必须包含 'ts_code', 'trade_date', 'name' 列
            （其余因子列缺失时该列保持 NULL，不强制要求齐全）
        chunk_size: 每批写入的记录数，默认 5000
    返回:
        tuple: (累计新增数量, 累计更新数量)
    """
    required_cols = {"ts_code", "trade_date", "name"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按联合主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["ts_code", "trade_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    total_new, total_updated = 0, 0
    now = datetime.now()

    # 按批次处理
    for start in range(0, len(df), chunk_size):
        chunk = df.iloc[start:start + chunk_size]
        with get_session() as session:
            keys = [(r["ts_code"], str(r["trade_date"])) for _, r in chunk.iterrows()]
            existing_rows = session.query(
                StockFactor.ts_code, StockFactor.trade_date,
            ).all()
            existing = {
                (code, td if isinstance(td, str) else str(td))
                for code, td in existing_rows
            }

            new_list = []
            updated_count = 0

            for _, row in chunk.iterrows():
                ts_code = row["ts_code"]
                trade_date = str(row["trade_date"])
                key = (ts_code, trade_date)

                if key in existing:
                    db = session.query(StockFactor).filter(
                        StockFactor.ts_code == ts_code,
                        StockFactor.trade_date == trade_date,
                    ).first()
                    if db:
                        db.name = row["name"]
                        if "industry" in row and _has_value(row["industry"]):
                            db.industry = row["industry"]
                        for fld in _FACTOR_FIELDS:
                            if fld in row and _has_value(row[fld]):
                                setattr(db, fld, row[fld])
                        db.updated_time = now
                        updated_count += 1
                else:
                    kwargs = {
                        "ts_code": ts_code,
                        "name": row["name"],
                        "trade_date": trade_date,
                        "created_time": now,
                        "updated_time": now,
                    }
                    if "industry" in row and _has_value(row["industry"]):
                        kwargs["industry"] = row["industry"]
                    for fld in _FACTOR_FIELDS:
                        if fld in row and _has_value(row[fld]):
                            kwargs[fld] = row[fld]
                    new_list.append(StockFactor(**kwargs))

            if new_list:
                session.add_all(new_list)

            total_new += len(new_list)
            total_updated += updated_count

    print(f"因子库数据库写入完成：新增 {total_new} 条，更新 {total_updated} 条")
    return (total_new, total_updated)


# ===================== 交易日历（trade_cal）ORM 与批量 upsert =====================
class TradeCal(Base):
    """
    交易日历表（对应 Tushare trade_cal 接口）
    https://tushare.pro/document/2?doc_id=26

    主键：cal_date
    目前仅存储上交所（SSE）交易日历，作为全市场交易日基准。
    字段均为字符串，日期类字段统一使用 YYYYMMDD 约定。
    """

    __tablename__ = "trade_cal"

    # ---- 主键 ----
    cal_date: Mapped[str] = mapped_column(
        String(20), primary_key=True, comment="日历日期 YYYYMMDD"
    )

    # ---- 交易状态 ----
    is_open: Mapped[str | None] = mapped_column(
        String(4), comment="是否交易 0休市 1交易"
    )
    pretrade_date: Mapped[str | None] = mapped_column(
        String(20), comment="上一个交易日 YYYYMMDD"
    )

    # ---- 时间戳 ----
    created_time: Mapped[datetime | None] = mapped_column(DateTime, comment="创建时间")
    updated_time: Mapped[datetime | None] = mapped_column(DateTime, comment="更新时间")

    def __repr__(self):
        return (
            f"<TradeCal(cal_date={self.cal_date}, "
            f"is_open={self.is_open}, pretrade_date={self.pretrade_date})>"
        )


# ---- upsert 字段映射 (DataFrame列名 → TradeCal属性) ----
_TRADE_CAL_FIELDS = [
    ("cal_date", "str"),
    ("is_open", str),
    ("pretrade_date", "str"),
]


def upsert_trade_cal(df) -> tuple:
    """
    批量 upsert 交易日历数据（主键 = cal_date）

    复用现有 upsert 模式：先查已存在主键 -> 合并 -> 写入。

    参数:
        df: 包含交易日历数据的 DataFrame，必须包含 'cal_date' 列
            （其余字段缺失时该列保持 NULL，不强制要求齐全）
    返回:
        tuple: (新增数量, 更新数量)
    """
    required_cols = {"cal_date"}
    if not required_cols.issubset(set(df.columns)):
        print(f"错误: DataFrame 必须包含 {required_cols} 列")
        return (0, 0)

    # 按主键去重，防止 DataFrame 内部重复行导致 IntegrityError
    before_dedup = len(df)
    df = df.drop_duplicates(subset=["cal_date"])
    if len(df) < before_dedup:
        print(f"DataFrame 内部去重：移除 {before_dedup - len(df)} 条重复记录")

    with get_session() as session:
        # 一次查询所有现有记录的主键
        existing_rows = session.query(TradeCal.cal_date).all()
        existing = {
            cd if isinstance(cd, str) else str(cd)
            for (cd,) in existing_rows
        }

        new_list, updated_count = [], 0
        now = datetime.now()

        for _, row in df.iterrows():
            cal_date = _td_to_str(row["cal_date"])
            if cal_date is None:
                continue
            key = cal_date

            if key in existing:
                # 更新路径
                tc = session.query(TradeCal).filter(
                    TradeCal.cal_date == cal_date,
                ).first()
                if tc:
                    for df_col, _type in _TRADE_CAL_FIELDS:
                        if df_col in row and _has_value(row[df_col]):
                            setattr(tc, df_col, row[df_col])
                    tc.updated_time = now
                    updated_count += 1
            else:
                # 新增路径
                kwargs = {
                    "cal_date": cal_date,
                    "created_time": now,
                    "updated_time": now,
                }
                for df_col, _type in _TRADE_CAL_FIELDS:
                    if df_col in row and _has_value(row[df_col]):
                        kwargs[df_col] = row[df_col]
                new_list.append(TradeCal(**kwargs))

        if new_list:
            session.add_all(new_list)

        print(f"交易日历写入完成：新增 {len(new_list)} 条，更新 {updated_count} 条")
        return (len(new_list), updated_count)


# ===================== 统一查询层（供 factor.py 等调用，返回 DataFrame） =====================
# 规范：
#   - 所有 get_*_by_date 函数统一返回 pd.DataFrame；无匹配数据时返回含 ORM 列名的空 DataFrame（不返回 None）。
#   - 在 with get_session() 块内用 pd.read_sql(query.statement, session.bind) 取数，
#     避免 expire_on_commit=False + session.close() 后 ORM 对象属性过期导致懒加载失败。
#   - 日期维度：StockFinaIndicator 按 ann_date（公告日期）截面；其余三张按 trade_date 截面。
#   - fields 限制返回列；ts_code 支持单值或列表（列表走 .in_ 过滤）。


def _empty_df(model) -> "pd.DataFrame":
    """返回与 ORM 表列名一致的空 DataFrame。"""
    return pd.DataFrame(columns=[c.name for c in model.__table__.columns])


def get_fina_indicator_by_ann_date(
    ts_code: str | list[str] | None = None,
    ann_date: str | None = None,
    start_ann_date: str | None = None,
    end_ann_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """
    按公告日期 ann_date 截面（或区间）查询财务指标，返回 DataFrame。

    该表无 trade_date 字段，联合主键为 (ts_code, end_date)，按用户约定以 ann_date 作截面维度。
    维度：规模 / 盈利 / 成长 / 现金（对应 FACTOR_REGISTRY 中 factor_source = 'stock_fina_indicator'）。
    """
    with get_session() as session:
        cols = (
            [getattr(StockFinaIndicator, f) for f in fields]
            if fields else StockFinaIndicator
        )
        q = session.query(*cols) if fields else session.query(StockFinaIndicator)
        if ts_code is not None:
            q = q.filter(
                StockFinaIndicator.ts_code.in_(ts_code)
                if isinstance(ts_code, list) else StockFinaIndicator.ts_code == ts_code
            )
        if ann_date is not None:
            q = q.filter(StockFinaIndicator.ann_date == ann_date)
        if start_ann_date is not None:
            q = q.filter(StockFinaIndicator.ann_date >= start_ann_date)
        if end_ann_date is not None:
            q = q.filter(StockFinaIndicator.ann_date <= end_ann_date)
        df = pd.read_sql(q.statement, session.bind) if q.count() > 0 else _empty_df(StockFinaIndicator)
    return df


def get_cashflow_by_ann_date(
    ts_code: str | list[str] | None = None,
    ann_date: str | None = None,
    start_ann_date: str | None = None,
    end_ann_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """
    按公告日期 ann_date 截面（或区间）查询现金流量表，返回 DataFrame。

    该表无 trade_date 字段，联合主键为 (ts_code, end_date)，按用户约定以 ann_date 作截面维度。
    维度：现金规模（对应 FACTOR_REGISTRY 中现金因子的 R4 子项 n_cashflow_act）。
    """
    with get_session() as session:
        cols = (
            [getattr(StockCashflow, f) for f in fields]
            if fields else StockCashflow
        )
        q = session.query(*cols) if fields else session.query(StockCashflow)
        if ts_code is not None:
            q = q.filter(
                StockCashflow.ts_code.in_(ts_code)
                if isinstance(ts_code, list) else StockCashflow.ts_code == ts_code
            )
        if ann_date is not None:
            q = q.filter(StockCashflow.ann_date == ann_date)
        if start_ann_date is not None:
            q = q.filter(StockCashflow.ann_date >= start_ann_date)
        if end_ann_date is not None:
            q = q.filter(StockCashflow.ann_date <= end_ann_date)
        df = pd.read_sql(q.statement, session.bind) if q.count() > 0 else _empty_df(StockCashflow)
    return df


def get_balancesheet_by_ann_date(
    ts_code: str | list[str] | None = None,
    ann_date: str | None = None,
    start_ann_date: str | None = None,
    end_ann_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """
    按公告日期 ann_date 截面（或区间）查询资产负债表，返回 DataFrame。

    该表无 trade_date 字段，联合主键为 (ts_code, end_date)，按用户约定以 ann_date 作截面维度。
    维度：盈利因子的 R6 子项总资产 total_assets。
    """
    with get_session() as session:
        cols = (
            [getattr(StockBalancesheet, f) for f in fields]
            if fields else StockBalancesheet
        )
        q = session.query(*cols) if fields else session.query(StockBalancesheet)
        if ts_code is not None:
            q = q.filter(
                StockBalancesheet.ts_code.in_(ts_code)
                if isinstance(ts_code, list) else StockBalancesheet.ts_code == ts_code
            )
        if ann_date is not None:
            q = q.filter(StockBalancesheet.ann_date == ann_date)
        if start_ann_date is not None:
            q = q.filter(StockBalancesheet.ann_date >= start_ann_date)
        if end_ann_date is not None:
            q = q.filter(StockBalancesheet.ann_date <= end_ann_date)
        df = pd.read_sql(q.statement, session.bind) if q.count() > 0 else _empty_df(StockBalancesheet)
    return df


def get_income_by_ann_date(
    ts_code: str | list[str] | None = None,
    ann_date: str | None = None,
    start_ann_date: str | None = None,
    end_ann_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """
    按公告日期 ann_date 截面（或区间）查询利润表，返回 DataFrame。

    该表无 trade_date 字段，联合主键为 (ts_code, end_date)，按用户约定以 ann_date 作截面维度。
    维度：成长因子的 R4 子项总营收 total_revenue。
    """
    with get_session() as session:
        cols = (
            [getattr(StockIncome, f) for f in fields]
            if fields else StockIncome
        )
        q = session.query(*cols) if fields else session.query(StockIncome)
        if ts_code is not None:
            q = q.filter(
                StockIncome.ts_code.in_(ts_code)
                if isinstance(ts_code, list) else StockIncome.ts_code == ts_code
            )
        if ann_date is not None:
            q = q.filter(StockIncome.ann_date == ann_date)
        if start_ann_date is not None:
            q = q.filter(StockIncome.ann_date >= start_ann_date)
        if end_ann_date is not None:
            q = q.filter(StockIncome.ann_date <= end_ann_date)
        df = pd.read_sql(q.statement, session.bind) if q.count() > 0 else _empty_df(StockIncome)
    return df


def get_daily_basic_by_trade_date(
    ts_code: str | list[str] | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """
    按交易日期 trade_date 截面（或区间）查询每日指标，返回 DataFrame。

    维度：规模 / 估值 / 波动（日频，对应 FACTOR_REGISTRY 中 factor_source = 'stock_daily_basic'）。
    """
    with get_session() as session:
        if fields:
            q = session.query(*[getattr(StockDailyBasic, f) for f in fields])
        else:
            q = session.query(StockDailyBasic)
        if ts_code is not None:
            q = q.filter(
                StockDailyBasic.ts_code.in_(ts_code)
                if isinstance(ts_code, list) else StockDailyBasic.ts_code == ts_code
            )
        if trade_date is not None:
            q = q.filter(StockDailyBasic.trade_date == trade_date)
        if start_date is not None:
            q = q.filter(StockDailyBasic.trade_date >= start_date)
        if end_date is not None:
            q = q.filter(StockDailyBasic.trade_date <= end_date)
        df = pd.read_sql(q.statement, session.bind) if q.count() > 0 else _empty_df(StockDailyBasic)
    return df


def get_weekly_by_trade_date(
    ts_code: str | list[str] | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """
    按交易日期 trade_date 截面（或区间）查询周K线行情，返回 DataFrame。

    维度：波动（周频，对应 FACTOR_REGISTRY 中 factor_source = 'stock_weekly'）。
    """
    with get_session() as session:
        if fields:
            q = session.query(*[getattr(StockWeekly, f) for f in fields])
        else:
            q = session.query(StockWeekly)
        if ts_code is not None:
            q = q.filter(
                StockWeekly.ts_code.in_(ts_code)
                if isinstance(ts_code, list) else StockWeekly.ts_code == ts_code
            )
        if trade_date is not None:
            q = q.filter(StockWeekly.trade_date == trade_date)
        if start_date is not None:
            q = q.filter(StockWeekly.trade_date >= start_date)
        if end_date is not None:
            q = q.filter(StockWeekly.trade_date <= end_date)
        df = pd.read_sql(q.statement, session.bind) if q.count() > 0 else _empty_df(StockWeekly)
    return df


def get_weekly_indicator_by_trade_date(
    ts_code: str | list[str] | None = None,
    trade_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    fields: list[str] | None = None,
) -> "pd.DataFrame":
    """
    按交易日期 trade_date 截面（或区间）查询周K线技术指标，返回 DataFrame。

    维度：技术（周频，对应 FACTOR_REGISTRY 中 factor_source = 'stock_weekly_indicator'）。
    """
    with get_session() as session:
        if fields:
            q = session.query(*[getattr(StockWeeklyIndicator, f) for f in fields])
        else:
            q = session.query(StockWeeklyIndicator)
        if ts_code is not None:
            q = q.filter(
                StockWeeklyIndicator.ts_code.in_(ts_code)
                if isinstance(ts_code, list) else StockWeeklyIndicator.ts_code == ts_code
            )
        if trade_date is not None:
            q = q.filter(StockWeeklyIndicator.trade_date == trade_date)
        if start_date is not None:
            q = q.filter(StockWeeklyIndicator.trade_date >= start_date)
        if end_date is not None:
            q = q.filter(StockWeeklyIndicator.trade_date <= end_date)
        df = pd.read_sql(q.statement, session.bind) if q.count() > 0 else _empty_df(StockWeeklyIndicator)
    return df


def get_all_date() -> list[str]:
    """
    返回统一截面日期序列（因子最终统一对齐到周频时使用）。

    执行步骤：
      1. 查询 TradeCal 中 is_open='1' 的所有 cal_date（交易日历开市日）；
      2. distinct 查询 StockDailyBasic 中所有日频 trade_date；
      3. distinct 查询 StockWeeklyIndicator 中所有周频 trade_date。
    合并策略：三者取交集（intersection），仅保留三个维度都存在的截面日期，
    保证因子对齐时每个截面在日频、周频、交易日历上均有数据。结果为升序去重的 list[str]。
    """
    with get_session() as session:
        cal_dates = [r[0] for r in session.query(TradeCal.cal_date)
                     .filter(TradeCal.is_open == "1").all()]
        daily_dates = [r[0] for r in session.query(StockDailyBasic.trade_date.distinct()).all()]
        weekly_dates = [r[0] for r in session.query(StockWeeklyIndicator.trade_date.distinct()).all()]
    return sorted(set(cal_dates) & set(daily_dates) & set(weekly_dates))


if __name__ == "__main__":
    # 快速自测
    init_db()
    print("数据库初始化完成，表已创建。")
    '''
    # 添加一条测试记录
    s = add_stock(
        ts_code="600000.SH", name="浦发银行",
        symbol="600000", area="上海", industry="银行",
        market="主板", exchange="SSE", list_status="L",
        list_date="19991110",
    )
    print(f"添加测试记录: {s}")
    '''
    #all_stocks = get_all_stocks()
    #print(f"当前共 {len(all_stocks)} 条股票记录")

    dt=get_all_date()
    print(dt[0:9])