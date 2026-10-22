# -*- coding: utf-8 -*-
"""只读差分：连续扫描副屏所有能力串上报的 VCP 码，找出「用户切 OSD 时跟着变」的那个。

不写任何值，零风险。运行期间请用手按显示器按键切换情景模式。

用法：python _tools/probe_diff.py [秒数]
结果写入 _shots/diff.log
"""
import sys
import time

import monitorcontrol

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 120
OUT = "_shots/diff.log"

m = monitorcontrol.get_monitors()[1]
m.__enter__()
cap = m.get_vcp_capabilities()
codes = sorted(int(k) for k in cap.get("vcp", {}))
print("扫 %d 个码：%s" % (len(codes), " ".join("0x%02X" % c for c in codes)))

values = {}      # code -> [vals...]
rounds = 0
end = time.time() + DURATION
while time.time() < end:
    rounds += 1
    for c in codes:
        try:
            v = m.vcp.get_vcp_feature(c)[0]
        except Exception:
            v = None
        values.setdefault(c, []).append(v)
    time.sleep(0.05)

m.__exit__(None, None, None)

lines = ["扫描 %d 轮，%d 个码" % (rounds, len(codes)), ""]
changed = []
for c in codes:
    seq = values.get(c, [])
    good = [v for v in seq if v is not None]
    if not good:
        lines.append("0x%02X  全部读失败" % c)
        continue
    uniq = sorted(set(good))
    if len(uniq) > 1:
        changed.append((c, uniq, good))
        lines.append("0x%02X  ★ 值变化过：%s  序列=%s"
                     % (c, uniq, good[:40]))
    else:
        lines.append("0x%02X  恒定 %s（%d/%d 次读到）"
                     % (c, uniq[0], len(good), len(seq)))

lines.insert(1, "变过的码：%s" % (", ".join("0x%02X" % c for c, _, _ in changed) or "无"))
text = "\n".join(lines)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(text + "\n")
print(text)
