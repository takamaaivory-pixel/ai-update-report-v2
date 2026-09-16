import json
from pathlib import Path
from html import escape

STATE_PATH = Path('data/audit_process_state.json')
OUTPUT_PATH = Path('dashboard.html')
LABELS = {
    '1': '① リスク評価', '2': '② 監査計画', '3': '③ 資料収集',
    '4': '④ 分析・検証', '5': '⑤ 指摘・原因分析', '6': '⑥ 報告', '7': '⑦ フォローアップ'
}
RUBRIC = {
    1: '検討・情報収集', 2: '試行・一部導入', 3: '定型・定常運用',
    4: '複数工程・部門連携', 5: '継続監視＋改善サイクル'
}

def esc(value):
    return escape(str(value))

def main():
    state = json.loads(STATE_PATH.read_text(encoding='utf-8'))
    history = [x for x in state.get('history', []) if x.get('date')][-26:]
    current = state.get('processes', {})
    changes = {x['process']: x for x in state.get('maturity_changes', [])}

    width, height = 980, 420
    left, right, top, bottom = 70, 25, 35, 70
    plot_w, plot_h = width-left-right, height-top-bottom
    def x(i): return left if len(history) <= 1 else left+i*plot_w/(len(history)-1)
    def y(level): return top+(5-level)*plot_h/4

    svg=[f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="7工程の成熟度推移グラフ">']
    for level in range(1,6):
        yy=y(level)
        svg.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" stroke="#d9dee3"/>')
        svg.append(f'<text x="{left-12}" y="{yy+5:.1f}" text-anchor="end" font-size="14">Lv{level}</text>')
    for i,snap in enumerate(history):
        xx=x(i); svg.append(f'<text x="{xx:.1f}" y="{height-28}" text-anchor="middle" font-size="11">{esc(snap["date"][5:])}</text>')
    for key in map(str,range(1,8)):
        vals=[int(s.get('processes',{}).get(key,{}).get('maturity',1)) for s in history]
        points=' '.join(f'{x(i):.1f},{y(v):.1f}' for i,v in enumerate(vals))
        svg.append(f'<polyline points="{points}" fill="none" stroke-width="3" class="line-{key}"/>')
        for i,v in enumerate(vals): svg.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" class="line-{key}"/>')
    svg.append('</svg>')

    rows=[]
    for key in map(str,range(1,8)):
        p=current.get(key,{}); c=changes.get(key,{})
        delta=int(c.get('delta',0)); sign=f'+{delta}' if delta>0 else str(delta)
        trend='↗' if delta>0 else ('↘' if delta<0 else '→')
        state_text='更新あり' if p.get('status')=='updated' else '更新なし'
        rows.append(f'<tr><td>{LABELS[key]}</td><td><strong>Lv{int(p.get("maturity",1))}/5</strong><br><span class="small">{esc(RUBRIC.get(int(p.get("maturity",1)),""))}</span></td><td class="trend">{sign} {trend}</td><td>{state_text}</td><td>{esc(p.get("change_reason",""))}</td></tr>')

    changed_items=[]
    for key in map(str,range(1,8)):
        c=changes.get(key,{})
        delta=int(c.get('delta',0))
        if delta!=0 or c.get('status')=='updated':
            arrow=f'{c.get("previous_maturity",1)} → {c.get("current_maturity",1)}'
            reason=c.get('reason') or current.get(key,{}).get('change_reason','内容更新')
            action=c.get('action') or c.get('implementation') or c.get('activity') or '記録なし'
            evidence=c.get('evidence') or c.get('source') or c.get('evidence_reference') or '記録なし'
            confirmed=c.get('human_confirmation') or c.get('review') or c.get('human_review') or '要確認'
            date=c.get('date') or c.get('effective_date') or state.get('last_updated','')
            changed_items.append(f'<article class="change-card"><h3>{LABELS[key]}</h3><div class="change-level">Lv{esc(arrow)}</div><p><strong>なぜ変化したか：</strong>{esc(reason)}</p><dl><dt>実施・導入内容</dt><dd>{esc(action)}</dd><dt>実施日・基準日</dt><dd>{esc(date)}</dd><dt>根拠・証跡</dt><dd>{esc(evidence)}</dd><dt>人間確認</dt><dd>{esc(confirmed)}</dd></dl><p class="small">※成熟度変更の最終判断には、原資料・ログ・承認記録等の確認が必要です。</p></article>')
    if not changed_items:
        changed_items.append('<article class="change-card"><h3>今週は成熟度の変化なし</h3><p>「更新なし」も履歴として保持しています。成熟度が変化した週には、理由・実施内容・根拠・人間確認をここへ表示します。</p></article>')

    history_rows=[]
    for snap in reversed(history):
        vals=[int(snap.get('processes',{}).get(k,{}).get('maturity',1)) for k in map(str,range(1,8))]
        history_rows.append(f'<tr><td>{esc(snap["date"])}</td><td>{" / ".join(str(v) for v in vals)}</td></tr>')

    rubric_rows=''.join(f'<tr><td>Lv{n}</td><td>{esc(d)}</td></tr>' for n,d in RUBRIC.items())
    current_levels=[int(current.get(k,{}).get('maturity',1)) for k in map(str,range(1,8))]
    avg=sum(current_levels)/len(current_levels) if current_levels else 0
    max_level=max(current_levels) if current_levels else 0
    max_names=[LABELS[str(i+1)] for i,v in enumerate(current_levels) if v==max_level]
    delta_values=[int(changes.get(k,{}).get('delta',0)) for k in map(str,range(1,8))]
    avg_delta=sum(delta_values)/len(delta_values) if delta_values else 0
    changed_count=sum(1 for k in map(str,range(1,8)) if changes.get(k,{}).get('status')=='updated')
    delta_text=f'+{avg_delta:.2f}' if avg_delta>0 else f'{avg_delta:.2f}'
    changed_names=[LABELS[k] for k in map(str,range(1,8)) if changes.get(k,{}).get('status')=='updated']
    changed_summary='、'.join(changed_names) if changed_names else '今週は更新なし'

    html=f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI×内部監査 成熟度ダッシュボード</title><style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#f4f6f8;color:#202124;margin:0;padding:16px;line-height:1.65}}main{{max-width:1050px;margin:auto}}header,section,footer{{background:#fff;padding:20px;border-radius:14px;margin-bottom:16px;box-shadow:0 2px 10px #0001}}h1{{margin:0 0 6px}}h2{{border-bottom:2px solid #eee;padding-bottom:6px}}h3{{margin-top:0}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #ddd;padding:9px;text-align:left;vertical-align:top}}th{{background:#f7f7f7}}.small,.note{{color:#5f6368;font-size:.9em}}.trend{{font-weight:700;white-space:nowrap}}.summary{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.metric{{background:#f7f7f7;border-radius:12px;padding:13px}}.metric strong{{display:block;font-size:1.35em;margin-top:2px}}.executive{{border-left:4px solid #666;background:#fafafa;padding:12px 14px;border-radius:8px;margin-top:14px}}.change-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.change-card{{border:1px solid #ddd;border-radius:12px;padding:14px;background:#fafafa}}.change-level{{font-size:1.3em;font-weight:700}}dt{{font-weight:700;margin-top:8px}}dd{{margin:2px 0 0 1em}}.chart-wrap{{overflow-x:auto}}svg{{width:100%;height:auto;min-height:300px}}.line-1{{stroke:#6b7280;fill:#6b7280}}.line-2{{stroke:#2563eb;fill:#2563eb}}.line-3{{stroke:#16a34a;fill:#16a34a}}.line-4{{stroke:#dc2626;fill:#dc2626}}.line-5{{stroke:#9333ea;fill:#9333ea}}.line-6{{stroke:#ea580c;fill:#ea580c}}.line-7{{stroke:#0891b2;fill:#0891b2}}.legend{{display:flex;flex-wrap:wrap;gap:8px 16px;margin:8px 0}}.legend span{{white-space:nowrap}}@media(max-width:900px){{.summary{{grid-template-columns:repeat(3,1fr)}}}}@media(max-width:700px){{body{{padding:8px}}header,section,footer{{padding:13px}}.summary,.change-grid{{grid-template-columns:1fr 1fr}}table{{display:block;overflow-x:auto}}svg{{min-width:720px}}}}@media(max-width:430px){{.summary{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<header><h1>AI × 内部監査 成熟度ダッシュボード</h1><p><strong>基準日：</strong>{esc(state.get('last_updated',''))}</p><div class="summary"><div class="metric"><span class="small">7工程平均</span><strong>{avg:.2f} / 5</strong></div><div class="metric"><span class="small">今週の更新工程</span><strong>{changed_count} / 7</strong></div><div class="metric"><span class="small">前週からの平均変化</span><strong>{delta_text}</strong></div><div class="metric"><span class="small">現在の最高レベル</span><strong>Lv{max_level}</strong></div><div class="metric"><span class="small">先行工程</span><strong>{esc('、'.join(max_names))}</strong></div></div><div class="executive"><strong>今週の要約：</strong>{esc(changed_summary)}。成熟度の変化は、AI機能の発表ではなく、内部監査工程での実際の試行・導入・定着等を基準に記録しています。</div><p class="note">この数値はAI機能の性能評価ではなく、内部監査工程への実運用の定着度を記録するための管理指標です。</p></header>
<section><h2>1. 現在地</h2><table><tr><th>工程</th><th>現在</th><th>前週比</th><th>状態</th><th>変化理由</th></tr>{''.join(rows)}</table></section>
<section><h2>2. 7工程の成熟度推移</h2><div class="legend">{''.join(f'<span>● {LABELS[str(k)]}</span>' for k in range(1,8))}</div><div class="chart-wrap">{''.join(svg)}</div><p class="note">直近26スナップショット（最大約半年）を表示。週次実行を継続すると、工程ごとの長期トレンドが蓄積されます。</p></section>
<section><h2>3. 今週の変化・確認ポイント</h2><div class="change-grid">{''.join(changed_items)}</div></section>
<section><h2>4. 成熟度の判定基準</h2><table><tr><th>レベル</th><th>意味</th></tr>{rubric_rows}</table><p class="note">ニュースやAI機能の発表だけでは成熟度を上げません。実際の試行・導入・定型運用等が確認できる場合にのみ更新候補とします。</p></section>
<section><h2>5. 週次スナップショット履歴</h2><table><tr><th>基準日</th><th>① ② ③ ④ ⑤ ⑥ ⑦</th></tr>{''.join(history_rows)}</table><p class="note">「更新なし」の週も保存します。これにより、変化が起きなかった期間も含めて高度化の経過を説明できます。</p></section>
<section><h2>6. このダッシュボードの読み方</h2><ol><li><strong>現在地</strong>で、7工程の今の状態を30秒で確認します。</li><li><strong>推移</strong>で、どの工程がいつ変化したかを確認します。</li><li><strong>変化・確認ポイント</strong>で、AIが示した更新理由・実施内容・根拠・人間確認を確認します。</li><li>重要な変更については、原資料・ログ・承認記録などを人間が確認してから、監査上の判断に利用します。</li></ol></section>
<footer><p><strong>運用原則：</strong>AIの出力は監査証拠そのものではありません。AIは情報整理と変化候補の抽出を担い、人間が根拠を確認して最終判断します。</p><p><a href="index.html">週刊レポートへ戻る</a></p></footer></main></body></html>'''
    OUTPUT_PATH.write_text(html,encoding='utf-8')
    print(f'Generated {OUTPUT_PATH}')

if __name__=='__main__': main()
