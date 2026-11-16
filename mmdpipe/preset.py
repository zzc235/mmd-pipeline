"""渲染预设：口味层的唯一落盘形式。

分层覆盖 default -> project -> stage，全部是 JSON，可 diff、可 review。
绝不进 gate：预设改坏了只毁画面，不毁数据。
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any

DEFAULT_PRESET: dict = {
    "schema": 1,
    "import": {
        "scale": 0.08,
        "types": ["MESH", "ARMATURE", "MORPHS", "PHYSICS"],
        "clean_model": True,
        "remove_doubles": False,
        "rename_bones": True,
    },
    "motion": {
        "bone_mapper": "PMX",
        "rename_bones": True,
        "use_underscore": False,
        "update_scene_settings": True,
        # 独立的表情 VMD：给了就和动作合并成一份再导入
        "expression": None,
    },
    "physics": {
        "substeps_per_frame": 10,
        "solver_iterations": 20,
        # 过约束动态单元（闭环桁架、无 mode2）默认关物理；可选 static | damp | report
        "suspect_units": "static",
        "unit_damping": True,          # 按物理单元加阻尼（袖/发/挂件这类名字匹配不到的）
        "unit_angular_damping": 0.75,
        "unit_linear_damping": 0.25,
        "angular_damping": 0.75,
        "linear_damping": 0.25,
        "bake_for_inspect": False,
        # 物理资格策略：report(只报告) / welded(静音全焊死) / strict(+僵死嫌疑单元) / off
        "policy": "report",
        # 显式声明：强制不做物理 / 强制保留物理（按刚体名或骨名子串匹配）
        "force_static": [],
        "force_physics": [],
        # PMX 每个刚体带一个「我只和哪几组碰」的掩码。mmd_tools 的 Model.build()
        # 会把「被掩码排除」的刚体对建成 disable_collisions 约束，但**只给距离够近的对**建
        # （distance < scale * (range_a + range_b) / 2）。远处被排除的对不建对象，
        # 于是它们在 Bullet 里照样会撞——这是「掩码有没有真生效」的分水岭。
        # 1.5 = mmd_tools 上游默认；调大 → 覆盖更多对、场景里约束更多、建场更慢。
        # 要全对覆盖就给一个大到永远成立的值（例如 1e6），代价用 mask 报告里那个数衡量。
        "non_collision_distance_scale": 1.5,
        # 建场后按掩码报告的覆盖率判红/黄：低于这个比例就 WARN（0 = 关掉这条判据）
        "mask_coverage_min": 0.0,
        # 把 PMX 的组号/掩码真正接进 Blender（`coordination/mask_channel_spec.md`）。
        # 关掉 = 回到「谁跟谁都碰」的老行为。**接上之后轨迹必然改变**，此前所有物理
        # 数字作废（D-075），那是预期行为不是缺陷。
        "apply_collision_masks": True,
    },
    "clearance": {
        "enabled": False,      # 是否在导入前修 PMX 的初始穿透
        "margin": 0.06,        # PMX 单位，0.06 ≈ 4.8 mm
    },
    # 道具挂接：[{"pmx": 路径, "bone": "手首.R", "loc": [x,y,z], "rot": [rx,ry,rz]}]
    "props": [],
    "look": {
        "route": "auto",                  # hsr | toon | custom
        "sdf_body_type": "W168",
        # 卡通着色的光照/明暗滑杆（HSR 插件提供）。留空 = 全用插件默认值。
        # 可用键见 stage.HSR_LOOK_KEYS
        "hsr": {},
        # 官方后期处理（HoYoverse - Post Processing 节点组）。默认关，开启后接进合成器。
        "post_processing": False,
        # native 路线的三点光：能量倍率（技能公式按 Cycles 算，EEVEE 要缩）
        "light_scale": 0.05,
        "lighting_profile": "skin",
        "sdf_variant": "00",
        "outline": True,
        "bg_color": [0.32, 0.34, 0.38, 1.0],
        "bg_strength": 0.6,
    },
    "camera": {
        "lens": 50.0,
        "sensor": 36.0,
        "margin": 1.25,
        "direction": [0.42, -0.88, 0.22],
        "loc": None,      # 冻住的相机位置：有值就不再测包围盒
        "rot": None,
    },
    "render": {
        # VMD 帧号以 30fps 为基准：30 时 1 帧 VMD = 1 帧画面，动作按作者编排速度播放。
        # 改成别的值不会重采样，只会整体改变播放速度（时长 = 帧数 / fps）。
        "fps": 30,
        "resolution": [720, 576],
        "taa_render_samples": 10,
        "crf": 18,
        "ffmpeg": "C:/Users/zzc/ffmpeg/bin/ffmpeg.exe",
        "ffprobe": "C:/Users/zzc/ffmpeg/bin/ffprobe.exe",
    },
}


def _deep_merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in patch.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def load(path: str | None = None, overrides: dict | None = None) -> dict:
    preset = copy.deepcopy(DEFAULT_PRESET)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            preset = _deep_merge(preset, json.load(fh))
    if overrides:
        preset = _deep_merge(preset, overrides)
    return preset


def section(preset: dict | None, name: str) -> dict:
    """取预设里的一段；缺整段、或只给了一部分时，用 `DEFAULT_PRESET` 补齐。

    为什么需要：`presets/*.json` 是**差分文件**，磁盘上并没有 `import` 段。
    走 `load()` 的产线不受影响，但直接调 `stage_import(preset_dict)` 的调用者
    （脚本、测试、将来面板单独调）拿到的可能是一份没有 `import` 的字典 ——
    `preset["import"]` 当场 `KeyError`，而且那一行在 `try` 之外，表现为
    「导入阶段直接抛栈」而不是可读的失败原因。2026-11-16 由 1号 实测撞出。
    """
    if preset is None:
        preset = {}
    if not isinstance(preset, dict):
        raise TypeError("预设必须是 dict，收到 %r" % (type(preset).__name__,))
    merged = _deep_merge(DEFAULT_PRESET, preset)
    if name not in merged:
        raise KeyError("预设里没有 %r 段，DEFAULT_PRESET 里也没有" % (name,))
    if not isinstance(merged[name], dict):
        raise TypeError("预设的 %r 段必须是 dict，收到 %r"
                        % (name, type(merged[name]).__name__))
    return merged[name]


def save(preset: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(preset, fh, ensure_ascii=False, indent=2)
    return path


class PresetStack:
    """三级覆盖：default -> project -> stage，取一次合并结果。"""

    def __init__(self, project_path: str | None = None):
        self.project = load(project_path)
        self.stage_patches: dict[str, dict] = {}

    def for_stage(self, stage: str) -> dict:
        return _deep_merge(self.project, self.stage_patches.get(stage, {}))

    def patch(self, stage: str, values: dict) -> None:
        self.stage_patches[stage] = _deep_merge(self.stage_patches.get(stage, {}), values)
