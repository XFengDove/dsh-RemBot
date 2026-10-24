# -*- coding: utf-8 -*-
"""本地模型性能基准：TTFT、解码速度、长上下文处理、加载耗时。"""
import json
import time
import urllib.request

MODEL = "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive:latest"
BASE = "http://127.0.0.1:11434"


def chat(messages, num_predict=256, num_ctx=8192, temperature=0.7):
    payload = {
        "model": MODEL, "messages": messages, "stream": True, "think": False,
        "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": temperature},
    }
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    first = None
    text = ""
    final = {}
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            obj = json.loads(line)
            msg = obj.get("message") or {}
            piece = msg.get("content") or ""
            if piece and first is None:
                first = time.time()
            text += piece
            if obj.get("done"):
                final = obj
    total = time.time() - t0
    ttft = (first - t0) if first else None
    ec = final.get("eval_count") or 0
    ed = (final.get("eval_duration") or 0) / 1e9
    pc = final.get("prompt_eval_count") or 0
    pd = (final.get("prompt_eval_duration") or 0) / 1e9
    ld = (final.get("load_duration") or 0) / 1e9
    return {
        "ttft": round(ttft, 2) if ttft else None,
        "total": round(total, 2),
        "eval_tokens": ec,
        "decode_tps": round(ec / ed, 1) if ed > 0 else None,
        "prompt_tokens": pc,
        "prompt_tps": round(pc / pd, 1) if pd > 0 else None,
        "load_s": round(ld, 2),
        "chars": len(text),
        "sample": text[:80].replace("\n", " "),
    }


LONG = ("以下是背景资料，请记住但不要复述。\n" +
        ("雷姆是来自《全职猎人》的角色，担任罗兹威尔宅邸的管家，负责照顾日常事务、整理资料、"
         "维护服务器与图像生成流程，并与星峰大人保持日常对话。\n") * 60)

TESTS = [
    ("短问答（≤120 token 输出）",
     [{"role": "user", "content": "用一句话介绍你自己"}], 120),
    ("中长输出（约 400 token）",
     [{"role": "user", "content": "用中文写一段约三百字的场景描写：雪夜里的老式蒸汽火车驶出森林。"}], 450),
    ("长上下文（约 4k 字符资料 + 提问）",
     [{"role": "system", "content": LONG}, {"role": "user", "content": "刚才资料里提到的角色是谁？只回答一句。"}], 100),
]

print("model:", MODEL)
print("-" * 78)
for name, msgs, npred in TESTS:
    r = chat(msgs, num_predict=npred)
    print(f"{name}")
    print(f"  TTFT={r['ttft']}s  total={r['total']}s  decode={r['decode_tps']} tok/s  "
          f"prompt={r['prompt_tokens']} tok @ {r['prompt_tps']} tok/s  load={r['load_s']}s")
    print(f"  样例: {r['sample']}")
    print("-" * 78)
