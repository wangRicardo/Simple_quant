# -*- coding: utf-8 -*-
"""
龙头战法量化系统 (Dragon Quant System)

把「机构行为」这一不可见变量，通过量价筹码数据识别为四个可判别的阶段：
    建仓 → 洗盘 → 启动 → 撤离

模块构成：
    datasource  数据接口层（东方财富，带缓存与重试）
    indicators  指标计算层（量能/价格/资金/筹码/形态）
    stage       四阶段识别引擎（加权证据打分卡）
    analyzer    特征工程与分析流水线
    screener    龙头候选池筛选
    report      HTML 报告渲染
    cli         命令行入口
"""
__version__ = "1.0.0"

from .datasource import EMClient
from . import indicators, stage, analyzer, screener

__all__ = ["EMClient", "indicators", "stage", "analyzer", "screener"]
