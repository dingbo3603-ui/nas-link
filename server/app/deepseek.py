import json
import re
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .config import Settings


ALLOWED_CATEGORIES = ["文档", "表格", "图片", "视频", "音频", "压缩包", "代码", "安装包", "其他"]


@dataclass
class Classification:
    category: str
    subcategory: str
    tags: list[str]
    summary: str
    confidence: float
    source: str = "deepseek"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeepSeekClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    async def _chat_json(self, model: str, system: str, user: str, max_tokens: int = 1_500) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("DeepSeek API key is not configured")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": max_tokens,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            response = await client.post(
                f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        if not content:
            raise RuntimeError("DeepSeek returned empty JSON content")
        return json.loads(content)

    async def classify(self, name: str, mime_type: str, size: int, extracted_text: str) -> Classification:
        snippet = ""
        if self.settings.deepseek_content_mode == "snippet":
            snippet = extracted_text[:10_000]
        system = (
            "你是私人NAS资料整理员。只能根据用户提供的文件元数据和文本片段分类，"
            "不得编造文件内容。输出json，字段固定为 category、subcategory、tags、summary、confidence。"
            f"category只能取：{ALLOWED_CATEGORIES}。subcategory使用2到12个简体中文字符；"
            "tags为最多8个短标签；summary不超过80个汉字；confidence为0到1。"
        )
        user = json.dumps(
            {"filename": name, "mime_type": mime_type, "size": size, "text_snippet": snippet},
            ensure_ascii=False,
        )
        data = await self._chat_json(self.settings.deepseek_classify_model, system, user)
        category = data.get("category") if data.get("category") in ALLOWED_CATEGORIES else "其他"
        tags = [str(tag)[:30] for tag in data.get("tags", []) if str(tag).strip()][:8]
        return Classification(
            category=category,
            subcategory=_clean_label(str(data.get("subcategory") or "未分类")),
            tags=tags,
            summary=str(data.get("summary") or "")[:160],
            confidence=max(0.0, min(1.0, float(data.get("confidence") or 0.0))),
        )

    async def expand_query(self, query: str) -> list[str]:
        if not self.configured:
            return _basic_keywords(query)
        system = (
            "你负责把中文找文件请求转换成检索词。输出json："
            '{"keywords":["词1","词2"]}。保留产品名、姓名、订单号、日期、扩展名等关键实体，最多10个词。'
        )
        data = await self._chat_json(self.settings.deepseek_classify_model, system, query, max_tokens=500)
        keywords = [str(item).strip()[:80] for item in data.get("keywords", []) if str(item).strip()]
        return keywords[:10] or _basic_keywords(query)

    async def answer_search(self, query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        if not self.configured:
            return {
                "answer": "已按文件名、标签和摘要找到以下候选文件。配置DeepSeek后可以进一步理解自然语言并排序。",
                "file_ids": [item["id"] for item in candidates[:10]],
                "provider": "local",
            }
        compact = [
            {
                "id": item["id"],
                "name": item["original_name"],
                "path": item["relative_path"],
                "category": item.get("category"),
                "tags": item.get("tags", []),
                "summary": item.get("summary", ""),
                "created_at": item.get("created_at"),
            }
            for item in candidates[:30]
        ]
        system = (
            "你是私人NAS找文件助手。只能从候选文件中回答，绝不虚构路径。"
            "输出json：answer为简洁中文说明，file_ids为按相关性排序的候选id数组。"
            "找不到时明确说没有匹配结果。"
        )
        data = await self._chat_json(
            self.settings.deepseek_answer_model,
            system,
            json.dumps({"query": query, "candidates": compact}, ensure_ascii=False),
            max_tokens=1_200,
        )
        valid = {item["id"] for item in compact}
        ids = [item for item in data.get("file_ids", []) if item in valid]
        return {"answer": str(data.get("answer") or ""), "file_ids": ids, "provider": "deepseek"}


def _clean_label(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\r\n]+", "-", value).strip(" .-")
    return cleaned[:24] or "未分类"


def _basic_keywords(query: str) -> list[str]:
    terms = re.findall(r"[\w\u4e00-\u9fff.-]+", query.lower())
    stop = {"我", "的", "想", "要", "找", "一下", "文件", "资料", "那个", "一个", "里面", "放在", "哪里"}
    return [term for term in terms if term not in stop and len(term) > 1][:10] or [query[:80]]

