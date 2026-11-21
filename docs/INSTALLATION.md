# 安装

## 环境

已验证 Windows / Maya 2023 / Maya USD 0.16.0，使用 Maya 自带 Python 3.9、
PySide2 和 USD SDK。其他 Maya 年份未验收，工具会明确拒绝。

安装的是 Python 工具目录，不是需要编译的 `.mll`。无需安装 pip 依赖或 MCP。

## 从 ZIP 使用

1. 下载 Releases 中的 Maya 独立包，解压到一个可长期保留的目录。
2. 保存当前工作。升级旧版本时建议重启 Maya，避免继续使用已缓存的 Python 模块。
3. 将 `launch_usd_pbr_simple.py` 拖入 Maya 视口。
4. 如首次加载本工具的撤销插件出现 Maya 自带安全提示，核对本地来源后自行处理。

`launch_usd_tool.py` 也会打开同一简易窗口。完整面板从窗口底部的“完整工具”进入。
两个入口均复用已打开窗口。

## Shelf 按钮

将 `install_usd_tool.py` 拖入视口，会创建或更新专用 `USDSceneTool` Shelf 按钮。
按钮引用当前工具目录，所以创建按钮后请保留该目录。

安装器不修改 Maya.env、用户启动脚本或系统插件文件。

## 从仓库运行

在 Maya Script Editor 的 **Python** 页签执行：

```python
import sys
project = r"D:\Tools\unreal-usd-maya-bridge"  # 改成实际解压目录
if project not in sys.path:
    sys.path.insert(0, project)
import usd_scene_tool
usd_scene_tool.show()
```

不要在 MEL 页签直接粘贴 Python。旧 Maya USD 对某些中文路径的支持有限；
若收到明确路径编码错误，请把完整资源目录和工具放到英文路径后重试。

## 关闭与卸载

关闭工具窗口即可结束使用。若使用过 Shelf 安装，可在 Maya 中删除对应 Shelf 按钮。
保留已保存场景使用的贴图和 `Maya_PBR_Textures`；这些图片仍是场景依赖。

不要为升级强行卸载正在承载撤销历史的插件。保存工作并重启 Maya 后再更换目录。
