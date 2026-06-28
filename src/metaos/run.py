"""MetaOS 引擎入口——运行所有场景验证"""

import os
import subprocess
import sys
import time

script_dir = os.path.dirname(__file__)
scenarios = [
    ("01_决策与原则冲突", "scenarios/test_01_decision.py"),
    ("02_免疫三层机制", "scenarios/test_02_immune.py"),
    ("03_基础设施故障", "scenarios/test_03_infrastructure.py"),
    ("04_资产污染处置", "scenarios/test_04_pollution.py"),
    ("05_群体场景", "scenarios/test_05_group.py"),
    ("06_认证测试", "scenarios/test_06_auth.py"),
    ("07_五领域覆盖", "scenarios/test_07_coverage.py"),
    ("08_CLI+集成", "scenarios/test_08_cli.py"),
]

# 检测 Ollama 是否活跃（影响测试耗时）
try:
    import json
    import urllib.request

    req = urllib.request.Request("http://localhost:11434/api/tags")
    ollama_check = urllib.request.urlopen(req, timeout=3)  # noqa: S310
    if ollama_check.status == 200:
        models = json.loads(ollama_check.read()).get("models", [])
        if models:
            model_name = models[0]["name"]
            print(f"⚠️  Ollama 检测通过 ({model_name}) — 各场景可能耗时较长")
            print("   首次推理需加载模型到内存 (9B 模型约 30-90s), 之后每个调用约 5-15s")
            print(f"   当前超时: OLLAMA_TIMEOUT={os.environ.get('OLLAMA_TIMEOUT', '120')}s")
            print("   场景内有多次调用，请耐心等待")
        else:
            print("⚠️  Ollama 已连接但无可用模型，回退 Mock 模式")
            models = None
    else:
        models = None
except Exception:  # noqa: BLE001  # defensive fallback
    models = None

results = {}
total_start = time.time()
for name, path in scenarios:
    print(f"\n\n{'#' * 60}")
    print(f"# 正在执行: {name}")
    print(f"{'#' * 60}")
    sys.stdout.flush()
    step_start = time.time()
    r = subprocess.run(
        [sys.executable, os.path.join(script_dir, path)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=script_dir,
    )
    elapsed = time.time() - step_start
    if r.returncode == 0:
        results[name] = "✅ PASS"
    else:
        results[name] = "❌ FAIL"
    print(r.stdout[-800:] if r.stdout else "")
    if r.stderr:
        print(r.stderr[-500:])
    print(f"  ⏱  {elapsed:.0f}s")

total_elapsed = time.time() - total_start
print(f"\n\n{'=' * 60}")
print("  MetaOS 引擎白盒验证结果")
print(f"{'=' * 60}")
for name, result in results.items():
    print(f"  {result}  {name}")
passed = sum(1 for r in results.values() if "PASS" in r)
print(f"\n  {passed}/{len(results)} 通过  ⏱ 总计 {total_elapsed:.0f}s")
