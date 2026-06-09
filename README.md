# 今日金价 (Gold Price)

AstrBot 插件 —— 查询国内外金银实时价格，生成可视化行情卡片。

## 功能

- 国内金价/银价（上海金交所 AU99.99 / Ag99.99），数据来自 [Jisu API](https://www.jisuapi.com/)
- 国际金价/银价（XAU / XAG），数据来自 [GoldAPI](https://gold-api.com/)
- 美元/人民币汇率，来自 [CurrencyAPI](https://currencyapi.net/)
- 自动将国际价格换算为元/克
- 生成精美的可视化卡片图片，失败时自动回退为纯文本

## 安装

将插件目录放入 AstrBot 的 `addons` 目录下，重启机器人即可。

## 配置

在 AstrBot WebUI 插件配置中填写以下 API Key：

| 配置项 | 说明 | 获取地址 |
| --- | --- | --- |
| `jisu_api_token` | 极速 API appkey | https://www.jisuapi.com/ |
| `gold_api_token` | GoldAPI x-api-key | https://gold-api.com/ |
| `currency_api_token` | CurrencyAPI key | https://currencyapi.net/ |

也可通过环境变量 `JISU_API_TOKEN`、`GOLD_API_TOKEN`、`CURRENCY_API_TOKEN` 配置。

## 使用

```
gold
```

或使用指令前缀：

```
-gold
```

## 依赖

- `aiohttp`
- `Pillow`
- `astrbot-api`

字体文件 `SourceHanSans-Regular.otf` 需置于插件目录下，用于渲染中文行情卡片。
