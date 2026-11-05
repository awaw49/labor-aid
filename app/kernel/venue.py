"""立案路径：城市参数 → 仲裁 / 诉讼 / 撤销 / 监察 / 法律援助，全部可点。"""
from __future__ import annotations

import urllib.parse


def _map_url(q: str) -> str:
    return "https://uri.amap.com/search?keyword=" + urllib.parse.quote(q)


def build_venue(city: dict, slots: dict, deadline: dict) -> list[dict]:
    blocks: list[dict] = []

    for a in city["arbitration"]:
        blocks.append({
            "stage": "仲裁申请（主路径）",
            "name": a["name"],
            "where": a["address"],
            "tel": a["tel"],
            "hours": a["hours"],
            "note": a["note"] + " " + a["appointment"],
            "actions": [
                {"kind": "tel", "label": f"拨打 {a['tel']}", "value": a["tel"]},
                {"kind": "copy", "label": "复制地址", "value": a["address"]},
                {"kind": "map", "label": "一键导航", "value": _map_url(a["map_query"])},
            ],
        })

    for o in city["online"]:
        acts = []
        if o.get("url"):
            acts.append({"kind": "url", "label": "打开入口", "value": o["url"]})
        acts.append({"kind": "copy", "label": "复制入口说明", "value": o["how"]})
        blocks.append({
            "stage": "网上预申请（仲裁）" if o.get("type") == "web" else "手机办理（仲裁）",
            "name": o["name"],
            "where": o.get("url") or ("浙里办 App" if o.get("type") == "app" else ""),
            "note": o["how"] + "。网上申请后仍须现场核验材料。",
            "actions": acts,
        })

    c = city["court"]
    days = deadline.get("days_left")
    court_acts = []
    if c.get("url"):
        court_acts.append({"kind": "url", "label": "打开入口", "value": c["url"]})
    court_acts += [{"kind": "copy", "label": "复制操作步骤", "value": c.get("how") or c["name"]},
                   {"kind": "tel", "label": "诉讼服务热线 12368", "value": "12368"}]
    blocks.append({
        "stage": "起诉（不服裁决，仲裁之后）",
        "name": c["name"],
        "where": "微信小程序「人民法院在线服务」",
        "note": (c.get("how") or "") + " " + c["note"] + (
            f"；你的案件时效剩余 {days} 天，裁决后再起算 15 日起诉期。" if days is not None else ""
        ),
        "actions": court_acts,
    })

    blocks.append({
        "stage": "单位申请撤销（一裁终局，仅告知）",
        "name": "仲裁委所在地中级人民法院",
        "where": f"{city['city']}中级人民法院",
        "note": "一裁终局案件中，用人单位有证据证明存在法定情形的，可自收到裁决书之日起 30 日内向中级法院申请撤销；劳动者无需操作。",
        "actions": [{"kind": "text", "label": "该路径由单位发起，你不需要做", "value": "info"}],
    })

    s = city["supervision"]
    blocks.append({
        "stage": "欠薪快速通道（可与仲裁并行）",
        "name": s["name"],
        "where": s.get("where") or s["name"],
        "note": s["how"] + " " + s["note"],
        "actions": [{"kind": "tel", "label": "拨打 12333", "value": "12333"}],
    })

    aid = city["legal_aid"]
    blocks.append({
        "stage": "兜底咨询 / 法律援助",
        "name": aid["name"],
        "where": aid["how"],
        "note": "本页面不是律师意见；复杂或金额较大的案件，建议先打 12348 或到法律援助中心面谈。",
        "actions": [{"kind": "tel", "label": "拨打 12348", "value": "12348"}],
    })

    return blocks
