#!/bin/bash
# GLB 资产 meshopt 压缩: 在 blender_assets.py 生成原始 GLB 后原地压缩
# -c 压缩(量化+deflate), -kn 保留节点名(部件清单/动画按名寻址), -km 保留节点结构(不多拆件)
# 护栏: 已压缩件自动跳过(重复量化会累积误差); factory_floor 用 -vpf 浮点位置
#   (整厂 30m 跨度默认 14bit 量化=1.8mm 步进, gltfpack 会报 15% 位置误差警告, 细节糊边)
set -e
DIR="$(cd "$(dirname "$0")/../frontend/public/twin-assets" && pwd)"
for f in "$DIR"/*.glb; do
  base="$(basename "$f")"
  if head -c 200000 "$f" | grep -aq "meshopt"; then
    echo "skip $base (already compressed)"
    continue
  fi
  extra=""
  if [ "$base" = "factory_floor.glb" ]; then extra="-vpf"; fi
  npx --yes gltfpack -i "$f" -o "$f" -c -kn -km $extra
  echo "compressed $base"
done
echo "ALL GLB COMPRESSED"
