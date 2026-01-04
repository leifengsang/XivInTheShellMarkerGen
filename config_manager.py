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
            except:
                return {}
        return {}

    @staticmethod
    def save_all_config(data):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置失败: {e}")

    @staticmethod
    def get_zone_config(zone_id):
        all_data = ConfigManager.load_all_config()
        # JSON key 必须是字符串
        return all_data.get(str(zone_id), {})

    @staticmethod
    def update_zone_config(zone_id, new_zone_data):
        # 1. 加载所有配置
        all_data = ConfigManager.load_all_config()
        z_key = str(zone_id)
        
        existing_zone_data = all_data.get(z_key, {})
        existing_skills = existing_zone_data.get('skills', {})
        
        new_skills = new_zone_data.get('skills', {})
        existing_skills.update(new_skills)
        existing_zone_data.update(new_zone_data)
        existing_zone_data['skills'] = existing_skills
        
        all_data[z_key] = existing_zone_data
        ConfigManager.save_all_config(all_data)

    @staticmethod
    def get_api_key():
        """读取全局缓存的 API Key"""
        all_data = ConfigManager.load_all_config()
        return all_data.get("GLOBAL_API_KEY", "")

    @staticmethod
    def save_api_key(api_key):
        """保存 API Key 到全局配置"""
        all_data = ConfigManager.load_all_config()
        if api_key and all_data.get("GLOBAL_API_KEY") != api_key:
            all_data["GLOBAL_API_KEY"] = api_key
            ConfigManager.save_all_config(all_data)