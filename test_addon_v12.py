"""验证重构后的插件（扩展全名是 bl_ext.user_default.mmd_pipeline）。"""
import bpy
import addon_utils

FULL = "bl_ext.user_default.mmd_pipeline"
addon_utils.enable(FULL, default_set=True, persistent=True)

pkg = __import__(FULL, fromlist=["mmdpipe", "operators"])
P, O = pkg.mmdpipe.params, pkg.operators

s = bpy.context.scene.mmdp
pub = [p.identifier for p in s.bl_rna.properties if not p.is_readonly and p.identifier != "rna_type"]
print("PANEL props:", len(pub), "| PARAMS:", len(P.PARAMS))
print("面板缺:", [p.name for p in P.PARAMS if p.name not in pub])
print("面板多:", [x for x in pub if x not in {p.name for p in P.PARAMS}])

s.pmx = "E:/a b/模型.pmx"
s.vmd = ""
s.motions = "E:/a b/A.vmd; E:/a b/B.vmd"
s.frames = 120
s.align = "match"
s.chain_mode = "nla"
s.chain_gap = 20
s.force_static = "xk_; zxk"
s.clearance = True
argv = O._argv_from(s)
print("ARGV:", " ".join(argv))
print("空格路径保留:", any("a b" in a for a in argv))
print("列表项数:", argv.count("--force-static"))
print("operator:", hasattr(bpy.ops.mmd_pipeline, "run"), "| 面板:", hasattr(bpy.types, "MMDP_PT_main"))
