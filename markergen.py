import re
import requests

# --- 常量定义 ---
FIGHTS_URL_PREFIX = "https://cn.fflogs.com/v1/report/fights/"
CASTS_URL_PREFIX = "https://cn.fflogs.com/v1/report/events/casts/"
SUMMARY_URL_PREFIX = "https://cn.fflogs.com/v1/report/events/summary/"
DAMAGE_URL_PREFIX = "https://cn.fflogs.com/v1/report/events/damage-taken/"
ANY_URL_PREFIX = "https://cn.fflogs.com/v1/report/events/any/"

# --- 数据模型类 ---

class RuntimeConfig:
    def __init__(self, logs_id, fight_id, api_key, translate=False):
        self.logs_id = logs_id
        self.fight_id = fight_id
        self.api_key = api_key
        self.translate_param = "&translate=true" if translate else ""
        self.convert_dic = {} 

class Fight:
    def __init__(self, start_time, end_time, fight_id, zone_id=0, zone_name="Unknown"):
        self.start_time = start_time
        self.end_time = end_time
        self.fight_id = fight_id
        self.zone_id = zone_id
        self.zone_name = zone_name

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

# --- 核心功能函数 ---

def parse_url(url):
    log_match = re.search(r'reports/([a-zA-Z0-9]+)', url)
    fight_match = re.search(r'fight=([^&]+)', url)

    if not log_match:
        raise ValueError("无法从链接中解析出 Logs ID")
    
    logs_id = log_match.group(1)
    
    if fight_match:
        fight_val = fight_match.group(1)
        if fight_val == "last":
            fight_id = "last"
        else:
            try:
                fight_id = int(fight_val)
            except ValueError:
                fight_id = 0
    else:
        fight_id = 0
    
    return logs_id, fight_id

def get_fight_data(config):
    url = f"{FIGHTS_URL_PREFIX}{config.logs_id}?api_key={config.api_key}{config.translate_param}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        fights = data.get('fights', [])
        
        if config.fight_id == "last":
            fight_data = fights[-1] if fights else None
        else:
            fight_data = next((fight for fight in fights if fight['id'] == config.fight_id), None)
            
        if fight_data is None:
            return None
        
        zone_id = fight_data.get('zoneID', 0)
        zone_name = fight_data.get('zoneName', 'Unknown Zone')
        
        return Fight(fight_data["start_time"], fight_data["end_time"], fight_data["id"], zone_id, zone_name)
    except Exception as e:
        print(f"获取战斗数据失败: {e}")
        return None

def get_real_fight_offset(fight, config):
    search_end = fight.start_time + 5000 
    damage_url = f"{DAMAGE_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={search_end}&hostility=1&api_key={config.api_key}{config.translate_param}"
    try:
        response = requests.get(damage_url)
        response.raise_for_status()
        data = response.json()
        events = data.get('events', [])
        for event in events:
            if event.get('type') == 'damage':
                return event['timestamp']
    except Exception as e:
        print(f"获取开怪锚点失败: {e}")
    return fight.start_time

def get_cast_source(fight, config, time_offset):
    url = f"{CASTS_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&hostility=1&api_key={config.api_key}{config.translate_param}"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"获取Cast数据失败: {e}")
        return []

    events = data.get('events', [])
    clean_events = []
    
    for i, event in enumerate(events):
        name = event.get('ability', {}).get('name', '')
        
        clean_events.append({
            'original_index': i,
            'event': event,
            'timestamp': event['timestamp'],
            'sourceInstance': event.get('sourceInstance', 0),
            'ability_name': name,
            'to_delete': False
        })

    group_map = {}
    for item in clean_events:
        key = (item['timestamp'], item['ability_name'])
        if key not in group_map: group_map[key] = []
        group_map[key].append(item)
        
    hidden_cleanup_tasks = []
    for key, items in group_map.items():
        if len(items) > 1:
            items.sort(key=lambda x: x['sourceInstance'])
            hidden_units = items[1:]
            for hidden in hidden_units:
                if hidden.get('event',{}).get('type','cast') == 'begincast':
                    hidden['to_delete'] = True
                    hidden_cleanup_tasks.append({
                        'sourceInstance': hidden['sourceInstance'],
                        'ability_name': hidden['ability_name'],
                        'search_start_idx': clean_events.index(hidden) + 1,
                        'origin_time': hidden['timestamp'],
                        'origin_duration': hidden['event'].get('duration', 0)
                    })

    for task in hidden_cleanup_tasks:
        s_id = task['sourceInstance']
        a_name = task['ability_name']
        start_idx = task['search_start_idx']
        window_start = task['origin_time'] + task['origin_duration']
        window_end = window_start + 3000

        for i in range(start_idx, len(clean_events)):
            target_item = clean_events[i]
            target_ts = target_item['timestamp']
            if (target_item['sourceInstance'] == s_id and target_item['ability_name'] == a_name):
                target_item['to_delete'] = True
                break

    source = []
    for item in clean_events:
        if item['to_delete']: continue
        
        event = item['event']
        desc = item['ability_name'] 
        duration = event.get('duration', 0)
        timestamp = item['timestamp']
        
        if duration > 0  and duration < 500: continue
        
        m = Marker(timestamp - time_offset, "Info", duration, desc, "casts", event)
        source.append(m)

    final_source = []
    cast_ignore_time = 100 
    last_marker = None
    for marker in source:
        if (last_marker is not None and marker.desc == last_marker.desc and 
            marker.duration == last_marker.duration and 
            marker.time - last_marker.time < cast_ignore_time):
            continue
        final_source.append(marker)
        last_marker = marker

    return final_source

def get_untargetable_list(fight, config, time_offset):
    source = []
    events_list = []

    filter_exp = 'type="targetabilityupdate"'
    summary_url = f"{SUMMARY_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&filter={filter_exp}&api_key={config.api_key}{config.translate_param}"
    try:
        resp = requests.get(summary_url)
        resp.raise_for_status()
        summary_data = resp.json()
        for e in summary_data.get('events', []):
            if 'targetable' in e:
                val = 1 if e['targetable'] == 1 else -1
                events_list.append({
                    'timestamp': e['timestamp'], 'type': 'targetability', 'val': val,
                    'raw': e, 'targetID': e.get('sourceID', e.get('targetID', 0))   
                })
    except Exception as e:
        print(f"获取Summary数据失败: {e}")

    filter_exp = "overkill>0"
    damage_url = f"{DAMAGE_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&hostility=1&filter={filter_exp}&api_key={config.api_key}{config.translate_param}"
    try:
        resp = requests.get(damage_url)
        resp.raise_for_status()
        damage_data = resp.json()
        for e in damage_data.get('events', []):
            events_list.append({
                'timestamp': e['timestamp'], 'type': 'overkill', 'val': -1,
                'raw': e, 'targetID': e.get('targetID', 0)
            })
    except Exception:
        pass

    events_list.sort(key=lambda x: x['timestamp'])
    
    unique_events = []
    last_seen_map = {}
    threshold = 100 
    for event in events_list:
        t_id = event['targetID']
        val = event['val']
        curr_ts = event['timestamp']
        key = (t_id, val)
        last_ts = last_seen_map.get(key)
        if last_ts is not None and (curr_ts - last_ts < threshold):
            continue
        unique_events.append(event)
        last_seen_map[key] = curr_ts
    events_list = unique_events
    
    count = 1
    current_zero_start_time = None
    current_zero_start_event = None
    dead_units = set()

    for event in events_list:
        prev_count = count
        if event['type'] == 'targetability': count += event['val']
        elif event['type'] == 'overkill':
            t_id = event['targetID']
            if t_id not in dead_units:
                count += event['val']
                dead_units.add(t_id)
        if count < 0: count = 0
            
        if prev_count > 0 and count == 0:
            current_zero_start_time = event['timestamp']
            current_zero_start_event = event['raw']
        elif prev_count == 0 and count > 0:
            if current_zero_start_time is not None:
                end_time = event['timestamp']
                duration = end_time - current_zero_start_time
                if duration > 0:
                     m = Marker(current_zero_start_time - time_offset, "Info", duration, "不可选中", "untargetable", current_zero_start_event)
                     m.color = "#b7b7b7"
                     source.append(m)
                current_zero_start_time = None
                current_zero_start_event = None

    if count == 0 and current_zero_start_time is not None:
        duration = fight.end_time - current_zero_start_time
        if duration > 0:
             m = Marker(current_zero_start_time - time_offset, "Info", duration, "不可选中", "untargetable", current_zero_start_event)
             m.color = "#b7b7b7"
             source.append(m)

    return source

def convert_marker_list(marker_list):
    return [marker.to_dict() for marker in marker_list]

def make_track_list(info_list, min_interval, max_tracks):
    marker_list_dic = {}
    info_list.sort(key=lambda x: x.time)

    for marker in info_list:
        track = 0
        marker_list = marker_list_dic.get(track, [])
        last_end_time = marker_list[-1].get_cast_end_time() if marker_list else 0
        
        while marker.time - last_end_time < min_interval:
            track += 1
            marker_list = marker_list_dic.get(track, [])
            last_end_time = marker_list[-1].get_cast_end_time() if marker_list else 0

        marker.track = track
        marker_list.append(marker)
        marker_list_dic[track] = marker_list

    track_list = []
    sorted_tracks = sorted(marker_list_dic.keys())
    
    for track in sorted_tracks:
        if track >= max_tracks:
            break
        track_list.append({
            "fileType": "MarkerTrackIndividual", 
            "track": track, 
            "markers": convert_marker_list(marker_list_dic[track])
        })
    return track_list

def fetch_log_data(logs_url, api_key, is_translate):
    try:
        logs_id, fight_id = parse_url(logs_url)
    except ValueError as e:
        return None, None, None, str(e)

    config = RuntimeConfig(logs_id, fight_id, api_key, translate=is_translate)
    
    fight = get_fight_data(config)
    if fight is None:
        return None, None, None, "找不到对应战斗数据 (Fight ID 错误或 API Key 无效)"

    time_offset = get_real_fight_offset(fight, config)
    
    cast_list = get_cast_source(fight, config, time_offset)
    untarget_list = get_untargetable_list(fight, config, time_offset)
    
    return cast_list, untarget_list, fight, "Success"

def generate_final_json(cast_list, untarget_list, user_config):
    min_interval = user_config['min_interval']
    max_tracks = user_config['max_tracks']
    filter_map = user_config['filter_map']

    final_cast_list = []
    for marker in cast_list:
        if marker.desc not in filter_map:
            continue
        
        marker.desc = filter_map[marker.desc]
        final_cast_list.append(marker)

    untargetable_track = {
        "fileType": "MarkerTrackIndividual", 
        "track": -1,
        "markers": convert_marker_list(untarget_list)
    }

    cast_tracks = make_track_list(final_cast_list, min_interval, max_tracks)
    final_tracks = [untargetable_track] + cast_tracks
    
    result_json = {
        'fileType': "MarkerTracksCombined", 
        "tracks": final_tracks
    }
    
    return result_json