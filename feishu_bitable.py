"""Fetch the SXCZ 4th table from Feishu and render its ranking image."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

API_ROOT = "https://open.feishu.cn/open-apis"


class FeishuAPIError(RuntimeError):
    """Raised when Feishu returns an unsuccessful response."""


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    app_token: str
    table_id: str

    @classmethod
    def from_environment(cls) -> "FeishuConfig":
        return cls(
            app_id=os.getenv("FEISHU_APP_ID") or "cli_aa65b34441f89d04",
            app_secret=os.getenv("FEISHU_APP_SECRET") or "aUaXeEqxZmtRrm0TMQGpbgfNpYHvQXuR",
            app_token=os.getenv("FEISHU_BITABLE_APP_TOKEN") or os.getenv("FEISHU_WIKI_TOKEN") or "APqKwRYDsiGbrJkPtWXcrhzYnGf",
            table_id=os.getenv("FEISHU_BITABLE_TABLE_ID") or "tblxCD4exXZXNWLb",
        )


def _request_json(method: str, url: str, *, body: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise FeishuAPIError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc
    except URLError as exc:
        raise FeishuAPIError(f"Network error: {exc.reason}") from exc
    if result.get("code", 0) != 0:
        raise FeishuAPIError(f"Feishu API error {result.get('code')}: {result.get('msg', result)}")
    return result


def _fetch_records(config: FeishuConfig) -> list[dict[str, Any]]:
    access_token = _request_json(
        "POST", f"{API_ROOT}/auth/v3/tenant_access_token/internal",
        body={"app_id": config.app_id, "app_secret": config.app_secret},
    )["tenant_access_token"]
    app_token = config.app_token
    if app_token.startswith("AP"):
        node = _request_json("GET", f"{API_ROOT}/wiki/v2/spaces/get_node?{urlencode({'token': app_token})}", token=access_token)["data"]["node"]
        if node.get("obj_type") != "bitable":
            raise FeishuAPIError(f"Wiki node is {node.get('obj_type')!r}, not a Bitable")
        app_token = node["obj_token"]
    records: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        query = {"page_size": "500"}
        if page_token:
            query["page_token"] = page_token
        page = _request_json("GET", f"{API_ROOT}/bitable/v1/apps/{app_token}/tables/{config.table_id}/records?{urlencode(query)}", token=access_token)["data"]
        records.extend(page.get("items", []))
        if not page.get("has_more"):
            return records
        page_token = page.get("page_token")
        if not page_token:
            raise FeishuAPIError("Feishu returned has_more=true without page_token")


GROUP_FIELD = "比赛组别"
SUBMIT_TIME_FIELD = "提交时间"
GROUPS = {
    "master": {"title": "MASTER 组", "nickname": "昵称 (Master)", "total": "Master组总分", "score_fields": ["エータ・ベータ・イータ", "Cult future", "Scythe of Death"]},
    "expert": {"title": "EXPERT 组", "nickname": "昵称 (Expert)", "total": "Expert组总分", "score_fields": ["ハードコア・シンドローム", "初音天地開闢神話", "Iudicium"]},
}


def _field_value(record: dict[str, Any], field: str) -> Any:
    value = record.get("fields", {}).get(field, "")
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        return value.get("text") or value.get("name") or value.get("value") or str(value)
    return value


def _score(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return float("-inf")


def _format_time(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000).strftime("%Y/%m/%d %H:%M")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return str(value)[:16]


def _group_rows(records: list[dict[str, Any]], group_name: str) -> tuple[list[str], list[list[str]]]:
    group = GROUPS[group_name]
    selected = [r for r in records if group_name in str(_field_value(r, GROUP_FIELD)).lower()]
    selected.sort(key=lambda r: _score(_field_value(r, group["total"])), reverse=True)
    headers = ["名次", "昵称", "总分", *group["score_fields"], SUBMIT_TIME_FIELD]
    return headers, [[str(rank), str(_field_value(record, group["nickname"])), str(_field_value(record, group["total"])), *(str(_field_value(record, field)) for field in group["score_fields"]), _format_time(_field_value(record, SUBMIT_TIME_FIELD))] for rank, record in enumerate(selected, 1)]


def _font(size: int, bold: bool = False):
    configured = os.getenv("SXCZ_FONT_PATH")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    candidates.extend([
        Path(__file__).resolve().parents[2] / "plugin_data" / "astrbot_plugin_chunithm_bot" / "fonts" / "SourceHanSans.ttc",
        Path("C:/Windows/Fonts") / ("msyhbd.ttc" if bold else "msyh.ttc"),
        Path("C:/Windows/Fonts/simsun.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansSC-Bold.otf" if bold else "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.otf"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ])
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    raise FileNotFoundError(
        "未找到支持中日文的字体。请安装 Noto Sans CJK/WenQuanYi，或设置 SXCZ_FONT_PATH 指向字体文件。"
    )


def save_ranked_tables_as_image(records: list[dict[str, Any]], output_path: str | os.PathLike[str]) -> str:
    body_font, header_font = _font(22), _font(30, True)
    padding, row_height = 16, 52
    tables = [(GROUPS[name]["title"], *_group_rows(records, name)) for name in ("master", "expert")]

    def required_width(values: list[str], minimum=100, maximum=420):
        width = max(int(body_font.getbbox(value or " ")[2]) for value in values) + padding * 2
        return min(maximum, max(minimum, width))

    nickname_width = required_width([h[1] for _, h, _ in tables] + [r[1] for _, _, rs in tables for r in rs])
    total_width = required_width([h[2] for _, h, _ in tables] + [r[2] for _, _, rs in tables for r in rs], 100, 180) + padding * 5
    submit_width = required_width([h[-1] for _, h, _ in tables] + [r[-1] for _, _, rs in tables for r in rs])
    prepared = []
    for title, headers, rows in tables:
        widths = [required_width([headers[0], *[r[0] for r in rows]]), nickname_width, total_width, total_width, total_width, total_width, submit_width]
        prepared.append((title, headers, rows, widths))
    width = max(sum(item[3]) for item in prepared)
    height = sum(row_height * (len(item[2]) + 2) + 10 for item in prepared) + 10
    image, draw = Image.new("RGB", (width, height), "white"), None
    draw = ImageDraw.Draw(image)

    def fitting_font(value, limit, base_size, bold=False):
        for size in range(base_size, 9, -1):
            font = _font(size, bold)
            if int(font.getbbox(value or " ")[2]) <= limit:
                return font
        return _font(10, bold)

    y = 10
    for title, headers, rows, widths in prepared:
        draw.text((width / 2, y + row_height / 2), title, fill="#7b2cbf" if title.startswith("MASTER") else "#c1121f", font=header_font, anchor="mm")
        y += row_height
        x = 0
        for index, header in enumerate(headers):
            draw.rectangle((x, y, x + widths[index], y + row_height), fill="#1f4e78", outline="#b7c9d6")
            draw.text((x + widths[index] / 2, y + row_height / 2), header, fill="white", font=fitting_font(header, widths[index] - 8, 22, True), anchor="mm")
            x += widths[index]
        for row_index, row in enumerate(rows):
            y += row_height
            x = 0
            for column, value in enumerate(row):
                draw.rectangle((x, y, x + widths[column], y + row_height), fill="#f3f7fa" if row_index % 2 else "white", outline="#d8e0e6")
                font = fitting_font(value[:100], widths[column] - padding * 2, 22) if 2 <= column <= 5 else body_font
                draw.text((x + widths[column] / 2, y + row_height / 2), value[:100], fill="#202124", font=font, anchor="mm")
                x += widths[column]
        y += row_height + 10
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return str(output)


def generate_ranked_tables_image(output_path: str | os.PathLike[str]) -> str:
    return save_ranked_tables_as_image(_fetch_records(FeishuConfig.from_environment()), output_path)
