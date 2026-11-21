# 开发与测试

## 项目结构

```text
usd_scene_tool/       Maya UI、检查、材质重建、Undo、兼容读取
ue_maya_bridge/       USD 包、相机数学、可选 Unreal 导出器
usd_learning/         原创合成 USD / 校准 PNG
tests/unit/          不需要 DCC 的单元测试
tests/maya/          独立 Maya 集成测试与自生成数据
scripts/             检查、Maya 测试运行器和发布打包
docs/                安装、操作、原理、边界与排错
.github/             CI、Issue 和 PR 模板
```

不把运行时强行变成 pip 包：拖入入口脚本和完整目录即可使用，Maya 依赖由宿主提供。
`requirements-dev.txt` 只用于开发格式化，不用于 Maya 安装。

## 普通 Python 检查

```bash
python -m pip install -r requirements-dev.txt
python -m black --check .
python -m unittest discover -s tests/unit -p "test_*.py"
python scripts/check_repository.py
```

格式化使用固定 Black 版本，代码保持 Python 3.9 语法。
单元测试覆盖 LOD/Nanite 策略、包清单校验、路径逃逸、内容变更和相机参数边界。

## Maya 集成测试

必须在独立 mayapy 运行，不能在工作场景中执行测试文件。运行器会为每个测试
创建独立 Maya 配置，把日志和结果写到忽略的 `.test-results/maya/`。

```bash
python scripts/run_maya_tests.py --mayapy "D:/Apps/Maya2023/bin/mayapy.exe"
```

把路径换成实际安装位置。测试使用仓库内的合成资源并生成自己的临时几何和摄影机，
不依赖作者电脑上的下载模型、旧运行记录、MCP、工作会话 PID 或绝对资源路径。

材质测试覆盖 PBR、独立拆图、ORM 像素一致、位深与缓存、法线、绑定、回滚及保存重开。
工作流测试覆盖简易 UI、手动覆盖、Phong、旧 Phong、相机与真实兼容读取子进程。

## 发布

不带 Maya 验收数据的本地构建：

```bash
python scripts/build_release.py
```

已完成集成测试后，构建带当前源码验收记录的发布包：

```bash
python scripts/build_release.py --validation-dir .test-results/maya
```

后者核对报告版本和每个运行模块的 SHA256，拒绝把旧测试结果贴到新代码上。
ZIP 使用明确文件列表和固定条目时间，不打包下载模型、缓存、日志、测试配置或凭据。
两个产品包和 `SHA256SUMS.txt` 位于 `dist/`；GitHub Releases 承载这些二进制附件，
Git 仓库只保存源码、文档、合成小样和开发配置。

发布前为最终 ZIP 做解压运行检查；源码检查通过不能替代宿主验收。
Unreal 交互验证只能在合适的测试工程中做，不把普通 CI 结果称为 UE 功能验证。

## 改动约定

保持导入新增、源文件不改、全局单位不隐式修改、已有场景不清空、失败完整回滚。
新增近似处理必须同时出现在界面、说明和报告中。涉及 Undo 时不要卸载工作会话
正在使用的撤销插件。
