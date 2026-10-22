# -*- coding: utf-8 -*-
"""探测每台显示器的 MCCS 能力（dict 形式）。"""
import json
import monitorcontrol

mons = monitorcontrol.get_monitors()
print("共 %d 台" % len(mons))
for i, m in enumerate(mons):
    print("\n===== 显示器 %d =====" % (i + 1))
    try:
        m.__enter__()
    except Exception as e:
        print("  打不开：%r" % (e,))
        continue
    try:
        cap = m.get_vcp_capabilities()
        print(json.dumps(cap, ensure_ascii=False, indent=2))
    except Exception as e:
        print("  能力串读失败：%r" % (e,))
    try:
        m.__exit__(None, None, None)
    except Exception:
        pass
