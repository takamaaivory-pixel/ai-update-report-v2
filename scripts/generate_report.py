import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from html import escape

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set.")

JST = timezone(timedelta(hours=9))
TODAY = datetime.now(JST).strftime("%Y-%m-%d")
MODEL = "gemini-3.1-flash-lite"
STATE_PATH = "data/audit_process_state.json"

MATURITY_RUBRIC = {
    1: "検討段階：活用方法を検討・情報収集している",
    2: "試行段階：PoC・パイロット・一部利用・導入を開始している",
    3: "定着段階：定型・定常・標準・本番運用として工程に組み込まれている",
    4: "連携段階：複数工程・部門をまたいで統合・連携して運用している",
    5: "高度化段階：継続監視とフィードバックを伴う改善サイクル・自律運用が定着している",
}

RESPONSE_CLASSES = {
    "required_now": "現在対応が必要", "required_if_used": "利用する場合に対応",
    "consider": "今後検討", "information_only": "情報収集のみ",
}
PROCESS_LABELS = {
    "1": "① リスク評価", "2": "② 監査計画", "3": "③ 資料収集", "4": "④ 分析・検証",
    "5": "⑤ 指摘・原因分析", "6": "⑥ 報告", "7": "⑦ フォローアップ",
}

def as_text_list(value, limit=5):
    return [str(x).strip() for x in value if str(x).strip()][:limit] if isinstance(value, list) else []

def normalize_v24(result):
    top5 = result.get("top5", []) if isinstance(result.get("top5", []), list) else []
    items = []
    for i, raw in enumerate(top5[:5], 1):
        raw = raw if isinstance(raw, dict) else {}
        cls = str(raw.get("response_classification", "information_only"))
        cls = cls if cls in RESPONSE_CLASSES else "information_only"
        item = dict(raw)
        item.update({"id": f"U{i}", "response_classification": cls,
                     "related_audit_processes": [str(x) for x in raw.get("related_audit_processes", []) if str(x) in PROCESS_LABELS],
                     "audit_impact": str(raw.get("audit_impact") or raw.get("audit") or ""),
                     "recommended_actions": as_text_list(raw.get("recommended_actions")),
                     "maturity_impact": str(raw.get("maturity_impact") or "現時点では成熟度への変更なし")})
        items.append(item)
    result["top5"] = items
    valid_ids = {x["id"] for x in items}
    watches = result.get("watch", []) if isinstance(result.get("watch", []), list) else []
    result["watch"] = [{"theme": str((x if isinstance(x, dict) else {"theme": x}).get("theme", "")),
                         "source_update_ids": [str(v) for v in (x if isinstance(x, dict) else {}).get("source_update_ids", []) if str(v) in valid_ids],
                         "watch_reason": str((x if isinstance(x, dict) else {}).get("watch_reason", "")),
                         "response_classification": str((x if isinstance(x, dict) else {}).get("response_classification", "information_only")),
                         "recommended_action": str((x if isinstance(x, dict) else {}).get("recommended_action", ""))} for x in watches[:5]]
    for x in result["watch"]:
        if x["response_classification"] not in RESPONSE_CLASSES: x["response_classification"] = "information_only"
    return result


def fetch_news(query, limit=6):
    params = urllib.parse.urlencode({"q": f"{query} when:7d", "hl": "en-US", "gl": "US", "ceid": "US:en"})
    url = "https://news.google.com/rss/search?" + params
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            root = ET.fromstring(r.read())
        out = []
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date = (item.findtext("pubDate") or "").strip()
            source = item.find("source")
            name = (source.text or "").strip() if source is not None else ""
            if title:
                out.append(f"- {title} | source={name} | date={date} | link={link}")
        return "\n".join(out) or "(none)"
    except Exception as e:
        print(f"News fetch failed: {e}")
        return "(unavailable)"


def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"x-goog-api-key": API_KEY, "Content-Type": "application/json"}, method="POST")
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode())
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"] if isinstance(p, dict)).strip()
        except urllib.error.HTTPError as e:
            e.read()
            print(f"Gemini HTTP {e.code} on attempt {attempt}/5")
            if e.code != 429 or attempt == 5:
                raise
            retry_after = e.headers.get("Retry-After") if e.headers else None
            try:
                wait = min(max(int(retry_after), 1), 300) if retry_after else min(2 ** attempt, 60)
            except ValueError:
                wait = min(2 ** attempt, 60)
            print(f"429 retry in {wait}s")
            time.sleep(wait)


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Gemini did not return a JSON object.")
    return json.loads(text[start:end + 1])


def previous_snapshot(state):
    history = state.get("history", [])
    today = state.get("last_updated", "")
    candidates = [x for x in history if x.get("date") and x.get("date") != today]
    return candidates[-1].get("processes", {}) if candidates else {}


def main():
    with open(STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)
    old = state["processes"]
    prev = previous_snapshot(state)
    news = "\n\n".join([
        "OpenAI:\n" + fetch_news("site:openai.com ChatGPT OpenAI"),
        "Google:\n" + fetch_news("site:blog.google Gemini Google AI"),
        "Anthropic:\n" + fetch_news("site:anthropic.com Claude Anthropic"),
        "Microsoft:\n" + fetch_news("site:techcommunity.microsoft.com Copilot Microsoft"),
        "Broader:\n" + fetch_news("OpenAI ChatGPT OR Google Gemini OR Anthropic Claude OR Microsoft Copilot"),
    ])
    rubric_text = "\n".join(f"Lv{k}: {v}" for k, v in MATURITY_RUBRIC.items())
    prompt = f'''あなたは内部監査・AIガバナンス向け週刊レポート編集者です。基準日={TODAY}。
ニュース候補だけを根拠に、事実と監査上の考察を分けてください。創作は禁止。確認できない製品名・機能・価格・URLは出さないでください。

現在の7工程状態:
{json.dumps(old, ensure_ascii=False, indent=2)}

成熟度の定義（AI機能の性能ではなく、監査工程への実運用の定着度）:
{rubric_text}

重要ルール:
- ニュースにAI機能の高度化があっても、それだけで監査工程の成熟度を上げないでください。
- 監査工程で実際に試行・導入・運用したことが確認できる場合だけ、更新候補にしてください。
- 「検討」「可能」「期待」「活用できる」だけでは成熟度2以上の根拠になりません。
- 更新なしなら現在の内容を維持し、status=unchangedとしてください。

今週のニュース候補:
{news}

JSONだけを返してください。HTMLやMarkdownは禁止。
形式:
{{
  "top5": [{{"title":"", "type":"新規|変更|継続|終了", "importance":"★★★|★★☆|★☆☆", "fact":"", "audit_impact":"", "response_classification":"required_now|required_if_used|consider|information_only", "related_audit_processes":["1"], "recommended_actions":[""], "maturity_impact":""}}],
  "companies": {{"openai":[],"gemini":[],"claude":[],"microsoft":[]}},
  "audit_implication":"",
  "process_updates": {{"1":{{"status":"updated|unchanged","current":"","reason":"","maturity":1}},"2":{{}},"3":{{}},"4":{{}},"5":{{}},"6":{{}},"7":{{}}}},
  "watch": [{{"theme":"", "source_update_ids":["U1"], "watch_reason":"", "response_classification":"information_only", "recommended_action":""}}],
  "sources": [{{"name":"","url":""}}]
}}
process_updatesのmaturityは上記定義に従う1～5の候補値です。最終的な成熟度は後段の固定Python処理でも検証・制限されます。AIは監査判断を代替せず、原資料・ログによる人間の検証が必要という前提を維持してください。'''
    result = normalize_v24(parse_json(call_gemini(prompt)))

    updates = result.get("process_updates", {})
    for key, item in old.items():
        u = updates.get(key, {})
        status = u.get("status", "unchanged")
        if status == "updated":
            item["status"] = "updated"
            item["previous"] = item["current"]
            item["current"] = u.get("current", item["current"])
            item["change_reason"] = u.get("reason", "")
            item["maturity"] = max(1, min(5, int(u.get("maturity", item.get("maturity", 1)))))
        else:
            item["status"] = "unchanged"

    # Explicit week-over-week delta for auditability.
    changes = []
    for key in map(str, range(1, 8)):
        current_level = int(old[key].get("maturity", 1))
        previous_level = int(prev.get(key, {}).get("maturity", current_level))
        delta = current_level - previous_level
        changes.append({
            "process": key,
            "name": old[key].get("name", ""),
            "previous_maturity": previous_level,
            "current_maturity": current_level,
            "delta": delta,
            "status": old[key].get("status", "unchanged"),
            "reason": old[key].get("change_reason", "") if delta != 0 or old[key].get("status") == "updated" else "",
        })
    state["last_updated"] = TODAY
    state["maturity_changes"] = changes
    state["history"] = [x for x in state.get("history", []) if x.get("date") != TODAY]
    state["history"].append({"date": TODAY, "processes": json.loads(json.dumps(old, ensure_ascii=False))})
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    def li(text): return "<li>" + escape(str(text)) + "</li>"
    html = ['<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI・内部監査継続的高度化レポート</title><style>body{font-family:system-ui,-apple-system,sans-serif;background:#f4f6f8;color:#202124;margin:0;padding:18px;line-height:1.7}main{max-width:1000px;margin:auto}section,header,footer{background:white;padding:20px;border-radius:14px;margin-bottom:16px;box-shadow:0 2px 10px #0001}h1{margin-top:0}h2{border-bottom:2px solid #eee;padding-bottom:6px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ddd;padding:9px;vertical-align:top}th{background:#f7f7f7}.updated{background:#fde7e9;color:#b3261e;font-weight:700}.unchanged{background:#f1f3f4;color:#5f6368;font-weight:700}.score{font-size:1.4em}.up{font-weight:700}.flat{font-weight:600}@media(max-width:600px){body{padding:9px}section,header,footer{padding:14px}table{display:block;overflow-x:auto}}</style></head><body><main>']
    html.append(f'<header><h1>AI・内部監査継続的高度化レポート</h1><p><strong>基準日：</strong>{escape(TODAY)}</p><p>AIアップデートを内部監査7工程の継続的な高度化へ結び付け、前週からの変化を蓄積します。</p></header>')
    html.append('<section><h2>1. 今週の重要アップデートTOP5</h2><p>各情報について、現時点の自社対応と内部監査への関係を分けて表示します。</p><table><tr><th>重要度</th><th>項目・自社対応</th><th>確認できた事実</th><th>監査への影響・関連工程・推奨アクション・成熟度への影響</th></tr>')
    for x in result.get("top5", [])[:5]:
        processes = "、".join(PROCESS_LABELS[p] for p in x["related_audit_processes"]) or "該当工程なし（情報収集）"
        actions = "<br>".join("・" + escape(a) for a in x["recommended_actions"]) or "個別アクションなし"
        detail = f'<strong>内部監査への影響：</strong>{escape(x["audit_impact"])}<br><strong>関連する内部監査7工程：</strong>{escape(processes)}<br><strong>推奨アクション：</strong>{actions}<br><strong>成熟度への影響：</strong>{escape(x["maturity_impact"])}'
        html.append(f'<tr><td class="score">{escape(str(x.get("importance","")))}</td><td><strong>{escape(str(x.get("type","")))}</strong><br>{escape(str(x.get("title","")))}<br><strong>自社対応：</strong>{escape(RESPONSE_CLASSES[x["response_classification"]])}</td><td>{escape(str(x.get("fact","")))}</td><td>{detail}</td></tr>')
    html.append('</table></section>')
    names = [("openai","2. ChatGPT / OpenAI"),("gemini","3. Gemini / Google"),("claude","4. Claude / Anthropic"),("microsoft","5. Microsoft Copilot")]
    for key, heading in names:
        html.append(f'<section><h2>{heading}</h2><ul>')
        items = result.get("companies", {}).get(key, [])
        for x in items[:4]:
            html.append(li(x if isinstance(x, str) else f"{x.get('title','')}: {x.get('fact','')} / 監査: {x.get('audit','')}"))
        html.append('</ul></section>')
    html.append(f'<section><h2>6. 内部監査への示唆</h2><p>{escape(str(result.get("audit_implication","")))}</p></section>')
    html.append('<section><h2>7. 内部監査プロセスの高度化への有用性</h2><table><tr><th>工程</th><th>状態</th><th>成熟度</th><th>前週比</th><th>内容</th></tr>')
    labels = {"1":"① リスク評価","2":"② 監査計画","3":"③ 資料収集","4":"④ 分析・検証","5":"⑤ 指摘・原因分析","6":"⑥ 報告","7":"⑦ フォローアップ"}
    for change in changes:
        key = change["process"]
        p = old[key]
        cls = "updated" if p["status"] == "updated" else "unchanged"
        delta = change["delta"]
        delta_text = f'+{delta}' if delta > 0 else str(delta)
        html.append(f'<tr><td>{labels[key]}</td><td class="{cls}">{"更新あり" if p["status"] == "updated" else "更新なし"}</td><td>{change["current_maturity"]}/5</td><td class="{"up" if delta > 0 else "flat"}">{delta_text}</td><td>{escape(p["current"])}</td></tr>')
    html.append('</table><h3>成熟度の判定基準</h3><table><tr><th>Lv</th><th>基準</th></tr>')
    for level, description in MATURITY_RUBRIC.items():
        html.append(f'<tr><td>{level}/5</td><td>{escape(description)}</td></tr>')
    html.append('</table><h3>今週の変化</h3><ul>')
    for change in changes:
        if change["delta"] != 0 or change["status"] == "updated":
            text = f'{change["name"]}: {change["previous_maturity"]}/5 → {change["current_maturity"]}/5'
            if change["reason"]: text += f' — {change["reason"]}'
            html.append(li(text))
    if not any(c["delta"] != 0 or c["status"] == "updated" for c in changes):
        html.append(li("成熟度の変化はありません。"))
    html.append('</ul><p><strong>原則：</strong>AIの出力は監査証拠そのものではありません。原資料・ログ・承認記録と突き合わせ、監査人が最終判断します。</p></section>')
    html.append('<section><h2>8. 今後ウォッチすべき事項</h2><table><tr><th>テーマ</th><th>今回の関連アップデート</th><th>ウォッチ理由</th><th>自社対応・推奨アクション</th></tr>')
    for x in result.get("watch", [])[:5]:
        html.append(f'<tr><td>{escape(x["theme"])}</td><td>{escape("、".join(x["source_update_ids"]) or "明示的な紐付けなし")}</td><td>{escape(x["watch_reason"])}</td><td><strong>{escape(RESPONSE_CLASSES[x["response_classification"]])}</strong><br>{escape(x["recommended_action"])}</td></tr>')
    html.append('</table></section>')
    html.append('<section><h2>9. 情報源</h2><ul>')
    for s in result.get("sources", []):
        url, name = str(s.get("url","")), str(s.get("name",""))
        if url.startswith("http://") or url.startswith("https://"):
            html.append(f'<li><a href="{escape(url, quote=True)}" rel="noopener">{escape(name or url)}</a></li>')
    html.append('</ul></section><footer><p>このレポートは公開情報に基づく情報整理であり、監査判断そのものを代替するものではありません。</p></footer></main></body></html>')
    with open("index.html", "w", encoding="utf-8") as f:
        f.write("".join(html))

if __name__ == "__main__":
    main()
