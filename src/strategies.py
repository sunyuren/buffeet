# -*- coding: utf-8 -*-
"""
策略定义模块
存放量化交易策略逻辑
"""


class BaseStrategy:
    """策略基类"""

    def __init__(self, name="BaseStrategy"):
        self.name = name

    def generate_signals(self, data):
        """生成交易信号"""
        raise NotImplementedError


class MaCrossStrategy(BaseStrategy):
    """双均线交叉策略"""

    def __init__(self, fast_window=5, slow_window=20):
        super().__init__("MACross")
        self.fast_window = fast_window
        self.slow_window = slow_window

    def generate_signals(self, data):
        """生成金叉/死叉信号"""
        # TODO: 实现双均线策略逻辑
        pass
