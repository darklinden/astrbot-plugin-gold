import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp
from astrbot.api import star, logger
from astrbot.api.event import AstrMessageEvent, filter

CST = timezone(timedelta(hours=8))
FETCH_INTERVAL = 30 * 60  # 30 minutes
OUNCE_TO_GRAM = 31.1035

# ── In-memory cache ──────────────────────────────────────────────────────────

@dataclass
class PriceData:
    metal: str
    currency: str
    update: str
    prev_close_price: str
    open_price: str
    low_price: str
    high_price: str
    price: str
    change_percent: str

@dataclass
class CachedData:
    time: float           # window timestamp
    gold_cny: Optional[PriceData] = None
    silver_cny: Optional[PriceData] = None
    gold_usd: Optional[PriceData] = None
    silver_usd: Optional[PriceData] = None

_cache: Optional[CachedData] = None
_rate_cache: Optional[tuple[float, float]] = None  # (rate, timestamp_ms)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _window_ts() -> float:
    now = time.time()
    return int(now / FETCH_INTERVAL) * FETCH_INTERVAL

def _parse_float(v) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

def _format_price(v: float, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}"


# ── Jisu API ────────────────────────────────────────────────────────────────

async def _fetch_jisu(session: aiohttp.ClientSession, url: str) -> Optional[dict]:
    for _ in range(5):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                return await resp.json()
        except Exception:
            await asyncio.sleep(1)
    return None

async def _fetch_jisu_prices(token: str) -> tuple[Optional[PriceData], Optional[PriceData]]:
    connector = aiohttp.TCPConnector(limit=1)
    async with aiohttp.ClientSession(connector=connector) as session:
        gold_url = f"https://api.jisuapi.com/gold/shgold?appkey={token}"
        silver_url = f"https://api.jisuapi.com/silver/shgold?appkey={token}"
        gold_resp, silver_resp = await asyncio.gather(
            _fetch_jisu(session, gold_url),
            _fetch_jisu(session, silver_url),
        )
    return _parse_jisu_gold(gold_resp), _parse_jisu_silver(silver_resp)

def _parse_jisu_gold(resp: Optional[dict]) -> Optional[PriceData]:
    if not resp or resp.get("status") != 0:
        return None
    results = resp.get("result", [])
    item = next((r for r in results if r.get("type") == "AU99.99"), None)
    if not item:
        return None
    return PriceData(
        metal="XAU", currency="CNY",
        update=item.get("updatetime", "N/A"),
        prev_close_price=str(_parse_float(item.get("lastclosingprice"))),
        open_price=str(_parse_float(item.get("openingprice"))),
        low_price=str(_parse_float(item.get("minprice"))),
        high_price=str(_parse_float(item.get("maxprice"))),
        price=str(_parse_float(item.get("price"))),
        change_percent=str(_parse_float(item.get("changepercent"))),
    )

def _parse_jisu_silver(resp: Optional[dict]) -> Optional[PriceData]:
    if not resp or resp.get("status") != 0:
        return None
    results = resp.get("result", [])
    item = next((r for r in results if r.get("type") == "Ag99.99"), None)
    if not item:
        return None
    div = lambda v: f"{_parse_float(v) / 1000:.2f}"
    change = item.get("changepercent")
    change_str = f"{_parse_float(change):.2f}%" if change else "N/A"
    return PriceData(
        metal="XAG", currency="CNY",
        update=item.get("updatetime", "N/A"),
        prev_close_price=div(item.get("lastclosingprice", 0)),
        open_price=div(item.get("openingprice", 0)),
        low_price=div(item.get("minprice", 0)),
        high_price=div(item.get("maxprice", 0)),
        price=div(item.get("price", 0)),
        change_percent=change_str,
    )


# ── GoldAPI ─────────────────────────────────────────────────────────────────

async def _fetch_goldapi(session: aiohttp.ClientSession, url: str, api_key: str) -> Optional[dict]:
    for _ in range(5):
        try:
            async with session.get(url, headers={"x-api-key": api_key},
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                return await resp.json()
        except Exception:
            await asyncio.sleep(1)
    return None

async def _fetch_goldapi_prices(token: str) -> tuple[Optional[PriceData], Optional[PriceData]]:
    now = int(time.time())
    start = now - 24 * 3600
    connector = aiohttp.TCPConnector(limit=1)
    async with aiohttp.ClientSession(connector=connector) as session:
        gold_price, gold_hist, silver_price, silver_hist = await asyncio.gather(
            _fetch_goldapi(session, "https://api.gold-api.com/price/XAU", token),
            _fetch_goldapi(session, f"https://api.gold-api.com/ohlc/XAU?startTimestamp={start}&endTimestamp={now}", token),
            _fetch_goldapi(session, "https://api.gold-api.com/price/XAG", token),
            _fetch_goldapi(session, f"https://api.gold-api.com/ohlc/XAG?startTimestamp={start}&endTimestamp={now}", token),
        )
    return (
        _build_goldapi_result(gold_price, gold_hist, "XAU"),
        _build_goldapi_result(silver_price, silver_hist, "XAG"),
    )

def _build_goldapi_result(price_resp, history_resp, metal) -> Optional[PriceData]:
    if not price_resp and not history_resp:
        return None

    price_str = str(price_resp.get("price", "")) if price_resp else None
    update_ts = price_resp.get("updatedAt", "") if price_resp else ""

    prev_close = str(history_resp.get("close", "")) if history_resp else None
    open_p = str(history_resp.get("open", "")) if history_resp else None
    high = str(history_resp.get("high", "")) if history_resp else None
    low = str(history_resp.get("low", "")) if history_resp else None
    change = history_resp.get("openCloseChangePercent", None) if history_resp else None

    return PriceData(
        metal=metal, currency="USD",
        update=str(update_ts) if update_ts else "N/A",
        prev_close_price=prev_close or "N/A",
        open_price=open_p or "N/A",
        low_price=low or "N/A",
        high_price=high or "N/A",
        price=price_str or "N/A",
        change_percent=f"{float(change):.2f}%" if change else "N/A",
    )


# ── Currency API ────────────────────────────────────────────────────────────

async def _fetch_usd_cny_rate(token: str) -> Optional[float]:
    global _rate_cache
    if _rate_cache:
        rate, ts = _rate_cache
        if (time.time() * 1000 - ts) < FETCH_INTERVAL * 1000:
            return rate

    url = f"https://currencyapi.net/api/v2/rates?base=USD&output=json&key={token}"
    connector = aiohttp.TCPConnector(limit=1)
    async with aiohttp.ClientSession(connector=connector) as session:
        for _ in range(5):
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    data = await resp.json()
                    rate = data.get("rates", {}).get("CNY")
                    if rate:
                        _rate_cache = (float(rate), time.time() * 1000)
                        return float(rate)
            except Exception:
                await asyncio.sleep(1)
    return None


# ── Aggregate ───────────────────────────────────────────────────────────────

async def _get_prices(jisu_token: str, gold_token: str, currency_token: str) -> tuple[CachedData, Optional[float]]:
    global _cache
    window = _window_ts()

    if _cache and _cache.time + FETCH_INTERVAL > time.time():
        logger.debug(f"[gold] Cache hit for window {window}")
    else:
        logger.debug("[gold] Fetching fresh prices...")

        gold_cny, silver_cny = await _fetch_jisu_prices(jisu_token)
        gold_usd, silver_usd = await _fetch_goldapi_prices(gold_token)

        _cache = CachedData(
            time=window,
            gold_cny=gold_cny,
            silver_cny=silver_cny,
            gold_usd=gold_usd,
            silver_usd=silver_usd,
        )

    rate = await _fetch_usd_cny_rate(currency_token)
    return _cache, rate


# ── Format response ─────────────────────────────────────────────────────────

def _build_response(data: CachedData, rate: Optional[float]) -> str:
    parts = []
    parts.append("💰 国内金价  数据来源: Jisu API (jisuapi.com)")

    if data.gold_cny:
        g = data.gold_cny
        parts.append(f"黄金价格: {g.price}元/克")
        parts.append(f"  开盘价: {g.open_price}元/克  最高价: {g.high_price}元/克  最低价: {g.low_price}元/克")
        parts.append(f"  涨跌幅: {g.change_percent}%  昨收价: {g.prev_close_price}元/克  更新时间: {g.update}")
    else:
        parts.append("黄金价格: 暂无数据")

    parts.append("")

    if data.silver_cny:
        s = data.silver_cny
        parts.append(f"白银价格: {s.price}元/克")
        parts.append(f"  开盘价: {s.open_price}元/克  最高价: {s.high_price}元/克  最低价: {s.low_price}元/克")
        parts.append(f"  涨跌幅: {s.change_percent}%  昨收价: {s.prev_close_price}元/克  更新时间: {s.update}")
    else:
        parts.append("白银价格: 暂无数据")

    parts.append("")
    parts.append("💰 国际金价  数据来源: GoldAPI (gold-api.com)  汇率来源: CurrencyAPI (currencyapi.net)")

    if data.gold_usd:
        g = data.gold_usd
        cny_str = f"{_parse_float(g.price) * rate / OUNCE_TO_GRAM:.2f}" if rate else "N/A"
        parts.append(f"黄金美元价格: {g.price} USD/盎司  折合 {cny_str}元/克")
        parts.append(f"  开盘价: {g.open_price} USD/盎司  最高价: {g.high_price} USD/盎司  最低价: {g.low_price} USD/盎司")
        parts.append(f"  涨跌幅: {g.change_percent}%  昨收价: {g.prev_close_price} USD/盎司  更新时间: {g.update}")
    else:
        parts.append("黄金美元价格: 暂无数据")

    parts.append("")

    if data.silver_usd:
        s = data.silver_usd
        cny_str = f"{_parse_float(s.price) * rate / OUNCE_TO_GRAM:.2f}" if rate else "N/A"
        parts.append(f"白银美元价格: {s.price} USD/盎司  折合 {cny_str}元/克")
        parts.append(f"  开盘价: {s.open_price} USD/盎司  最高价: {s.high_price} USD/盎司  最低价: {s.low_price} USD/盎司")
        parts.append(f"  涨跌幅: {s.change_percent}%  昨收价: {s.prev_close_price} USD/盎司  更新时间: {s.update}")
    else:
        parts.append("白银美元价格: 暂无数据")

    return "\n".join(parts)


# ── Plugin ──────────────────────────────────────────────────────────────────

class Main(star.Star):
    """今日金价 - 查询国内外金银实时价格。

    用法: gold 或 -gold
    数据来源: Jisu API (国内) + GoldAPI (国际)
    """

    def __init__(self, context, config=None):
        super().__init__(context, config)
        self.config = config

    def _cfg(self, key: str) -> str:
        """Read config key, fall back to env var."""
        return (self.config.get(key, "") if self.config else "") or os.getenv(key.upper(), "")

    @filter.command("gold")
    async def gold(self, event: AstrMessageEvent) -> None:
        jisu_token = self._cfg("jisu_api_token")
        gold_token = self._cfg("gold_api_token")
        currency_token = self._cfg("currency_api_token")

        if not jisu_token and not gold_token:
            yield event.plain_result(
                "金价查询未配置 API Key。请在 WebUI 插件配置中填写 Jisu API Token 和 GoldAPI Token。"
            )
            return

        try:
            data, rate = await _get_prices(jisu_token, gold_token, currency_token)
        except Exception as e:
            logger.error(f"[gold] Error: {e}")
            yield event.plain_result("金价查询出错，请稍后再试。")
            return

        try:
            from .gold_card import build_card  # late import to avoid circular dep
            import tempfile
            png_bytes = build_card(data, rate)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(png_bytes)
                temp_path = f.name
            yield event.image_result(temp_path)
        except Exception as e:
            logger.error(f"[gold] Image render failed, falling back to text: {e}")
            yield event.plain_result(_build_response(data, rate))
