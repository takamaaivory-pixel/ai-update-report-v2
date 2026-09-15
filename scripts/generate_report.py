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
            body = e.read().decode(errors="replace")
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


def main():
    with open(STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)
    old = state["processes"]
    news = "\n\n".join([
        "OpenAI:\n" + fetch_news("site:openai.com ChatGPT OpenAI"),
        "Google:\n" + fetch_news("site:blog.google Gemini Google AI"),
        "Anthropic:\n" + fetch_news("site:anthropic.com Claude Anthropic"),
        "Microsoft:\n" + fetch_news("site:techcommunity.microsoft.com Copilot Microsoft"),
        "Broader:\n" + fetch_news("OpenAI ChatGPT OR Google Gemini OR Anthropic Claude OR Microsoft Copilot"),
    ])
    prompt = f'''あなたは内部監査・AIガバナンス向け週刊レポート編集者です。基準日={TODAY}。
ニュース候補だけを根拠に、事実と監査上の考察を分けてください。創作は禁止。確認できない製品名・機能・価格・URLは出さないでください。

現在の7工程状態:
{json.dumps(old, ensure_ascii=False, indent=2)}

今週のニュース候補:
{news}

JSONだけを返してください。HTMLやMarkdownは禁止。
形式:
{{
  "top5": [{{"title":"", "type":"新規|変更|継続|終了", "importance":"★★★|★★☆|★☆☆", "fact":"", "audit":""}}],
  "companies": {{"openai":[],"gemini":[],"claude":[],"microsoft":[]}},
  "audit_implication":"",
  "process_updates": {{"1":{{"status":"updated|unchanged","current":"","reason":"","maturity":1}},"2":{{}},"3":{{}},"4":{{}},"5":{{}},"6":{{}},"7":{{}}}},
  "watch": ["", "", ""],
  "sources": [{{"name":"","url":""}}]
}}
process_updatesでは、更新なしなら現在の内容を維持し、status=unchangedとしてください。更新ありの場合だけcurrent/reason/maturityを変更してください。maturityは1～5です。AIは監査判断を代替せず、原資料・ログによる人間の検証が必要という前提を維持してください。'''
    result = parse_json(call_gemini(prompt))

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

    state["last_updated"] = TODAY
    state["history"].append({"date": TODAY, "processes": json.loads(json.dumps(old, ensure_ascii=False))})
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    def li(text): return "<li>" + escape(str(text)) + "</li>"
    html = ['<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI・内部監査継続的高度化レポート</title><style>body{font-family:system-ui,-apple-system,sans-serif;background:#f4f6f8;color:#202124;margin:0;padding:18px;line-height:1.7}main{max-width:1000px;margin:auto}section,header,footer{background:white;padding:20px;border-radius:14px;margin-bottom:16px;box-shadow:0 2px 10px #0001}h1{margin-top:0}h2{border-bottom:2px solid #eee;padding-bottom:6px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #ddd;padding:9px;vertical-align:top}th{background:#f7f7f7}.updated{background:#fde7e9;color:#b3261e;font-weight:700}.unchanged{background:#f1f3f4;color:#5f6368;font-weight:700}.score{font-size:1.4em}@media(max-width:600px){body{padding:9px}section,header,footer{padding:14px}table{display:block;overflow-x:auto}}</style></head><body><main>']
    html.append(f'<header><h1>AI・内部監査継続的高度化レポート</h1><p><strong>基準日：</strong>{escape(TODAY)}</p><p>AIアップデートを内部監査7工程の継続的な高度化へ結び付け、前週からの変化を蓄積します。</p></header>')
    html.append('<section><h2>1. 今週の重要アップデートTOP5</h2><table><tr><th>重要度</th><th>項目</th><th>確認できた事実</th><th>監査上の確認事項</th></tr>')
    for x in result.get("top5", [])[:5]:
        html.append(f'<tr><td class="score">{escape(str(x.get("importance","")))}</td><td><strong>{escape(str(x.get("type","")))}</strong><br>{escape(str(x.get("title","")))}</td><td>{escape(str(x.get("fact","")))}</td><td>{escape(str(x.get("audit","")))}</td></tr>')
    html.append('</table></section>')
    names = [("openai","2. ChatGPT / OpenAI"),("gemini","3. Gemini / Google"),("claude","4. Claude / Anthropic"),("microsoft","5. Microsoft Copilot")]
    for key, heading in names:
        html.append(f'<section><h2>{heading}</h2><ul>')
        items = result.get("companies", {}).get(key, [])
        for x in items[:4]:
            html.append(li(x if isinstance(x, str) else f"{x.get('title','')}: {x.get('fact','')} / 監査: {x.get('audit','')}"))
        html.append('</ul></section>')
    html.append(f'<section><h2>6. 内部監査への示唆</h2><p>{escape(str(result.get("audit_implication","")))}</p></section>')
    html.append('<section><h2>7. 内部監査プロセスの高度化への有用性</h2><table><tr><th>工程</th><th>状態</th><th>成熟度</th><th>内容</th></tr>')
    for key in map(str, range(1,8)):
        p = old[key]
        cls = "updated" if p["status"] == "updated" else "unchanged"
        label = "更新あり" if p["status"] == "updated" else "更新なし"
        html.append(f'<tr><td>① リスク評価</td>' if key=="1" else f'<tr><td>② 監査計画</td>' if key=="2" else f'<tr><td>③ 資料収集</td>' if key=="3" else f'<tr><td>④ 分析・検証</td>' if key=="4" else f'<tr><td>⑤ 指摘・原因分析</td>' if key=="5" else f'<tr><td>⑥ 報告</td>' if key=="6" else f'<tr><td>⑦ フォローアップ</td>')
        html.append(f'<td class="{cls}">{label}</td><td>{p.get("maturity",1)}/5</td><td>{escape(p["current"])}</td></tr>')
    html.append('</table><p><strong>原則：</strong>AIの出力は監査証拠そのものではありません。原資料・ログ・承認記録と突き合わせ、監査人が最終判断します。</p></section>')
    html.append('<section><h2>8. 今後ウォッチすべき事項</h2><ul>' + ''.join(li(x) for x in result.get("watch", [])[:5]) + '</ul></section>')
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
