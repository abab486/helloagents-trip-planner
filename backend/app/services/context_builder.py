"""上下文构建器

把三个子 Agent 返回的超长 Markdown 文本，压缩成「有优先级 + 有 Token 预算」的 Planner Prompt。

优先级设计：
  P0 用户需求：固定保留，不参与裁剪
  P1 业务数据：景点 > 天气 > 酒店，按优先级逐级压缩
  P2 组装兜底：仍超预算时继续降级，最后才硬截断

同时会过滤掉工具失败时模型写的大段「抱歉 / 报错 / 建议」文本——这些内容对 Planner 毫无价值，
却会占用大量上下文。
"""

import json
import re
from typing import Any, Dict, Iterator, List

from ..models.mini import MiniAttraction, MiniHotel, MiniWeather
from ..models.schemas import TripRequest

# 子 Agent 在工具失败时会把整段道歉写进回答，出现这些词且没有结构化数据，就判定为无效内容
FAILURE_MARKERS = (
    "未找到工具",
    "WinError",
    "工具调用失败",
    "异步操作失败",
    "无法获取",
    "未获取到",
    "搜索未能成功",
    "查询再次失败",
    "工具暂时不可用",
    "不会凭空编造",
)

# 明显不是景点 / 酒店名的加粗文本
NOISE_NAME_KEYWORDS = (
    "推荐", "建议", "注意", "提示", "总结", "路线", "攻略", "首次",
    "如果", "可以", "需要", "原因", "下一步", "方案",
)

MAX_ATTRACTIONS = 5
MAX_HOTELS = 3
MAX_WEATHER = 4


class ContextBuilder:
    """把原始长文本压缩成结构化、可控长度的 Planner 上下文"""

    def __init__(self, max_token_budget: int = 4000):
        self.max_token_budget = max_token_budget
        self.last_stats: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    def build_planner_context(
        self,
        request: TripRequest,
        attraction_raw: str,
        weather_raw: str,
        hotel_raw: str,
    ) -> str:
        """把三个子 Agent 的原始字符串压缩成最终的 Planner Prompt"""
        tokens_before = sum(
            self.estimate_tokens(text)
            for text in (attraction_raw, weather_raw, hotel_raw)
        )

        attractions = self._extract_attractions(attraction_raw)
        weather = self._extract_weather(weather_raw)
        hotels = self._extract_hotels(hotel_raw)

        # 超出预算时逐级降级：先砍酒店，再砍天气，最后压缩景点
        while True:
            prompt = self._assemble(request, attractions, weather, hotels)
            if self.estimate_tokens(prompt) <= self.max_token_budget:
                break
            if len(hotels) > 1:
                hotels = hotels[:1]
            elif len(weather) > 2:
                weather = weather[:2]
            elif len(attractions) > 3:
                attractions = attractions[:3]
            else:
                prompt = self._truncate(prompt)
                break

        self.last_stats = {
            "tokens_before": tokens_before,
            "tokens_after": self.estimate_tokens(prompt),
            "attractions": len(attractions),
            "weather": len(weather),
            "hotels": len(hotels),
        }
        return prompt

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """粗略估算 Token：1 个汉字约 1 Token，其他字符约 0.3 Token"""
        if not text:
            return 0
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        other = len(text) - cjk
        return int(cjk + other * 0.3)

    # ------------------------------------------------------------------
    # P0：用户需求
    # ------------------------------------------------------------------
    @staticmethod
    def _build_user_requirements(request: TripRequest) -> str:
        preferences = "、".join(request.preferences) if request.preferences else "无"
        lines = [
            "【用户核心需求】",
            f"- 目的地: {request.city}",
            f"- 日期: {request.start_date} 至 {request.end_date}（{request.travel_days} 天）",
            f"- 偏好: {preferences}",
            f"- 住宿: {request.accommodation}",
            f"- 交通: {request.transportation}",
        ]
        extra = (request.free_text_input or "").strip()
        if extra:
            lines.append(f"- 额外要求: {extra}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # P1 + P2：组装
    # ------------------------------------------------------------------
    def _assemble(
        self,
        request: TripRequest,
        attractions: List[MiniAttraction],
        weather: List[MiniWeather],
        hotels: List[MiniHotel],
    ) -> str:
        lines = [self._build_user_requirements(request), "", "【可用景点信息（已精简）】"]
        lines.extend([item.to_brief() for item in attractions] or ["（未获取到景点数据）"])

        lines.extend(["", "【天气信息（已精简）】"])
        weather_lines = [item.to_brief() for item in weather if item.to_brief()]
        lines.extend(weather_lines or ["（未获取到天气数据）"])

        lines.extend(["", "【酒店推荐（已精简）】"])
        lines.extend([item.to_brief() for item in hotels] or ["（未获取到酒店数据）"])

        lines.extend([
            "",
            "【生成要求】",
            "1. 每天安排 2-3 个景点，只能从上述景点中选择，不要编造不存在的景点。",
            "2. 每天包含早中晚三餐，并推荐一个酒店。",
            "3. weather_info 覆盖每一天，温度只写数字。",
            "4. 严格按系统提示中的 JSON 结构输出，并包含 budget 预算汇总。",
        ])
        return "\n".join(lines).strip()

    def _truncate(self, prompt: str) -> str:
        limit = max(200, self.max_token_budget - 40)
        return prompt[:limit] + "\n...(信息已截断，请根据上述可用信息尽量安排)"

    # ------------------------------------------------------------------
    # 清洗工具
    # ------------------------------------------------------------------
    @staticmethod
    def _clean(raw: str) -> str:
        """去掉代码围栏、表情符号、残留的工具调用标记，并压缩空行"""
        if not raw:
            return ""
        text = raw.strip()
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(
            "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\uFE0F\u2B00-\u2BFF]",
            "",
            text,
        )
        text = re.sub(r"\[TOOL_CALL:[^\]]*\]", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _is_failure(cls, text: str) -> bool:
        """判断这段文本是不是工具失败的道歉内容"""
        if not text:
            return True
        if cls._looks_like_data(text):
            return False
        return any(marker in text for marker in FAILURE_MARKERS)

    @staticmethod
    def _looks_like_data(text: str) -> bool:
        if "|" in text and text.count("|") >= 2:
            return True
        if re.search(r"\*\*[^*\n]{2,40}\*\*\s*[（(]", text):
            return True
        return bool(re.search(r"℃|°C", text))

    @staticmethod
    def _is_noise(name: str) -> bool:
        if not name or len(name) < 2 or len(name) > 40:
            return True
        return any(keyword in name for keyword in NOISE_NAME_KEYWORDS)

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _find_price(text: str) -> str:
        match = re.search(r"(\d{2,4})\s*[-~—至到]\s*(\d{2,4})\s*元", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}元"
        match = re.search(r"(\d{2,4})\s*元(?:/晚)?", text)
        return f"{match.group(1)}元" if match else ""

    # ------------------------------------------------------------------
    # 解析：JSON / Markdown 表格 / 加粗条目 / 列表
    # ------------------------------------------------------------------
    @staticmethod
    def _try_json_rows(text: str) -> List[Dict[str, Any]]:
        candidates = []
        fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
        if fence:
            candidates.append(fence.group(1))
        candidates.append(text)

        for candidate in candidates:
            for pattern in (r"\[.*\]", r"\{.*\}"):
                match = re.search(pattern, candidate, re.S)
                if not match:
                    continue
                try:
                    data = json.loads(match.group(0))
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(data, dict):
                    for key in ("attractions", "hotels", "data", "items", "results"):
                        rows = data.get(key)
                        if isinstance(rows, list):
                            return [row for row in rows if isinstance(row, dict)]
                    return []
                if isinstance(data, list):
                    return [row for row in data if isinstance(row, dict)]
        return []

    @staticmethod
    def _table_rows(text: str) -> Iterator[List[str]]:
        for line in text.splitlines():
            if line.count("|") < 2:
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if not cells or not cells[0]:
                continue
            if set(cells[0]) <= set("-: "):
                continue
            if len(cells[0]) <= 4 and re.search(r"(名称|景点|地址|日期|天气|温度|序号|酒店|项目)", cells[0]):
                continue
            yield cells

    # ------------------------------------------------------------------
    # 三个提取器
    # ------------------------------------------------------------------
    def _extract_attractions(self, raw_text: str) -> List[MiniAttraction]:
        text = self._clean(raw_text)
        if self._is_failure(text):
            return []

        items: List[MiniAttraction] = []

        for row in self._try_json_rows(text):
            name = str(row.get("name") or "").strip()
            if name:
                items.append(MiniAttraction(
                    name=name,
                    address=str(row.get("address") or "").strip(),
                    visit_duration=self._safe_int(row.get("visit_duration"), 60),
                ))

        if not items:
            for cells in self._table_rows(text):
                name = cells[0]
                if self._is_noise(name):
                    continue
                items.append(MiniAttraction(
                    name=name,
                    address=cells[1] if len(cells) > 1 else "",
                ))

        if not items:
            for match in re.finditer(r"\*\*([^*\n]{2,40})\*\*\s*(?:[（(]([^）)\n]{2,60})[）)])?", text):
                name = match.group(1).strip()
                if self._is_noise(name):
                    continue
                items.append(MiniAttraction(name=name, address=(match.group(2) or "").strip()))

        if not items:
            for line in text.splitlines():
                match = re.match(
                    r"^\s*[-*+]\s+(.{2,40}?)\s*(?:[（(]([^）)]{2,60})[）)])?\s*$",
                    line,
                )
                if not match:
                    continue
                name = match.group(1).strip()
                if self._is_noise(name):
                    continue
                items.append(MiniAttraction(name=name, address=(match.group(2) or "").strip()))

        return self._dedup_attractions(items)[:MAX_ATTRACTIONS]

    def _extract_hotels(self, raw_text: str) -> List[MiniHotel]:
        text = self._clean(raw_text)
        if self._is_failure(text):
            return []

        items: List[MiniHotel] = []

        for row in self._try_json_rows(text):
            name = str(row.get("name") or "").strip()
            if name:
                items.append(MiniHotel(
                    name=name,
                    price_range=str(row.get("price_range") or "").strip(),
                ))

        if not items:
            for cells in self._table_rows(text):
                joined = " ".join(cells)
                if re.search(r"(酒店|宾馆|客栈|民宿)", cells[0]) or self._find_price(joined):
                    items.append(MiniHotel(name=cells[0], price_range=self._find_price(joined)))

        if not items:
            for match in re.finditer(r"\*\*([^*\n]{2,40})\*\*([^\n]{0,80})", text):
                name = match.group(1).strip()
                tail = match.group(2)
                price = self._find_price(tail)
                if re.search(r"(酒店|宾馆|客栈|民宿)", name) or price:
                    items.append(MiniHotel(name=name, price_range=price))

        if not items:
            for line in text.splitlines():
                stripped = line.strip(" \t-*+#")
                if re.search(r"(酒店|宾馆|客栈|民宿)", stripped) and len(stripped) <= 80:
                    name = re.split(r"[（(]", stripped)[0].strip(" -*")
                    items.append(MiniHotel(name=name, price_range=self._find_price(stripped)))

        seen = set()
        result: List[MiniHotel] = []
        for item in items:
            if item.name in seen or self._is_noise(item.name):
                continue
            seen.add(item.name)
            result.append(item)
        return result[:MAX_HOTELS]

    def _extract_weather(self, raw_text: str) -> List[MiniWeather]:
        text = self._clean(raw_text)
        if self._is_failure(text):
            return []

        items: List[MiniWeather] = []

        for cells in self._table_rows(text):
            joined = " ".join(cells)
            if re.search(r"\d", cells[0]) and re.search(r"(晴|多云|阴|雨|雪|雾|霾|℃|°C)", joined):
                items.append(MiniWeather(
                    date=cells[0],
                    weather=cells[1] if len(cells) > 1 else "",
                    temp=cells[2] if len(cells) > 2 else "",
                ))

        if not items:
            for line in text.splitlines():
                stripped = line.strip(" \t-*#")
                if not stripped or len(stripped) > 60:
                    continue
                has_date = re.search(r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s*月\s*\d{1,2}\s*日)", stripped)
                has_temp = "℃" in stripped or "°C" in stripped
                if has_date or has_temp:
                    items.append(MiniWeather(weather=stripped))

        return items[:MAX_WEATHER]

    # ------------------------------------------------------------------
    # 去重
    # ------------------------------------------------------------------
    @staticmethod
    def _dedup_attractions(items: List[MiniAttraction]) -> List[MiniAttraction]:
        """按名称去重，并去掉「西津渡历史文化街区-凉亭」这类子景点"""
        names = {item.name for item in items}
        result: List[MiniAttraction] = []
        seen = set()
        for item in items:
            if item.name in seen:
                continue
            if "-" in item.name:
                parent = item.name.split("-", 1)[0]
                if parent in names and parent != item.name:
                    continue
            seen.add(item.name)
            result.append(item)
        return result
