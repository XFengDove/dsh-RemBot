# -*- coding: utf-8 -*-
"""诊断：列出所有部件的尺寸/位置，找出飘在空中的长条。"""
import importlib.util
import os

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("gh", os.path.join(HERE, "great_hall.py"))
gh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gh)

bpy.ops.wm.read_factory_settings(use_empty=True)
gh.OBJS.clear()
gh.join_all = lambda name: None   # 跳过合并
cam = gh.build()

print("=== 部件清单 ===")
for o in gh.OBJS:
    d = [round(v, 2) for v in o.dimensions]
    l = [round(v, 2) for v in o.location]
    flag = ""
    if d[0] > 120 and d[2] < 3.5:
        flag = "  <== 长条"
    print(f"{o.name:16s} dim={d} loc={l}{flag}")
