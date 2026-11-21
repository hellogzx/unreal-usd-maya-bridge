"""Small USD importer with Standard Surface and preview Phong targets."""

from pathlib import Path
from PySide2 import QtCore, QtGui, QtWidgets
from . import __version__, core

_WINDOW = None
BASE = Path(__file__).resolve().parents[1]
CHANNELS = (
    ("diffuseColor", "Base Color"),
    ("metallic", "Metallic"),
    ("roughness", "Roughness"),
    ("normal", "Normal"),
)


class Window(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("USDSimplePBR")
        self.setWindowTitle("USD → Maya 材质 · " + __version__)
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        self.resize(720, 560)
        self.setMinimumWidth(620)
        self.setFont(QtGui.QFont("Microsoft YaHei UI", 10))
        self.setStyleSheet(
            """
            QDialog { background:#272e36; }
            QLabel,QCheckBox { color:#e4eaee; font-size:13px; }
            QLineEdit,QComboBox,QPlainTextEdit { background:#1d242b; color:#e4eaee; padding:6px; }
            QPushButton { background:#3c4752; color:#e4eaee; padding:7px 12px; }
            QPushButton:disabled { color:#89949e; }
            QGroupBox { color:#e4eaee; font-size:13px; }
        """
        )
        self.result = None
        self.inspection = None
        self.overrides = {}
        self.busy = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        self.heading = QtWidgets.QLabel("USD → Standard Surface")
        self.heading.setStyleSheet("color:#7cddce;font-size:22px;font-weight:600")
        layout.addWidget(self.heading)
        layout.addWidget(QtWidgets.QLabel("选择 USD 和目标材质，一键导入模型并连接贴图。"))
        file_row = QtWidgets.QHBoxLayout()
        file_row.addWidget(QtWidgets.QLabel("USD 文件"))
        self.path = QtWidgets.QLineEdit()
        self.path.setObjectName("simpleUsdPath")
        self.path.setPlaceholderText("选择 .usd / .usda / .usdc")
        self.path.textChanged.connect(self.path_changed)
        self.path.editingFinished.connect(self.inspect)
        self.browse_button = QtWidgets.QPushButton("选择 USD…")
        self.browse_button.clicked.connect(self.browse)
        file_row.addWidget(self.path, 1)
        file_row.addWidget(self.browse_button)
        layout.addLayout(file_row)
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("转换为"))
        self.material_mode = QtWidgets.QComboBox()
        self.material_mode.setObjectName("simpleMaterialMode")
        self.material_mode.addItem("Maya Standard Surface（PBR）", "pbr")
        self.material_mode.addItem("Maya Phong（预览近似）", "phong_preview")
        mode_row.addWidget(self.material_mode, 1)
        layout.addLayout(mode_row)
        self.target_row = QtWidgets.QWidget()
        target_layout = QtWidgets.QHBoxLayout(self.target_row)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.addWidget(QtWidgets.QLabel("当前贴图对应的材质"))
        self.target = QtWidgets.QComboBox()
        self.target.currentIndexChanged.connect(self.target_changed)
        target_layout.addWidget(self.target, 1)
        layout.addWidget(self.target_row)
        self.target_row.hide()
        texture_box = QtWidgets.QGroupBox("四个 PBR 通道 · 留空时自动读取 USD 材质")
        grid = QtWidgets.QGridLayout(texture_box)
        self.channel_fields = {}
        self.channel_buttons = {}
        for row, (key, label) in enumerate(CHANNELS):
            grid.addWidget(QtWidgets.QLabel(label), row, 0)
            field = QtWidgets.QLineEdit()
            field.setObjectName("simple_" + key)
            field.setClearButtonEnabled(True)
            field.setPlaceholderText("自动使用 USD 贴图或常量；也可手动选择")
            field.textChanged.connect(lambda text, k=key: self.channel_changed(k, text))
            button = QtWidgets.QPushButton("选择贴图…")
            button.clicked.connect(lambda checked=False, k=key: self.choose_texture(k))
            grid.addWidget(field, row, 1)
            grid.addWidget(button, row, 2)
            self.channel_fields[key] = field
            self.channel_buttons[key] = button
        grid.setColumnStretch(1, 1)
        layout.addWidget(texture_box)
        self.hint = QtWidgets.QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.more = QtWidgets.QPushButton("更多选项")
        self.more.setCheckable(True)
        self.more.toggled.connect(self.toggle_options)
        layout.addWidget(self.more, alignment=QtCore.Qt.AlignLeft)
        self.options = QtWidgets.QWidget()
        options_layout = QtWidgets.QVBoxLayout(self.options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        self.flip_normal_y = QtWidgets.QCheckBox("Normal 翻转绿色通道（DirectX 贴图需要时开启）")
        self.output_directory = QtWidgets.QLineEdit()
        self.output_directory.setPlaceholderText(
            "独立贴图输出目录：留空使用 USD 同级 Maya_PBR_Textures"
        )
        options_layout.addWidget(self.flip_normal_y)
        options_layout.addWidget(self.output_directory)
        layout.addWidget(self.options)
        self.options.hide()
        self.import_button = QtWidgets.QPushButton("导入 USD 并生成 PBR 材质")
        self.import_button.setObjectName("simpleImportPBR")
        self.import_button.setMinimumHeight(44)
        self.import_button.setStyleSheet(
            "background:#227e73;font-size:15px;font-weight:600;color:white"
        )
        self.import_button.clicked.connect(self.load)
        layout.addWidget(self.import_button)
        self.status = QtWidgets.QLabel("就绪 · Maya 2023，厘米、Y-up")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        bottom = QtWidgets.QHBoxLayout()
        self.select_model_button = QtWidgets.QPushButton("选择模型")
        self.select_material_button = QtWidgets.QPushButton("选择材质")
        self.sample_button = QtWidgets.QPushButton("PBR 示例")
        self.advanced_button = QtWidgets.QPushButton("完整工具")
        self.select_model_button.clicked.connect(lambda: self.select(False))
        self.select_material_button.clicked.connect(lambda: self.select(True))
        self.sample_button.clicked.connect(self.sample)
        self.advanced_button.clicked.connect(self.advanced)
        for button in (
            self.select_model_button,
            self.select_material_button,
            self.sample_button,
            self.advanced_button,
        ):
            bottom.addWidget(button)
        layout.addLayout(bottom)
        self.details = QtWidgets.QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.hide()
        self.details_button = QtWidgets.QPushButton("查看详情")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.details.setVisible)
        self.details_button.toggled.connect(
            lambda checked: self.details_button.setText("收起详情" if checked else "查看详情")
        )
        layout.addWidget(self.details_button, alignment=QtCore.Qt.AlignLeft)
        layout.addWidget(self.details)
        self.material_mode.currentIndexChanged.connect(self.mode_changed)
        self.mode_changed()
        self.update_buttons()

    def mode_changed(self, *args):
        phong = self.material_mode.currentData() == "phong_preview"
        name = "Phong" if phong else "Standard Surface"
        self.heading.setText("USD → " + name)
        self.import_button.setText("导入 USD 并生成 " + name + " 材质")
        self.hint.setText(
            "Phong 预览近似：Roughness 转高光范围；Metallic 控制漫反射与高光颜色，无法与 PBR 完全一致。"
            if phong
            else "Metallic / Roughness 使用灰度图；Normal 使用 RGB 法线图。已有 ORM 会自动拆分。"
        )
        if self.inspection:
            self.status.setText("已选择 " + name + "，导入时自动连接贴图；可撤销。")

    def update_buttons(self):
        self.import_button.setEnabled(bool(self.path.text().strip()) and not self.busy)
        for widget in (
            self.path,
            self.browse_button,
            self.target,
            self.material_mode,
            self.more,
            self.output_directory,
            self.flip_normal_y,
            self.sample_button,
            self.advanced_button,
            *self.channel_fields.values(),
            *self.channel_buttons.values(),
        ):
            widget.setEnabled(not self.busy)
        self.select_model_button.setEnabled(bool(self.result) and not self.busy)
        self.select_material_button.setEnabled(
            bool(self.result and self.result.get("materials")) and not self.busy
        )

    def toggle_options(self, visible):
        self.options.setVisible(visible)
        self.more.setText("收起选项" if visible else "更多选项")

    def path_changed(self):
        self.inspection = None
        self.overrides = {}
        self.target.blockSignals(True)
        self.target.clear()
        self.target.blockSignals(False)
        self.target_row.hide()
        self.target_changed()
        self.status.setText("已选择文件，导入时会自动检查。")
        self.update_buttons()

    def browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 USD", self.path.text(), "USD (*.usd *.usda *.usdc)"
        )
        if path:
            self.path.setText(path)
            self.inspect()

    def inspect(self):
        if self.busy or not self.path.text().strip():
            return False
        try:
            report = core.inspect_file(self.path.text().strip())
            problems = report["errors"] + report["pbr_errors"]
            if problems:
                raise core.ToolError("\n".join(problems))
            self.inspection = report
            current = self.target.currentData()
            self.target.blockSignals(True)
            self.target.clear()
            for plan in report["pbr_materials"]:
                self.target.addItem(plan["path"], plan["path"])
            if any(
                b["material"] is None or any(s["material"] is None for s in b["subsets"])
                for b in report["pbr_bindings"]
            ):
                self.target.addItem("未绑定材质的模型", "__unbound__")
            if self.target.count() == 0:
                self.target.addItem("无模型材质", "__unbound__")
            if current is not None and self.target.findData(current) >= 0:
                self.target.setCurrentIndex(self.target.findData(current))
            self.target.blockSignals(False)
            self.target_row.setVisible(self.target.count() > 1)
            self.target_changed()
            self.status.setText(
                "文件已就绪 · {} 个网格，{} 个材质。".format(
                    report["meshes"], len(report["pbr_materials"])
                )
            )
            return True
        except Exception as error:
            self.inspection = None
            self.error(error)
            return False

    def target_changed(self, *args):
        target = self.target.currentData() or "__unbound__"
        values = self.overrides.get(target, {})
        plan = next(
            (p for p in (self.inspection or {}).get("pbr_materials", []) if p["path"] == target),
            None,
        )
        for key, field in self.channel_fields.items():
            field.blockSignals(True)
            field.setText(values.get(key, ""))
            data = plan["inputs"][key] if plan else {}
            if "texture" in data:
                texture = data["texture"]
                field.setPlaceholderText(
                    "USD："
                    + Path(texture["path"]).name
                    + (" → 自动拆为独立图" if key in ("roughness", "metallic") else "")
                )
                field.setToolTip(texture["path"])
            else:
                field.setPlaceholderText("USD 常量／默认值；可选择一张贴图")
                field.setToolTip("清空手动路径后使用 USD 原值。")
            field.blockSignals(False)

    def channel_changed(self, key, text):
        target = self.target.currentData() or "__unbound__"
        values = self.overrides.setdefault(target, {})
        if text.strip():
            values[key] = text.strip()
        else:
            values.pop(key, None)

    def choose_texture(self, key):
        if not self.inspection and not self.inspect():
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择 " + dict(CHANNELS)[key] + " 贴图",
            self.channel_fields[key].text(),
            "Images (*.png *.jpg *.jpeg)",
        )
        if path:
            self.channel_fields[key].setText(path)

    def load(self):
        if self.busy or not self.inspect():
            return
        self.busy = True
        mode = self.material_mode.currentData()
        name = "Phong" if mode == "phong_preview" else "Standard Surface"
        self.status.setText("正在导入并连接 " + name + "；如有首次插件安全提示，请核对后处理。")
        self.update_buttons()
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
        try:
            result = core.load_file(
                self.path.text().strip(),
                mode,
                flip_normal_y=self.flip_normal_y.isChecked(),
                texture_output_directory=self.output_directory.text().strip(),
                material_overrides={k: v for k, v in self.overrides.items() if v},
            )
            self.result = result
            self.status.setText(
                "完成 · {} 个网格，{} 个 {}；可撤销。".format(
                    result["native_mesh_paths"], len(result["materials"]), name
                )
            )
            lines = ["[导入完成] " + result["root"]]
            lines += [
                "[{}] {}".format(t.get("usage", "贴图"), t["path"]) for t in result["textures"]
            ]
            lines += ["[提示] " + w for w in result["warnings"]]
            lines += ["生成的独立贴图会保留，供撤销重做及保存后的场景使用。"]
            self.details.setPlainText("\n".join(lines))
            target = self.target.currentData()
            plan = next(
                (
                    m
                    for m in result["materials"]
                    if m.get("usd_material") == (None if target == "__unbound__" else target)
                ),
                None,
            )
            if plan:
                for key, field in self.channel_fields.items():
                    texture = plan.get("channel_textures", {}).get(key)
                    if texture and not field.text():
                        field.setPlaceholderText("已连接：" + Path(texture["path"]).name)
                        field.setToolTip(texture["path"])
        except Exception as error:
            self.error(error)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.busy = False
            self.update_buttons()

    def error(self, error):
        self.status.setText("未完成：" + str(error).splitlines()[0])
        self.details.setPlainText(str(error))
        self.details_button.setChecked(True)

    def select(self, materials):
        try:
            if self.result:
                core.select_result(self.result, materials)
        except Exception as error:
            self.error(error)

    def sample(self):
        self.path.setText(str(BASE / "usd_learning/05_pbr_separate_textures.usda"))
        self.inspect()

    def advanced(self):
        from .ui import show

        show()


def show():
    global _WINDOW
    if _WINDOW is not None:
        try:
            _WINDOW.show()
            _WINDOW.raise_()
            _WINDOW.activateWindow()
            return _WINDOW
        except RuntimeError:
            _WINDOW = None
    from maya import OpenMayaUI
    from shiboken2 import wrapInstance

    pointer = OpenMayaUI.MQtUtil.mainWindow()
    _WINDOW = Window(wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None)
    _WINDOW.show()
    return _WINDOW
