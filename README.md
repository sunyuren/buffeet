# Buffett 量化分析系统

金融量化分析与策略回测工具。

## 项目结构

```
buffeet/
├── data/               # 数据存储
│   ├── raw/            #   自动抓取入库的原始数据
│   ├── processed/      #   加工后的数据
│   └── reference/      #   手动补充的数据参考文件（不入库，供手动分析引用）
├── notebooks/          # Jupyter Notebook
├── src/                # 核心代码
│   ├── data_fetch.py   #   数据获取
│   ├── indicators.py   #   技术指标
│   ├── strategies.py   #   策略定义
│   └── backtest.py     #   回测引擎
├── output/             # 输出结果
├── config.py           # 配置文件
├── main.py             # 主入口
└── requirements.txt    # 依赖列表
```

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```
