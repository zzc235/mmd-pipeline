# -*- coding: utf-8 -*-
"""基线文件的口径（纯 Python，不开 Blender）。

单独一个模块的理由：`m04_capsule_probe.py` 顶层无条件调 `main()`（它只在 Blender 里跑），
所以那支脚本里的函数**没法离屏 import 来测**。把口径挪到这里，探针 import 它、测试也 import 它，
**同一份实现，不复制**。

## 为什么零值对必须留下

老写法只写 `v > 0` 的对。于是「这一帧这个对有没有基线」只能靠「key 在不在表里」，而
**在基线帧本来没重叠的对**会被探针记成 `pairs_without_baseline` —— 它们的真值是 0，不是「缺数据」。
预注册（§七 正控）要求两侧 `pairs_without_baseline == 0`，否则该组判 UNKNOWN；实测第一轮
`C@W2` 39、`D` 6789，冻结比对器据此判 UNKNOWN。所以：

* 表要覆盖**整个候选对宇宙**（含 0）；
* 并显式记 `pairs_with_zero_overlap`，让读的人一眼看出「0 是量出来的」而不是「没量」。
"""


def baseline_payload(blend, roi_label, baseline_frame, baseline):
    """基线文件的内容（含零值对）。`baseline` 是 `{pair_key: 重叠量(m)}`。"""
    values = {k: round(float(v), 6) for k, v in sorted(baseline.items())}
    return {
        "spec": "penetration_baseline/2",
        "basis": "capsule",
        "scene": str(blend).replace("\\", "/").rsplit("/", 1)[-1],
        "roi": roi_label,
        "baseline_frame": int(baseline_frame),
        "note": "按刚体对记录的重叠量（**含 0**：0 = 该对在基线帧量过、没重叠）。"
                "判定用 max(0, depth-baseline) > epsilon；该基线只对这一份交付物成立。",
        "pairs": len(values),
        "pairs_with_zero_overlap": sum(1 for v in values.values() if v == 0.0),
        "baseline_m": values,
    }
