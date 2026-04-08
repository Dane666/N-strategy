# N-strategy

`N-strategy` 是一个面向 A 股的选股扫描项目，核心思路是：

- 识别 `N 字第一笔放量启动`
- 识别 `2 到 5 天缩量回调`
- 结合 `KDJ 的 J 值超卖`
- 使用 `十字星 / 锤头线` 做洗盘确认
- 输出 `正式命中` 或 `候选观察`

如果当日没有严格满足全部条件的股票，程序也会返回评分最高的候选股，避免全市场扫描后完全没有结果。

## 一、策略逻辑

### 1. 趋势背景

- 大盘处于相对转强阶段：
  - 上证指数站上 20 日均线，或
  - 上证指数单日涨幅大于 1%
- 如果大盘不够强，则允许个股本身处于长期下跌后的底部区域

### 2. N 字第一笔

- 最近 10 个交易日内出现一根大阳线
- 涨幅大于 5%
- 当日量比 5 日均量大于 1.5

### 3. 缩量回调

- 大阳线后连续回调 2 到 5 天
- 回调期间满足以下任一超卖条件：
  - `J < 0`
  - `J < 10 且 K < 20`
- 超卖当天或次日出现十字星 / 锤头线
- 回调量能明显萎缩

### 4. 买点触发

- 今日收盘价大于昨日收盘价
- 今日 J 值大于昨日 J 值
- 今日成交量大于昨日成交量

### 5. 候选股兜底

- 如果不满足严格买点，但结构完整度较高，程序会保留为 `候选观察`
- 候选结果会明确说明缺少哪一步触发条件

## 二、项目结构

- [main.py](/Users/admin/Documents/codeHub/N-strategy/main.py)
  扫描入口
- [strategy.py](/Users/admin/Documents/codeHub/N-strategy/strategy.py)
  策略识别与评分逻辑
- [data_fetcher.py](/Users/admin/Documents/codeHub/N-strategy/data_fetcher.py)
  数据获取与缓存
- [notifier.py](/Users/admin/Documents/codeHub/N-strategy/notifier.py)
  飞书通知
- [config.py](/Users/admin/Documents/codeHub/N-strategy/config.py)
  全局参数配置

## 三、环境准备

### 1. 创建环境

```bash
conda env create -f environment.yml
```

### 2. 使用环境运行

```bash
conda run -n n-strategy python main.py --limit 50 --allow-empty
```

## 四、数据说明与运行时点

### 1. 当前数据更偏向盘后信号

本项目使用的是腾讯日线 K 线接口。

这类数据在交易时段内可能已经出现“当天这一根日线”，但其中的：

- 收盘价
- 成交量
- 涨跌幅

在收盘前都可能还没有最终定型。

因此，当前策略更适合按 **盘后日线确认策略** 使用，而不是盘中实时打板策略。

### 2. 为什么不建议盘中运行

本策略依赖以下条件：

- 今日收盘价是否高于昨日收盘价
- 今日 J 值是否拐头向上
- 今日成交量是否高于昨日成交量

这些条件在盘中都会不断变化，所以盘中运行容易出现：

- 临时满足，收盘后失效
- 量能未走完，导致误判
- J 值在收盘前来回波动

### 3. 建议运行时间

建议按 **A 股收盘后 15:10 到 15:30（北京时间）** 运行。

原因：

- 15:00 收盘后，日线数据需要一点时间落库或同步
- 15:10 之后再取数，稳定性更高
- 15:20 左右是比较稳妥的折中时点

### 4. GitHub Actions 当前定时任务

当前仓库工作流已设置为：

- 每个交易日 **15:20（北京时间）** 自动运行

GitHub Actions 使用的是 UTC 时间，所以工作流里对应为：

- `07:20 UTC`

## 五、本地使用方法

### 1. 小范围测试

```bash
conda run -n n-strategy python main.py --limit 50 --allow-empty
```

说明：

- `--limit 50` 表示只扫描前 50 只股票
- `--allow-empty` 表示即使没有结果也正常退出

### 2. 全市场扫描

```bash
conda run -n n-strategy python main.py --allow-empty --top 20
```

说明：

- 不传 `--limit` 时默认扫描全市场
- `--top 20` 表示输出和通知最多展示前 20 条

### 3. 发送飞书通知

当前推荐使用 **纯文本通知**，因为你目前的 webhook 链路会把 JSON 结构直接显示成文本，不适合卡片模式。

本地运行：

```bash
FEISHU_WEBHOOK_URL="你的 webhook" \
FEISHU_MESSAGE_MODE=text \
conda run -n n-strategy python main.py --notify --allow-empty --top 20
```

### 4. 测试飞书通知

```bash
FEISHU_WEBHOOK_URL="你的 webhook" \
FEISHU_MESSAGE_MODE=text \
conda run -n n-strategy python main.py --test-notify
```

如果看到的是整洁正文，而不是 JSON 字符串，说明当前文本通知链路配置正确。

### 5. 飞书 Flow 推荐填写方式

如果你当前使用的是 `flow/api/trigger-webhook/...` 这种 Flow Webhook，请不要再使用“完整 JSON 字符串”作为消息内容。

本项目发送给 Flow 的数据结构只有两个字段：

- `title`
- `content`

在飞书流程中建议这样配置：

1. `Webhook 触发` 节点接收请求
2. 发送消息节点中：
   - 消息标题：选择 `Webhook 触发.title`
   - 消息内容：选择 `Webhook 触发.content`

这样最终看到的是正常文本摘要，而不是整段 JSON。

## 六、GitHub Actions 使用方式

工作流文件：

- [n-strategy-scan.yml](/Users/admin/Documents/codeHub/N-strategy/.github/workflows/n-strategy-scan.yml)

### 1. 配置 GitHub Secret

打开仓库：

`Settings -> Secrets and variables -> Actions`

新增以下 Secret：

- `FEISHU_WEBHOOK_URL`

值填写你当前可用的飞书 webhook。

### 2. 手动运行工作流

打开：

`Actions -> n-strategy-scan -> Run workflow`

### 3. 工作流默认行为

工作流会自动执行：

1. 安装依赖
2. 做语法检查
3. 发送一条纯文本测试消息
4. 在北京时间 15:20 的定时任务或手动触发时进行全市场扫描
5. 发送纯文本扫描摘要

## 七、通知内容说明

通知会尽量保持简洁，只保留核心信息：

- 股票代码与名称
- 正式命中 / 候选观察
- 分组与评分
- 超卖等级与形态
- 涨幅与量比
- 回调信息
- 触发说明
- 候选原因（如果有）

## 八、补充说明

- 如果你当前使用的是飞书 Flow Webhook，建议保持 `FEISHU_MESSAGE_MODE=text`
- 如果未来切换到真正支持机器人卡片的 webhook，再考虑恢复卡片通知
