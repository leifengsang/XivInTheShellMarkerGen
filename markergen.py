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
        raise ValueError("无法从链接中解析出 Logs ID，请检查链接格式。")

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
    # 移除 try-except，让错误抛出
    url = f"{FIGHTS_URL_PREFIX}{config.logs_id}?api_key={config.api_key}{config.translate_param}"

    response = requests.get(url, timeout=10)  # 增加 timeout
    response.raise_for_status()  # 如果是 404/500 等错误，这里会抛出 HTTPError

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


def get_real_fight_offset(fight, config):
    # 移除 try-except
    search_end = fight.start_time + 5000
    damage_url = f"{DAMAGE_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={search_end}&hostility=1&api_key={config.api_key}{config.translate_param}"

    response = requests.get(damage_url, timeout=10)
    response.raise_for_status()
    data = response.json()
    events = data.get('events', [])
    for event in events:
        if event.get('type') == 'damage':
            return event['timestamp']

    return fight.start_time


def get_cast_source(fight, config, time_offset):
    # 移除 try-except
    url = f"{CASTS_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&hostility=1&api_key={config.api_key}{config.translate_param}"

    response = requests.get(url, timeout=20)  # 施法列表可能很大，超时给长一点
    response.raise_for_status()
    data = response.json()

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
                if hidden.get('event', {}).get('type', 'cast') == 'begincast':
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
            if target_item['sourceInstance'] == s_id and target_item['ability_name'] == a_name:
                target_item['to_delete'] = True
                break

    source = []
    for item in clean_events:
        if item['to_delete']:
            continue

        event = item['event']
        desc = item['ability_name']
        duration = event.get('duration', 0)
        timestamp = item['timestamp']

        if duration > 0 and duration < 500:
            continue

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
    # 这里我们也可以移除 try-except，或者保留它但明确如果失败返回空
    # 考虑到这些是辅助信息，如果失败可以不阻断主流程，但也建议抛出错误让用户知道网络有问题
    # 为了严谨，这里也改为抛出错误
    source = []
    events_list = []

    filter_exp = 'type="targetabilityupdate"'
    summary_url = f"{SUMMARY_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&hostility=1&filter={filter_exp}&api_key={config.api_key}{config.translate_param}"
    # 允许这里失败抛出异常
    resp = requests.get(summary_url, timeout=10)
    resp.raise_for_status()
    summary_data = resp.json()
    for e in summary_data.get('events', []):
        src = e.get('source')
        tgt = e.get('target')
        if isinstance(src, dict) and src.get('type') == 'NPC': continue
        if isinstance(tgt, dict) and tgt.get('type') == 'NPC': continue
        if e.get('sourceIsFriendly', False): continue

        if 'targetable' in e:
            val = 1 if e['targetable'] == 1 else -1
            events_list.append({
                'timestamp': e['timestamp'], 'type': 'targetability', 'val': val,
                'raw': e, 'targetID': e.get('sourceID', e.get('targetID', 0))
            })

    filter_exp = "overkill>0"
    damage_url = f"{DAMAGE_URL_PREFIX}{config.logs_id}?start={fight.start_time}&end={fight.end_time}&hostility=1&filter={filter_exp}&api_key={config.api_key}{config.translate_param}"

    # 允许这里失败抛出异常
    resp = requests.get(damage_url, timeout=10)
    resp.raise_for_status()
    damage_data = resp.json()
    for e in damage_data.get('events', []):
        events_list.append({
            'timestamp': e['timestamp'], 'type': 'overkill', 'val': -1,
            'raw': e, 'targetID': e.get('targetID', 0)
        })

    events_list.sort(key=lambda x: x['timestamp'])

    unique_events = []

    # 按 targetID 分组
    events_by_tid = {}
    for event in events_list:
        tid = event['targetID']
        if tid not in events_by_tid:
            events_by_tid[tid] = []
        events_by_tid[tid].append(event)

    for tid, group in events_by_tid.items():
        if not group:
            continue

        # group 已经是按 timestamp 排序的了

        # 将连续相同的 val 分为一块 (Chunking)
        chunks = []
        current_chunk = [group[0]]

        for i in range(1, len(group)):
            curr_event = group[i]
            # 比较当前事件 val 和当前块中事件的 val 是否相同
            if curr_event['val'] == current_chunk[0]['val']:
                current_chunk.append(curr_event)
            else:
                chunks.append(current_chunk)
                current_chunk = [curr_event]
        chunks.append(current_chunk)

        # 在每个块中根据规则选最优事件保留
        for chunk in chunks:
            best_event = None

            # 筛选出 type 为 targetability 的事件
            target_candidates = [e for e in chunk if e['type'] == 'targetability']

            if target_candidates:
                # 规则A: 优先保留 targetability 类型
                # 规则B: 如果有多个，保留时间最早的 (由于 chunk 有序，第一个即最早)
                best_event = target_candidates[0]
            else:
                # 规则C: 如果没有 targetability (全是 overkill)，保留时间最早的
                best_event = chunk[0]

            unique_events.append(best_event)

    # 第四步：将所有 ID 去重后的事件合并，重新按时间排序，供后续计数使用
    events_list = sorted(unique_events, key=lambda x: x['timestamp'])

    count = 1
    current_zero_start_time = None
    current_zero_start_event = None
    dead_units = set()

    for event in events_list:
        prev_count = count
        count += event['val']
        if count < 0:
            count = 0

        if prev_count > 0 and count == 0:
            current_zero_start_time = event['timestamp']
            current_zero_start_event = event['raw']
        elif prev_count == 0 and count > 0:
            if current_zero_start_time is not None:
                end_time = event['timestamp']
                duration = end_time - current_zero_start_time
                if duration > 0:
                    m = Marker(current_zero_start_time - time_offset, "Info", duration, "不可选中", "untargetable",
                               current_zero_start_event)
                    m.color = "#b7b7b7"
                    source.append(m)
                current_zero_start_time = None
                current_zero_start_event = None

    if count == 0 and current_zero_start_time is not None:
        duration = fight.end_time - current_zero_start_time
        if duration > 0:
            m = Marker(current_zero_start_time - time_offset, "Info", duration, "不可选中", "untargetable",
                       current_zero_start_event)
            m.color = "#b7b7b7"
            source.append(m)

    return source


def convert_marker_list(marker_list):
    return [marker.to_dict() for marker in marker_list]


def make_track_list(info_list, min_interval, max_tracks):
    marker_list_dic = {}
    info_list.sort(key=lambda x: x.time)
    
    # 定义硬性下限
    MIN_INTERVAL_FLOOR = 1000 

    for marker in info_list:
        current_interval = min_interval
        
        while True:
            track = 0
            found_track = False
            
            # 内层循环：寻找可用轨道
            while True:
                marker_list = marker_list_dic.get(track, [])
                if not marker_list:
                    found_track = True
                    break # 找到了位置，执行插入
                last_end_time = marker_list[-1].get_cast_end_time()
                
                # 检查是否满足当前间隔
                if marker.time - last_end_time >= current_interval:
                    found_track = True
                    break # 找到了位置，执行插入
                
                track += 1 # 没找到就开新轨道
                
                if track >= max_tracks:
                    # 如果目前的间隔比 1000 大，说明还有压缩空间
                    # 减小 current_interval 重试
                    if current_interval > MIN_INTERVAL_FLOOR:
                        break 
                    else:
                        # 如果已经死守到 1000 了，或者更小
                        # 代码会继续执行 while True，进入 track = max_tracks
                        pass 

            if found_track:
                marker.track = track
                if track not in marker_list_dic:
                    marker_list_dic[track] = []
                marker_list_dic[track].append(marker)
                break 
            else:
                current_interval = max(current_interval - 100, MIN_INTERVAL_FLOOR)


    track_list = []
    sorted_tracks = sorted(marker_list_dic.keys())

    for track in sorted_tracks:
        track_list.append({
            "fileType": "MarkerTrackIndividual",
            "track": track,
            "markers": convert_marker_list(marker_list_dic[track])
        })
        
    return track_list


def fetch_log_data(logs_url, api_key, is_translate):
    # 这里进行总的异常捕获，返回给 GUI 显示
    try:
        logs_id, fight_id = parse_url(logs_url)
        config = RuntimeConfig(logs_id, fight_id, api_key, translate=is_translate)

        # 这些函数现在会抛出 Exception 而不是打印 error
        fight = get_fight_data(config)

        if fight is None:
            # 可能是 fight_id 逻辑找不到，或者其他非异常错误
            return None, None, None, "在报告中未找到符合条件的 Fight ID (可能是 last 参数无效，或者 Logs ID 错误)"

        time_offset = get_real_fight_offset(fight, config)
        cast_list = get_cast_source(fight, config, time_offset)
        untarget_list = get_untargetable_list(fight, config, time_offset)

        return cast_list, untarget_list, fight, "Success"

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 400:
            return None, None, None, f"API请求错误 (400): 请检查 API Key 是否正确，或 Logs 权限是否公开。\n详细: {e}"
        if e.response.status_code == 401:
            return None, None, None, f"API Key 无效 (401)。请检查 Key。"
        if e.response.status_code == 429:
            return None, None, None, f"请求过于频繁 (429)。请稍后再试。"
        return None, None, None, f"网络请求 HTTP 错误: {e}"
    except requests.exceptions.ConnectionError:
        return None, None, None, "网络连接失败。请检查你的网络设置。"
    except requests.exceptions.Timeout:
        return None, None, None, "请求 FFLogs 超时。网络可能不稳定。"
    except ValueError as e:
        return None, None, None, f"数据解析错误: {e}"
    except Exception as e:
        return None, None, None, f"未知错误: {e}"


def generate_final_json(cast_list, untarget_list, user_config):
    # 保持原样，逻辑不需要变
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

