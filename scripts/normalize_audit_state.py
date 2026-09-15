import json
import re
from pathlib import Path

STATE_PATH = Path("data/audit_process_state.json")
HTML_PATH = Path("index.html")

# Maturity measures operational adoption, not AI capability.
# Each level requires evidence in the current process description.
LEVEL_EVIDENCE = {
    2: re.compile(r"試行|一部利用|パイロット|PoC|実証|導入", re.I),
    3: re.compile(r"定型運用|定常運用|標準運用|本番運用|定着|実運用|工程に組み込み", re.I),
    4: re.compile(r"工程連携|複数工程|複数部門|横断運用|統合運用|連携運用", re.I),
    5: re.compile(r"継続監視|フィードバック.*改善|改善サイクル|継続的高度化|自動.*フィードバック|自律運用", re.I),
}

MATURITY_RUBRIC = {
    1: "検討段階：活用方法を検討・情報収集している",
    2: "試行段階：PoC・パイロット・一部利用・導入を開始している",
    3: "定着段階：定型・定常・標準・本番運用として工程に組み込まれている",
    4: "連携段階：複数工程・部門をまたいで統合・連携して運用している",
    5: "高度化段階：継続監視とフィードバックを伴う改善サイクル・自律運用が定着している",
}


def evidence_level(text: str) -> int:
    level = 1
    for candidate in range(2, 6):
        if LEVEL_EVIDENCE[candidate].search(text):
            level = candidate
    return level


def normalize_history(history, today):
    # Keep one snapshot per date. For duplicate test runs, the latest snapshot wins.
    by_date = {}
    order = []
    for entry in history:
        date = entry.get("date")
        if not date:
            continue
        if date not in by_date:
            order.append(date)
        by_date[date] = entry
    order = [d for d in order if d != today]
    return [by_date[d] for d in order]


def update_html_maturity(processes):
    if not HTML_PATH.exists():
        return
    html = HTML_PATH.read_text(encoding="utf-8")
    values = [str(processes[str(i)].get("maturity", 1)) + "/5" for i in range(1, 8)]
    marker = '<section><h2>7. 内部監査プロセスの高度化への有用性</h2>'
    start = html.find(marker)
    if start < 0:
        return
    end = html.find('</section>', start)
    if end < 0:
        return
    section = html[start:end]
    section = re.sub(r'<td>[1-5]/5</td>', lambda m, it=iter(values): f'<td>{next(it)}</td>', section, count=7)
    HTML_PATH.write_text(html[:start] + section + html[end:], encoding="utf-8")


def main():
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    today = state.get("last_updated", "")
    old_history = state.get("history", [])

    # Maturity can only move upward, and by at most one level per reporting cycle.
    # It also cannot exceed the operational evidence visible in the current text.
    previous_by_key = {}
    if old_history:
        normalized = normalize_history(old_history, today)
        if normalized:
            previous_by_key = normalized[-1].get("processes", {})

    for key, process in state.get("processes", {}).items():
        current = str(process.get("current", ""))
        candidate = max(1, min(5, int(process.get("maturity", 1))))
        previous = previous_by_key.get(key, {})
        previous_maturity = max(1, min(5, int(previous.get("maturity", process.get("maturity", 1)))))

        operational_level = evidence_level(current)
        guarded = min(candidate, previous_maturity + 1, operational_level)
        process["maturity"] = max(previous_maturity, guarded)

        if process.get("status") != "updated":
            process["maturity"] = previous_maturity

    state["history"] = normalize_history(old_history, today)
    state["history"].append({
        "date": today,
        "processes": json.loads(json.dumps(state["processes"], ensure_ascii=False)),
    })

    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    update_html_maturity(state["processes"])


if __name__ == "__main__":
    main()
