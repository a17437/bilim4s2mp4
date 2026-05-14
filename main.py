import os
import sys
import shutil
import subprocess
import re
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

#### 设置 ####
FILE_FROM = "from"  # B站缓存源目录
OUT_DIR = "out"     # 导出根目录
LOG_FILE = "error.log"

# 线程锁
log_lock = threading.Lock()

def write_log(message, detail=""):
    """线程安全的日志写入"""
    with log_lock:
        with open(LOG_FILE, 'a', encoding='utf-8') as file:
            file.write(f"{message}\n{detail}\n----===----\n")
        print(f"[错误] {message} (详情请查看 {LOG_FILE})")

def sanitize_filename(name):
    """清理文件名，保留空格以利于刮削"""
    name = str(name)
    illegal_chars = r'[\\/:\*\?"<>\|]'
    sanitized = re.sub(illegal_chars, ' ', name)
    return re.sub(r'\s+', ' ', sanitized).strip()

def get_jellyfin_metadata(json_path):
    """
    智能解析 entry.json，自动区分:
    1. 番剧/剧集 (TV Shows)
    2. 电影 (Movies)
    3. UP主视频 (UP Videos)
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as file:
            data = json.load(file)
            
        show_title = sanitize_filename(data.get("title", "未知标题"))
        type_tag = str(data.get("type_tag", ""))
        
        # ==========================================
        # 场景 1: PGC 内容 (官方番剧、电视剧、电影)
        # ==========================================
        if "ep" in data and data["ep"] is not None:
            ep_index_raw = str(data["ep"].get("index", ""))
            ep_title = sanitize_filename(data["ep"].get("index_title", ""))
            
            # 【判断是否为电影】通常电影的 index 是 "正片" 或空值
            if ep_index_raw == "正片" or not ep_index_raw:
                # 电影标准结构: out/Movies/电影名/电影名.mp4
                filename = f"{show_title}.mp4" if not ep_title else f"{show_title} - {ep_title}.mp4"
                target_folder = os.path.join(OUT_DIR, "Movies", show_title)
            else:
                # 剧集标准结构: out/TV Shows/剧集名/Season 01/剧集名 - S01E01 - 标题.mp4
                ep_num = ep_index_raw.zfill(2) if ep_index_raw.isdigit() else ep_index_raw
                filename = f"{show_title} - S01E{ep_num} - {ep_title}.mp4"
                target_folder = os.path.join(OUT_DIR, "TV Shows", show_title, "Season 01")

        # ==========================================
        # 场景 2: UGC 内容 (UP主日常视频、教程、合集)
        # ==========================================
        elif "page_data" in data and data["page_data"] is not None:
            part_title = sanitize_filename(data["page_data"].get("part", "单P视频"))
            part_num = str(data["page_data"].get("page", "1")).zfill(2)
            
            # 尝试获取 UP 主名字 (部分 B站缓存版本带有 owner_name)
            owner = sanitize_filename(data.get("owner_name", ""))
            
            # 为了避免冗余，如果合集标题和分P标题一模一样，就不重复拼接了
            if show_title == part_title:
                filename = f"{show_title} - P{part_num}.mp4"
            else:
                filename = f"{show_title} - P{part_num} - {part_title}.mp4"
            
            # 结构: out/UP Videos/[UP主]视频标题/...
            folder_name = f"[{owner}] {show_title}" if owner else show_title
            target_folder = os.path.join(OUT_DIR, "UP Videos", folder_name)

        # ==========================================
        # 场景 3: 兜底方案 (未知结构)
        # ==========================================
        else:
            filename = f"{show_title}.mp4"
            target_folder = os.path.join(OUT_DIR, "Others", show_title)
            
        return target_folder, filename, type_tag
        
    except Exception as e:
        write_log(f"解析JSON失败: {json_path}", str(e))
        return None, None, None

def process_single_video(two_dir_path):
    json_path = os.path.join(two_dir_path, "entry.json")
    if not os.path.isfile(json_path):
        return False

    target_folder, target_filename, type_tag = get_jellyfin_metadata(json_path)
    if not target_folder or not type_tag:
        return False

    media_dir = os.path.join(two_dir_path, type_tag)
    video_file = os.path.join(media_dir, "video.m4s")
    audio_file = os.path.join(media_dir, "audio.m4s")
    
    if not os.path.isfile(video_file):
        write_log(f"没有找到视频文件 video.m4s", media_dir)
        return False

    os.makedirs(target_folder, exist_ok=True)
    final_output_path = os.path.join(target_folder, target_filename)
    temp_output_path = final_output_path + ".temp.mp4"

    # 防重复与断点续传保护
    if os.path.isfile(final_output_path):
        with log_lock:
            print(f"[跳过已存在] {target_filename}")
        return True

    cmd = ['ffmpeg', '-y', '-i', video_file]
    if os.path.isfile(audio_file):
        cmd.extend(['-i', audio_file, '-c', 'copy', temp_output_path])
    else:
        cmd.extend(['-c', 'copy', temp_output_path])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            write_log(f"FFmpeg 处理失败: {media_dir}", result.stderr)
            if os.path.exists(temp_output_path): os.remove(temp_output_path)
            return False
            
        shutil.move(temp_output_path, final_output_path)
        with log_lock:
            # 打印相对路径，看起来更清爽
            rel_path = os.path.relpath(final_output_path, OUT_DIR)
            print(f"[合并成功] -> {rel_path}")
        return True
        
    except Exception as e:
        write_log(f"执行时发生错误: {media_dir}", str(e))
        return False

def main():
    print("="*50)
    print("Bilibili 缓存多线程分离导出 (支持电影/番剧/UP主)")
    print("="*50)

    if not os.path.isdir(FILE_FROM):
        print(f"找不到来源目录 '{FILE_FROM}'，请检查。")
        sys.exit(1)

    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        f.write("=== 日志开始 ===\n")

    tasks = []
    for one_dir in os.listdir(FILE_FROM):
        one_dir_path = os.path.join(FILE_FROM, one_dir)
        if not os.path.isdir(one_dir_path): continue
        for two_dir in os.listdir(one_dir_path):
            two_dir_path = os.path.join(one_dir_path, two_dir)
            if os.path.isdir(two_dir_path):
                tasks.append(two_dir_path)

    total = len(tasks)
    print(f"扫描完毕，共发现 {total} 个视频缓存。")
    if total == 0: return

    max_workers = os.cpu_count() or 4
    success_count = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {executor.submit(process_single_video, task): task for task in tasks}
        for future in as_completed(future_to_task):
            if future.result():
                success_count += 1

    print("="*50)
    print(f"处理完成！成功导出: {success_count}/{total}")

if __name__ == '__main__':
    main()
