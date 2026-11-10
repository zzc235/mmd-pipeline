import sys
sys.path.insert(0, r"E:/dsh pr/woker2")
from mmdpipe import stage as S
print(S.stage_probe({}, 1).text())
