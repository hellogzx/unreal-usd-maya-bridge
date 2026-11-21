# 原创 USD 学习小样

这些合成资源用于检查连接和比例，不是照片级模型。
全部资产路径为相对路径，可随完整目录移动。

| 文件 | 内容 |
| --- | --- |
| 01_material_binding.usda | 200×200cm 四边形、st UV、纯色材质与绑定 |
| 02_texture_binding.usda | 通过 subLayers 添加棋盘图片 |
| 03_roughness_override.usda | 在更强层中覆盖粗糙度 |
| 04_pbr_textures.usda | 两个盒子，比较独立图片与 ORM 通道 |
| 05_pbr_separate_textures.usda | 两个盒子，两材质使用四张独立图片 |
| textures/ | 棋盘、颜色、粗糙度、金属度、ORM 和切线法线校准 PNG |

简易窗口的“PBR 示例”选择 05，不立即导入。
选择 Standard Surface 检查 PBR 通道，选择 Phong 检查预览近似。
不要把测试图片的校准图案当作真实材质效果。
