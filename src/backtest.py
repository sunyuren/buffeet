# -*- coding: utf-8 -*-
"""
回测引擎模块
基于向量化回测的实现
"""

import pandas as pd
import numpy as np


def run_backtest(data, signals, initial_capital=100000):
    """
    简单的向量化回测

    Parameters:
        data: DataFrame, 含 OHLCV 数据
        signals: Series, 交易信号 (1=买入, -1=卖出, 0=持仓)
        initial_capital: 初始资金

    Returns:
        dict: 回测结果 (收益曲线、夏普比率、最大回撤等)
    """
    returns = data['close'].pct_change()
    strategy_returns = signals.shift(1) * returns
    equity_curve = (1 + strategy_returns).cumprod() * initial_capital

    total_return = (equity_curve.iloc[-1] / initial_capital - 1)
    sharpe = strategy_returns.mean() / strategy_returns.std() * np.sqrt(252)

    drawdown = equity_curve / equity_curve.cummax() - 1
    max_drawdown = drawdown.min()

    return {
        'equity_curve': equity_curve,
        'total_return': total_return,
        'sharpe_ratio': sharpe,
        'max_drawdown': max_drawdown,
    }
