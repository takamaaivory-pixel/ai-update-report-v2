import json
from pathlib import Path
from html import escape

STATE_PATH = Path('data/audit_process_state.json')
OUTPUT_PATH = Path('dashboard.html')
LABELS = {
    '1': '① リスク評価', '2': '② 監査計画', '3': '③ 資料収集',
    '4': '④ 分析・検証', '5': '⑤ 指摘・原因分析', '6': '⑥ 報告', '7': '⑦ フォローアップ'
}


def esc(value):
    return escape(str(value))


def main():
    state = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    history = state.get('history', [])
    # One snapshot per date is expected after normalization.
    history = [x for x in history if x.get('date')]
    history = history[-26:]
    changes = {x['process']: x for x in state.get('maturity_changes', [])}

    width, height = 980, 420
    left, right, top, bottom = 70, 25, 35, 70
    plot_w, plot_h = width - left - right, height - top - bottom

    def x(i):
        return left if len(history) <= 1 else left + i * plot_w / (len(history) - 1)

    def y(level):
        return top + (5 - level) * plot_h / 4

    svg = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="7工程の成熟度推移グラフ">']
    for level in range(1, 6):
        yy = y(level)
        svg.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" stroke="#d9dee3"/>')
        svg.append(f'<text x="{left-12}" y="{yy+5:.1f}" text-anchor="end" font-size="14">Lv{level}</text>')
    for i, snap in enumerate(history):
        xx = x(i)
        svg.append(f'<text x="{xx:.1f}" y="{height-28}" text-anchor="middle" font-size="11">{esc(snap["date"][5:])}</text>')

    for key in map(str, range(1, 8)):
        vals = [int(s.get('processes', {}).get(key, {}).get('maturity', 1)) for s in history]
        points = ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in enumerate(vals))
        # Use default SVG palette via CSS classes; no fixed semantic color is assigned.
        svg.append(f'<polyline points="{points}" fill="none" stroke-width="3" class="line-{key}"/>')
        for i, v in enumerate(vals):
            svg.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" class="line-{key}"/>')
    svg.append('</svg>')

    current = state.get('processes', {})
    rows = []
    for key in map(str, range(1, 8)):
        p = current.get(key, {})
        c = changes.get(key, {})
        delta = int(c.get('delta', 0))
        sign = f'+{delta}' if delta > 0 else str(delta)
        trend = '↗' if delta > 0 else ('↘' if delta < 0 else '→')
        rows.append(f'<tr><td>{LABELS[key]}</td><td><strong>Lv{int(p.get("maturity", 1))}/5</strong></td><td>{sign} {trend}</td><td>{"更新あり" if p.get("status") == "updated" else "更新なし"}</td><td>{esc(p.get("change_reason", ""))}</td></tr>')

    rubric = [
        (1, '検討・情報収集'), (2, '試行・一部導入'), (3, '定型・定常運用'),
        (4, '複数工程・部門連携'), (5, '継続監視＋改善サイクル')
    ]
    rubric_rows = ''.join(f'<tr><td>Lv{n}</td><td>{esc(d)}</td></tr>' for n, d in rubric)

    html = f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI×内部監査 成熟度ダッシュボード</title><style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#f4f6f8;color:#202124;margin:0;padding:16px;line-height:1.6}}main{{max-width:1050px;margin:auto}}header,section,footer{{background:#fff;padding:20px;border-radius:14px;margin-bottom:16px;box-shadow:0 2px 10px #0001}}h1{{margin:0 0 6px}}h2{{border-bottom:2px solid #eee;padding-bottom:6px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ddd;padding:9px;text-align:left;vertical-align:top}}th{{background:#f7f7f7}}svg{{width:100%;height:auto;min-height:300px}}.line-1{{stroke:#6b7280;fill:#6b7280}}.line-2{{stroke:#2563eb;fill:#2563eb}}.line-3{{stroke:#16a34a;fill:#16a34a}}.line-4{{stroke:#dc2626;fill:#dc2626}}.line-5{{stroke:#9333ea;fill:#9333ea}}.line-6{{stroke:#ea580c;fill:#ea580c}}.line-7{{stroke:#0891b2;fill:#0891b2}}.note{{color:#5f6368}}@media(max-width:600px){{body{{padding:8px}}header,section,footer{{padding:13px}}table{{display:block;overflow-x:auto}}svg{{min-width:720px}}.chart-wrap{{overflow-x:auto}}}}</style></head><body><main>
<header><h1>AI × 内部監査 成熟度ダッシュボード</h1><p><strong>基準日：</strong>{esc(state.get('last_updated',''))}</p><p class="note">内部監査7工程について、蓄積した週次スナップショットから成熟度の推移と前週比を確認します。</p></header>
<section><h2>現在地</h2><table><tr><th>工程</th><th>現在</th><th>前週比</th><th>状態</th><th>変化理由</th></tr>{''.join(rows)}</table></section>
<section><h2>7工程の成熟度推移</h2><div class="chart-wrap">{''.join(svg)}</div><p class="note">表示は直近26スナップショット（最大約半年）。成熟度はAI機能の性能ではなく、監査工程への実運用の定着度を示します。</p></section>
<section><h2>成熟度の判定基準</h2><table><tr><th>レベル</th><th>基準</th></tr>{rubric_rows}</table></section>
<section><h2>今週の変化</h2><ul>{''.join(f'<li>{LABELS[k]}：Lv{c.get("previous_maturity", 1)} → Lv{c.get("current_maturity", 1)}（{("+"+str(c.get("delta"))) if int(c.get("delta",0))>0 else str(c.get("delta",0))}）{esc(c.get("reason", ""))}</li>' for k,c in changes.items() if int(c.get('delta',0)) != 0 or c.get('status') == 'updated') or '<li>成熟度の変化なし</li>'}</ul></section>
<footer><p>AIの出力は監査証拠そのものではありません。原資料・ログ・承認記録と突き合わせ、人間が最終判断します。</p><p><a href="index.html">週刊レポートへ戻る</a></p></footer></main></body></html>'''
    OUTPUT_PATH.write_text(html, encoding='utf-8')
    print(f'Generated {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
