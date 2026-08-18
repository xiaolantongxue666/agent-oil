"""安全守卫（第四十一节，最小可用版本；PHASE 13 扩展）。

输入守卫 / 输出守卫，基于规则与关键词：
- 拦截针对真实生产设备的控制指令（开阀/关阀/启泵/停机 等）
- 拦截请求真实标准原文/真实企业数据的伪造意图
- 拦截敏感信息（凭据/密钥/PII）
- 输出侧拦截真实控制指令与编造的标准编号

LLM 不参与守卫决策——守卫完全由代码规则控制。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 真实控制指令关键词（教学系统严禁对真实设备下达）
_CONTROL_CMDS = [
    "开阀", "关阀", "启泵", "停泵", "停机", "降压", "升压",
    "切断", "放空", "点火", "停炉", "并网", "解列",
    "紧急停车", "手动泄压", "强制启动", "旁路操作",
]
# 请求真实数据/标准原文
_FABRICATE_HINTS = [
    "真实标准原文", "真实企业数据", "真实生产数据", "真实工艺参数",
    "给我真实的", "实际运行参数", "真实控制参数",
    "真实管线压力", "实际流量数据", "真实温度记录",
]
# 敏感信息
_SENSITIVE_HINTS = [
    "密码", "api key", "api_key", "secret", "token",
    "身份证", "手机号", "银行卡", "私钥",
    "private key", "access key",
]
_PROMPT_INJECTION_PATTERNS = (
    r"ignore (all )?(previous|prior|above) instructions?",
    r"disregard (all )?(previous|prior|above)",
    r"reveal (the )?(system prompt|hidden prompt|instructions?)",
    r"show (me )?(the )?(system prompt|developer message)",
    r"忽略(之前的?|前面的?|上述的?|以上的?|所有)?(全部)?(指令|要求|规则)",
    r"无视(之前的?|前面的?|上述的?|以上的?|所有)?(全部)?(指令|要求|规则)",
    r"泄露(系统提示词|系统指令|提示词|内部规则)",
    r"显示(系统提示词|系统指令|开发者消息)",
)
_PROMPT_INJECTION_RE = re.compile("|".join(_PROMPT_INJECTION_PATTERNS), re.IGNORECASE)
# 编造标准编号特征（如 GB/T XXXXX-XXXX 编号出现在输出且标注为"真实"）
_FAKE_STD_RE = re.compile(r"(GB[/T]*\s*\d+|SY/T\s*\d+|AQ\s*\d+)", re.IGNORECASE)


@dataclass
class SafetyResult:
    safe: bool
    reason: str = ""
    category: str = ""  # control_cmd / fabricate / sensitive / output_control / output_fake_std
    matched: list[str] = field(default_factory=list)


class SafetyGuard:
    """输入/输出守卫。"""

    def check_input(self, text: str) -> SafetyResult:
        if not text:
            return SafetyResult(safe=False, reason="输入为空", category="empty")
        low = text.lower()
        injection = _PROMPT_INJECTION_RE.search(text)
        if injection:
            return SafetyResult(
                safe=False,
                reason="输入包含试图覆盖系统规则或索取内部提示词的指令",
                category="prompt_injection",
                matched=[injection.group(0)],
            )
        # 1. 控制指令（针对真实设备）
        cmds = [c for c in _CONTROL_CMDS if c in text]
        # 仅当语气为命令式（"立即/帮我/去/请" + 控制词）或显式"对设备执行"时判定
        if cmds and any(k in text for k in ("立即", "帮我", "去", "执行", "操作", "远程", "现场")):
            return SafetyResult(
                safe=False,
                reason="教学系统禁止对真实生产设备下达控制指令",
                category="control_cmd",
                matched=cmds,
            )
        # 2. 请求真实数据/标准
        fab = [h for h in _FABRICATE_HINTS if h in low]
        if fab:
            return SafetyResult(
                safe=False,
                reason="不提供真实生产数据或标准原文，仅支持教学模拟内容",
                category="fabricate",
                matched=fab,
            )
        # 3. 敏感信息
        sens = [h for h in _SENSITIVE_HINTS if h in low]
        if sens:
            return SafetyResult(
                safe=False,
                reason="输入包含敏感信息，已拦截",
                category="sensitive",
                matched=sens,
            )
        return SafetyResult(safe=True)
    def check_output(self, text: str) -> SafetyResult:
        if not text:
            return SafetyResult(safe=True)
        # 输出含真实控制指令
        cmds = [c for c in _CONTROL_CMDS if c in text]
        if cmds and any(k in text for k in ("立即", "请", "应当", "需要")):
            return SafetyResult(
                safe=False,
                reason="输出包含疑似真实设备控制指令，已拦截",
                category="output_control",
                matched=cmds,
            )
        # 编造标准编号（仅在输出明确标注"真实标准"时判定，避免误伤教学编号）
        if ("真实标准" in text or "正式标准" in text) and _FAKE_STD_RE.search(text):
            return SafetyResult(
                safe=False,
                reason="输出疑似编造真实标准编号，已拦截",
                category="output_fake_std",
                matched=[_FAKE_STD_RE.search(text).group(0)],  # type: ignore[union-attr]
            )
        return SafetyResult(safe=True)


def build_safe_output_message(result: SafetyResult) -> str:
    """将输出守卫结果转换为统一的教学安全替代文案。"""

    return (
        f"（输出已通过安全校验调整）{result.reason}。"
        "本系统仅提供教学模拟内容，不输出真实设备控制指令或编造的标准编号。"
    )


# ---------- 单例 ----------
_guard: SafetyGuard | None = None


def get_safety_guard() -> SafetyGuard:
    global _guard
    if _guard is None:
        _guard = SafetyGuard()
    return _guard


__all__ = [
    "SafetyGuard",
    "SafetyResult",
    "build_safe_output_message",
    "get_safety_guard",
]
