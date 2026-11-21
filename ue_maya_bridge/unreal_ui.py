"""Windows Unreal export panel using the engine's bundled tkinter, no pip."""

import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from . import unreal_usd
from .usd_options import normalize_options, choice_label

_WINDOW = None


class Window:
    def __init__(self):
        import unreal

        self.root = tk.Tk()
        self.root.title("UE → Maya USD · Previs 0.5.0")
        self.root.geometry("930x820")
        self.root.minsize(800, 710)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.closed, self.busy, self.package = False, False, None
        self.inspection = None
        self.tick = None
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            ".", font=("Microsoft YaHei UI", 10), background="#29323b", foreground="#e8edf2"
        )
        style.configure("TButton", padding=(12, 7))
        style.configure("Treeview", background="#202831", fieldbackground="#202831", rowheight=28)
        style.map("Treeview", background=[("selected", "#247a71")])
        style.configure("TEntry", fieldbackground="#202831", foreground="#e8edf2")
        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Unreal → USD → Maya", font=("Microsoft YaHei UI", 19, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            frame,
            text="静态组件 / Blueprint / ISM / HISM · 厘米 / Y-up · 可选渲染 LOD / Nanite 代理",
        ).pack(anchor="w", pady=(6, 12))
        self.scope = tk.StringVar(self.root, "selection")
        scopes = ttk.Frame(frame)
        scopes.pack(fill="x")
        self.selected_radio = ttk.Radiobutton(
            scopes,
            text="选中对象",
            variable=self.scope,
            value="selection",
            command=self.scope_changed,
        )
        self.loaded_radio = ttk.Radiobutton(
            scopes,
            text="当前已加载场景",
            variable=self.scope,
            value="loaded",
            command=self.scope_changed,
        )
        self.selected_radio.pack(side="left", padx=(0, 24))
        self.loaded_radio.pack(side="left")
        ttk.Label(
            frame,
            text="不自动展开子对象；已加载场景不包含未加载的区块、流送关卡或数据层。",
            wraplength=790,
        ).pack(anchor="w", pady=(6, 12))
        quality = ttk.LabelFrame(frame, text="模型精度与几何格式", padding=8)
        quality.pack(fill="x", pady=(0, 10))
        self.nanite = tk.BooleanVar(self.root, False)
        self.nanite_check = ttk.Checkbutton(
            quality, text="允许 Nanite 快速代理（近似外形，非完整源网格）", variable=self.nanite
        )
        self.nanite_check.grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))
        self.include_cameras = tk.BooleanVar(self.root, True)
        self.camera_check = ttk.Checkbutton(
            quality, text="包含静态摄影机（当前已求值状态）", variable=self.include_cameras
        )
        self.camera_check.grid(row=1, column=0, columnspan=6, sticky="w", pady=(0, 6))
        ttk.Label(quality, text="渲染 LOD：").grid(row=2, column=0, sticky="w")
        self.lod = tk.StringVar(self.root, "0")
        self.lod_spin = ttk.Spinbox(quality, from_=0, to=7, textvariable=self.lod, width=5)
        self.lod_spin.grid(row=2, column=1, sticky="w")
        ttk.Label(quality, text="缺少该 LOD：").grid(row=2, column=2, padx=(12, 0))
        self.missing_lod = tk.StringVar(self.root, "跳过该资源")
        self.missing_combo = ttk.Combobox(
            quality,
            textvariable=self.missing_lod,
            values=("跳过该资源", "退回 LOD0"),
            state="readonly",
            width=13,
        )
        self.missing_combo.grid(row=2, column=3)
        ttk.Label(quality, text="资源格式：").grid(row=2, column=4, padx=(12, 0))
        self.asset_format = tk.StringVar(self.root, "USDC")
        self.format_combo = ttk.Combobox(
            quality,
            textvariable=self.asset_format,
            values=("USDC", "USDA"),
            state="readonly",
            width=9,
        )
        self.format_combo.grid(row=2, column=5)
        ttk.Label(
            quality,
            text="使用工具指定的 LOD，不跟随视距或组件强制 LOD；不会生成 LOD 或修改资产。",
            wraplength=820,
        ).grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="输出目录：").pack(side="left")
        default = (
            Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_saved_dir()))
            / "UEToMayaUSD"
        )
        self.output = tk.StringVar(self.root, str(default))
        self.path_entry = ttk.Entry(row, textvariable=self.output)
        self.path_entry.pack(side="left", fill="x", expand=True)
        self.browse_button = ttk.Button(row, text="浏览…", command=self.browse)
        self.browse_button.pack(side="left", padx=(8, 0))
        actions = ttk.Frame(frame)
        actions.pack(fill="x", pady=12)
        self.check_button = ttk.Button(actions, text="检查当前范围", command=self.check)
        self.export_button = ttk.Button(actions, text="导出 USD 包", command=self.export)
        self.check_button.pack(side="left")
        self.export_button.pack(side="left", padx=8)
        self.locate_button = ttk.Button(
            actions, text="定位列表项", command=self.locate, state="disabled"
        )
        self.locate_button.pack(side="left", padx=8)
        self.summary = tk.StringVar(self.root, "等待检查 · 导出前会重新读取当前范围")
        ttk.Label(frame, textvariable=self.summary, wraplength=800).pack(anchor="w", pady=(0, 8))
        columns = ("label", "type", "status", "reason")
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_frame, columns=columns, show="headings", height=8)
        for name, label, width in zip(
            columns, ("Actor / 组件 / 实例", "类型", "状态", "说明"), (240, 160, 85, 310)
        ):
            self.table.heading(name, text=label)
            self.table.column(name, width=width, minwidth=60, stretch=True)
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table.bind("<<TreeviewSelect>>", self.describe_row)
        self.row_detail = tk.StringVar(self.root, "选中列表行可查看完整来源或跳过原因。")
        ttk.Label(frame, textvariable=self.row_detail, wraplength=790).pack(anchor="w", pady=8)
        self.bar = ttk.Progressbar(frame, mode="determinate")
        self.bar.pack(fill="x")
        self.status = tk.StringVar(self.root, "就绪")
        ttk.Label(frame, textvariable=self.status, wraplength=790).pack(anchor="w", pady=8)
        self.result_path = tk.StringVar(
            self.root, "导出后在 Maya 中打开 scene.usda；移动时保留整个文件夹。"
        )
        self.result_entry = ttk.Entry(frame, textvariable=self.result_path, state="readonly")
        self.result_entry.pack(fill="x")
        result_actions = ttk.Frame(frame)
        result_actions.pack(fill="x", pady=(8, 0))
        self.open_button = ttk.Button(
            result_actions, text="打开输出文件夹", command=self.open_folder, state="disabled"
        )
        self.copy_button = ttk.Button(
            result_actions, text="复制根 USD 路径", command=self.copy_path, state="disabled"
        )
        self.open_button.pack(side="left")
        self.copy_button.pack(side="left", padx=8)
        self.rows = {}
        for variable in (
            self.nanite,
            self.lod,
            self.missing_lod,
            self.asset_format,
            self.include_cameras,
        ):
            variable.trace_add("write", lambda *_: self.scope_changed())
        self.root.update_idletasks()

    def read_options(self):
        return normalize_options(
            {
                "nanite_mode": "proxy" if self.nanite.get() else "skip",
                "lod_index": int(self.lod.get()),
                "missing_lod": "lod0" if self.missing_lod.get() == "退回 LOD0" else "skip",
                "asset_format": self.asset_format.get().lower(),
                "include_cameras": self.include_cameras.get(),
            }
        )

    def describe_row(self, event=None):
        selection = self.table.selection()
        if selection:
            item = self.rows[selection[0]]
            detail = "{}\n{}{}".format(
                item["actor"],
                item.get("component") or "",
                (
                    " · 实例 {}".format(item["instance_index"])
                    if item.get("instance_index") is not None
                    else ""
                ),
            )
            if "mesh" in item and self.inspection:
                stat = self.inspection["statistics"]["assets"][item["mesh"]]
                detail += "\n{} · {} · {:,} 三角面 / {} 个 LOD".format(
                    item["mesh"],
                    choice_label(item["geometry_choice"]),
                    stat["triangles"],
                    stat["lod_count"],
                )
                forced = item.get("component_forced_lod", 0)
                if forced and forced - 1 != item["geometry_choice"]["effective_lod"]:
                    detail += "\n组件强制 LOD{}，本次按工具设置覆盖。".format(forced - 1)
            if item.get("reasons"):
                detail += "\n" + "；".join(item["reasons"])
            if "focal_length_mm" in item:
                hint = item["frame_hint"]
                detail += "\n摄影机 {:.4g} mm · 有效画幅 {:.4g} × {:.4g} mm · 建议 {} × {}".format(
                    item["focal_length_mm"],
                    item["aperture_width_mm"],
                    item["aperture_height_mm"],
                    hint["width"],
                    hint["height"],
                )
            self.row_detail.set(detail)
        self.locate_button.configure(state="normal" if selection and not self.busy else "disabled")

    def locate(self):
        if self.busy or not self.table.selection():
            return
        try:
            item = self.rows[self.table.selection()[0]]
            result = unreal_usd.locate_item(item)
            self.status.set("已定位目标；当前选区已改变。选中对象模式会按新选区导出。")
            return result
        except Exception as error:
            self.fail(error)

    def scope_changed(self):
        self.inspection = None
        self.table.delete(*self.table.get_children())
        self.rows.clear()
        self.locate_button.configure(state="disabled")
        self.summary.set("范围已更改，请重新检查；导出也会重新读取。")

    def browse(self):
        directory = filedialog.askdirectory(
            parent=self.root,
            title="选择 USD 包保存目录",
            initialdir=self.output.get(),
            mustexist=False,
        )
        if directory:
            self.output.set(directory)

    def set_busy(self, state):
        self.busy = state
        for widget in (
            self.check_button,
            self.export_button,
            self.browse_button,
            self.path_entry,
            self.selected_radio,
            self.loaded_radio,
            self.nanite_check,
            self.lod_spin,
            self.camera_check,
        ):
            widget.configure(state="disabled" if state else "normal")
        for widget in (self.missing_combo, self.format_combo):
            widget.configure(state="disabled" if state else "readonly")
        for widget in (self.open_button, self.copy_button):
            widget.configure(state="normal" if self.package and not state else "disabled")
        self.locate_button.configure(
            state="normal" if self.table.selection() and not state else "disabled"
        )
        self.root.update_idletasks()

    def display(self, report):
        self.inspection = report
        self.table.delete(*self.table.get_children())
        self.rows.clear()
        # Keep huge instance sets from filling the UI; export still uses all.
        for item in report["accepted"][:1000]:
            label = item["label"] + " / " + item["component_name"]
            if item["instance_index"] is not None:
                label += " / " + str(item["instance_index"])
            row = self.table.insert(
                "",
                "end",
                values=(
                    label,
                    item["type"],
                    "代理" if item["geometry_choice"]["nanite"] else "可导出",
                    choice_label(item["geometry_choice"]),
                ),
            )
            self.rows[row] = item
        for item in report["skipped"][:1000]:
            reason = "；".join(item["reasons"])
            row = self.table.insert(
                "", "end", values=(item["label"], item.get("type", "不支持"), "跳过", reason)
            )
            self.rows[row] = item
        for item in report.get("cameras", [])[:1000]:
            row = self.table.insert(
                "",
                "end",
                values=(
                    item["label"],
                    item["camera_type"],
                    "摄影机",
                    "{:.4g} mm / {:.4g}:1".format(item["focal_length_mm"], item["aspect_ratio"]),
                ),
            )
            self.rows[row] = item
        stats = report["statistics"]
        self.summary.set(
            "扫描 {} Actor · 导出 {} Actor / {} 网格组件 / {} 摆放 · 实例 {} · 唯一资源 {} · 跳过项 {}\n所选几何三角面：唯一 {:,} / 全部摆放等效 {:,} · Nanite 代理 {} 摆放 / LOD 回退 {} 资源 · 摄影机 {}".format(
                report["scanned"],
                report["actor_count"],
                report["component_count"],
                report["accepted_count"],
                report["instance_count"],
                report["asset_count"],
                len(report["skipped"]),
                stats["unique_triangles"],
                stats["placed_triangles"],
                stats["proxy_placements"],
                stats["lod_fallback_assets"],
                report.get("camera_count", 0),
            )
        )
        if stats["placed_triangles"] > 10_000_000:
            self.row_detail.set(
                "场景摆放后的等效三角面超过一千万；建议先使用 USD Stage，并检查实际内存与视口表现。"
            )

    def fail(self, error):
        import unreal

        self.status.set("未完成：" + str(error))
        unreal.log_error("UE → Maya USD: " + str(error))

    def check(self):
        if self.busy:
            return
        self.set_busy(True)
        self.inspection = None
        try:
            self.display(unreal_usd.inspect_scope(self.scope.get(), self.read_options()))
            self.status.set(
                "检查完成。"
                if self.inspection["accepted_count"] or self.inspection.get("camera_count")
                else "没有可导出的对象，请查看范围及跳过原因。"
            )
        except Exception as error:
            self.fail(error)
        finally:
            self.set_busy(False)

    def progress(self, completed, total, message):
        self.bar.configure(maximum=total, value=completed)
        self.status.set("{}/{} · {}".format(completed, total, message))
        # Do not dispatch input or re-enter Unreal while its exporter is active.
        self.root.update_idletasks()

    def export(self):
        if self.busy:
            return
        self.package = None
        self.result_path.set("正在导出；成功后显示新的根 USD 路径。")
        self.bar.configure(value=0)
        self.set_busy(True)
        try:
            if not self.output.get().strip():
                raise ValueError("请选择输出目录。")
            options = self.read_options()
            report = unreal_usd.inspect_scope(self.scope.get(), options)
            self.display(report)
            folder = unreal_usd.export_scope(
                self.scope.get(), self.output.get().strip(), self.progress, options
            )
            manifest = json.loads((Path(folder) / "usd_manifest.json").read_text(encoding="utf-8"))
            self.package = folder
            self.result_path.set(str(Path(folder) / "scene.usda"))
            self.status.set(
                "{}：{} Actor / {} 摆放 / {} 资源 / {} 摄影机，跳过项 {} · USD {:.2f} MB / {:.2f} 秒。".format(
                    "部分完成" if manifest["skipped"] else "导出完成",
                    len(manifest["actors"]),
                    len(manifest["placements"]),
                    len(manifest["assets"]),
                    len(manifest.get("cameras", [])),
                    len(manifest["skipped"]),
                    manifest["metrics"]["usd_bytes"] / 1048576,
                    manifest["metrics"]["usd_export_seconds"],
                )
            )
        except Exception as error:
            self.result_path.set("本次导出未完成；诊断信息请查看 Unreal Output Log 或失败目录。")
            self.fail(error)
        finally:
            self.set_busy(False)

    def open_folder(self):
        if self.package:
            os.startfile(self.package)

    def copy_path(self):
        if self.package:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(Path(self.package) / "scene.usda"))

    def pump(self, delta_time=0):
        if self.closed:
            return
        try:
            self.root.update()
        except tk.TclError:
            self.close()

    def close(self):
        if self.busy or self.closed:
            return
        import unreal

        self.closed = True
        if self.tick is not None:
            unreal.unregister_slate_post_tick_callback(self.tick)
            self.tick = None
        self.root.destroy()


def show():
    global _WINDOW
    import unreal

    unreal_usd._ready()
    if _WINDOW is not None and not _WINDOW.closed:
        _WINDOW.root.deiconify()
        _WINDOW.root.lift()
        return _WINDOW
    _WINDOW = Window()
    _WINDOW.tick = unreal.register_slate_post_tick_callback(_WINDOW.pump)
    # Parenting is cosmetic; failure must not prevent a usable export panel.
    try:
        unreal.parent_external_window_to_slate(
            _WINDOW.root.winfo_id(), unreal.SlateParentWindowSearchMethod.MAIN_WINDOW
        )
    except Exception as error:
        unreal.log_warning("USD 面板以独立窗口显示：" + str(error))
    return _WINDOW
