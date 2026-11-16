# -*- coding: utf-8 -*-
"""离屏自检：`plan_324_probe.py` 的三件套算法是否与 `apply_collision_masks()` 同义。

探针要在锁窗口里跑（30–40 s），所以映射错一行就等于白占一次窗口。这里用**假对象**把
`plans()` / `pair_key()` / `disabled_pairs()` 的接线先钉一遍，不需要 bpy：

* 正控：有一对「位重叠但 PMX 说不碰」⇒ `constraints_needed` 里必须出现它；
* 已挡对：把它放进 `blocked` ⇒ `already_blocked=1, to_add=needed-1`；
* 已挡错的：放一条不在 needed 里的约束 ⇒ 只影响 `release_pairs`，不许影响 `needed`；
* 恒等式：`needed == already + to_add`。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))          # .../out/subai/M00/scripts -> worktree
sys.path.insert(0, ROOT)

from mmdpipe import mask as mask_mod


class FakeRigid:
    def __init__(self, group, mask_bits):
        self.collision_group_number = group
        self.collision_group_mask = [bool(mask_bits >> n & 1) for n in range(16)]


class FakeObj:
    def __init__(self, name, group, mask_bits):
        self.name = name
        self.mmd_rigid = FakeRigid(group, mask_bits)


class FakeCon:
    def __init__(self, a, b, disable=True):
        self.object1 = a
        self.object2 = b
        self.disable_collisions = disable


class FakeConObj:
    def __init__(self, con):
        self.rigid_body_constraint = con


def body(name, group, mask_bits):
    return FakeObj(name, group, mask_bits)


def three():
    """造三种关系（掩码语义 True=与该组碰，`pmx_collides` 要求两边都允许）：

    * `x` 组 0，允许组 1；`y` 组 1，允许组 0 ⇒ x×y **PMX 该碰**，且位重叠（共享 bit0/bit1）
      ⇒ 不用约束；挡上它就是**挡错**（`release_pairs`）。
    * `z` 组 2，允许组 0：x 不允许组 2 ⇒ x×z **不该碰**，但 `x` 的 bits 含 bit0、`z` 的 bits
      含 bit0 ⇒ 共享位 ⇒ **要补一条约束**（这就是 needed 的那一条）。
    * `y`×`z`：y 只允许组 0、z 只允许组 0，互相不允许 ⇒ 不该碰；bits（bit0|bit1 vs bit0|bit2）
      共享 bit0 ⇒ **也要补一条**。
    """
    return [body("x", 0, 1 << 1), body("y", 1, 1 << 0), body("z", 2, 1 << 0)]


def numbers(bodies, already):
    plan = mask_mod.plans(bodies, blocked=already)
    needed_pairs = [mask_mod.pair_key(a, b) for a, b in plan["constraints_needed"]]
    already_needed = sum(1 for pair in needed_pairs if pair in already)
    return {"needed": len(needed_pairs), "already": already_needed,
            "to_add": len(needed_pairs) - already_needed,
            "pairs": sorted(needed_pairs), "plan": plan}


def check(label, got, want):
    ok = got == want
    print("[%s] %s got=%r want=%r" % ("ok" if ok else "RED", label, got, want))
    return ok


def main():
    good = True
    bodies = three()
    base = numbers(bodies, set())
    print("  needed pairs:", base["pairs"])
    good &= check("needed = 2（x×z 与 y×z）", base["needed"], 2)
    good &= check("x×y 是 PMX 该碰的对，不在 needed 里",
                  any({"x", "y"} == set(p.split("|")) if "|" in p else False
                      for p in base["pairs"]), False)
    good &= check("没有已挡对", base["already"], 0)
    good &= check("全部要补", base["to_add"], base["needed"])

    # 已挡对：把 needed 里的一条挡上 ⇒ already=1, to_add=needed-1
    blocked = {base["pairs"][0]}
    after = numbers(bodies, blocked)
    good &= check("已挡对 recognized", after["already"], 1)
    good &= check("已挡对后要补少一条", after["to_add"], base["needed"] - 1)

    # 已挡错：x×y 是 PMX 该碰且位重叠，挡它就是挡错 ⇒ 进 release_pairs，不改 needed
    wrong = {mask_mod.pair_key("x", "y")}
    wrongres = numbers(bodies, wrong)
    good &= check("挡错的不改 needed", wrongres["needed"], base["needed"])
    good &= check("挡错的进 release_pairs", len(wrongres["plan"].get("release_pairs") or []), 1)

    # `disabled_pairs()` 只认 disable_collisions=True
    objs = [FakeConObj(FakeCon(bodies[0], bodies[1], True)),
            FakeConObj(FakeCon(bodies[0], bodies[2], False)),
            FakeConObj(None)]
    pairs = mask_mod.disabled_pairs(objs)
    good &= check("disabled_pairs 只收 True 的约束", len(pairs), 1)

    good &= check("恒等式 needed == already + to_add",
                  after["needed"] == after["already"] + after["to_add"], True)

    # 探针里的纯映射也要过一遍：真跑一次 Blender 窗口 40 s，映射错一行就白占一次
    import importlib.util
    import types

    sys.modules.setdefault("bpy", types.ModuleType("bpy"))
    mathutils = types.ModuleType("mathutils")
    mathutils.Vector = object
    sys.modules.setdefault("mathutils", mathutils)
    probe_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plan_324_probe.py")
    spec = importlib.util.spec_from_file_location("plan_324_probe_offline", probe_path)
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    plan3 = mask_mod.plans(bodies, blocked=blocked)      # 带一条已挡对
    fields = probe.plan_fields(plan3, bodies, blocked)
    good &= check("plan_fields: needed", fields["constraints_needed"], 2)
    good &= check("plan_fields: already", fields["constraints_already_blocked"], 1)
    good &= check("plan_fields: to_add", fields["constraints_to_add"], 1)
    good &= check("plan_fields: groups_seen 非空", bool(fields["groups_seen"]), True)
    good &= check("plan_fields: asymmetric_pairs 是整数（不是 len()）",
                  isinstance(fields["asymmetric_pairs"], int), True)
    good &= check("plan_fields: 恒等式", fields["constraints_needed"],
                  fields["constraints_already_blocked"] + fields["constraints_to_add"])
    exps = probe.expectations_of(fields)
    good &= check("expectations 全绿（假场景上）", [k for k, v in exps.items() if not v], [])
    print("RESULT:", "OK" if good else "RED")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
