import json
import os

CONFIG_FILE = "timeline_config.json"

class ConfigManager:
    @staticmethod
    def load_all_config():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                # 读取错误可以接受（返回默认空配置），但最好抛出让上层知道文件坏了
                # 这里为了稳健，如果文件坏了就抛出异常，让GUI决定是否重置
                raise Exception(f"配置文件损坏: {e}")
        return {}

    @staticmethod
    def save_all_config(data):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 不要 print，抛出给 GUI 弹窗
            raise Exception(f"无法写入配置文件: {e}")

    # --- 全局设置 (Interval, Tracks) ---
    @staticmethod
    def get_global_settings():
        """读取全局通用的设置 (min_interval, max_tracks)"""
        all_data = ConfigManager.load_all_config()
        return all_data.get("GLOBAL_SETTINGS", {
            "min_interval": 1000,
            "max_tracks": 20
        })

    @staticmethod
    def save_global_settings(min_interval, max_tracks):
        """保存全局设置"""
        all_data = ConfigManager.load_all_config()
        all_data["GLOBAL_SETTINGS"] = {
            "min_interval": int(min_interval),
            "max_tracks": int(max_tracks)
        }
        ConfigManager.save_all_config(all_data)
        
    @staticmethod
    def get_zone_config(zone_id):
        all_data = ConfigManager.load_all_config()
        return all_data.get(str(zone_id), {})

    @staticmethod
    def update_zone_skills(zone_id, new_skills_data):
        """更新特定区域的技能配置 (不再保存 interval/tracks)"""
        all_data = ConfigManager.load_all_config()
        z_key = str(zone_id)
        
        existing_zone_data = all_data.get(z_key, {})
        existing_skills = existing_zone_data.get('skills', {})
        
        # 合并技能配置
        existing_skills.update(new_skills_data)
        
        existing_zone_data['skills'] = existing_skills
        all_data[z_key] = existing_zone_data
        
        ConfigManager.save_all_config(all_data)

    @staticmethod
    def get_api_key():
        all_data = ConfigManager.load_all_config()
        return all_data.get("GLOBAL_API_KEY", "")

    @staticmethod
    def save_api_key(api_key):
        all_data = ConfigManager.load_all_config()
        if api_key and all_data.get("GLOBAL_API_KEY") != api_key:
            all_data["GLOBAL_API_KEY"] = api_key
            ConfigManager.save_all_config(all_data)
