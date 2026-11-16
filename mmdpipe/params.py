"""参数唯一声明源（single source of truth）。

规则：**不要再往 runner 的 argparse 和面板各加一份字段。**
这里声明一次，argparse 和 Blender PropertyGroup 都从它生成，
从结构上让"面板是 CLI 子集"不可能发生。

字段说明：
    name     下划线形式（argparse 自动转成 --chain-gap，PropertyGroup 直接用它）
    kind     path | str | int | float | bool | choice | list
    advanced True 的进面板"高级"折叠区（逃生参数不该占主位）
    ui       面板标签等
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    default: Any = None
    help: str = ""
    choices: tuple = ()
    required: bool = False
    advanced: bool = False
    label: str = ""
    metavar: str = ""

    @property
    def flag(self) -> str:
        return "--" + self.name.replace("_", "-")

    @property
    def title(self) -> str:
        return self.label or self.name


PARAMS: tuple[Param, ...] = (
    # ---- 输入 ----
    Param("pmx", "path", required=True, label="模型 PMX",
          help="PMX 模型文件（只读，改动落在 --out 的副本上）"),
    Param("vmd", "path", label="动作 VMD",
          help="单个动作；与 --motions 二选一"),
    Param("motions", "str", label="多段动作",
          help="分号分隔的多个 VMD，按顺序拼接（配合 chain-mode）"),
    Param("expression", "path", advanced=True, label="表情 VMD",
          help="独立的表情 VMD，合并进动作后一起导入"),
    Param("preset", "path", label="预设 JSON",
          help="相机/外观/物理/渲染参数的预设文件；不填用内置默认"),
    Param("camera", "path", label="相机 JSON",
          help="冻结机位参数；给了就跳过按包围盒取景"),

    # ---- 输出与长度 ----
    Param("out", "path", default="mmdpipe_out", label="输出目录",
          help="所有产物写到这里（源文件不会被改）"),
    Param("layout", "choice", default="isolated", choices=("isolated", "legacy"),
          label="产物布局",
          help="isolated：中间产物进 work/<run>，成片只在全流程通过后落 final/<run>；"
               "legacy：全部写在 --out 根目录（旧行为）"),
    Param("frames", "int", default=360, label="帧数", help="要渲染的帧数"),
    Param("fps", "choice", default="30", choices=("24", "30"), label="帧率",
          help="VMD 以 30fps 为基准；改 fps 不重采样，等于变速"),

    # ---- 物理 ----
    Param("physics_policy", "choice", default="strict",
          choices=("report", "welded", "strict", "off"), label="物理策略",
          help="report 只报告 / welded 静音焊死 / strict 再加僵死嫌疑 / off 关闭"),
    Param("force_static", "list", advanced=True,
          metavar="PAT", label="强制不做物理",
          help="按刚体名或骨名子串匹配，可重复"),
    Param("force_physics", "list", advanced=True,
          metavar="PAT", label="强制保留物理",
          help="按刚体名或骨名子串匹配，可重复"),
    Param("probe", "bool", default=False, advanced=True, label="物理活性探针",
          help="跑 G5 物理活性探针，确认刚体真的在动"),

    # ---- 多段拼接 ----
    Param("chain_mode", "choice", default="splice", choices=("splice", "nla"),
          label="拼接方式",
          help="splice 字节硬切（快、无损）/ nla 分层烘焙（可交叉淡化与对齐）"),
    Param("chain_gap", "int", default=0, label="段间空帧",
          help="两段之间的空帧数；太小会看到明显甩动"),
    Param("chain_blend", "int", default=0, label="交叉淡化帧",
          help="NLA 模式的淡化长度（0=不淡化）"),
    Param("align", "choice", default="auto", choices=("auto", "none", "match"),
          label="根链对齐",
          help="auto 按测量判定 / none 不动（刻意的换场）/ match 强制对齐"),

    # ---- 其他 ----
    Param("clearance", "bool", default=False, label="修初始穿透",
          help="导入前检测并外移穿模刚体（改的是 PMX 副本）"),
    Param("clearance_margin", "float", advanced=True, label="净空余量",
          help="净空修复的余量（PMX 单位，默认 0.06 ≈ 4.8 mm）"),
    Param("prop", "list", advanced=True, metavar="PMX@BONE", label="挂接道具",
          help="例：刀.pmx@手首.R，可重复"),
    Param("force", "bool", default=False, advanced=True, label="放行 BLOCK",
          help="遇到 BLOCK 仍然继续（危险，仅调试用）"),
)


def by_name(name: str) -> Param:
    for p in PARAMS:
        if p.name == name:
            return p
    raise KeyError(name)


# ---- 面板四区（M07）----
# 参数 → 区由这里唯一决定，面板不再自己列字段。
# 加新参数却忘了归区时，import 阶段就 raise —— 宁可插件装不上，也不要某个旋钮
# 悄悄从面板上消失（v1.2.0 就有过「高级项折叠后找不到」的投诉）。
ZONES = ("asset", "physics", "render")

ZONE_OF = {
    # 资产：输入、输出、时长
    "pmx": "asset",
    "vmd": "asset",
    "motions": "asset",
    "expression": "asset",
    "preset": "asset",
    "camera": "asset",
    "out": "asset",
    "layout": "asset",
    "frames": "asset",
    "fps": "asset",
    # 物理：策略、诊断、净空
    "physics_policy": "physics",
    "force_static": "physics",
    "force_physics": "physics",
    "probe": "physics",
    "clearance": "physics",
    "clearance_margin": "physics",
    # 渲染：拼接、对齐、道具
    "chain_mode": "render",
    "chain_gap": "render",
    "chain_blend": "render",
    "align": "render",
    "prop": "render",
    "force": "render",
}

_missing = sorted(p.name for p in PARAMS if p.name not in ZONE_OF)
_extra = sorted(set(ZONE_OF) - {p.name for p in PARAMS})
if _missing or _extra:
    raise ValueError("面板分区与参数声明不一致：缺 %s 多 %s（见 params.ZONE_OF）"
                     % (_missing, _extra))


def by_zone(zone: str) -> tuple:
    """某一区的参数（顺序与 PARAMS 声明一致，面板显示顺序即声明顺序）。"""
    if zone not in ZONES:
        raise KeyError(zone)
    return tuple(p for p in PARAMS if ZONE_OF[p.name] == zone)


def add_arguments(ap) -> None:
    """把声明转成 argparse 参数。runner 只调这个，不再自己写 add_argument。"""
    for p in PARAMS:
        kw = {"help": p.help}
        if p.kind == "path":
            kw["default"] = p.default
            if p.required:
                kw["required"] = True
        elif p.kind == "str":
            kw["default"] = p.default
        elif p.kind == "int":
            kw["type"] = int
            kw["default"] = p.default
        elif p.kind == "float":
            kw["type"] = float
            kw["default"] = p.default
        elif p.kind == "bool":
            kw["action"] = "store_true"
            kw["default"] = bool(p.default)
        elif p.kind == "choice":
            kw["choices"] = list(p.choices)
            kw["default"] = p.default
        elif p.kind == "list":
            kw["action"] = "append"
            kw["default"] = None
            if p.metavar:
                kw["metavar"] = p.metavar
            else:
                kw["metavar"] = p.name.upper()
        if p.kind == "choice" and p.name == "fps":
            kw["type"] = int          # runner 里按整数用
        ap.add_argument(p.flag, **kw)


def blender_properties(bpy):
    """把声明转成 Blender PropertyGroup 的属性字典。

    用同一份 PARAMS 生成，面板和 CLI 不可能再漂移。
    """
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

    out: dict[str, tuple] = {}
    for p in PARAMS:
        desc = p.help or p.title
        if p.kind == "path":
            prop = StringProperty(name=p.title, description=desc, subtype="FILE_PATH")
        elif p.kind == "str":
            prop = StringProperty(name=p.title, description=desc)
        elif p.kind == "int":
            prop = IntProperty(name=p.title, description=desc,
                               default=p.default if p.default is not None else 0)
        elif p.kind == "float":
            prop = FloatProperty(name=p.title, description=desc,
                                 default=p.default if p.default is not None else 0.0)
        elif p.kind == "bool":
            prop = BoolProperty(name=p.title, description=desc,
                                default=bool(p.default))
        elif p.kind == "choice":
            items = [(c, c, "") for c in p.choices]
            prop = EnumProperty(name=p.title, description=desc, items=items,
                                default=str(p.default))
        elif p.kind == "list":
            prop = StringProperty(name=p.title, description=desc)
        else:                                    # pragma: no cover
            raise ValueError("未知参数类型 %s" % p.kind)
        out[p.name] = prop
    return out
