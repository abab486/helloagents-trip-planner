"""上下文压缩用的精简数据模型

子 Agent 返回的是大段 Markdown（表格、表情符号、推荐语），直接拼给 Planner 会浪费大量 Token。
这里只保留规划行程真正需要的字段，用于结构化承接清洗结果。
"""

from typing import Optional

from pydantic import BaseModel


class MiniAttraction(BaseModel):
    """精简景点：只保留名称、地址、建议游览时长"""

    name: str
    address: Optional[str] = ""
    visit_duration: int = 60

    def to_brief(self) -> str:
        """压成一行文本，供 Prompt 使用"""
        address = f"（{self.address}）" if self.address else ""
        return f"- {self.name}{address}"


class MiniHotel(BaseModel):
    """精简酒店：只保留名称和价格区间"""

    name: str
    price_range: Optional[str] = ""

    def to_brief(self) -> str:
        price = f"（{self.price_range}）" if self.price_range else ""
        return f"- {self.name}{price}"


class MiniWeather(BaseModel):
    """精简天气：日期 + 天气 + 温度，其余（风力、湿度等）丢弃"""

    date: str = ""
    weather: str = ""
    temp: str = ""

    def to_brief(self) -> str:
        parts = [item for item in (self.date, self.weather, self.temp) if item]
        return "- " + " ".join(parts) if parts else ""
