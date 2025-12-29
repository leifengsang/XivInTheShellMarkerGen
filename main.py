import json
import os

import requests

FIGHTS_URL_PREFIX = "https://cn.fflogs.com/v1/report/fights/"
CASTS_URL_PREFIX = "https://cn.fflogs.com/v1/report/events/casts/"
DAMAGE_TAKEN_URL_PREFIX = "https://cn.fflogs.com/v1/report/events/damage-taken/"
SUMMARY_URL_PREFIX = "https://cn.fflogs.com/v1/report/events/summary/"


class Config:
    def __init__(self, cast_name_list, damage_name_list, convert_dic, logs_id, fight_id, api_key, file_name):
        self.cast_name_list = cast_name_list
        self.damage_name_list = damage_name_list
        self.convert_dic = convert_dic
        self.logs_id = logs_id
        self.fight_id = fight_id
        self.api_key = api_key
        self.file_name = file_name

    def __repr__(self):
        return str(self.__dict__)


class Fight:

    def __init__(self, start_time, end_time, fight_id):
        self.start_time = start_time
        self.end_time = end_time
        self.fight_id = fight_id

    def __repr__(self):
        return f"Fight(start_time={self.start_time}, end_time={self.end_time})"


class Marker:

    def __init__(self, time, marker_type, duration, desc, source, raw):
        self.time = time
        self.marker_type = marker_type
        self.duration = duration
        self.desc = desc
        self.source = source
        self.raw = raw
        self.color = "#217ff5"
        self.show_text = True
        self.track = 0

    def __repr__(self):
        return (f"marker(time={self.time}, marker_type={self.marker_type},"
                f"duration={self.duration}, desc={self.desc}, source={self.source})")

    def to_dict(self):
        return {
            "time": self.time / 1000,
            "markerType": self.marker_type,
            "duration": self.duration / 1000,
            "description": self.desc,
            "color": self.color,
            "showText": self.show_text
        }

    def get_cast_end_time(self):
        return self.time + self.duration


class Damage:

    def __init__(self, target_id, time):
        self.target_id = target_id
        self.time = time

    def __repr__(self):
        return f"Damage(target_id={self.target_id}, time={self.time})"


def load_config_from_json():
    """从JSON文件加载配置"""
    config_path = "config.txt"

    if not os.path.exists(config_path):
        print(f"配置文件 {config_path} 不存在")
        return None

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)

        # 将配置赋值给全局变量
        cast_name_list = config_data.get("CAST_NAME_LIST", [])
        damage_name_list = config_data.get("DAMAGE_NAME_LIST", [])
        convert_dic = config_data.get("CONVERT_DIC", {})
        logs_id = config_data.get("LOGS_ID", "")
        fight_id = config_data.get("FIGHT_ID", 0)
        api_key = config_data.get("API_KEY", "")
        file_name = config_data.get("FILE_NAME", "output.txt")

        data = Config(cast_name_list, damage_name_list, convert_dic, logs_id, fight_id, api_key, file_name)
        print(f"配置加载成功:{data}")
        return data

    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
    except Exception as e:
        print(f"加载配置失败: {e}")


config = load_config_from_json()


def get_fight_data():
    url = f"{FIGHTS_URL_PREFIX}{config.logs_id}?api_key={config.api_key}"
    response = requests.get(url)
    data = response.json()
    fight_data = next((fight for fight in data['fights'] if fight['id'] == config.fight_id), None)
    if fight_data is None:
        return None
    else:
        return Fight(fight_data["start_time"], fight_data["end_time"], fight_data["id"])


def get_cast_source(fight):
    source = []
    time_offset = fight.start_time
    # 获得enemy的casts列表
    url = f"{CASTS_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&hostility=1&api_key={config.api_key}"
    response = requests.get(url)
    data = response.json()
    marker_list = []
    for event in data['events']:
        timestamp = event['timestamp']
        ability = event['ability']
        name = ability['name']
        if name not in config.cast_name_list:
            continue
        duration = event['duration'] if "duration" in event is not None else 0
        desc = config.convert_dic[name] if name in config.convert_dic else name
        marker_list.append(Marker(timestamp - time_offset, "Info", duration, desc, "casts", event))

    cast_ignore_time = 100  # 一个技能可能对多个目标同时释放，在指定时间内ignore
    damage_ignore_time = 1000  # 一个技能可能读完条后还会给一个单独的cast，在指定时间内ignore
    cast_end_dic = {}
    last_marker = None
    for marker in marker_list:
        if (last_marker is not None and marker.desc == last_marker.desc and marker.duration == last_marker.duration
                and marker.time - last_marker.time < cast_ignore_time):
            # ignore同一时间多次释放的技能
            continue

        if last_marker is not None and marker.desc == last_marker.desc and marker.time == last_marker.time:
            # 同一时间开始读条的技能，可能是有隐藏单位在同时读条，只取读条最长的
            if marker.duration < last_marker.duration:
                continue
            else:
                source.pop()

        if marker.duration == 0 and marker.desc in cast_end_dic and marker.time - cast_end_dic[
            marker.desc] < damage_ignore_time:
            # 部分技能读完条后会给一个单独的cast，干掉
            continue

        source.append(marker)

        if marker.duration > 0:
            cast_end_dic[marker.desc] = marker.get_cast_end_time()
        last_marker = marker
    return source


def get_damage_source(fight):
    source = []
    time_offset = fight.start_time
    # 获得damage-taken列表
    url = f"{DAMAGE_TAKEN_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&api_key={config.api_key}"
    response = requests.get(url)
    data = response.json()
    marker_list = []
    for event in data['events']:
        damage_type = event['type']
        if damage_type != "damage":
            continue

        timestamp = event['timestamp']
        ability = event['ability']
        name = ability['name']
        if name not in config.damage_name_list:
            continue
        desc = config.convert_dic[name] if name in config.convert_dic else name
        marker_list.append(Marker(timestamp - time_offset, "Info", 0, desc, "damage-taken", event))

    damage_ignore_time = 1000  # 一个技能可能对多个目标同时释放，在指定时间内ignore
    last_damage_dic = {}
    for marker in marker_list:
        damage = Damage(marker.raw["targetID"], marker.time)
        if marker.desc in last_damage_dic:
            last_damage = last_damage_dic[marker.desc]
            if damage.target_id != last_damage.target_id and damage.time - last_damage.time < damage_ignore_time:
                # 本次伤害对象和上次不一样，考虑一段时间内ignore
                continue
        source.append(marker)

        last_damage_dic[marker.desc] = damage
    return source


def get_info_list(fight):
    source = []
    source.extend(get_cast_source(fight))
    source.extend(get_damage_source(fight))

    source.sort(key=lambda x: x.time)
    return source


def get_untargetable_list(fight):
    source = []
    time_offset = fight.start_time
    # 获得summary列表
    url = f"{SUMMARY_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&api_key={config.api_key}"
    response = requests.get(url)
    data = response.json()
    for event in data['events']:
        timestamp = event['timestamp']
        if "targetable" not in event:
            continue

        desc = "不可选中" if event["targetable"] == 0 else "可选中"
        source.append(Marker(timestamp - time_offset, "Info", 0, desc, "damage-taken", event))
        source[-1].color = "#b7b7b7"
    return source


def convert_marker_list(marker_list):
    source = []
    for marker in marker_list:
        source.append(marker.to_dict())
    return source


def make_track_list(info_list):
    min_marker_interval_time = 5000
    marker_list_dic = {}
    for marker in info_list:
        track = 0
        marker_list = marker_list_dic.get(track, [])
        last_time = marker_list[-1].get_cast_end_time() if track in marker_list_dic else 0
        while marker.time - last_time < min_marker_interval_time:
            track += 1
            marker_list = marker_list_dic.get(track, [])
            last_time = marker_list[-1].get_cast_end_time() if track in marker_list_dic else 0

        marker.track = track
        marker_list.append(marker)
        marker_list_dic[track] = marker_list

    track_list = []
    for track, marker_list in marker_list_dic.items():
        track_list.append(
            {"fileType": "MarkerTrackIndividual", "track": track, "markers": convert_marker_list(marker_list)})
    return track_list


def main():
    if config is None:
        return

    fight = get_fight_data()
    if fight is None:
        print("找不到对应战斗")
        return

    info_list = get_info_list(fight)

    untargetable_list = get_untargetable_list(fight)
    untargetable_track_dic = {"fileType": "MarkerTrackIndividual", "track": -1,
                              "markers": convert_marker_list(untargetable_list)}

    track_list = [untargetable_track_dic]
    track_list.extend(make_track_list(info_list))

    json_dic = {'fileType': "MarkerTracksCombined", "tracks": track_list}
    with open(config.file_name, 'w', encoding='utf-8') as f:
        f.write(json.dumps(json_dic))


if __name__ == '__main__':
    main()
    os.system("pause")
