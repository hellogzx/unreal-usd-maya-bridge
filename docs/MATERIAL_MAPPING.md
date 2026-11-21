# 材质映射

## Standard Surface

| USD 输入 | Maya 属性 | 图片 |
| --- | --- | --- |
| diffuseColor | baseColor | sRGB；源明确标 raw 时尊重该设置 |
| metallic | metalness | 独立灰度 PNG，Raw |
| roughness | specularRoughness | 独立灰度 PNG，Raw |
| normal | bump2d → normalCamera | 独立 RGB，Raw、切线空间 |
| ior | specularIOR | 受支持范围内的常量 |

USD 法线网络需要标准 `scale=(2,2,2,1)`、`bias=(-1,-1,-1,0)` 解码，也接受
已记录的绿色翻转形式。Maya 的 tangent bump2d 负责无符号法线解码，因此不会
再把这组 USD 解码重复乘一次。

## 独立通道提取

按 USD 明确连接的 R/G/B/A 分量提取，不根据文件名猜 ORM 顺序。
拆分在像素数据上执行，不进行 sRGB 转换；scale/bias 留在 Maya file 节点。

支持 8 位 PNG/JPEG、16 位整数 PNG。当前不拆分 EXR、TIFF 或 HDR。
Roughness、Metallic 使用不同图片和不同 file 节点；Normal 保留自己的 RGB 图。
缓存依据源内容、通道、用途和算法版本命名，并校验记录中的 SHA256。

## Phong 预览近似

Phong 没有与 PBR 直接对应的 metallic/roughness 属性。本工具定义的可编辑规则为：

```text
r = clamp(roughness, 0.02, 1)
cosinePower = clamp(2 / r² - 2, 2, 1000)
F0 = ((ior - 1) / (ior + 1))²
diffuse = 1 - metallic
specularColor = lerp(F0, baseColor, metallic)
reflectivity = lerp(F0, 1, metallic)
```

Base Color 接 `color`；Normal 走同样的 tangent bump2d。贴图驱动的粗糙度通过
可编辑的 clamp、multiplyDivide 等节点换算。它不等价于 PBR BRDF，不能还原
微表面、Fresnel、反射模糊或能量响应。

原理参照各自参数定义：[Autodesk Phong](https://help.autodesk.com/cloudhelp/2025/ENU/Maya-LightingShading/files/GUID-3EDEB1B3-4E48-485A-9714-9998F6E4944D.htm)、
[UsdPreviewSurface 规范](https://openusd.org/release/wp_usdpreviewsurface.html)。
上面的有界换算是本工具的预览启发式，并非两方规定的等价转换标准。
