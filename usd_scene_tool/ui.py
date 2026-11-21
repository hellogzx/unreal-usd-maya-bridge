"""Small Qt5 UI, using only Maya's bundled PySide2."""

import json
from contextlib import contextmanager
from pathlib import Path

from PySide2 import QtCore, QtGui, QtWidgets

from . import __version__, core

_WINDOW = None
BASE = Path(__file__).resolve().parents[1]
SAMPLES = [
    ("纯色与绑定", "01_material_binding.usda"),
    ("棋盘贴图", "02_texture_binding.usda"),
    ("分层覆盖", "03_roughness_override.usda"),
    ("PBR 独立贴图", "05_pbr_separate_textures.usda"),
]


class Window(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("USDSceneMaterialTool")
        self.setWindowTitle("USD 场景与材质工具 · " + __version__)
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.resize(960, 900)
        self.setMinimumSize(760, 700)
        self.setFont(QtGui.QFont("Microsoft YaHei UI", 10))
        # Maya's application stylesheet otherwise overrides some font metrics
        # and form-layout sizing. Keep this dialog's controls consistent.
        self.setStyleSheet(
            """
            QLabel, QLineEdit, QPushButton, QGroupBox, QRadioButton, QCheckBox,
            QTabBar::tab, QHeaderView::section, QPlainTextEdit, QTableWidget {
                font-family: 'Microsoft YaHei UI'; font-size: 13px;
            }
            QLabel, QGroupBox, QRadioButton, QCheckBox { color: #e4eaee; }
            QLineEdit, QPlainTextEdit, QTableWidget { background: #1d242b; color: #e4eaee; selection-background-color: #227e73; }
            QPushButton { background: #3c4752; color: #e4eaee; padding: 6px 10px; }
            QPushButton:disabled { color: #85909a; background: #303942; }
            QTabBar::tab, QHeaderView::section { background: #303942; color: #e4eaee; padding: 6px; }
            QTabBar::tab:selected { background: #227e73; color: white; }
        """
        )
        palette = self.palette()
        for role, color in (
            (QtGui.QPalette.Window, "#272e36"),
            (QtGui.QPalette.WindowText, "#e4eaee"),
            (QtGui.QPalette.Base, "#1d242b"),
            (QtGui.QPalette.AlternateBase, "#303942"),
            (QtGui.QPalette.Text, "#e4eaee"),
            (QtGui.QPalette.Button, "#3c4752"),
            (QtGui.QPalette.ButtonText, "#e4eaee"),
            (QtGui.QPalette.Highlight, "#227e73"),
            (QtGui.QPalette.HighlightedText, "#ffffff"),
        ):
            palette.setColor(role, QtGui.QColor(color))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.inspection = None
        self.result = None
        self.loaded_cameras = []
        self._busy = False
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        title = QtWidgets.QLabel("USD 场景与材质")
        title.setStyleSheet("font-size: 22px; font-weight: 600; color: #7cddce;")
        layout.addWidget(title)
        self.env_label = QtWidgets.QLabel("Maya 2023 · 检查或载入时自动加载 Maya USD")
        self.env_label.setStyleSheet("color: #b9c2c9;")
        layout.addWidget(self.env_label)

        file_row = QtWidgets.QHBoxLayout()
        self.path = QtWidgets.QLineEdit()
        self.path.setObjectName("usdFilePath")
        self.path.setPlaceholderText("选择 .usd / .usda / .usdc 场景文件")
        self.path.setMinimumHeight(34)
        self.browse_button = QtWidgets.QPushButton("浏览…")
        self.browse_button.clicked.connect(self.browse)
        file_row.addWidget(self.path, 1)
        file_row.addWidget(self.browse_button)
        layout.addLayout(file_row)
        self.path.textChanged.connect(self.path_changed)

        mode_box = QtWidgets.QGroupBox("载入方式")
        modes = QtWidgets.QVBoxLayout(mode_box)
        self.phong = QtWidgets.QRadioButton("转成 Maya 模型／摄影机 + Phong　·　可编辑原生节点")
        self.phong.setObjectName("phongMode")
        self.pbr = QtWidgets.QRadioButton(
            "转成 Maya 模型／摄影机 + Standard Surface（PBR）· 自动拆分独立通道贴图"
        )
        self.pbr.setObjectName("pbrMode")
        self.stage = QtWidgets.QRadioButton("保留 USD Stage　·　附加可切换的静态摄影机副本")
        self.stage.setObjectName("stageMode")
        self.phong.setChecked(True)
        modes.addWidget(self.phong)
        modes.addWidget(self.pbr)
        modes.addWidget(self.stage)
        self.flip_normal_y = QtWidgets.QCheckBox("PBR 法线翻转绿色通道（DirectX 贴图需要时开启）")
        self.flip_normal_y.setObjectName("flipNormalY")
        self.flip_normal_y.setToolTip(
            "在 USD 已记录的法线解码基础上额外翻转 Y。仅影响本次 PBR 导入。"
        )
        modes.addWidget(self.flip_normal_y)
        for radio in (self.phong, self.pbr, self.stage):
            radio.toggled.connect(self.mode_changed)
        self.allow_missing = QtWidgets.QCheckBox("允许缺失贴图／资产（可能显示占位外观）")
        self.allow_missing.setObjectName("allowMissingTextures")
        modes.addWidget(self.allow_missing)
        texture_row = QtWidgets.QHBoxLayout()
        texture_row.addWidget(QtWidgets.QLabel("独立贴图目录："))
        self.texture_directory = QtWidgets.QLineEdit()
        self.texture_directory.setObjectName("textureOutputDirectory")
        self.texture_directory.setPlaceholderText("留空：USD 同级 Maya_PBR_Textures 文件夹")
        self.texture_directory.setToolTip(
            "Roughness、Metallic 写为不同灰度 PNG；Normal 保持独立 RGB 图片。撤销不删除生成文件。"
        )
        self.texture_directory_button = QtWidgets.QPushButton("选择目录…")
        self.texture_directory_button.clicked.connect(self.browse_texture_directory)
        texture_row.addWidget(self.texture_directory, 1)
        texture_row.addWidget(self.texture_directory_button)
        modes.addLayout(texture_row)
        layout.addWidget(mode_box)

        action_row = QtWidgets.QHBoxLayout()
        self.check_button = QtWidgets.QPushButton("检查文件")
        self.check_button.setObjectName("inspectButton")
        self.check_button.clicked.connect(self.check)
        self.load_button = QtWidgets.QPushButton("载入当前场景")
        self.load_button.setObjectName("loadButton")
        self.load_button.setMinimumHeight(38)
        self.load_button.setStyleSheet(
            "QPushButton { background: #227e73; color: white; font-weight: 600; padding: 8px 18px; } QPushButton:disabled { background: #555; }"
        )
        self.load_button.clicked.connect(self.load)
        action_row.addWidget(self.check_button)
        action_row.addWidget(self.load_button, 1)
        layout.addLayout(action_row)
        self.status = QtWidgets.QLabel("就绪 · 首版支持厘米、Y-up 的 USD 与 Maya 场景")
        self.status.setWordWrap(True)
        self.status.setObjectName("statusLabel")
        layout.addWidget(self.status)

        self.tabs = QtWidgets.QTabWidget()
        overview = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(overview)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.summary_labels = {}
        for key, label in [
            ("units", "单位 / 轴向"),
            ("meshes", "模型 / 实例"),
            ("materials", "材质 / 面子集"),
            ("layers", "依赖层 / 缺失资产"),
            ("loaded", "最近载入"),
        ]:
            value = QtWidgets.QLabel("—")
            value.setWordWrap(True)
            value.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            value.setMinimumHeight(24)
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.summary_labels[key] = value
            form.addRow(label + "：", value)
        self.tabs.addTab(overview, "文件概览")
        self.materials = QtWidgets.QTableWidget(0, 5)
        self.materials.setHorizontalHeaderLabels(
            ["USD 材质路径", "Shader 类型", "roughness", "Phong 检查", "PBR 检查"]
        )
        self.materials.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.materials.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.materials.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.materials.setColumnWidth(1, 150)
        self.materials.setColumnWidth(2, 80)
        self.materials.setColumnWidth(3, 100)
        self.materials.setColumnWidth(4, 100)
        self.materials.verticalHeader().hide()
        self.tabs.addTab(self.materials, "USD 材质")
        self.source = QtWidgets.QPlainTextEdit()
        self.source.setObjectName("ueSourceReport")
        self.source.setReadOnly(True)
        self.source.setPlaceholderText("选择 UE 导出包中的 scene.usda，可在此查看来源及跳过清单。")
        self.tabs.addTab(self.source, "UE 来源")
        camera_tab = QtWidgets.QWidget()
        camera_layout = QtWidgets.QVBoxLayout(camera_tab)
        camera_layout.addWidget(QtWidgets.QLabel("最近一次载入的 Maya 摄影机 · 下列参数为导入快照"))
        self.camera_table = QtWidgets.QTableWidget(0, 5)
        self.camera_table.setObjectName("cameraTable")
        self.camera_table.setHorizontalHeaderLabels(
            ["名称", "来源类型", "导入焦距 mm", "有效画幅 mm", "建议输出"]
        )
        self.camera_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.camera_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.camera_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.camera_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.camera_table.verticalHeader().hide()
        for column, width in ((1, 110), (2, 105), (3, 150), (4, 120)):
            self.camera_table.setColumnWidth(column, width)
        self.camera_table.itemSelectionChanged.connect(self.camera_selection_changed)
        camera_layout.addWidget(self.camera_table, 1)
        self.camera_info = QtWidgets.QLabel("载入含摄影机的 USD 后，可在此选择并切换视角。")
        self.camera_info.setWordWrap(True)
        camera_layout.addWidget(self.camera_info)
        camera_tools = QtWidgets.QHBoxLayout()
        self.camera_select = QtWidgets.QPushButton("选择摄影机")
        self.camera_view = QtWidgets.QPushButton("切换视角")
        self.camera_frame = QtWidgets.QPushButton("匹配源画幅")
        self.camera_select.clicked.connect(lambda: self.camera_action("select"))
        self.camera_view.clicked.connect(lambda: self.camera_action("view"))
        self.camera_frame.clicked.connect(lambda: self.camera_action("frame"))
        for button in (self.camera_select, self.camera_view, self.camera_frame):
            camera_tools.addWidget(button)
        camera_layout.addLayout(camera_tools)
        note = QtWidgets.QLabel(
            "匹配源画幅会调整当前场景的全局输出宽高和像素比例，可撤销。切换视角不会改变渲染摄影机选择。"
        )
        note.setWordWrap(True)
        camera_layout.addWidget(note)
        self.tabs.addTab(camera_tab, "摄影机")
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("resultLog")
        self.log.setPlaceholderText("检查结果、缺失路径、实际生成的材质和错误详情会显示在这里。")
        self.tabs.addTab(self.log, "结果与详情")
        layout.addWidget(self.tabs, 1)

        tools = QtWidgets.QHBoxLayout()
        self.select_button = QtWidgets.QPushButton("选择载入对象")
        self.select_button.clicked.connect(lambda: self.select(False))
        self.material_button = QtWidgets.QPushButton("选择材质")
        self.material_button.clicked.connect(lambda: self.select(True))
        self.hypershade_button = QtWidgets.QPushButton("打开 Hypershade")
        self.hypershade_button.clicked.connect(self.hypershade)
        self.report_button = QtWidgets.QPushButton("保存报告…")
        self.report_button.clicked.connect(self.export_report)
        for button in (
            self.select_button,
            self.material_button,
            self.hypershade_button,
            self.report_button,
        ):
            tools.addWidget(button)
        layout.addLayout(tools)

        samples = QtWidgets.QHBoxLayout()
        samples.addWidget(QtWidgets.QLabel("学习样例："))
        self.sample_buttons = []
        for i, (label, _) in enumerate(SAMPLES):
            button = QtWidgets.QPushButton("{} · {}".format(i + 1, label))
            button.setObjectName("sampleButton" + str(i + 1))
            button.clicked.connect(lambda checked=False, index=i: self.choose_sample(index))
            samples.addWidget(button)
            self.sample_buttons.append(button)
        layout.addLayout(samples)
        footer = QtWidgets.QLabel(
            "载入会添加到当前场景。可用 Maya 的 Ctrl+Z 撤销。原生导入不会自动跟随外部 USD 更新。"
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #b9c2c9; font-size: 11px;")
        layout.addWidget(footer)
        self.update_buttons()

    def update_buttons(self):
        has_path = bool(self.path.text().strip())
        for button in (self.check_button, self.load_button):
            button.setEnabled(has_path and not self._busy)
        self.select_button.setEnabled(bool(self.result) and not self._busy)
        self.material_button.setEnabled(
            bool(self.result and self.result.get("materials", self.result.get("phongs")))
            and not self._busy
        )
        for radio in (self.phong, self.pbr, self.stage):
            radio.setEnabled(not self._busy)
        self.flip_normal_y.setEnabled(self.pbr.isChecked() and not self._busy)
        self.texture_directory.setEnabled(self.pbr.isChecked() and not self._busy)
        self.texture_directory_button.setEnabled(self.pbr.isChecked() and not self._busy)
        self.report_button.setEnabled(bool(self.inspection or self.result) and not self._busy)
        has_camera = bool(self.loaded_cameras and self.camera_table.currentRow() >= 0)
        for button in (self.camera_select, self.camera_view, self.camera_frame):
            button.setEnabled(has_camera and not self._busy)

    def mode_changed(self):
        if not hasattr(self, "load_button"):
            return
        self.update_buttons()
        if self.inspection:
            label = (
                "PBR"
                if self.pbr.isChecked()
                else ("Phong" if self.phong.isChecked() else "USD Stage")
            )
            self.status.setText("已选择 " + label + "；载入前会重新检查对应材质支持。")

    def camera_selection_changed(self):
        row = self.camera_table.currentRow()
        if 0 <= row < len(self.loaded_cameras):
            record = self.loaded_cameras[row]
            hint = record["frame_hint"]
            self.camera_info.setText(
                "{} · 目标比例 {:.6g}:1 · 匹配后输出 {} × {}，方形像素。\n{}".format(
                    record["label"],
                    record["aspect_ratio"],
                    hint["width"],
                    hint["height"],
                    record["prim"],
                )
            )
        self.update_buttons()

    def display_cameras(self, records):
        self.loaded_cameras = records
        self.camera_table.setRowCount(0)
        self.camera_table.setRowCount(len(records))
        for row, record in enumerate(records):
            kind = {
                "CineCameraComponent": "CineCamera",
                "CameraComponent": "普通相机",
                "UsdCamera": "USD 相机",
            }.get(record["camera_type"], record["camera_type"])
            hint = record["frame_hint"]
            values = (
                record["label"],
                kind,
                "{:.6g}".format(record["focal_length_mm"]),
                "{:.6g} × {:.6g}".format(record["aperture_width_mm"], record["aperture_height_mm"]),
                "{} × {}".format(hint["width"], hint["height"]),
            )
            for column, value in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(value)
                cell.setToolTip(value)
                self.camera_table.setItem(row, column, cell)
        if records:
            self.camera_table.selectRow(0)
        else:
            self.camera_info.setText("最近一次载入没有可切换的静态摄影机。")
        self.update_buttons()

    def camera_action(self, operation):
        row = self.camera_table.currentRow()
        if not 0 <= row < len(self.loaded_cameras):
            return
        try:
            from . import cameras

            record = self.loaded_cameras[row]
            if operation == "select":
                cameras.select_camera(record)
                self.status.setText("已选择摄影机：" + record["label"])
            elif operation == "view":
                cameras.view_camera(record)
                self.status.setText("已切换摄影机；需要一致构图时请匹配源画幅。")
            else:
                hint = cameras.match_frame(record)
                self.status.setText(
                    "已匹配源画幅：{} × {}，像素比例 1，可撤销。".format(
                        hint["width"], hint["height"]
                    )
                )
        except Exception as exc:
            self.error(exc)

    def path_changed(self):
        self.inspection = None
        self.source.clear()
        self.materials.setRowCount(0)
        for key in ("units", "meshes", "materials", "layers"):
            self.summary_labels[key].setText("—")
        self.status.setText("文件已更改，等待检查。")
        self.update_buttons()

    @contextmanager
    def working(self, message):
        if self._busy:
            raise core.ToolError("正在处理，请等待当前操作完成。")
        self._busy = True
        self.status.setText(message)
        self.update_buttons()
        self.browse_button.setEnabled(False)
        self.path.setEnabled(False)
        for button in self.sample_buttons:
            button.setEnabled(False)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ExcludeUserInputEvents)
        try:
            yield
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._busy = False
            self.browse_button.setEnabled(True)
            self.path.setEnabled(True)
            for button in self.sample_buttons:
                button.setEnabled(True)
            self.update_buttons()

    def error(self, exc):
        self.status.setText("未完成：" + str(exc).splitlines()[0])
        self.log.appendPlainText("\n[未完成]\n" + str(exc))
        self.tabs.setCurrentWidget(self.log)

    def browse(self):
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 USD 场景", self.path.text(), "USD 场景 (*.usd *.usda *.usdc)"
        )
        if filename:
            self.path.setText(filename)
            self.check()

    def choose_sample(self, index):
        if SAMPLES[index][1] in ("04_pbr_textures.usda", "05_pbr_separate_textures.usda"):
            self.pbr.setChecked(True)
        self.path.setText(str(BASE / "usd_learning" / SAMPLES[index][1]))
        self.check()

    def display_inspection(self, report):
        self.inspection = report
        source = report.get("ue_source", {})
        if source.get("status") == "verified":
            mode = source.get("scope", {}).get("mode", "explicit")
            mode_label = {
                "selection": "选中对象",
                "loaded": "当前已加载场景",
                "explicit": "显式对象列表",
            }.get(mode, mode)
            lines = [
                "[已核对] USD 文件校验与 UE 来源报告一致。",
                "引擎：" + source["engine_version"],
                "时间 UTC：" + source["created_utc"],
                "范围：" + mode_label,
                "导出 {} Actor / {} 组件 / {} 摆放 / {} 实例 / {} 份资源 / {} 跳过项".format(
                    source["actor_count"],
                    source.get("component_count", 0),
                    source.get("placement_count", source["actor_count"]),
                    source.get("instance_count", 0),
                    source["asset_count"],
                    source["skipped_count"],
                ),
                "几何来源：" + source["geometry_source"],
                "报告：" + source["manifest"],
            ]
            options = source.get("options")
            if options:
                lines += [
                    "[精度设置] 请求 LOD{} · {} · 缺失 LOD 时{}".format(
                        options["lod_index"],
                        options["asset_format"].upper(),
                        "退回 LOD0" if options["missing_lod"] == "lod0" else "跳过",
                    )
                ]
                metrics = source["metrics"]
                lines += [
                    "[导出统计] USD {:.2f} MB / {:.2f} 秒（不含报告写入）".format(
                        metrics["usd_bytes"] / 1048576, metrics["usd_export_seconds"]
                    )
                ]
            stats = source.get("statistics", {})
            if "unique_triangles" in stats:
                lines += [
                    "[几何三角面] 唯一资源 {:,} / 全部摆放等效 {:,}".format(
                        stats["unique_triangles"], stats["placed_triangles"]
                    )
                ]
            lines += ["\n[提示] " + s for s in source["warnings"]]
            lines += [
                "\n[摄影机] {} · {:.6g} mm · 有效画幅 {:.6g} × {:.6g} mm\n{}".format(
                    c["label"],
                    c["focal_length_mm"],
                    c["aperture_width_mm"],
                    c["aperture_height_mm"],
                    c["prim"],
                )
                for c in source.get("cameras", [])
            ]
            if options:
                from ue_maya_bridge.usd_options import choice_label

                lines += [
                    "\n[资源精度] {}\n{} · {:,} 三角面".format(
                        key, choice_label(item["geometry_choice"]), item["triangles"]
                    )
                    for key, item in stats["assets"].items()
                ]
            lines += [
                "\n[跳过] {}\n{}\n{}".format(
                    item.get("label", ""), item.get("actor", ""), "；".join(item["reasons"])
                )
                for item in source["skipped"]
            ]
            lines += [
                "\n[摆放] {}\n{}\n{} · 实例 {} → {}".format(
                    item["label"],
                    item["actor"],
                    item.get("component", "旧版无组件记录"),
                    item.get("instance_index"),
                    item["prim"],
                )
                for item in source["placements"][:1000]
            ]
            if len(source["placements"]) > 1000:
                lines += ["\n仅显示前 1000 条摆放；完整记录请保存报告。"]
            self.source.setPlainText("\n".join(lines))
        elif source.get("status") == "invalid":
            self.source.setPlainText(
                "[UE 来源报告未通过检查]\n" + "\n".join(source.get("errors", []))
            )
        else:
            self.source.setPlainText("无 UE 来源报告。仍可按普通 USD 文件检查和载入。")
        self.env_label.setText(
            "Maya {}  ·  Maya USD {}  ·  USD SDK {}".format(
                report["maya"], report["maya_usd"], ".".join(map(str, report["usd_sdk"]))
            )
        )
        values = {
            "units": "{} 米/单位 · {}-up".format(report["meters_per_unit"], report["up_axis"]),
            "meshes": "{} 个 Mesh 路径 / {} 个实例根 / {} 个摄影机".format(
                report["meshes"], report["instances"], report["camera_count"]
            ),
            "materials": "{} 个材质 / {} 个面子集".format(
                len(report["materials"]), report["face_subsets"]
            ),
            "layers": "{} 层 / {} 个缺失资产".format(
                len(report["layers"]), len(report["missing_assets"])
            ),
        }
        for key, value in values.items():
            self.summary_labels[key].setText(value)
        self.materials.setRowCount(len(report["materials"]))
        for row, material in enumerate(report["materials"]):
            roughness = material["inputs"].get("roughness", {})
            rough_text = (
                "连接" if roughness.get("connected") else str(roughness.get("value", "默认"))
            )
            if isinstance(roughness.get("value"), float):
                rough_text = "{:.4g}".format(roughness["value"])
            status = (
                "未绑定"
                if not material["bound"]
                else ("需处理" if material["issues"] else "可转换")
            )
            pbr_issues = [
                e for e in report.get("pbr_errors", []) if e.startswith(material["path"] + "：")
            ]
            pbr_status = (
                "未绑定" if not material["bound"] else ("需处理" if pbr_issues else "可转换")
            )
            for col, value in enumerate(
                (
                    material["path"],
                    material["shader_id"] or "无通用输出",
                    rough_text,
                    status,
                    pbr_status,
                )
            ):
                item = QtWidgets.QTableWidgetItem(value)
                item.setToolTip("\n".join(pbr_issues if col == 4 else material["issues"]) or value)
                self.materials.setItem(row, col, item)
        lines = ["[文件] " + report["path"]]
        lines += ["[阻止载入] " + s for s in report["errors"]]
        lines += ["[Phong 限制] " + s for s in report["native_errors"]]
        lines += ["[PBR 限制] " + s for s in report.get("pbr_errors", [])]
        lines += ["[PBR 提示] " + s for s in report.get("pbr_warnings", [])]
        lines += ["[提示] " + s for s in report["warnings"]]
        lines += ["[缺失资产] " + s for s in report["missing_assets"]]
        lines += ["[依赖层] " + s for s in report["layers"]]
        self.log.setPlainText("\n".join(lines))

    def check(self):
        try:
            with self.working("正在检查文件、依赖和材质…"):
                report = core.inspect_file(self.path.text().strip())
                self.display_inspection(report)
                if report["errors"]:
                    self.status.setText("检查完成 · 存在阻止载入的问题，请看详情。")
                    self.tabs.setCurrentWidget(self.log)
                elif self.pbr.isChecked() and report.get("pbr_errors"):
                    self.status.setText("检查完成 · PBR 转换存在限制，请查看详情。")
                elif self.phong.isChecked() and report["native_errors"]:
                    self.status.setText("检查完成 · Phong 转换存在限制；可查看 PBR／Stage 路线。")
                else:
                    self.status.setText(
                        "检查完成 · {} 个模型，{} 个材质。".format(
                            report["meshes"], len(report["materials"])
                        )
                    )
        except Exception as exc:
            self.error(exc)

    def load(self):
        try:
            with self.working("正在加载插件与场景；若 Maya 弹出首次授权提示，请先核对并处理…"):
                mode = (
                    "stage"
                    if self.stage.isChecked()
                    else ("pbr" if self.pbr.isChecked() else "phong")
                )
                result = core.load_file(
                    self.path.text().strip(),
                    mode,
                    self.allow_missing.isChecked(),
                    self.flip_normal_y.isChecked() if mode == "pbr" else False,
                    self.texture_directory.text().strip() if mode == "pbr" else "",
                )
                self.result = result
                self.display_inspection(result["inspection"])
                self.display_cameras(result.get("cameras", []))
                self.summary_labels["loaded"].setText(result["root"])
                self.log.appendPlainText("\n[载入完成] " + result["root"])
                for material in result["phongs"]:
                    self.log.appendPlainText(
                        "[Phong] {} · cosinePower={:.6g}".format(
                            material["node"], material["cosine_power"]
                        )
                    )
                for material in result.get("pbr_materials", []):
                    self.log.appendPlainText(
                        "[PBR Standard Surface] {}\n{}".format(
                            material["node"], material["usd_material"] or "默认灰色"
                        )
                    )
                for texture in result["textures"]:
                    self.log.appendPlainText(
                        "[贴图 {}] {} · {}\n{}".format(
                            texture.get("usage", ""),
                            texture["node"],
                            texture["color_space"],
                            texture["path"],
                        )
                    )
                for record in result.get("separated_textures", []):
                    self.log.appendPlainText(
                        "[独立 {}] {} 通道 → {}\n{}".format(
                            record["usage"],
                            record["source_channel"].upper(),
                            record["path"],
                            (
                                "复用已校验文件"
                                if record["reused"]
                                else "{} 位灰度 PNG".format(record["bits"])
                            ),
                        )
                    )
                if result.get("separated_textures"):
                    self.log.appendPlainText(
                        "[提示] 撤销只移除场景节点，生成的独立贴图文件会保留，供重做和保存后的场景使用。"
                    )
                for warning in result["warnings"]:
                    self.log.appendPlainText("[提示] " + warning)
                if mode == "stage":
                    self.status.setText(
                        "USD 场景已载入 · {} 个模型 / {} 个静态摄影机副本".format(
                            result["inspection"]["meshes"], result["native_cameras"]
                        )
                    )
                else:
                    self.status.setText(
                        "载入完成{} · {} 个网格摆放 / {} 个 Shape / {} 个 {} / {} 个摄影机".format(
                            "（含提示）" if result["warnings"] else "",
                            result.get("native_mesh_paths", result["native_meshes"]),
                            result["native_meshes"],
                            len(result.get("materials", result["phongs"])),
                            "PBR 材质" if mode == "pbr" else "Phong",
                            result["native_cameras"],
                        )
                    )
                self.tabs.setCurrentWidget(self.log)
        except Exception as exc:
            self.error(exc)

    def select(self, materials):
        try:
            if self.result:
                core.select_result(self.result, materials)
        except Exception as exc:
            self.error(exc)

    def browse_texture_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "选择独立通道贴图输出目录",
            self.texture_directory.text() or str(Path(self.path.text()).parent),
        )
        if directory:
            self.texture_directory.setText(directory)

    def hypershade(self):
        try:
            import maya.mel as mel

            mel.eval("HypershadeWindow;")
        except Exception as exc:
            self.error(exc)

    def export_report(self):
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "保存检查报告", "usd_report.json", "JSON 报告 (*.json)"
        )
        if filename:
            try:
                core.save_report(
                    filename, {"inspection": self.inspection, "last_import": self.result}
                )
                self.status.setText("报告已保存：" + filename)
            except Exception as exc:
                self.error(exc)


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
    parent = wrapInstance(int(pointer), QtWidgets.QWidget) if pointer else None
    _WINDOW = Window(parent)
    _WINDOW.show()
    return _WINDOW
