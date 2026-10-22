"""名称归一化

模型输出的名称很脏：带括号、带子景点、带「风景区」后缀、带城市名。
统一在这里清洗，再交给价格库匹配。
"""

import re

CITY_SUFFIXES = ("市",)
GENERIC_SUFFIXES = ("风景区", "景区", "旅游区", "游览区", "景点")

_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_SUB_SPOT_RE = re.compile(r"\s*(?:——|—|--|-)\s*.+$")
_TRIM_CHARS = " \t·•、,，.。:："


def normalize_city(city: str) -> str:
    """「镇江市」→「镇江」"""
    text = (city or "").strip()
    for suffix in CITY_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
    return text.strip()


def normalize_attraction_name(name: str, city: str = "") -> str:
    """清洗景点名，便于精确匹配

    例：
        金山寺(金山公园内)        → 金山寺
        西津渡历史文化街区-五十三坡 → 西津渡历史文化街区
        北固山风景区              → 北固山
        镇江市金山寺              → 金山寺
    """
    text = (name or "").strip()
    if not text:
        return ""

    # 1. 去掉括号及其中内容
    text = _PAREN_RE.sub("", text)

    # 2. 去掉子景点后缀（只保留第一个破折号之前的部分）
    text = _SUB_SPOT_RE.sub("", text)

    # 3. 去掉「城市+市」前缀（如「镇江市金山寺」）。
    #    不能直接剥裸城市名，否则「镇江博物馆」会变成「博物馆」。
    city_name = normalize_city(city)
    if city_name and text.startswith(city_name + "市"):
        text = text[len(city_name) + 1:]

    # 4. 去掉通用后缀（注意：公园可能是别名的一部分，交给别名表处理，这里不删）
    for suffix in GENERIC_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]

    return text.strip(_TRIM_CHARS)


def normalize_transport_mode(mode: str) -> str:
    """把用户填写的交通方式映射成价格库里的标准 mode"""
    text = (mode or "").strip()
    if not text:
        return "其他"

    mapping = {
        "公共交通": "公共交通",
        "公交": "公共交通",
        "地铁": "公共交通",
        "公交地铁": "公共交通",
        "打车": "打车",
        "出租车": "打车",
        "网约车": "打车",
        "自驾": "自驾",
        "开车": "自驾",
        "租车": "自驾",
        "步行": "步行",
    }
    for key, value in mapping.items():
        if key in text:
            return value
    return text
