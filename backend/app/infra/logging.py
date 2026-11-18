"""带 request_id 透传的日志配置。

老代码用 print() 打 emoji，在 GBK 的 Windows 控制台会直接抛编码错误。
新链路统一走这套 logger，request_id 存在 ContextVar 里，跨层自动带上。
注意目前只有 api / service 这一侧接了它，旧链路还有一百多处 print 没迁。
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

# 当前请求的 id，默认 "-"：不在请求上下文里（启动脚本、定时任务）也不会取不到值
# 用 ContextVar 而不是 thread-local：asyncio 一个线程跑多个协程，thread-local 会串
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
_CONFIGURED = False


# 生成 12 位短 id：够区分请求，日志里又不占地方
def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


# 取当前请求 id，接口层拿它塞进响应体
def get_request_id() -> str:
    return request_id_ctx.get()


# 设值并返回 token；token 要留着，请求结束传给 reset
def set_request_id(value: str):
    return request_id_ctx.set(value)


# 用 token 复原。必须在请求结束时调，否则会污染下一个请求的上下文
def reset_request_id(token) -> None:
    request_id_ctx.reset(token)


# 每条日志经过 handler 时补上 request_id 字段
# LogRecord 本身没这个属性，格式串里的 %(request_id)s 全靠它填
class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


# 配一次就够，模块级标志防止重复配置（注意它非线程安全，并发首次调用理论上会配两遍）
def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    # 让控制台按 UTF-8 输出，老代码 emoji 崩溃就是缺了这一步
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - some streams do not support it
        pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        )
    )
    # filter 挂在 handler 上而不是 logger 上：日志冒泡到根 handler 时才统一补 id
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    # 清掉原有 handler 再装自己的；副作用是 uvicorn 自带的日志格式也一并被覆盖
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _CONFIGURED = True


# 只是 logging.getLogger 的薄封装，不建 handler 也不设级别
# 所以必须先跑过 configure_logging，否则日志只会有 Python 的默认输出
def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
