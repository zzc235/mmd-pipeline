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
