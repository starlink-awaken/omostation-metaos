#!/usr/bin/env python3
"""MetaOS Dashboard — 生成 HTML 看板"""

import json
import sys
from pathlib import Path

from metaos.cli.ssot_scan import scan_ssot  # type: ignore[import-not-found]
from metaos.core.engine import SEngine  # type: ignore[import-not-found]

ENGINE_DIR = Path(__file__).parent.resolve()


def generate(data_dir: str = "") -> str:
    engine = SEngine(data_dir=data_dir)
    health = engine.system_health()
    ollama = engine.m.get_ollama_info()
    h_id = engine._current_h_id or ""
    decisions = engine.d.get_decisions(h_id, 15) if h_id else []
    principles = engine.d.get_principles(status="active")

    # SSOT
    try:
        entries = scan_ssot(str(ENGINE_DIR.parent))
        total = len(entries)
        has = sum(1 for e in entries if e["ssot"])
        ssot_pct = round(has / total * 100, 1) if total > 0 else 0
    except Exception:
        ssot_pct, total, has = 0, 0, 0

    decisions_json = json.dumps(
        [
            {
                "id": d.decision_id[:8],
                "time": d.timestamp.strftime("%m-%d %H:%M"),
                "level": d.level,
                "desc": d.description[:50],
                "pending": d.outcome_pending_review,
            }
            for d in decisions[-10:]
        ],
        ensure_ascii=False,
    )

    principles_json = json.dumps(
        [{"id": p.principle_id[:8], "content": p.content[:80], "tags": p.applicability_tags} for p in principles[-8:]],
        ensure_ascii=False,
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MetaOS Dashboard</title>
<style>
  * {{margin:0;padding:0;box-sizing:border-box;}}
  body {{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:#f5f5f7;color:#1d1d1f;padding:24px;max-width:1000px;margin:0 auto;}}
  h1 {{font-size:28px;font-weight:600;margin-bottom:4px;}}
  .sub {{color:#86868b;font-size:14px;margin-bottom:24px;}}
  .grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-bottom:24px;}}
  .card {{background:#fff;border-radius:12px;padding:16px;box-shadow:0 1px 3px rgba(0,0,0,.08);}}
  .card h3 {{font-size:12px;text-transform:uppercase;color:#86868b;margin-bottom:8px;letter-spacing:.5px;}}
  .card .value {{font-size:28px;font-weight:600;}}
  .card .note {{font-size:12px;color:#86868b;margin-top:4px;}}
  .section {{background:#fff;border-radius:12px;padding:16px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08);}}
  .section h2 {{font-size:16px;font-weight:600;margin-bottom:12px;}}
  table {{width:100%;border-collapse:collapse;font-size:13px;}}
  th {{text-align:left;color:#86868b;font-weight:500;padding:6px 8px;border-bottom:1px solid #e8e8ed;}}
  td {{padding:6px 8px;border-bottom:1px solid #e8e8ed;}}
  .badge {{display:inline-block;padding:1px 8px;border-radius:4px;font-size:11px;font-weight:500;}}
  .green {{background:#e8f5e9;color:#2e7d32;}}
  .yellow {{background:#fff8e1;color:#f57f17;}}
  .red {{background:#ffebee;color:#c62828;}}
  .pill {{display:inline-block;padding:1px 6px;border-radius:3px;background:#f0f0f0;font-size:11px;margin:1px;}}
  .ollama-ok {{color:#2e7d32;}} .ollama-no {{color:#c62828;}}
  @media (prefers-color-scheme:dark) {{
    body {{background:#1c1c1e;color:#f5f5f7;}}
    .card,.section {{background:#2c2c2e;}}
    th {{color:#98989d;border-bottom-color:#3a3a3c;}}
    td {{border-bottom-color:#3a3a3c;}}
    .pill {{background:#3a3a3c;}}
  }}
</style>
</head>
<body>
<h1>🧠 MetaOS</h1>
<p class="sub">引擎健康度 · 决策日志 · SSOT 覆盖 · 原则库</p>

<div class="grid">
  <div class="card">
    <h3>后端</h3>
    <div class="value">{engine.m.backend_name}</div>
    <div class="note">{"🟢 Ollama: " + ollama.get("model", "") if ollama.get("available") else "🔴 Ollama 不可用"}</div>
  </div>
  <div class="card">
    <h3>模型池</h3>
    <div class="value">{health.get("m_pool", "?")}</div>
    <div class="note">{"检测到 " + str(len(ollama.get("detected_models", []))) + " 个模型" if ollama.get("available") else "Mock 模式"}</div>
  </div>
  <div class="card">
    <h3>SSOT 覆盖</h3>
    <div class="value">{ssot_pct}%</div>
    <div class="note">{has}/{total} 文件</div>
  </div>
  <div class="card">
    <h3>原则库</h3>
    <div class="value">{len(principles)}</div>
    <div class="note">活跃原则数</div>
  </div>
  <div class="card">
    <h3>免疫系统</h3>
    <div class="value">{len(health.get("frozen", []))}/{len(health.get("meltdown", []))}</div>
    <div class="note">冻结/熔断</div>
  </div>
  <div class="card">
    <h3>待确认</h3>
    <div class="value">{health.get("pending_reviews", 0)}</div>
    <div class="note">黄灯待确认决策</div>
  </div>
</div>

<div class="section">
  <h2>📋 最近决策</h2>
  <div id="decisions">加载中...</div>
</div>

<div class="section">
  <h2>📌 活跃原则</h2>
  <div id="principles">加载中...</div>
</div>

<script>
const decisions = {decisions_json};
const principles = {principles_json};

function levelBadge(level) {{
  const m = {{'green':'green','yellow':'yellow','red':'red'}};
  return `<span class="badge ${{m[level]||'green'}}">${{'🟢🟡🔴'['green yellow red'.split(' ').indexOf(level)]||'🟢'}} ${{level}}</span>`;
}}

function renderDecisions(d) {{
  if (!d.length) return '<p style="color:#86868b;font-size:13px;">暂无决策记录</p>';
  let h = '<table><tr><th>时间</th><th>级别</th><th>描述</th></tr>';
  d.slice().reverse().forEach(r => {{
    h += `<tr><td style="white-space:nowrap">${{r.time}}</td><td>${{levelBadge(r.level)}}</td><td>${{r.desc}}</td></tr>`;
  }});
  h += '</table>';
  return h;
}}

function renderPrinciples(p) {{
  if (!p.length) return '<p style="color:#86868b;font-size:13px;">暂无原则，运行 metaos review 积累</p>';
  let h = '<table><tr><th>原则</th><th>来源</th></tr>';
  p.slice().reverse().forEach(r => {{
    const tags = (r.tags||[]).map(t => `<span class="pill">${{t}}</span>`).join('');
    h += `<tr><td>${{r.content}}</td><td style="white-space:nowrap">${{tags}}</td></tr>`;
  }});
  h += '</table>';
  return h;
}}

document.getElementById('decisions').innerHTML = renderDecisions(decisions);
document.getElementById('principles').innerHTML = renderPrinciples(principles);
</script>
</body>
</html>"""
    return html


def main():
    data_dir = sys.argv[1] if len(sys.argv) > 1 else ""
    html = generate(data_dir)
    out_path = Path.home() / ".metaos" / "dashboard.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ Dashboard: {out_path}")
    print("   在浏览器中打开查看")


if __name__ == "__main__":
    main()
