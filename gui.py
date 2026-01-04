import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json

# 导入拆分后的模块
from config_manager import ConfigManager
from markergen import fetch_log_data, generate_final_json

class SkillConfigDialog(tk.Toplevel):
    def __init__(self, parent, skill_list, zone_id, zone_name):
        super().__init__(parent)
        self.zone_id = zone_id
        self.title(f"导出配置 - {zone_name} (ZoneID: {zone_id})")
        self.geometry("600x600")
        self.result = None 
        self.skill_vars = {}

        # 1. 读取该 Zone 的本地配置
        self.saved_config = ConfigManager.get_zone_config(self.zone_id)
        
        # 获取保存的值，如果不存在则使用默认值
        default_interval = self.saved_config.get('min_interval', 1000)
        default_tracks = self.saved_config.get('max_tracks', 20)
        saved_skills = self.saved_config.get('skills', {}) # 格式: {'技能名': {'export': True, 'rename': 'xxx'}}

        self.transient(parent)
        self.grab_set()
        
        # --- 顶部：通用设置 ---
        top_frame = tk.LabelFrame(self, text="通用设置", padx=10, pady=10)
        top_frame.pack(fill='x', padx=10, pady=5)

        tk.Label(top_frame, text="最小间隔(ms):").grid(row=0, column=0, padx=5)
        self.interval_entry = tk.Entry(top_frame, width=10)
        self.interval_entry.insert(0, str(default_interval)) # 填入保存值
        self.interval_entry.grid(row=0, column=1, padx=5)

        tk.Label(top_frame, text="最大轨道数(Max Tracks):").grid(row=0, column=2, padx=5)
        self.tracks_entry = tk.Entry(top_frame, width=10)
        self.tracks_entry.insert(0, str(default_tracks)) # 填入保存值
        self.tracks_entry.grid(row=0, column=3, padx=5)

        # --- 中部：技能列表 ---
        list_frame = tk.LabelFrame(self, text="技能筛选与重命名", padx=5, pady=5)
        list_frame.pack(fill='both', expand=True, padx=10, pady=5)

        canvas = tk.Canvas(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        sorted_skills = sorted(list(skill_list))
        
        tk.Label(self.scrollable_frame, text="导出?", font=('bold')).grid(row=0, column=0, padx=5, pady=5)
        tk.Label(self.scrollable_frame, text="原名", font=('bold')).grid(row=0, column=1, padx=5, pady=5, sticky='w')
        tk.Label(self.scrollable_frame, text="导出名称 (可编辑)", font=('bold')).grid(row=0, column=2, padx=5, pady=5, sticky='w')

        for idx, skill_name in enumerate(sorted_skills):
            row = idx + 1
            
            # 从配置中读取默认状态
            skill_conf = saved_skills.get(skill_name, {})
            # 默认勾选，默认显示原名
            default_check = skill_conf.get('export', True)
            default_rename = skill_conf.get('rename', skill_name)

            check_var = tk.BooleanVar(value=default_check)
            rename_var = tk.StringVar(value=default_rename)
            
            self.skill_vars[skill_name] = {
                'check': check_var,
                'rename': rename_var
            }

            ck = tk.Checkbutton(self.scrollable_frame, variable=check_var)
            ck.grid(row=row, column=0, padx=5)

            lbl = tk.Label(self.scrollable_frame, text=skill_name)
            lbl.grid(row=row, column=1, padx=10, sticky='w')

            entry = tk.Entry(self.scrollable_frame, textvariable=rename_var, width=30)
            entry.grid(row=row, column=2, padx=10, sticky='w')

        # --- 底部：按钮 ---
        btn_frame = tk.Frame(self, pady=10)
        btn_frame.pack(fill='x')
        
        tk.Button(btn_frame, text="确定并保存配置", command=self.on_ok, bg="#dddddd", width=20).pack(side='right', padx=20)
        tk.Button(btn_frame, text="取消", command=self.destroy, width=15).pack(side='right', padx=20)

    def on_ok(self):
        try:
            min_interval = int(self.interval_entry.get())
            max_tracks = int(self.tracks_entry.get())
        except ValueError:
            messagebox.showerror("错误", "时间间隔和轨道数必须是整数")
            return

        filter_map = {}
        skills_config_to_save = {}

        for original_name, vars in self.skill_vars.items():
            is_checked = vars['check'].get()
            rename_val = vars['rename'].get().strip()
            
            # 1. 准备保存到文件的数据
            skills_config_to_save[original_name] = {
                'export': is_checked,
                'rename': rename_val
            }

            # 2. 准备传给生成器的数据
            if is_checked:
                filter_map[original_name] = rename_val if rename_val else original_name

        # --- 保存配置到本地 ---
        new_zone_config = {
            'min_interval': min_interval,
            'max_tracks': max_tracks,
            'skills': skills_config_to_save
        }
        ConfigManager.update_zone_config(self.zone_id, new_zone_config)

        self.result = {
            'min_interval': min_interval,
            'max_tracks': max_tracks,
            'filter_map': filter_map
        }
        self.destroy()

class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FFLogs Timeline Generator")
        self.geometry("500x380")
        
        self.generated_data = None 

        self.create_widgets()

    def create_widgets(self):
        padding = {'padx': 10, 'pady': 5}

        tk.Label(self, text="FFLogs URL (带 fight id):").pack(anchor='w', **padding)
        self.url_entry = tk.Entry(self, width=60)
        self.url_entry.pack(fill='x', **padding)

        tk.Label(self, text="FFLogs API Key (v1):").pack(anchor='w', **padding)
        self.api_entry = tk.Entry(self, width=60) 
        self.api_entry.pack(fill='x', **padding)

        saved_key = ConfigManager.get_api_key()
        if saved_key:
            self.api_entry.insert(0, saved_key)
            
        self.translate_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="请求时自动翻译 (&translate=true)", variable=self.translate_var).pack(anchor='w', **padding)

        self.btn_generate = tk.Button(self, text="获取数据并配置...", command=self.on_process_start, bg="#dddddd")
        self.btn_generate.pack(pady=15)

        self.status_label = tk.Label(self, text="准备就绪", fg="gray")
        self.status_label.pack()

        ttk.Separator(self, orient='horizontal').pack(fill='x', pady=10)

        btn_frame = tk.Frame(self)
        btn_frame.pack(fill='x', pady=10)

        self.btn_copy = tk.Button(btn_frame, text="复制 JSON", command=self.on_copy, state='disabled')
        self.btn_copy.pack(side='left', expand=True, padx=5)

        self.btn_save = tk.Button(btn_frame, text="另存为文件...", command=self.on_save, state='disabled')
        self.btn_save.pack(side='right', expand=True, padx=5)

    def on_process_start(self):
        url = self.url_entry.get().strip()
        api_key = self.api_entry.get().strip()

        if not url or not api_key:
            messagebox.showwarning("提示", "请输入 URL 和 API Key")
            return
        ConfigManager.save_api_key(api_key)
        self.status_label.config(text="正在从 FFLogs 下载数据...", fg="blue")
        self.update()

        cast_list, untarget_list, fight, msg = fetch_log_data(url, api_key, self.translate_var.get())

        if cast_list is None:
            self.status_label.config(text=f"下载失败: {msg}", fg="red")
            messagebox.showerror("错误", msg)
            return

        self.status_label.config(text="数据获取成功，等待配置...", fg="orange")
        
        unique_skills = set(marker.desc for marker in cast_list)
        
        dialog = SkillConfigDialog(self, unique_skills, fight.zone_id, fight.zone_name)
        self.wait_window(dialog) 

        if dialog.result is None:
            self.status_label.config(text="用户取消了操作", fg="gray")
            return

        self.status_label.config(text="正在处理...", fg="blue")
        json_obj = generate_final_json(cast_list, untarget_list, dialog.result)

        self.generated_data = json.dumps(json_obj, ensure_ascii=False, indent=2)
        self.status_label.config(text=f"生成成功! 包含 {len(json_obj['tracks'])} 个轨道", fg="green")
        self.btn_copy.config(state='normal')
        self.btn_save.config(state='normal')

    def on_copy(self):
        if self.generated_data:
            self.clipboard_clear()
            self.clipboard_append(self.generated_data)
            self.update() 
            messagebox.showinfo("成功", "JSON 已复制到剪贴板")

    def on_save(self):
        if not self.generated_data: return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            initialfile="timeline.json"
        )
        if filepath:
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(self.generated_data)
                messagebox.showinfo("成功", f"文件已保存至:\n{filepath}")
            except Exception as e:
                messagebox.showerror("保存失败", str(e))


if __name__ == '__main__':
    app = Application()
    app.mainloop()