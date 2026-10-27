import time
import datetime
import random
# 🚨 _strptime 모듈 스레딩 충돌 방지를 위한 강제 초기화
try:
    time.strptime("2026-01-01", "%Y-%m-%d")
    datetime.datetime.strptime("2026-01-01", "%Y-%m-%d")
except Exception:
    pass

import streamlit as st
import yt_dlp
import os
import tempfile
import re
import concurrent.futures
import json
import librosa
import numpy as np
import asyncio
import subprocess
import urllib.parse
import warnings
import uuid
import requests

# 콘솔 경고문 숨김 처리
warnings.filterwarnings("ignore", category=FutureWarning)

st.set_page_config(page_title="Music Searcher", page_icon="🎧", layout="wide")

# ==========================================
# 🎨 다크/라이트 테마 엔진 초기화 (가독성 극대화)
# ==========================================
if 'app_theme' not in st.session_state: 
    st.session_state.app_theme = "Dark"

if st.session_state.app_theme == "Dark":
    C_BG_MAIN, C_BG_GRAD, C_BG_CARD, C_BG_HOVER, C_BG_SEC = "#0A0A0C", "#15151e", "#121217", "#1a1a24", "#0e0e13"
    C_TEXT_MAIN, C_TEXT_SUB, C_TEXT_MUTED, C_TEXT_DARK = "#f1f5f9", "#cbd5e1", "#94a3b8", "#64748b"
    C_BORDER = "#26262e"
    C_ACCENT, C_ACCENT_HOVER = "#17C8F0", "#38bdf8"
    C_SUCCESS, C_WARN, C_DANGER, C_PURPLE = "#22c55e", "#f59e0b", "#ef4444", "#a855f7"
else:
    C_BG_MAIN, C_BG_GRAD, C_BG_CARD, C_BG_HOVER, C_BG_SEC = "#f1f5f9", "#e2e8f0", "#ffffff", "#e2e8f0", "#f8fafc"
    C_TEXT_MAIN, C_TEXT_SUB, C_TEXT_MUTED, C_TEXT_DARK = "#000000", "#1e293b", "#334155", "#475569"
    C_BORDER = "#94a3b8"
    C_ACCENT, C_ACCENT_HOVER = "#0284c7", "#0369a1"
    C_SUCCESS, C_WARN, C_DANGER, C_PURPLE = "#15803d", "#b45309", "#b91c1c", "#7e22ce"

yt_icon = f'<svg height="15" width="20" viewBox="0 0 24 24" style="fill: {C_DANGER}; vertical-align: middle; margin-right: 6px;"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>'

# 📂 클라우드 임시 폴더 설정 (사용자 간 파일 충돌 방지)
CLOUD_TEMP_DIR = os.path.join(tempfile.gettempdir(), "music_searcher_temp")
os.makedirs(CLOUD_TEMP_DIR, exist_ok=True)

# 🔑 다중 사용자 보안 모드: 서버 하드디스크에 개인정보(키/북마크/히스토리)를 저장하지 않고 개별 브라우저 세션에서만 관리
def load_api_keys():
    keys = {
        "gemini": st.session_state.get("saved_gemini_key", ""),
        "groq": st.session_state.get("saved_groq_key", "")
    }
    # 관리자가 Streamlit Secrets에 기본 키를 넣어둔 경우에만 폴백으로 사용
    try:
        if not keys["gemini"] and "GEMINI_API_KEY" in st.secrets:
            keys["gemini"] = st.secrets["GEMINI_API_KEY"]
        if not keys["groq"] and "GROQ_API_KEY" in st.secrets:
            keys["groq"] = st.secrets["GROQ_API_KEY"]
    except Exception:
        pass
    return keys

def save_api_keys(gemini, groq):
    st.session_state.saved_gemini_key = str(gemini).strip()
    st.session_state.saved_groq_key = str(groq).strip()
    return True

def load_ai_history():
    return st.session_state.get("ai_history", [])

def save_ai_history(history_data):
    st.session_state.ai_history = history_data
    return True

def load_bookmarks():
    return st.session_state.get("bookmarks", [])

def save_bookmarks(bms):
    st.session_state.bookmarks = bms
    return True

def get_compatible_keys(camelot):
    match = re.match(r"(\d+)([AB])", camelot)
    if not match: return []
    num = int(match.group(1))
    letter = match.group(2)
    comp = [camelot]
    comp.append(f"{num-1 if num > 1 else 12}{letter}")
    comp.append(f"{num+1 if num < 12 else 1}{letter}")
    comp.append(f"{num}{'B' if letter == 'A' else 'A'}")
    return comp

def generate_mix_sequence(tracks, bpm_range=None, target_time_sec=None):
    if not tracks: return []
    valid_tracks = tracks
    if bpm_range:
        valid_tracks = [t for t in tracks if bpm_range[0] <= t['bpm'] <= bpm_range[1]]
    if not valid_tracks: return []
        
    ordered = [min(valid_tracks, key=lambda x: x['bpm'])]
    remaining = list(valid_tracks)
    remaining.remove(ordered[0])
    current_time = ordered[0].get('duration', 210)
    
    while remaining:
        if target_time_sec and current_time >= target_time_sec: break
        current = ordered[-1]
        compatible = [t for t in remaining if t['camelot'] in current['comp_keys']]
        if compatible:
            next_t = min(compatible, key=lambda x: abs(x['bpm'] - current['bpm']))
        else:
            next_t = min(remaining, key=lambda x: abs(x['bpm'] - current['bpm']))
        ordered.append(next_t)
        remaining.remove(next_t)
        current_time += next_t.get('duration', 210)
    return ordered

# ⚡ [초정밀 오디오 분석 엔진]
def analyze_track_pro(file_path):
    try:
        y, sr = librosa.load(file_path, sr=22050)
        duration_sec = librosa.get_duration(y=y, sr=sr)
        
        offset_sec = min(60.0, duration_sec * 0.2) if duration_sec else 0.0
        start_idx = int(offset_sec * sr)
        end_idx = min(len(y), start_idx + int(60.0 * sr))
        y_core = y[start_idx:end_idx]
        
        tempo, _ = librosa.beat.beat_track(y=y_core, sr=sr)
        bpm = int(round(tempo[0])) if isinstance(tempo, (list, tuple, np.ndarray)) else int(round(tempo))
        
        y_harmonic, _ = librosa.effects.hpss(y_core)
        chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr)
        chroma_sum = np.sum(chroma, axis=1)
        
        maj_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        min_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
        pitches = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        
        camelot_map = {
            'C': ('8B', '5A'), 'C#': ('3B', '12A'), 'D': ('10B', '7A'), 'D#': ('5B', '2A'),
            'E': ('12B', '9A'), 'F': ('7B', '4A'), 'F#': ('2B', '11A'), 'G': ('9B', '6A'),
            'G#': ('4B', '1A'), 'A': ('11B', '8A'), 'A#': ('6B', '3A'), 'B': ('1B', '10A')
        }
        
        maj_corrs = [np.corrcoef(chroma_sum, np.roll(maj_profile, i))[0, 1] for i in range(12)]
        min_corrs = [np.corrcoef(chroma_sum, np.roll(min_profile, i))[0, 1] for i in range(12)]
        
        max_maj, max_min = max(maj_corrs), max(min_corrs)
        
        if max_maj > max_min:
            key_idx = maj_corrs.index(max_maj)
            camelot = camelot_map[pitches[key_idx]][0]
            rb_key = pitches[key_idx].replace('D#', 'Eb').replace('G#', 'Ab').replace('A#', 'Bb')
        else:
            key_idx = min_corrs.index(max_min)
            camelot = camelot_map[pitches[key_idx]][1]
            rb_key = f"{pitches[key_idx].replace('D#', 'Eb').replace('G#', 'Ab').replace('A#', 'Bb')}m"
            
        cues = {"intro": {"bb": "1마디 1박", "t": "00:00"}, "build": {"bb": "17마디 1박", "t": "01:04"}, "drop": {"bb": "33마디 1박", "t": "02:08"}, "outro": {"bb": "81마디 1박", "t": "04:30"}}
        return bpm, rb_key, camelot, cues, duration_sec
        
    except Exception:
        return None, None, None, None, None

def fetch_tracks(platform, query):
    prefix = "ytsearch10:" if platform == 'YouTube' else "scsearch5:"
    opts = {'extract_flat': 'in_playlist', 'quiet': True, 'geo_bypass': True, 'nocheckcertificate': True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            res = ydl.extract_info(f"{prefix}{query}", download=False)
            entries = []
            for e in res.get('entries', []):
                if e:
                    e['platform'] = platform
                    entries.append(e)
            return entries
    except Exception:
        return []

def process_downloaded_file(i_dict, target_codec, orig_file, down_dir):
    artist, track, raw_title = i_dict.get('artist'), i_dict.get('track'), i_dict.get('title', '')
    uploader = i_dict.get('uploader', '')
    if artist and track: clean_title = f"{artist} - {track}"
    elif " - " in raw_title: clean_title = raw_title
    elif uploader and uploader.lower() not in raw_title.lower(): clean_title = f"{uploader} - {raw_title}"
    else: clean_title = raw_title
    
    clean_title = re.sub(r'^\d+[\.\-\s]+', '', clean_title).strip()
    clean_title = re.sub(r'[\\*?:"<>|/]', "", clean_title)
    
    target_ext = f".{target_codec}"
    d_file = os.path.splitext(orig_file)[0] + target_ext
    new_file = os.path.join(down_dir, f"{clean_title}_{uuid.uuid4().hex[:6]}{target_ext}")
    
    if os.path.exists(d_file):
        if d_file != new_file:
            if os.path.exists(new_file):
                try: os.remove(new_file)
                except: pass
            os.replace(d_file, new_file)
        
        artist_tag, title_tag = "", clean_title
        if " - " in clean_title:
            parts = clean_title.split(" - ", 1)
            artist_tag, title_tag = parts[0].strip(), parts[1].strip()
            
        temp_filepath = new_file + f".temp{target_ext}"
        cmd = ['ffmpeg', '-y', '-i', new_file]
        if artist_tag: cmd.extend(['-metadata', f'artist={artist_tag}'])
        cmd.extend(['-metadata', f'title={title_tag}', '-codec', 'copy', temp_filepath])
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(temp_filepath): os.replace(temp_filepath, new_file)
        except Exception:
            if os.path.exists(temp_filepath):
                try: os.remove(temp_filepath)
                except: pass
    return clean_title, new_file

def fetch_and_analyze_single_track(full_name, target_dir):
    temp_id = uuid.uuid4().hex[:8]
    temp_out = os.path.join(target_dir, f"tmp_fast_{temp_id}.%(ext)s")
    
    ydl_opts = {
        'format': 'ba[abr<=64]/worstaudio/ba', 
        'outtmpl': temp_out, 
        'quiet': True, 
        'noplaylist': True,
        'nocheckcertificate': True,
        'geo_bypass': True
    }
    
    search_queries = [f"{full_name} audio", f"{full_name} lyrics", full_name]
    
    for query in search_queries:
        dl_file = None
        converted_file = None
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=True)
                if 'entries' in info and info['entries']:
                    info = info['entries'][0]
                dl_file = ydl.prepare_filename(info)
            
            if dl_file and os.path.exists(dl_file):
                converted_file = os.path.splitext(dl_file)[0] + f"_conv_{temp_id}.mp3"
                subprocess.run(['ffmpeg', '-y', '-i', dl_file, '-codec:a', 'libmp3lame', '-b:a', '64k', converted_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                target_audio = converted_file if os.path.exists(converted_file) else dl_file
                bpm, rb_key, camelot, cues, duration = analyze_track_pro(target_audio)
                
                if bpm and camelot:
                    return {
                        "name": full_name, "bpm": bpm, "key": rb_key, "camelot": camelot,
                        "comp_keys": get_compatible_keys(camelot), "cues": cues, "duration": duration or 210
                    }
        except Exception:
            pass
        finally:
            for f in [dl_file, converted_file]:
                if f and os.path.exists(f):
                    try: os.remove(f)
                    except: pass
                    
    return None

st.markdown(f'''
<style>
    [data-testid="stHeader"] {{ display: none !important; }}
    [data-testid="stToolbar"] {{ display: none !important; }}
    footer {{ display: none !important; }}
    [class*="viewerBadge"] {{ display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }}
    [data-testid="stStatusWidget"] {{ display: none !important; }}
    [data-testid="stDecoration"] {{ display: none !important; }}
    
    [data-testid="stAppViewContainer"] {{ 
        background-color: {C_BG_MAIN} !important; 
        background-image: radial-gradient(circle at 50% 0%, {C_BG_GRAD} 0%, {C_BG_MAIN} 75%) !important;
        position: relative; 
        z-index: 1; 
    }}
    .stApp {{ background-color: transparent !important; color: {C_TEXT_MAIN}; padding-top: 2rem; }}
    
    button[data-baseweb="tab"] {{ color: {C_TEXT_MUTED} !important; font-size: 16px !important; font-weight: 700 !important; background-color: transparent !important; padding: 8px 18px !important; transition: all 0.2s ease !important; }}
    button[data-baseweb="tab"]:hover {{ color: {C_TEXT_MAIN} !important; }}
    button[data-baseweb="tab"][aria-selected="true"] {{ color: {C_ACCENT} !important; font-weight: 800 !important; }}
    div[data-baseweb="tab-highlight"] {{ background-color: {C_ACCENT} !important; height: 3px !important; border-radius: 2px !important; }}
    div[data-baseweb="tab-border"] {{ background-color: {C_BORDER} !important; }}
    
    div[data-testid="stForm"] {{ background-color: {C_BG_CARD} !important; border: 2px solid {C_ACCENT} !important; border-radius: 12px !important; padding: 4px 6px 4px 14px !important; box-shadow: 0 0 15px {C_ACCENT}40 !important; }}
    div[data-testid="stForm"]:focus-within {{ border-color: {C_ACCENT_HOVER} !important; box-shadow: 0 0 20px {C_ACCENT_HOVER}80 !important; }}
    div[data-testid="stForm"] > div[data-testid="stVerticalBlock"] {{ width: 100% !important; display: flex !important; flex-direction: row !important; align-items: center !important; gap: 12px !important; margin: 0 !important; padding: 0 !important; }}
    .stTextInput {{ flex-grow: 1 !important; margin: 0 !important; padding: 0 !important; }}
    .stTextInput div[data-baseweb="base-input"], .stTextInput div[data-baseweb="input"] {{ background-color: {C_BG_CARD} !important; border: none !important; box-shadow: none !important; outline: none !important; }}
    
    .stTextInput input {{ background-color: {C_BG_CARD} !important; color: {C_TEXT_MAIN} !important; border: none !important; outline: none !important; box-shadow: none !important; font-size: 15px !important; height: 44px !important; padding-left: 36px !important; background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="%23{C_ACCENT[1:]}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>') !important; background-repeat: no-repeat !important; background-position: 4px center !important; }}
    .stTextInput input::placeholder {{ color: {C_TEXT_DARK} !important; opacity: 1 !important; font-weight: 500 !important; }}
    
    .stFormSubmitButton {{ margin: 0 !important; width: auto !important; flex-shrink: 0 !important; }}
    .stFormSubmitButton button {{ background-color: {C_ACCENT} !important; color: #ffffff !important; border: none !important; border-radius: 8px !important; font-weight: 800 !important; height: 38px !important; min-width: 84px !important; padding: 0 18px !important; font-size: 16px !important; transition: all 0.2s ease !important; }}
    .stFormSubmitButton button:hover {{ background-color: {C_ACCENT_HOVER} !important; box-shadow: 0 0 10px {C_ACCENT_HOVER}60 !important; color: #ffffff !important; }}
    
    .stButton button[kind="secondary"], .stDownloadButton button {{ background-color: {C_BG_CARD} !important; color: {C_TEXT_MAIN} !important; border: 1px solid {C_BORDER} !important; border-radius: 8px !important; font-weight: 700 !important; transition: all 0.2s ease; white-space: nowrap !important; }}
    .stButton button[kind="secondary"]:hover, .stDownloadButton button:hover {{ border-color: {C_ACCENT} !important; color: {C_ACCENT} !important; box-shadow: 0 0 10px {C_ACCENT}20 !important; }}
    
    .stButton button[kind="primary"] {{ background-color: {C_ACCENT} !important; color: #ffffff !important; border: 1px solid {C_ACCENT} !important; border-radius: 8px !important; font-weight: 800 !important; white-space: nowrap !important; box-shadow: 0 0 10px {C_ACCENT}40 !important; }}
    .stButton button[kind="primary"]:hover {{ background-color: {C_ACCENT_HOVER} !important; border-color: {C_ACCENT_HOVER} !important; box-shadow: 0 0 15px {C_ACCENT_HOVER}60 !important; color: #ffffff !important; }}

    .format-badge {{ background-color: {C_BG_CARD}; color: {C_ACCENT}; font-size: 17px; font-weight: 700; padding: 2px 6px; border-radius: 4px; margin-left: 6px; border: 1px solid {C_BORDER}; }}
    .meta-pill {{ background-color: {C_BG_CARD}; color: {C_TEXT_SUB}; font-size: 17px; padding: 8px 0px; border-radius: 8px; font-weight: 700; text-align: center; border: 1px solid {C_BORDER}; display: block; width: 100%; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }}
    
    .ai-box {{ background: linear-gradient(145deg, {C_BG_CARD} 0%, {C_BG_HOVER} 100%); border: 1px solid {C_ACCENT}; border-radius: 12px; padding: 24px; margin-top: 20px; box-shadow: 0 0 20px {C_ACCENT}20; }}
    div[data-testid="stWidgetLabel"] p, div[data-testid="stWidgetLabel"] label, label {{ color: {C_ACCENT} !important; font-size: 15px !important; font-weight: 700 !important; visibility: visible !important; display: block !important; }}
    .stTextArea textarea {{ background-color: {C_BG_CARD} !important; color: {C_TEXT_MAIN} !important; border: 1px solid {C_BORDER} !important; border-radius: 8px !important; font-size: 15px !important; }}
    .stTextArea textarea:focus {{ border-color: {C_ACCENT} !important; box-shadow: 0 0 10px {C_ACCENT}50 !important; }}
    div[data-baseweb="select"] > div {{ border: 1px solid {C_BORDER} !important; border-radius: 8px !important; background-color: {C_BG_CARD} !important; color: {C_TEXT_MAIN} !important;}}
    div[data-baseweb="tag"] {{ background-color: {C_BG_HOVER} !important; border: 1px solid {C_ACCENT} !important; }}
    div[data-baseweb="tag"] * {{ background-color: transparent !important; color: {C_ACCENT} !important; }}
</style>
''' , unsafe_allow_html=True)

def render_inline_search_box(target_id):
    if st.session_state.get('inline_search_target') == target_id:
        st.markdown(f"<div style='margin-top: 2px; margin-bottom: 12px; padding: 14px; border: 1px solid {C_ACCENT}; border-radius: 0 0 8px 8px; background-color: {C_BG_SEC}; box-shadow: 0 4px 12px rgba(0,0,0,0.2);'>", unsafe_allow_html=True)
        c_head, c_close = st.columns([8.5, 1.5])
        with c_head: st.markdown(f"<span style='color:{C_ACCENT}; font-weight:800; font-size:15px;'>⬇️ 즉시 재생 및 다운로드 (YouTube Top 5)</span>", unsafe_allow_html=True)
        with c_close:
            if st.button("✖ 닫기", key=f"close_{target_id}", use_container_width=True):
                st.session_state.inline_search_target = None
                st.rerun()
                
        if not st.session_state.get('inline_search_results'): st.warning("검색 결과가 없습니다.")
        else:
            for r_idx, video in enumerate(st.session_state.inline_search_results):
                v_duration = video.get('duration')
                t_str = f"{int(v_duration) // 60}:{int(v_duration) % 60:02d}" if v_duration else "미상"
                v_title = video.get('title', 'Unknown')
                unique_k = f"{target_id}_{r_idx}"
                
                c_title, c_play, c_dl = st.columns([6.0, 1.8, 2.2])
                with c_title:
                    st.markdown(f"<div style='padding-top:6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'>{yt_icon} <span style='color:{C_TEXT_MAIN}; font-size:14px; font-weight:600;'>{v_title}</span> <span style='color:{C_TEXT_DARK}; font-size:13px;'>({t_str})</span></div>", unsafe_allow_html=True)
                with c_play:
                    if st.button("▶ Play", key=f"inl_play_{unique_k}", use_container_width=True):
                        with st.spinner("연결 중..."):
                            try:
                                ydl_opts = {'format': 'bestaudio/best', 'quiet': True, 'geo_bypass': True}
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    info = ydl.extract_info(video['url'], download=False)
                                    st.session_state.inline_preview_target = unique_k
                                    st.session_state.inline_preview_url = info.get('url')
                                    st.rerun()
                            except Exception: st.warning("재생 불가")
                with c_dl:
                    active_fmt = st.session_state.get('active_format', 'MP3')
                    if unique_k in st.session_state.get('ready_downloads', {}):
                        f_info = st.session_state.ready_downloads[unique_k]
                        st.download_button(
                            label=f"💾 기기에 저장 ({active_fmt})",
                            data=f_info['bytes'],
                            file_name=f_info['filename'],
                            mime=f_info['mime'],
                            key=f"save_btn_inl_{unique_k}",
                            use_container_width=True
                        )
                    else:
                        if st.button(f"⬇ {active_fmt} 추출", key=f"inl_dl_{unique_k}", use_container_width=True):
                            target_codec = 'flac' if active_fmt == 'FLAC' else 'mp3'
                            st.session_state.inline_dl_status[unique_k] = "⏳ 추출 및 분석 중..."
                            dl_prog = st.progress(0.0)
                            
                            def inl_hook(d):
                                if d['status'] == 'downloading':
                                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                                    if total: dl_prog.progress(max(0.0, min(1.0, d.get('downloaded_bytes', 0) / total)))
                                    
                            try:
                                down_dir = st.session_state.local_dir
                                os.makedirs(down_dir, exist_ok=True)
                                ydl_dl_opts = {
                                    'format': 'bestaudio/best', 'outtmpl': os.path.join(down_dir, f'inl_{unique_k}_%(title)s.%(ext)s'),
                                    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': target_codec}],
                                    'quiet': True, 'geo_bypass': True, 'progress_hooks': [inl_hook]
                                }
                                if active_fmt != 'FLAC': ydl_dl_opts['postprocessors'][0]['preferredquality'] = '320'
                                
                                with yt_dlp.YoutubeDL(ydl_dl_opts) as ydl_d:
                                    i_dict = ydl_d.extract_info(video['url'], download=True)
                                    orig_f = ydl_d.prepare_filename(i_dict)
                                    clean_t, final_file_path = process_downloaded_file(i_dict, target_codec, orig_f, down_dir)
                                    
                                    dl_prog.empty()
                                    bpm, rb_key, camelot, cues, _ = analyze_track_pro(final_file_path)
                                    
                                    if os.path.exists(final_file_path):
                                        with open(final_file_path, "rb") as f_bytes:
                                            st.session_state.ready_downloads[unique_k] = {
                                                "bytes": f_bytes.read(),
                                                "filename": f"{clean_t}.{target_codec}",
                                                "mime": "audio/flac" if target_codec == "flac" else "audio/mpeg"
                                            }
                                        try: os.remove(final_file_path)
                                        except: pass

                                    if bpm and camelot:
                                        st.session_state.inline_dl_status[unique_k] = f"✅ 준비 완료! 위 [💾 기기에 저장]을 누르세요 | <span style='color:{C_PURPLE}; font-weight:800;'>{bpm} BPM &nbsp;·&nbsp; {rb_key} ({camelot}🎧)</span>"
                                    else:
                                        st.session_state.inline_dl_status[unique_k] = f"✅ 준비 완료: {clean_t}.{target_codec}"
                                    
                                st.rerun()
                            except Exception:
                                dl_prog.empty()
                                st.session_state.inline_dl_status[unique_k] = "⚠️ 추출 실패"
                                st.rerun()

                if st.session_state.get('inline_preview_target') == unique_k and st.session_state.get('inline_preview_url'):
                    st.audio(st.session_state.inline_preview_url, autoplay=True)
                
                if unique_k in st.session_state.get('inline_dl_status', {}):
                    status_msg = st.session_state.inline_dl_status[unique_k]
                    s_color = C_SUCCESS if "완료" in status_msg else C_DANGER
                    st.markdown(f"<div style='text-align:right; color:{s_color}; font-size:13px; font-weight:700;'>{status_msg}</div>", unsafe_allow_html=True)
                st.markdown(f"<hr style='margin: 6px 0; border-top: 1px dashed {C_BORDER};'>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

def trigger_search(query_str):
    st.session_state.search_input_value = query_str
    st.session_state.search_query = query_str
    st.session_state.auto_search = True
    st.session_state.current_view = "Search"
    st.session_state.page = 1

def save_key_callback():
    curr_gemini = st.session_state.get("gemini_api_key_input", "").strip()
    curr_groq = st.session_state.get("groq_api_key_input", "").strip()
    
    if curr_gemini or curr_groq:
        save_api_keys(curr_gemini, curr_groq)
        st.session_state.key_save_status = "success"
    else:
        st.session_state.key_save_status = "empty"

# 세션 상태 초기화
if 'bookmarks' not in st.session_state: st.session_state.bookmarks = []
if 'ai_history' not in st.session_state: st.session_state.ai_history = []
if 'current_view' not in st.session_state: st.session_state.current_view = "Search"
if 'search_query' not in st.session_state: st.session_state.search_query = ""
if 'search_results' not in st.session_state: st.session_state.search_results = []
if 'page' not in st.session_state: st.session_state.page = 1
if 'active_preview' not in st.session_state: st.session_state.active_preview = None
if 'preview_url' not in st.session_state: st.session_state.preview_url = None
if 'ai_active_preview' not in st.session_state: st.session_state.ai_active_preview = None
if 'ai_preview_url' not in st.session_state: st.session_state.ai_preview_url = None
if 'active_format' not in st.session_state: st.session_state.active_format = "MP3"
if 'download_queue' not in st.session_state: st.session_state.download_queue = []
if 'download_status' not in st.session_state: st.session_state.download_status = {}
if 'ready_downloads' not in st.session_state: st.session_state.ready_downloads = {}
if 'analyzed_cache' not in st.session_state: st.session_state.analyzed_cache = {}
if 'local_dir' not in st.session_state: st.session_state.local_dir = CLOUD_TEMP_DIR

global_loaded_keys = load_api_keys()
if 'gemini_api_key_input' not in st.session_state: st.session_state.gemini_api_key_input = global_loaded_keys.get("gemini", "")
if 'groq_api_key_input' not in st.session_state: st.session_state.groq_api_key_input = global_loaded_keys.get("groq", "")

if 'inline_search_target' not in st.session_state: st.session_state.inline_search_target = None
if 'inline_search_results' not in st.session_state: st.session_state.inline_search_results = []
if 'inline_preview_target' not in st.session_state: st.session_state.inline_preview_target = None
if 'inline_preview_url' not in st.session_state: st.session_state.inline_preview_url = None
if 'inline_dl_status' not in st.session_state: st.session_state.inline_dl_status = {}

if 'search_input_value' not in st.session_state:
    st.session_state.search_input_value = st.session_state.search_query


# ==========================================
# 🚀 1. 메인 네비게이션 탭
# ==========================================
c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
with c1:
    is_search_view = st.session_state.current_view == "Search"
    if st.button("SEARCH 🔍", type="primary" if is_search_view else "secondary", use_container_width=True, key="view_search"):
        st.session_state.current_view = "Search"
        st.rerun()
with c2:
    is_tracklist_view = st.session_state.current_view == "Tracklist"
    if st.button("TRACKS 🔗", type="primary" if is_tracklist_view else "secondary", use_container_width=True, key="view_tracklist"):
        st.session_state.current_view = "Tracklist"
        st.rerun()
with c3:
    is_bm_view = st.session_state.current_view == "Bookmarks"
    b_label = f"BOOKMARKS ({len(st.session_state.bookmarks)}) ⭐"
    if st.button(b_label, type="primary" if is_bm_view else "secondary", use_container_width=True, key="view_bm"):
        st.session_state.current_view = "Bookmarks"
        st.rerun()
with c4:
    is_ai_view = st.session_state.current_view == "AI"
    if st.button("AI STUDIO 🎛️", type="primary" if is_ai_view else "secondary", use_container_width=True, key="view_ai"):
        st.session_state.current_view = "AI"
        st.rerun()
with c5:
    theme_lbl = "☀️ Light" if st.session_state.app_theme == "Dark" else "🌙 Dark"
    if st.button(theme_lbl, type="secondary", use_container_width=True, key="toggle_theme"):
        st.session_state.app_theme = "Light" if st.session_state.app_theme == "Dark" else "Dark"
        st.rerun()

st.markdown(f"<hr style='margin: 10px 0 20px 0; border: none; border-top: 1px solid {C_BORDER};'>", unsafe_allow_html=True)


# ==========================================
# 🚀 2. 글로벌 다운로드 포맷 설정
# ==========================================
if st.session_state.current_view in ["Search", "Bookmarks", "AI"]:
    col_fmt_lbl, col_mp3, col_flac, _ = st.columns([1.5, 1.2, 1.2, 6.1])
    with col_fmt_lbl:
        st.markdown(f"<div style='text-align:left; color:{C_ACCENT}; font-weight:700; font-size:15px; padding-top:6px;'>⚙ 다운로드 포맷 설정:</div>", unsafe_allow_html=True)
    with col_mp3:
        is_mp3_active = st.session_state.active_format == "MP3"
        if st.button("MP3", type="primary" if is_mp3_active else "secondary", use_container_width=True, key="fmt_mp3_global"):
            st.session_state.active_format = "MP3"
            st.rerun()
    with col_flac:
        is_flac_active = st.session_state.active_format == "FLAC"
        if st.button("FLAC", type="primary" if is_flac_active else "secondary", use_container_width=True, key="fmt_flac_global"):
            st.session_state.active_format = "FLAC"
            st.rerun()
    st.markdown("<br>", unsafe_allow_html=True)


# ==========================================
# 🚀 3. 화면별 개별 콘텐츠 렌더링
# ==========================================

if st.session_state.current_view == "AI":
    st.markdown(f'''
    <div class="ai-box">
        <h3 style="color:{C_ACCENT}; margin-top:0;">🎛 AI Harmonic Mix & Curation Studio</h3>
        <p style="color:{C_TEXT_SUB}; font-size: 16px;">디깅부터 믹스셋 생성, AI 큐레이션 및 카멜롯 휠 하모닉 믹스 분석까지 통합 활용해보세요.</p>
    </div>
    ''', unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    if 'custom_playlist' not in st.session_state: st.session_state.custom_playlist = []
    if 'uploader_key' not in st.session_state: st.session_state.uploader_key = 0

    tab1, tab2 = st.tabs(["📂 내 음원 파일로 믹스셋 짜기", "✨ AI 맞춤형 플레이리스트"])

    with tab1:
        st.markdown(f"<br><p style='color:{C_ACCENT}; font-weight:700; margin-bottom:10px;'>🎯 플레이리스트 생성 옵션</p>", unsafe_allow_html=True)
        default_min, default_max = 120, 128
        if st.session_state.custom_playlist:
            bpms = [t['bpm'] for t in st.session_state.custom_playlist if t.get('bpm')]
            if bpms:
                default_min = max(60, min(bpms) - 2)
                default_max = min(220, max(bpms) + 2)
                
        col_time, col_bpm = st.columns([1, 1])
        with col_time: target_time_str = st.selectbox("⏳ 목표 플레이 타임", ["15분 (Short Mix)", "30분 (Standard Mix)", "1시간 (Long Mix)", "제한 없음 (전체 곡)"])
        with col_bpm: target_bpm_range = st.slider("🎚 목표 BPM 범위", min_value=60, max_value=220, value=(default_min, default_max), step=1)
            
        st.markdown("<br>", unsafe_allow_html=True)
        uploaded_files = st.file_uploader("🎵 분석할 음원 파일 추가 (여러 파일 동시 선택 및 드래그 앤 드롭 가능)", type=["mp3", "flac", "wav"], accept_multiple_files=True, key=f"mix_uploader_{st.session_state.uploader_key}")
        
        if uploaded_files:
            current_names = [t['name'] for t in st.session_state.custom_playlist]
            for f in uploaded_files:
                if f.name not in current_names:
                    with st.spinner(f"오디오 정밀 스캔 중: {f.name}"):
                        ext_suffix = os.path.splitext(f.name)[1] or ".mp3"
                        with tempfile.NamedTemporaryFile(delete=False, suffix=ext_suffix) as tmp:
                            tmp.write(f.getvalue())
                            tmp_path = tmp.name
                        bpm, rb_key, camelot, cues, duration = analyze_track_pro(tmp_path)
                        try: os.remove(tmp_path)
                        except Exception: pass
                        if bpm and camelot:
                            st.session_state.custom_playlist.append({
                                "name": f.name, "bpm": bpm, "key": rb_key, "camelot": camelot,
                                "comp_keys": get_compatible_keys(camelot), "cues": cues, "duration": duration
                            })
            st.session_state.uploader_key += 1
            st.rerun()

        if st.session_state.custom_playlist:
            st.markdown(f"<p style='color:{C_ACCENT}; font-weight:700; margin-bottom:10px;'>📋 업로드된 원본 트랙 리스트</p>", unsafe_allow_html=True)
            tracks_to_delete = []
            for idx, track in enumerate(st.session_state.custom_playlist):
                col_num, col_title, col_del = st.columns([0.6, 8.4, 1])
                with col_num: st.markdown(f"<div style='color:{C_ACCENT}; font-weight:800; padding-top:10px; font-size:17px;'>{idx+1}</div>", unsafe_allow_html=True)
                with col_title:
                    c_badge = f"{track['key']} ({track['camelot']})" if track['camelot'] else track['key']
                    st.markdown(f'''
                    <div style="background-color:{C_BG_CARD}; border:1px solid {C_BORDER}; border-radius:8px; padding:10px 14px; color:{C_TEXT_MAIN}; font-weight:600; font-size:16px; display:flex; justify-content:space-between; align-items:center;">
                        <span>{track['name']}</span>
                        <span style="color:{C_ACCENT}; font-size:16px; font-weight:700; background-color:{C_BG_HOVER}; padding:2px 8px; border-radius:4px; border:1px solid {C_BORDER};">{track['bpm']} BPM &nbsp;|&nbsp; {c_badge}</span>
                    </div>
                    ''', unsafe_allow_html=True)
                with col_del:
                    if st.button("삭제", key=f"del_track_{idx}", use_container_width=True): tracks_to_delete.append(idx)
                        
            if tracks_to_delete:
                for idx in sorted(tracks_to_delete, reverse=True): st.session_state.custom_playlist.pop(idx)
                st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)
            valid_data = st.session_state.custom_playlist
            if valid_data:
                st.markdown(f"<p style='color:{C_ACCENT}; font-weight:700; margin-top:20px; margin-bottom:10px;'>🎛️ AI 추천 최종 믹싱 플레이리스트</p>", unsafe_allow_html=True)
                target_time_sec = None
                if "15분" in target_time_str: target_time_sec = 15 * 60
                elif "30분" in target_time_str: target_time_sec = 30 * 60
                elif "1시간" in target_time_str: target_time_sec = 60 * 60
                mix_seq = generate_mix_sequence(valid_data, bpm_range=target_bpm_range, target_time_sec=target_time_sec)
                
                if not mix_seq:
                    st.warning("선택하신 BPM 범위에 해당하는 곡이 없습니다. 범위를 넓혀보세요!")
                else:
                    seq_elements = []
                    for idx, t in enumerate(mix_seq):
                        cues = t.get('cues', {'intro': {'bb': '1마디 1박', 't': '00:00'}, 'build': {'bb': '1마디 1박', 't': '00:00'}, 'drop': {'bb': '1마디 1박', 't': '00:00'}, 'outro': {'bb': '1마디 1박', 't': '00:00'}})
                        if isinstance(cues.get('intro'), str):
                            cues = {'intro': {'bb': cues['intro'], 't': cues['intro']}, 'build': {'bb': '분석중', 't': '00:00'}, 'drop': {'bb': cues['drop'], 't': cues['drop']}, 'outro': {'bb': cues['outro'], 't': cues['outro']}}
                        c_str = f"{t['key']} ({t['camelot']})" if t['camelot'] else t['key']
                        card = (
                            f'<div style="background-color:{C_BG_CARD}; border: 1px solid {C_BORDER}; border-radius: 8px; padding: 12px 16px; margin-bottom: 4px;">'
                            f'<span style="color:{C_ACCENT}; font-weight:800; margin-right:10px;">#{idx+1}</span>'
                            f'<span style="color:{C_TEXT_MAIN}; font-weight:600; font-size:16px;">{t["name"]}</span><br>'
                            f'<span style="color:{C_TEXT_MUTED}; font-weight:700; font-size:16px; margin-left: 28px;">[{t["bpm"]} BPM | {c_str}]</span>'
                            f'<div style="margin-top: 10px; margin-left: 28px; padding: 10px; background-color: {C_BG_SEC}; border-radius: 6px; font-size: 17px; color: {C_TEXT_MUTED}; border-left: 2px solid {C_ACCENT}; line-height: 1.6;">'
                            f'📍 <b>추천 큐 포인트 (마디/박자)</b><br>'
                            f'<span style="color:{C_SUCCESS};">▶ Intro</span> {cues["intro"]["bb"]} ({cues["intro"]["t"]}) &nbsp;|&nbsp; '
                            f'<span style="color:{C_PURPLE};">📈 Build-up</span> {cues["build"]["bb"]} ({cues["build"]["t"]}) &nbsp;|&nbsp; '
                            f'<span style="color:{C_WARN};">🔥 Drop</span> {cues["drop"]["bb"]} ({cues["drop"]["t"]}) &nbsp;|&nbsp; '
                            f'<span style="color:{C_DANGER};">⏬ Outro</span> {cues["outro"]["bb"]} ({cues["outro"]["t"]})'
                            f'</div>'
                            f'</div>'
                        )
                        seq_elements.append(card)
                        
                        if idx < len(mix_seq) - 1:
                            next_t = mix_seq[idx+1]
                            next_cues = next_t.get('cues', {'intro': {'bb': '1마디 1박', 't': '00:00'}, 'build': {'bb': '1마디 1박', 't': '00:00'}, 'drop': {'bb': '1마디 1박', 't': '00:00'}, 'outro': {'bb': '1마디 1박', 't': '00:00'}})
                            if isinstance(next_cues.get('intro'), str):
                                next_cues = {'intro': {'bb': next_cues['intro'], 't': next_cues['intro']}, 'build': {'bb': '분석중', 't': '00:00'}, 'drop': {'bb': next_cues['drop'], 't': next_cues['drop']}, 'outro': {'bb': next_cues['outro'], 't': next_cues['outro']}}
                            key_match = next_t['camelot'] in t['comp_keys']
                            bpm_diff = next_t['bpm'] - t['bpm']
                            bpm_str = f"+{bpm_diff}" if bpm_diff >= 0 else f"{bpm_diff}"
                            if key_match: match_text = f"<span style='color:{C_SUCCESS}; font-weight:700;'>✨ Perfect Match (Key 호환)</span> &nbsp;|&nbsp; <span style='color:{C_TEXT_SUB};'>BPM {bpm_str}</span>"
                            else: match_text = f"<span style='color:{C_DANGER}; font-weight:700;'>⚠️ Key 불일치 (루프/효과음 믹싱 권장)</span> &nbsp;|&nbsp; <span style='color:{C_TEXT_SUB};'>BPM {bpm_str}</span>"
                                
                            divider = (
                                f'<div style="text-align:center; background-color:{C_BG_SEC}; border-radius:6px; padding:12px 0; margin: 6px 0; font-size:17px;">'
                                f'⬇️ {match_text}<br>'
                                f'<div style="margin-top:12px; color:{C_TEXT_MAIN}; text-align:left; display:inline-block; line-height: 1.6;">'
                                f'<div style="background-color:{C_BG_CARD}; padding:8px 14px; border-radius:6px; border:1px solid {C_BORDER}; margin-bottom: 6px;">'
                                f'🎧 <b>Option 1 (Standard Blend):</b> 윗 곡 <span style="color:{C_DANGER};">[Outro / {cues["outro"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:{C_SUCCESS};">[Intro / {next_cues["intro"]["bb"]}]</span> 매칭'
                                f'</div>'
                                f'<div style="background-color:{C_BG_CARD}; padding:8px 14px; border-radius:6px; border:1px solid {C_BORDER};">'
                                f'🎧 <b>Option 2 (Drop/Slam Mix):</b> 윗 곡 <span style="color:{C_PURPLE};">[Build-up / {cues["build"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:{C_WARN};">[Drop / {next_cues["drop"]["bb"]}]</span> 즉시 전환'
                                f'</div>'
                                f'</div>'
                                f'</div>'
                            )
                            seq_elements.append(divider)
                    st.markdown("".join(seq_elements), unsafe_allow_html=True)

    with tab2:
        st.markdown(f"<br><p style='color:{C_ACCENT}; font-weight:700; margin-bottom:10px;'>✨ 자연어 & 레퍼런스 기반 플레이리스트 큐레이션</p>", unsafe_allow_html=True)
        st.markdown(f"<p style='color:{C_TEXT_MUTED}; font-size:15px; margin-bottom:20px;'>듀얼 엔진(Groq/Gemini) 자동 우회 시스템과 모델별 추론/사고 엔진 선택이 지원됩니다. (입력하신 API 키는 현재 브라우저 세션에만 안전하게 보관됩니다.)</p>", unsafe_allow_html=True)
        
        saved_keys = load_api_keys()
        
        col_groq, col_gemini, col_save = st.columns([4.2, 4.2, 1.6])
        with col_groq:
            api_key_groq = st.text_input("⚡ Groq API Key (초고속 엔진)", type="password", placeholder="gsk_...", key="groq_api_key_input")
            if saved_keys.get("groq"): st.markdown(f"<span style='color:{C_SUCCESS}; font-size:13px; font-weight:600;'>✓ 현재 세션에 적용됨 ({saved_keys['groq'][:6]}...)</span>", unsafe_allow_html=True)
        with col_gemini:
            api_key_gemini = st.text_input("🧠 Gemini API Key (정밀/한글 엔진)", type="password", placeholder="AI Studio 키", key="gemini_api_key_input")
            if saved_keys.get("gemini"): st.markdown(f"<span style='color:{C_SUCCESS}; font-size:13px; font-weight:600;'>✓ 현재 세션에 적용됨 ({saved_keys['gemini'][:6]}...)</span>", unsafe_allow_html=True)
        with col_save:
            st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
            st.button("💾 Keys 적용", use_container_width=True, key="btn_save_keys", on_click=save_key_callback)

        if st.session_state.get("key_save_status") == "success":
            st.success("✅ 현재 브라우저 세션에 키가 안전하게 적용되었습니다!")
            st.session_state.key_save_status = None
        elif st.session_state.get("key_save_status") == "empty":
            st.warning("키를 입력하세요")
            st.session_state.key_save_status = None
            
        st.markdown(f"<hr style='margin: 15px 0; border: none; border-top: 1px solid {C_BORDER};'>", unsafe_allow_html=True)
        
        col_engine_sel, col_model_sel = st.columns([1, 1])
        with col_engine_sel:
            engine_choice = st.radio("🚀 메인 AI 엔진 선택 (서버 지연 시 자동 우회)", ["Groq (초고속/글로벌 팝 ⚡)", "Gemini (정밀/국내 가요 🧠)"], horizontal=True)
        
        with col_model_sel:
            if "Groq" in engine_choice:
                groq_models = {
                    "GPT-OSS 120B (최신 고성능/기본 권장 🧠)": "openai/gpt-oss-120b",
                    "Llama 3.3 70B Versatile (안정적/다목적)": "llama-3.3-70b-versatile",
                    "GPT-OSS 20B (초고속/경량 ⚡)": "openai/gpt-oss-20b"
                }
                selected_model_name = st.selectbox("🤖 Groq 사고/모델 버전 선택", list(groq_models.keys()), index=0)
                selected_groq_model = groq_models[selected_model_name]
                selected_gemini_model = "gemini-2.5-flash"
            else:
                gemini_models = {
                    "2.5 Flash (빠른 큐레이션 / 기본 권장)": "gemini-2.5-flash",
                    "2.5 Pro (고급 추론 / 심층 사고 🧠)": "gemini-2.5-pro",
                    "2.0 Flash (초경량 / 빠른 속도 ⚡)": "gemini-2.0-flash"
                }
                selected_model_name = st.selectbox("🤖 Gemini 사고/모델 버전 선택", list(gemini_models.keys()), index=0)
                selected_gemini_model = gemini_models[selected_model_name]
                selected_groq_model = "openai/gpt-oss-120b"

        ref_yt_link = st.text_input("🔗 YouTube 레퍼런스 영상 링크 (선택 사항)", placeholder="예: https://www.youtube.com/watch?v=...", key="gemini_ref_yt_input")
        curation_genres = ["Disco (정통 디스코)", "Nu Disco", "Funk / Soul", "Jazz (재즈)", "Classical (클래식)", "Lo-Fi / Chillhop", "Acoustic / Folk", "Pop / Mainstream", "K-Pop", "R&B / Soul", "Hip Hop / Trap", "Indie Rock / Band", "Ambient / New Age", "City Pop", "Bossa Nova", "Deep House / EDM", "Synthwave / Retro", "OST / 영화·드라마 음악", "Piano Solo"]
        
        col_genre_select, col_count = st.columns([7.5, 2.5])
        with col_genre_select: selected_genres = st.multiselect("선호 장르 선택 (선택 사항, 복수 선택 가능)", curation_genres, default=[], help="비워둘 경우 AI가 레퍼런스 및 요청 내용만으로 장르를 결정합니다.")
        with col_count: track_count = st.selectbox("추천 곡 수", [5, 10, 15, 20, 25, 30], index=1)

        user_prompt = st.text_area("어떤 분위기나 상황의 음악이 필요한가요?", placeholder="예: 70~80년대 정통 디스코 사운드, 브라스와 현악기 세션이 살아있는 신나는 곡 (bpm 100~115)", height=100, key="gemini_user_prompt_input")
        
        if st.button("🎵 AI 플레이리스트 생성", use_container_width=True, key="btn_gen_ai_playlist"):
            active_groq = api_key_groq.strip() or saved_keys.get("groq")
            active_gemini = api_key_gemini.strip() or saved_keys.get("gemini")
            
            if not active_groq and not active_gemini:
                st.warning("Groq 또는 Gemini API Key 중 하나는 반드시 입력해주세요.")
            elif not user_prompt and not selected_genres and not ref_yt_link:
                st.warning("레퍼런스 링크, 선호 장르, 분위기/상황 설명 중 적어도 하나를 입력해주세요.")
            else:
                # 입력된 키를 현재 세션에 자동 반영
                save_api_keys(active_gemini or "", active_groq or "")
                ref_info_context = ""
                if ref_yt_link:
                    with st.spinner("🔗 YouTube 레퍼런스 영상 분석 중..."):
                        try:
                            ydl_ref_opts = {'quiet': True, 'skip_download': True}
                            with yt_dlp.YoutubeDL(ydl_ref_opts) as ydl_ref:
                                r_info = ydl_ref.extract_info(ref_yt_link, download=False)
                                r_title, r_artist = r_info.get('title', ''), r_info.get('artist') or r_info.get('uploader', '')
                                r_tags = ", ".join(r_info.get('tags', [])[:6]) if r_info.get('tags') else ""
                                ref_info_context = f"\n- 기준 레퍼런스 곡: '{r_title}' (아티스트: {r_artist})\n- 태그: {r_tags}\n(이 곡의 장르, 질감, BPM 분위기와 결이 유사한 곡 선곡할 것)"
                        except Exception as re_err: st.warning(f"레퍼런스 링크 분석 실패: {re_err}")

                genre_instruction = f"- 지정 장르: {', '.join(selected_genres)}" if selected_genres else "- 장르: 요청 상황에 최적화된 장르"
                user_req_text = f"- 세부 분위기/조건: {user_prompt}" if user_prompt else ""
                
                prompt_text = f"""당신은 전 세계 모든 음악을 꿰뚫고 있는 전설적인 큐레이터입니다.
                다음 조건과 레퍼런스를 바탕으로 정확히 {track_count}곡의 플레이리스트를 구성하세요.
                [선곡 기준 및 조건]
                {genre_instruction}
                {ref_info_context}
                {user_req_text}
                [출력 형식 제약]
                반드시 아래 JSON 규격으로만 응답해야 합니다. 마크다운이나 기타 텍스트는 일절 제외하세요.
                {{ "playlistTitle": "테마를 관통하는 감성적인 플레이리스트 제목", "description": "선곡 테마 설명 (2~3문장)", "tracks": [ {{ "title": "정확한 곡 제목", "artist": "정확한 아티스트명", "reason": "해당 곡 선곡 이유 1문장" }} ] }}"""
                
                primary_engine = "Groq" if "Groq" in engine_choice else "Gemini"
                engine_queue = [primary_engine, "Gemini" if primary_engine == "Groq" else "Groq"]
                
                success, last_error, executed_model = False, None, None
                parsed_playlist = None

                for target_engine in engine_queue:
                    if target_engine == "Groq" and not active_groq: continue
                    if target_engine == "Gemini" and not active_gemini: continue
                    
                    target_model_name = selected_groq_model if target_engine == "Groq" else selected_gemini_model
                    with st.spinner(f"[{target_engine} | {target_model_name}] 모델이 {track_count}곡을 선곡 중입니다..."):
                        try:
                            raw_output = ""
                            if target_engine == "Groq":
                                from groq import Groq
                                client = Groq(api_key=active_groq)
                                completion = client.chat.completions.create(
                                    model=selected_groq_model,
                                    messages=[{"role": "user", "content": prompt_text}],
                                    temperature=0.7,
                                    response_format={"type": "json_object"}
                                )
                                raw_output = completion.choices[0].message.content
                            else:
                                try:
                                    from google import genai
                                    from google.genai import types
                                    client = genai.Client(api_key=active_gemini)
                                    response = client.models.generate_content(model=selected_gemini_model, contents=prompt_text, config=types.GenerateContentConfig(response_mime_type="application/json"))
                                    raw_output = response.text
                                except ImportError:
                                    import google.generativeai as legacy_genai
                                    legacy_genai.configure(api_key=active_gemini)
                                    legacy_model = legacy_genai.GenerativeModel(model_name=selected_gemini_model, generation_config={"response_mime_type": "application/json"})
                                    raw_output = legacy_model.generate_content(prompt_text).text
                            
                            clean_text = raw_output.strip()
                            if clean_text.startswith("```json"): clean_text = clean_text[7:]
                            if clean_text.startswith("```"): clean_text = clean_text[3:]
                            if clean_text.endswith("```"): clean_text = clean_text[:-3]
                            
                            parsed_playlist = json.loads(clean_text.strip())
                            success, executed_model = True, f"{target_engine} ({target_model_name})"
                            break
                            
                        except Exception as ex:
                            last_error = ex
                            st.warning(f"⚠️ [{target_engine}] 호출 실패 (원인: {ex}) - 우회 경로를 탐색합니다...")
                            time.sleep(0.5)
                            
                if not success:
                    st.error(f"모든 AI 엔진 호출에 실패했습니다: {last_error}")
                else:
                    with st.spinner("iTunes API에서 고화질 앨범 아트와 메타데이터를 연동 중입니다..."):
                        for trk in parsed_playlist.get("tracks", []):
                            try:
                                q_str = urllib.parse.quote(f"{trk['artist']} {trk['title']}")
                                itunes_res = requests.get(f"[https://itunes.apple.com/search?term=](https://itunes.apple.com/search?term=){q_str}&entity=song&limit=1", timeout=3).json()
                                if itunes_res.get('resultCount', 0) > 0:
                                    high_res_img = itunes_res['results'][0].get('artworkUrl100', '').replace('100x100bb', '300x300bb')
                                    trk['cover'] = high_res_img
                                else: trk['cover'] = ""
                            except: trk['cover'] = ""

                    analyzed_ai_tracks = []
                    tracks_list = parsed_playlist.get("tracks", [])
                    if tracks_list:
                        with st.spinner("🎧 선곡된 트랙들을 오디오 스트림으로 자동 분석 중입니다 (약 1~2분 소요)..."):
                            my_prog = st.progress(0.0, text="안전 모드로 오디오 분석 중...")
                            track_names = [f"{trk.get('artist', '')} - {trk.get('title', '')}" for trk in tracks_list]
                            
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                                futures = [executor.submit(fetch_and_analyze_single_track, name, st.session_state.local_dir) for name in track_names]
                                completed_count = 0
                                for f in concurrent.futures.as_completed(futures):
                                    res = f.result()
                                    if res: analyzed_ai_tracks.append(res)
                                    completed_count += 1
                                    my_prog.progress(completed_count / len(track_names), text=f"오디오 분석 중... ({completed_count}/{len(track_names)}) 완료")
                                    time.sleep(1.5)
                            
                            my_prog.empty()

                    mix_seq_result = None
                    if analyzed_ai_tracks:
                        mix_seq_result = generate_mix_sequence(analyzed_ai_tracks)
                        missed_count = len(tracks_list) - len(analyzed_ai_tracks)
                        if missed_count > 0:
                            st.session_state.analysis_msg = f"⚠️ {missed_count}곡은 유튜브 연령 제한 등으로 분석에서 제외되었습니다."
                        else:
                            st.session_state.analysis_msg = f"✨ 총 {len(analyzed_ai_tracks)}곡의 클래식 조성 및 카멜롯 휠 하모닉 믹스 정렬이 완료되었습니다!"
                    else:
                        st.session_state.analysis_msg = "⚠️ 음원 분석에 실패했습니다. 유튜브 연결 상태를 확인해주세요."

                    st.session_state.ai_playlist = parsed_playlist
                    st.session_state.ai_mix_sequence = mix_seq_result
                    st.session_state.ai_active_preview = None
                    st.session_state.ai_preview_url = None
                    
                    history_entry = {
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
                        "model": executed_model,
                        "request_summary": user_prompt if user_prompt else (", ".join(selected_genres) if selected_genres else "레퍼런스 기반"),
                        "playlist": parsed_playlist,
                        "mix_sequence": mix_seq_result 
                    }
                    st.session_state.ai_history.insert(0, history_entry)
                    save_ai_history(st.session_state.ai_history)

        if 'ai_playlist' in st.session_state and st.session_state.ai_playlist:
            pl = st.session_state.ai_playlist
            tracks = pl.get('tracks', [])
            
            col_title_area, col_export_btn = st.columns([6.5, 3.5])
            with col_title_area:
                st.markdown(f"<br><h3 style='color:{C_ACCENT}; font-weight:800; margin-bottom:4px; word-break: keep-all; overflow-wrap: break-word; line-height: 1.4;'>🎧 {pl.get('playlistTitle', 'AI 추천 플레이리스트')} ({len(tracks)}곡)</h3>", unsafe_allow_html=True)
            with col_export_btn:
                st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
                json_export_str = json.dumps(pl, ensure_ascii=False, indent=4)
                h_safe_title = re.sub(r'[\\*?:"<>|/]', "", pl.get('playlistTitle', 'playlist')).replace(' ', '_')
                st.download_button(
                    label="📥 플레이리스트 파일로 내보내기", 
                    data=json_export_str, 
                    file_name=f"{h_safe_title}.json", 
                    mime="application/json", 
                    use_container_width=True, 
                    key="download_current_playlist_file"
                )

            st.markdown(f"<p style='color:{C_TEXT_SUB}; font-size:16px; margin-bottom:20px;'>{pl.get('description', '')}</p>", unsafe_allow_html=True)
            
            if st.session_state.get('analysis_msg'):
                if "⚠️" in st.session_state.analysis_msg: st.warning(st.session_state.analysis_msg)
                else: st.success(st.session_state.analysis_msg)
                st.session_state.analysis_msg = "" 

            if st.session_state.get('ai_mix_sequence'):
                st.markdown(f"<br><h4 style='color:{C_SUCCESS}; font-weight:800;'>🎛 클래식 조성 및 카멜롯 휠 하모닉 믹스 추천 플레이리스트 순서</h4>", unsafe_allow_html=True)
                mix_seq = st.session_state.ai_mix_sequence
                for idx, t in enumerate(mix_seq):
                    cues = t.get('cues', {"intro": {"bb": "1마디 1박", "t": "00:00"}, "build": {"bb": "17마디 1박", "t": "01:04"}, "drop": {"bb": "33마디 1박", "t": "02:08"}, "outro": {"bb": "81마디 1박", "t": "04:30"}})
                    if isinstance(cues.get('intro'), str): cues = {'intro': {'bb': cues['intro'], 't': cues['intro']}, 'build': {'bb': '분석중', 't': '00:00'}, 'drop': {'bb': cues['drop'], 't': cues['drop']}, 'outro': {'bb': cues['outro'], 't': cues['outro']}}
                    c_str = f"{t['key']} ({t['camelot']})" if t['camelot'] else t['key']

                    with st.container(border=True):
                        col_seq_info, col_seq_btns = st.columns([7, 3])
                        with col_seq_info:
                            st.markdown(f"<span style='color:{C_ACCENT}; font-weight:800; font-size:17px;'>#{idx+1} {t['name']}</span>", unsafe_allow_html=True)
                            st.markdown(f"<span style='color:{C_TEXT_MUTED}; font-weight:700; font-size:15px;'>[{t['bpm']} BPM | {c_str}]</span>", unsafe_allow_html=True)
                            st.markdown(f"""
                            <div style="margin-top: 8px; padding: 8px 12px; background-color: {C_BG_SEC}; border-radius: 6px; font-size: 14px; color: {C_TEXT_MUTED}; border-left: 2px solid {C_ACCENT}; line-height: 1.5;">
                            📍 <b>추천 큐 포인트 (마디/박자)</b><br>
                            <span style="color:{C_SUCCESS};">▶ Intro</span> {cues["intro"]["bb"]} ({cues["intro"]["t"]}) &nbsp;|&nbsp; 
                            <span style="color:{C_PURPLE};">📈 Build-up</span> {cues["build"]["bb"]} ({cues["build"]["t"]}) &nbsp;|&nbsp; 
                            <span style="color:{C_WARN};">🔥 Drop</span> {cues["drop"]["bb"]} ({cues["drop"]["t"]}) &nbsp;|&nbsp; 
                            <span style="color:{C_DANGER};">⏬ Outro</span> {cues["outro"]["bb"]} ({cues["outro"]["t"]})
                            </div>
                            """, unsafe_allow_html=True)
                            
                        with col_seq_btns:
                            st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
                            if st.button("▶ Play", key=f"mix_seq_play_{idx}", use_container_width=True):
                                with st.spinner("미리듣기 연결 중..."):
                                    try:
                                        with yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True, 'geo_bypass': True}) as ydl_s:
                                            res = ydl_s.extract_info(f"ytsearch1:{t['name']}", download=False)
                                            if res.get('entries') and res['entries'][0]:
                                                st.session_state.ai_active_preview = f"mix_{idx}"
                                                st.session_state.ai_preview_url = ydl_s.extract_info(res['entries'][0]['url'], download=False).get('url')
                                                st.rerun()
                                    except Exception: st.warning("실패")
                                        
                            if st.button("🔎 검색/다운", key=f"mix_seq_search_{idx}", use_container_width=True):
                                with st.spinner("검색 중..."):
                                    st.session_state.inline_search_target = f"curr_mix_{idx}"
                                    st.session_state.inline_search_results = fetch_tracks('YouTube', t['name'])[:5]
                                    st.session_state.inline_dl_status = {}
                                st.rerun()
                        
                        if st.session_state.get('ai_active_preview') == f"mix_{idx}" and st.session_state.get('ai_preview_url'):
                            st.audio(st.session_state.ai_preview_url, autoplay=True)
                            
                    render_inline_search_box(f"curr_mix_{idx}")
                    
                    if idx < len(mix_seq) - 1:
                        next_t = mix_seq[idx+1]
                        key_match = next_t['camelot'] in t['comp_keys']
                        bpm_diff = next_t['bpm'] - t['bpm']
                        bpm_str = f"+{bpm_diff}" if bpm_diff >= 0 else f"{bpm_diff}"
                        match_text = f"<span style='color:{C_SUCCESS}; font-weight:700;'>✨ Perfect Match (Key 호환)</span> &nbsp;|&nbsp; <span style='color:{C_TEXT_SUB};'>BPM {bpm_str}</span>" if key_match else f"<span style='color:{C_DANGER}; font-weight:700;'>⚠️ Key 불일치 (루프/효과음 믹싱 권장)</span> &nbsp;|&nbsp; <span style='color:{C_TEXT_SUB};'>BPM {bpm_str}</span>"
                        
                        next_cues = next_t.get('cues', {"intro": {"bb": "1마디 1박", "t": "00:00"}, "build": {"bb": "17마디 1박", "t": "01:04"}, "drop": {"bb": "33마디 1박", "t": "02:08"}, "outro": {"bb": "81마디 1박", "t": "04:30"}})
                        if isinstance(next_cues.get('intro'), str): next_cues = {'intro': {'bb': next_cues['intro']}, 'build': {'bb': '분석중'}, 'drop': {'bb': next_cues['drop']}, 'outro': {'bb': next_cues['outro']}}
                        
                        st.markdown(f"""
                        <div style="text-align:center; background-color:{C_BG_SEC}; border-radius:6px; padding:12px 0; margin: 6px 0; font-size:17px;">
                        ⬇️ {match_text}<br>
                        <div style="margin-top:12px; color:{C_TEXT_MAIN}; text-align:left; display:inline-block; line-height: 1.6;">
                        <div style="background-color:{C_BG_CARD}; padding:8px 14px; border-radius:6px; border:1px solid {C_BORDER}; margin-bottom: 6px;">
                        🎧 <b>Option 1 (Standard Blend):</b> 윗 곡 <span style="color:{C_DANGER};">[Outro / {cues["outro"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:{C_SUCCESS};">[Intro / {next_cues["intro"]["bb"]}]</span> 매칭
                        </div>
                        <div style="background-color:{C_BG_CARD}; padding:8px 14px; border-radius:6px; border:1px solid {C_BORDER};">
                        🎧 <b>Option 2 (Drop/Slam Mix):</b> 윗 곡 <span style="color:{C_PURPLE};">[Build-up / {cues["build"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:{C_WARN};">[Drop / {next_cues["drop"]["bb"]}]</span> 즉시 전환
                        </div>
                        </div>
                        </div>
                        """, unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)

            st.markdown(f"<p style='color:{C_ACCENT}; font-weight:700; margin-top:20px; margin-bottom:10px;'>📋 개별 트랙 큐레이션 상세 (앨범 아트 포함)</p>", unsafe_allow_html=True)
            for idx, track in enumerate(tracks):
                search_query = f"{track.get('artist', '')} - {track.get('title', '')}"
                cover_html = f"<img src='{track['cover']}' width='60' height='60' style='border-radius:6px; object-fit:cover; margin-right: 14px; box-shadow: 0 2px 5px rgba(0,0,0,0.5);'>" if track.get('cover') else f"<div style='width:60px; height:60px; background:{C_BORDER}; border-radius:6px; margin-right:14px; display:inline-block;'></div>"
                
                st.markdown(f"""
                <div style="background-color:{C_BG_CARD}; border:1px solid {C_BORDER}; border-radius:8px; padding:12px 16px; margin-bottom:8px; display:flex; align-items:center;">
                    {cover_html}
                    <div>
                        <div style="color:{C_ACCENT}; font-weight:800; font-size:17px; margin-bottom:4px;">#{idx+1} {search_query}</div>
                        <div style="color:{C_TEXT_MUTED}; font-size:14px;">💡 {track.get('reason', '')}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                col_blank, col_play, col_action = st.columns([6.2, 1.8, 2.0])
                with col_play:
                    if st.button("▶ Play", key=f"ai_play_{idx}", use_container_width=True):
                        with st.spinner("미리듣기 연결 중..."):
                            try:
                                with yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True, 'geo_bypass': True}) as ydl_s:
                                    res = ydl_s.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if res.get('entries') and res['entries'][0]:
                                        st.session_state.ai_active_preview = f"curr_{idx}"
                                        st.session_state.ai_preview_url = ydl_s.extract_info(res['entries'][0]['url'], download=False).get('url')
                                        st.rerun()
                            except Exception: st.warning("실패")
                with col_action:
                    if st.button("🔎 검색/다운", key=f"ai_track_search_{idx}", use_container_width=True):
                        with st.spinner("검색 중..."):
                            st.session_state.inline_search_target = f"curr_track_{idx}"
                            st.session_state.inline_search_results = fetch_tracks('YouTube', search_query)[:5]
                            st.session_state.inline_dl_status = {}
                        st.rerun()
                        
                if st.session_state.get('ai_active_preview') == f"curr_{idx}" and st.session_state.get('ai_preview_url'):
                    st.audio(st.session_state.ai_preview_url, autoplay=True)
                    
                render_inline_search_box(f"curr_track_{idx}")
                st.markdown(f"<hr style='margin: 12px 0; border: none; border-top: 1px solid {C_BORDER};'>", unsafe_allow_html=True)

        # AI 히스토리 백업 및 복원 영역
        st.markdown(f"<br><br><h4 style='color:{C_ACCENT}; font-weight:800; border-bottom:1px solid {C_BORDER}; padding-bottom:8px;'>📜 지난 AI 플레이리스트 기록 히스토리</h4>", unsafe_allow_html=True)
        with st.expander("💾 AI 히스토리 전체 백업 및 복원 (클라우드 데이터 유지용)"):
            c_hi_ex, c_hi_im = st.columns(2)
            with c_hi_ex:
                hi_json = json.dumps(st.session_state.ai_history, ensure_ascii=False, indent=4)
                st.download_button("📥 히스토리 전체 JSON 백업", data=hi_json, file_name="my_ai_history.json", mime="application/json", use_container_width=True)
            with c_hi_im:
                up_hi = st.file_uploader("📤 백업한 히스토리 JSON 불러오기", type=["json"], label_visibility="collapsed", key="upload_ai_hist_json")
                if up_hi:
                    try:
                        loaded_hi = json.load(up_hi)
                        if isinstance(loaded_hi, list):
                            st.session_state.ai_history = loaded_hi
                            save_ai_history(loaded_hi)
                            st.success("히스토리 복원 완료!")
                            st.rerun()
                    except Exception:
                        st.error("올바른 JSON 파일이 아닙니다.")

        if st.session_state.get('ai_history'):
            for h_idx, h_item in enumerate(st.session_state.ai_history):
                h_time = h_item.get("timestamp", "시간 미상")
                h_model = h_item.get("model", "")
                h_summary = h_item.get("request_summary", "")
                h_pl = h_item.get("playlist", {})
                h_title = h_pl.get("playlistTitle", "플레이리스트")
                h_tracks = h_pl.get("tracks", [])
                
                with st.expander(f"📁 [{h_time}] {h_title} ({len(h_tracks)}곡) - 엔진: {h_model}"):
                    col_h_btn1, col_h_btn2, col_del = st.columns([4.2, 4.2, 1.6])
                    
                    with col_h_btn1:
                        h_json_str = json.dumps(h_pl, ensure_ascii=False, indent=4)
                        h_safe_title = re.sub(r'[\\*?:"<>|/]', "", h_title).replace(' ', '_')
                        st.download_button(
                            label="📥 파일로 내보내기", 
                            data=h_json_str, 
                            file_name=f"history_{h_safe_title}.json", 
                            mime="application/json", 
                            key=f"hist_download_{h_idx}", 
                            use_container_width=True
                        )
                        
                    with col_h_btn2:
                        if not h_item.get('mix_sequence'):
                            if st.button("🎛️ 하모닉 믹스 분석 및 정렬", key=f"hist_mix_btn_{h_idx}", use_container_width=True):
                                with st.spinner("히스토리 곡들을 순차적으로 안전하게 분석 중입니다..."):
                                    analyzed_h_tracks = []
                                    h_prog = st.progress(0.0, text="안전 모드로 오디오 분석 중...")
                                    h_track_names = [f"{trk.get('artist', '')} - {trk.get('title', '')}" for trk in h_tracks]
                                    
                                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                                        futures = [executor.submit(fetch_and_analyze_single_track, name, st.session_state.local_dir) for name in h_track_names]
                                        completed_h = 0
                                        for f in concurrent.futures.as_completed(futures):
                                            res = f.result()
                                            if res: analyzed_h_tracks.append(res)
                                            completed_h += 1
                                            h_prog.progress(completed_h / len(h_tracks), text=f"안전 모드로 오디오 분석 중... ({completed_h}/{len(h_tracks)}) 완료")
                                            time.sleep(1.5)
                                    
                                    h_prog.empty()
                                    if analyzed_h_tracks:
                                        h_item['mix_sequence'] = generate_mix_sequence(analyzed_h_tracks)
                                        save_ai_history(st.session_state.ai_history)
                                        missed_count = len(h_tracks) - len(analyzed_h_tracks)
                                        if missed_count > 0:
                                            st.warning(f"⚠️ {missed_count}곡은 유튜브 연령 제한 등으로 제외되었습니다.")
                                        st.success(f"✨ 총 {len(analyzed_h_tracks)}곡의 하모닉 믹스 정렬 완료!")
                                        st.rerun()
                                    else: st.error("음원 분석에 실패했습니다. 유튜브 연결 상태를 확인해주세요.")

                    with col_del:
                        if st.button("🗑️ 기록 삭제", key=f"hist_delete_{h_idx}", use_container_width=True):
                            st.session_state.ai_history.pop(h_idx)
                            save_ai_history(st.session_state.ai_history)
                            st.rerun()

                    if h_item.get('mix_sequence'):
                        st.markdown(f"<p style='color:{C_SUCCESS}; font-weight:700; margin-top:12px;'>🎛 하모닉 믹스 정렬 결과</p>", unsafe_allow_html=True)
                        for hm_idx, hm_t in enumerate(h_item['mix_sequence']):
                            hm_cstr = f"{hm_t['key']} ({hm_t['camelot']})" if hm_t['camelot'] else hm_t['key']
                            hm_cues = hm_t.get('cues', {"intro": {"bb": "1마디 1박", "t": "00:00"}, "build": {"bb": "17마디 1박", "t": "01:04"}, "drop": {"bb": "33마디 1박", "t": "02:08"}, "outro": {"bb": "81마디 1박", "t": "04:30"}})
                            if isinstance(hm_cues.get('intro'), str): hm_cues = {'intro': {'bb': hm_cues['intro']}, 'build': {'bb': '분석중'}, 'drop': {'bb': hm_cues['drop']}, 'outro': {'bb': hm_cues['outro']}}
                            
                            with st.container(border=True):
                                col_hm_info, col_hm_btn = st.columns([7, 3])
                                with col_hm_info:
                                    st.markdown(f"<span style='color:{C_ACCENT}; font-weight:700;'>#{hm_idx+1} {hm_t['name']}</span><br><span style='color:{C_TEXT_MUTED}; font-size:14px;'>[{hm_t['bpm']} BPM | {hm_cstr}]</span>", unsafe_allow_html=True)
                                    st.markdown(f"""
                                    <div style="margin-top: 8px; padding: 6px 10px; background-color: {C_BG_SEC}; border-radius: 6px; font-size: 13px; color: {C_TEXT_MUTED}; border-left: 2px solid {C_ACCENT}; line-height: 1.5;">
                                    <span style="color:{C_SUCCESS};">▶ Intro</span> {hm_cues["intro"]["bb"]} &nbsp;|&nbsp; <span style="color:{C_PURPLE};">📈 Build</span> {hm_cues["build"]["bb"]} &nbsp;|&nbsp; <span style="color:{C_WARN};">🔥 Drop</span> {hm_cues["drop"]["bb"]} &nbsp;|&nbsp; <span style="color:{C_DANGER};">⏬ Outro</span> {hm_cues["outro"]["bb"]}
                                    </div>
                                    """, unsafe_allow_html=True)
                                with col_hm_btn:
                                    if st.button("▶ Play", key=f"hm_play_{h_idx}_{hm_idx}", use_container_width=True):
                                        with st.spinner("연결 중..."):
                                            try:
                                                with yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True, 'geo_bypass': True}) as ydl_s:
                                                    res = ydl_s.extract_info(f"ytsearch1:{hm_t['name']}", download=False)
                                                    if res.get('entries') and res['entries'][0]:
                                                        st.session_state.ai_active_preview = f"hm_{h_idx}_{hm_idx}"
                                                        st.session_state.ai_preview_url = ydl_s.extract_info(res['entries'][0]['url'], download=False).get('url')
                                                        st.rerun()
                                            except Exception: st.warning("실패")
                                                
                                    if st.button("🔎 검색/다운", key=f"hm_search_{h_idx}_{hm_idx}", use_container_width=True):
                                        with st.spinner("검색 중..."):
                                            st.session_state.inline_search_target = f"hist_mix_{h_idx}_{hm_idx}"
                                            st.session_state.inline_search_results = fetch_tracks('YouTube', hm_t['name'])[:5]
                                            st.session_state.inline_dl_status = {}
                                        st.rerun()
                                
                                if st.session_state.get('ai_active_preview') == f"hm_{h_idx}_{hm_idx}" and st.session_state.get('ai_preview_url'):
                                    st.audio(st.session_state.ai_preview_url, autoplay=True)
                            
                            render_inline_search_box(f"hist_mix_{h_idx}_{hm_idx}")
                                    
                            if hm_idx < len(h_item['mix_sequence']) - 1:
                                next_h_t = h_item['mix_sequence'][hm_idx+1]
                                key_match = next_h_t['camelot'] in hm_t['comp_keys']
                                bpm_str = f"+{next_h_t['bpm'] - hm_t['bpm']}" if next_h_t['bpm'] - hm_t['bpm'] >= 0 else f"{next_h_t['bpm'] - hm_t['bpm']}"
                                match_text = f"<span style='color:{C_SUCCESS}; font-weight:700;'>✨ Perfect Match (Key 호환)</span> &nbsp;|&nbsp; <span style='color:{C_TEXT_SUB};'>BPM {bpm_str}</span>" if key_match else f"<span style='color:{C_DANGER}; font-weight:700;'>⚠️ Key 불일치 (루프/효과음 믹 권장)</span> &nbsp;|&nbsp; <span style='color:{C_TEXT_SUB};'>BPM {bpm_str}</span>"
                                
                                hm_next_cues = next_h_t.get('cues', {"intro": {"bb": "1마디 1박", "t": "00:00"}, "build": {"bb": "17마디 1박", "t": "01:04"}, "drop": {"bb": "33마디 1박", "t": "02:08"}, "outro": {"bb": "81마디 1박", "t": "04:30"}})
                                if isinstance(hm_next_cues.get('intro'), str): hm_next_cues = {'intro': {'bb': hm_next_cues['intro']}, 'build': {'bb': '분석중'}, 'drop': {'bb': hm_next_cues['drop']}, 'outro': {'bb': hm_next_cues['outro']}}
                                
                                st.markdown(f"""
                                <div style="text-align:center; background-color:{C_BG_SEC}; border-radius:6px; padding:10px 0; margin: 4px 0 12px 0; font-size:15px; border:1px solid {C_BORDER};">
                                ⬇ {match_text}<br>
                                <div style="margin-top:8px; color:{C_TEXT_MAIN}; display:inline-block; text-align:left; font-size:14px;">
                                🎧 <b>Option 1:</b> 윗 곡 <span style="color:{C_DANGER};">[Outro / {hm_cues["outro"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:{C_SUCCESS};">[Intro / {hm_next_cues["intro"]["bb"]}]</span><br>
                                🎧 <b>Option 2:</b> 윗 곡 <span style="color:{C_PURPLE};">[Build-up / {hm_cues["build"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:{C_WARN};">[Drop / {hm_next_cues["drop"]["bb"]}]</span>
                                </div>
                                </div>
                                """, unsafe_allow_html=True)

                    st.markdown(f"<p style='color:{C_TEXT_MUTED}; font-size:14px; margin-top:10px; margin-bottom:8px;'>요청 조건: {h_summary}</p>", unsafe_allow_html=True)
                    st.markdown(f"<p style='color:{C_TEXT_SUB}; font-size:15px; margin-bottom:14px;'>{h_pl.get('description', '')}</p>", unsafe_allow_html=True)
                    
                    for t_idx, trk in enumerate(h_tracks):
                        h_search_query = f"{trk.get('artist', '')} - {trk.get('title', '')}"
                        col_t_info, col_t_play, col_t_dl = st.columns([6.2, 1.8, 2.0])
                        with col_t_info:
                            st.markdown(f"<span style='color:{C_ACCENT}; font-weight:700;'>#{t_idx+1} {h_search_query}</span><br><span style='color:{C_TEXT_DARK}; font-size:13px;'>{trk.get('reason', '')}</span>", unsafe_allow_html=True)
                        with col_t_play:
                            if st.button("▶ Play", key=f"hist_play_{h_idx}_{t_idx}", use_container_width=True):
                                with st.spinner("미리듣기 연결 중..."):
                                    try:
                                        ydl_stream_opts = {
                                            'format': 'bestaudio/best',
                                            'quiet': True,
                                            'geo_bypass': True,
                                            'nocheckcertificate': True
                                        }
                                        with yt_dlp.YoutubeDL(ydl_stream_opts) as ydl_s:
                                            res = ydl_s.extract_info(f"ytsearch1:{h_search_query}", download=False)
                                            if res.get('entries') and res['entries'][0]:
                                                st.session_state.ai_active_preview = f"hist_{h_idx}_{t_idx}"
                                                st.session_state.ai_preview_url = ydl_s.extract_info(res['entries'][0]['url'], download=False).get('url')
                                                st.rerun()
                                            else: st.warning("재생 가능한 음원을 찾지 못했습니다.")
                                    except Exception as pe: st.warning(f"미리듣기 실패: {pe}")
                        with col_t_dl:
                            if st.button("🔎 검색/다운", key=f"hist_dl_{h_idx}_{t_idx}", use_container_width=True):
                                with st.spinner("검색 중..."):
                                    st.session_state.inline_search_target = f"hist_track_{h_idx}_{t_idx}"
                                    st.session_state.inline_search_results = fetch_tracks('YouTube', h_search_query)[:5]
                                    st.session_state.inline_dl_status = {}
                                st.rerun()
                                
                        if st.session_state.get('ai_active_preview') == f"hist_{h_idx}_{t_idx}" and st.session_state.get('ai_preview_url'):
                            st.audio(st.session_state.ai_preview_url, autoplay=True)
                            
                        render_inline_search_box(f"hist_track_{h_idx}_{t_idx}")
                        st.markdown(f"<hr style='margin: 8px 0; border: none; border-top: 1px solid {C_BG_HOVER};'>", unsafe_allow_html=True)

elif st.session_state.current_view == "Tracklist":
    st.markdown(f"""<div class="ai-box"><h3 style="color:{C_ACCENT}; margin-top:0;">🔗 YouTube Tracklist Extractor</h3><p style="color:{C_TEXT_SUB}; font-size: 16px;">DJ 믹스셋이나 페스티벌 영상의 유튜브 링크를 입력하면 수록곡(Tracklist)을 자동 추출합니다.</p></div><br>""", unsafe_allow_html=True)
    yt_link = st.text_input("YouTube 영상 링크를 입력하세요", placeholder="[https://www.youtube.com/watch?v=](https://www.youtube.com/watch?v=)...", key="yt_tracklist_input")
    if st.button("🚀 트랙리스트 추출", use_container_width=True):
        if yt_link:
            with st.spinner("트랙리스트를 분석 중입니다..."):
                try:
                    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True}) as ydl:
                        info = ydl.extract_info(yt_link, download=False)
                    extracted = [ch.get('title') for ch in info['chapters']] if info.get('chapters') else ([m.strip() for m in re.findall(r'(?:(?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—]?\s*(.+)', info.get('description', ''))] if info.get('description') else [])
                    if extracted:
                        st.session_state.extracted_tracks = extracted
                        st.rerun()
                    else: st.warning("트랙리스트를 찾을 수 없습니다.")
                except Exception as e: st.error(f"오류: {e}")
                    
    st.markdown(f"<br><p style='color:{C_TEXT_MUTED}; font-size:15px; margin-bottom:5px;'>💡 영상에 목록이 없나요? 유튜브 댓글이나 1001Tracklists에서 복사해 직접 붙여넣으세요.</p>", unsafe_allow_html=True)
    manual_text = st.text_area("텍스트", placeholder="00:00 Artist - Title\n03:30 Artist2 - Title2", label_visibility="collapsed", height=120)
    if st.button("📝 붙여넣은 텍스트에서 트랙 추출", use_container_width=True):
        if manual_text:
            extracted = [re.sub(r'^\d+[\.\-\)][\s\-]*', '', re.sub(r'\[?(?:(?:\d{1,2}:)?\d{1,2}:\d{2})\]?\s*[-–—]?\s*', '', line).strip()).strip() for line in manual_text.strip().split('\n') if line.strip() and "http" not in line]
            if extracted:
                st.session_state.extracted_tracks = extracted
                st.rerun()
            else: st.warning("유효한 트랙을 찾을 수 없습니다.")

    st.markdown(f"<br><p style='color:{C_TEXT_MUTED}; font-size:15px; margin-bottom:5px;'>🎧 텍스트마저 없다면? AI가 소리를 직접 듣고 찾아냅니다 (3~5분 소요).</p>", unsafe_allow_html=True)
    if st.button("🤖 AI 오디오 스캔 (Shazam) 실행", use_container_width=True):
        if not yt_link: st.warning("먼저 링크를 입력해주세요.")
        else:
            try:
                import shazamio, nest_asyncio
                nest_asyncio.apply()
                from shazamio import Shazam
                with st.spinner("AI 스캔 준비 중..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as tmp_audio: tmp_path = tmp_audio.name
                    with yt_dlp.YoutubeDL({'format': 'worstaudio/worst', 'outtmpl': tmp_path, 'quiet': True}) as ydl:
                        duration = ydl.extract_info(yt_link, download=True).get('duration', 3600)
                    async def scan_audio():
                        shazam, results, chunk = Shazam(), [], 180
                        scan_prog = st.progress(0.0, text="AI 스캔 시작...")
                        for i in range(int(duration // chunk) + 1):
                            snip_path = tmp_path + f"_{i}.mp3"
                            subprocess.run(['ffmpeg', '-y', '-i', tmp_path, '-ss', str(i*chunk), '-t', '15', '-c:a', 'libmp3lame', snip_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            if os.path.exists(snip_path):
                                try:
                                    out = await (shazam.recognize_song(snip_path) if hasattr(shazam, 'recognize_song') else shazam.recognize(snip_path))
                                    if 'track' in out:
                                        t_name = f"{out['track'].get('subtitle', '')} - {out['track'].get('title', '')}".strip(" - ")
                                        if t_name and t_name not in results: results.append(t_name)
                                except: pass
                                try: os.remove(snip_path)
                                except: pass
                            scan_prog.progress(min(1.0, (i + 1) / (int(duration // chunk) + 1)), text=f"AI 스캔 중... ({len(results)}곡 발견)")
                        scan_prog.empty()
                        return results
                    
                    extracted_ai = asyncio.run(scan_audio())
                    try: os.remove(tmp_path)
                    except: pass
                    
                    if extracted_ai:
                        st.session_state.extracted_tracks = extracted_ai
                        st.rerun()
                    else: st.warning("인식된 곡이 없습니다.")
            except ImportError: st.error("`pip install shazamio nest_asyncio` 실행 필요.")

    if st.session_state.get('extracted_tracks'):
        st.markdown(f"<p style='color:{C_ACCENT}; font-weight:700; margin-top:20px; margin-bottom:10px;'>📋 추출된 트랙 리스트 ({len(st.session_state.extracted_tracks)}곡)</p>", unsafe_allow_html=True)
        for idx, track in enumerate(st.session_state.extracted_tracks):
            col_num, col_name, col_btn = st.columns([0.6, 7.4, 2])
            with col_num: st.markdown(f"<div style='color:{C_ACCENT}; font-weight:800; padding-top:10px; font-size:17px;'>{idx+1}</div>", unsafe_allow_html=True)
            with col_name: st.markdown(f"<div style='background-color:{C_BG_CARD}; border:1px solid {C_BORDER}; border-radius:8px; padding:10px 14px; color:{C_TEXT_MAIN}; font-weight:600; font-size:16px;'>{track}</div>", unsafe_allow_html=True)
            with col_btn:
                clean_track = re.sub(r'^(?:(?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—]?\s*', '', track).strip()
                st.button("🔎 검색하기", key=f"search_track_{idx}", use_container_width=True, on_click=trigger_search, args=(clean_track,))

elif st.session_state.current_view in ["Search", "Bookmarks"]:
    
    if st.session_state.current_view == "Search":
        with st.form(key='search_form'):
            user_input = st.text_input("Search", label_visibility="collapsed", placeholder="Search for songs, artists...", autocomplete="off", key="search_input_value")
            submit_button = st.form_submit_button(label="Search")

        do_search = submit_button or st.session_state.get('auto_search', False)
        if do_search:
            st.session_state.auto_search = False
            if st.session_state.search_input_value:
                st.session_state.search_query = st.session_state.search_input_value
                user_input = st.session_state.search_input_value
                st.session_state.page = 1
                st.session_state.download_queue = []
                st.session_state.download_status = {}
                with st.spinner("Searching tracks... Please wait!"):
                    combined_entries = []
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        yt_future = executor.submit(fetch_tracks, 'YouTube', user_input)
                        sc_future = executor.submit(fetch_tracks, 'SoundCloud', user_input)
                        combined_entries.extend(yt_future.result())
                        combined_entries.extend(sc_future.result())

                    filtered_entries = []
                    for video in combined_entries:
                        duration = video.get('duration')
                        platform = video.get('platform', '')
                        uploader = str(video.get('uploader', '')).lower()
                        
                        if duration is not None and duration > 0 and duration < 600 and video.get('url'):
                            if platform == 'SoundCloud' and duration == 30: continue
                            if platform == 'YouTube' and ('vevo' in uploader or uploader.endswith(' - topic')): continue
                            filtered_entries.append(video)

                    st.session_state.search_results = filtered_entries
                    st.session_state.active_preview = None
                    st.session_state.preview_url = None
            else:
                st.warning("Please enter a search query!")
    else:
        # 북마크 백업 및 복원 영역 (클라우드 초기화 대비)
        with st.expander("💾 북마크 백업 및 복원 (내 기기에 보관용)"):
            c_bm_ex, c_bm_im = st.columns(2)
            with c_bm_ex:
                bm_json = json.dumps(st.session_state.bookmarks, ensure_ascii=False, indent=4)
                st.download_button("📥 북마크 JSON 파일로 백업", data=bm_json, file_name="my_bookmarks.json", mime="application/json", use_container_width=True)
            with c_bm_im:
                up_bm = st.file_uploader("📤 백업한 북마크 JSON 불러오기", type=["json"], label_visibility="collapsed")
                if up_bm:
                    try:
                        loaded_bms = json.load(up_bm)
                        if isinstance(loaded_bms, list):
                            st.session_state.bookmarks = loaded_bms
                            save_bookmarks(loaded_bms)
                            st.success("북마크 복원 완료!")
                            st.rerun()
                    except Exception:
                        st.error("올바른 JSON 파일이 아닙니다.")

    active_list = st.session_state.search_results if st.session_state.current_view == "Search" else st.session_state.bookmarks
    total_tracks = len(active_list)
    
    if total_tracks == 0:
        if st.session_state.current_view == "Bookmarks":
            st.markdown(f"<div style='text-align: center; color: {C_TEXT_DARK}; font-size:15px; font-weight:600; margin-top:20px;'>⭐ 저장된 북마크가 없습니다. 검색에서 원하는 곡을 Star 해보세요!</div>", unsafe_allow_html=True)
            
        quotes = [
            ("One good thing about music, when it hits you, you feel no pain.", "음악의 가장 좋은 점은, 그것이 당신을 때려도 아무런 고통을 느끼지 않는다는 것이다.", "Bob Marley"),
            ("Without music, life would be a mistake.", "음악이 없다면, 삶은 하나의 오류일 것이다.", "Friedrich Nietzsche"),
            ("A DJ is someone who plays music, but a great DJ is someone who creates a journey.", "DJ는 음악을 트는 사람이지만, 위대한 DJ는 사람들을 새로운 여정으로 이끄는 사람이다.", "Tiësto"),
            ("I just want to make people dance.", "나는 그저 사람들을 춤추게 만들고 싶을 뿐이다.", "Avicii"),
            ("Music is the answer to your problems.", "음악은 당신이 가진 문제들의 해답이다.", "Frankie Knuckles"),
            ("Techno is everything you haven't imagined yet.", "테크노는 당신이 아직 상상하지 못한 모든 것이다.", "Jeff Mills"),
            ("Music is the universal language of mankind.", "음악은 인류의 보편적인 언어다.", "Henry Wadsworth Longfellow"),
            ("The music sounds better with you.", "음악은 당신과 함께할 때 훨씬 더 좋게 들린다.", "Stardust"),
            ("My job is to bring joy to people through music.", "내 직업은 음악을 통해 사람들에게 기쁨을 주는 것이다.", "Carl Cox"),
            ("Where words fail, music speaks.", "말이 소용없는 곳에서, 음악이 말하기 시작한다.", "Hans Christian Andersen")
        ]
        
        q_en, q_ko, a = random.choice(quotes)
        st.markdown(f'''
        <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 50vh; opacity: 0.7;">
            <div style="font-size: 22px; font-weight: 700; color: {C_TEXT_MUTED}; font-style: italic; text-align: center; max-width: 800px; word-break: keep-all; line-height: 1.5;">"{q_en}"</div>
            <div style="font-size: 17px; font-weight: 600; color: {C_TEXT_DARK}; text-align: center; margin-top: 14px; max-width: 800px; word-break: keep-all; line-height: 1.6;">{q_ko}</div>
            <div style="font-size: 16px; font-weight: 800; color: {C_ACCENT}; margin-top: 24px; letter-spacing: 1px;">— {a}</div>
        </div>
        ''', unsafe_allow_html=True)
        
    elif total_tracks > 0:
        items_per_page = 50
        total_pages = max(1, (total_tracks - 1) // items_per_page + 1)
        if st.session_state.page > total_pages: st.session_state.page = total_pages

        title_prefix = "SEARCH RESULTS" if st.session_state.current_view == "Search" else "BOOKMARKS"
        st.markdown(f"<p style='color: {C_ACCENT}; font-weight: 600; font-size: 16px; margin-top: 10px; margin-bottom: 12px;'>{title_prefix} ({total_tracks} tracks) - [{st.session_state.active_format} MODE]</p>", unsafe_allow_html=True)

        start_idx = (st.session_state.page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_tracks)
        page_items = active_list[start_idx:end_idx]

        with st.container(border=True):
            for local_i, video in enumerate(page_items):
                i = start_idx + local_i
                dl_key = f"{st.session_state.current_view}_{i}"
                duration = video.get('duration')
                time_str = f"{int(duration) // 60}:{int(duration) % 60:02d}" if duration else "미상"
                size_str = f"{(duration * 320 * 1000 / 8) / (1024 * 1024):.1f} MB" if duration else "- MB"
                platform = video.get('platform', 'Unknown')
                
                sc_icon = f'<svg height="15" width="24" viewBox="0 0 24 24" style="fill: {C_WARN}; vertical-align: middle; margin-right: 6px;"><path d="M19.36 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.64-4.96z"/></svg>'
                platform_html = yt_icon if platform == 'YouTube' else sc_icon
                
                col_info, col_meta, col_actions = st.columns([4, 3, 5])
                with col_info:
                    st.markdown(f"{platform_html} <span style='color: {C_TEXT_MAIN}; font-weight: 600;'>{video.get('title')}</span> <span class='format-badge'>{st.session_state.active_format}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color: {C_TEXT_DARK}; font-size: 16px; margin-left: 26px;'>{video.get('uploader', '정보 없음')}</span>", unsafe_allow_html=True)
                with col_meta:
                    m1, m2, m3 = st.columns(3)
                    with m1: st.markdown(f"<div class='meta-pill'>{size_str}</div>", unsafe_allow_html=True)
                    with m2: st.markdown(f"<div class='meta-pill'>{'Lossless' if st.session_state.active_format == 'FLAC' else '320 kbps'}</div>", unsafe_allow_html=True)
                    with m3: st.markdown(f"<div class='meta-pill'>{time_str}</div>", unsafe_allow_html=True)
                with col_actions:
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("▶ Play", key=f"preview_{dl_key}", help="Instant Preview", use_container_width=True):
                            with st.spinner("Loading stream..."):
                                try:
                                    with yt_dlp.YoutubeDL({'format': 'bestaudio/best', 'quiet': True, 'geo_bypass': True}) as ydl_s:
                                        st.session_state.active_preview = i
                                        st.session_state.preview_url = ydl_s.extract_info(video['url'], download=False).get('url')
                                        st.rerun()
                                except Exception: st.warning("Preview unavailable.")
                    with b2:
                        is_bm = any(b['url'] == video['url'] for b in st.session_state.bookmarks)
                        if st.button("🌟 Starred" if is_bm else "⭐ Star", key=f"bm_{dl_key}", use_container_width=True):
                            if is_bm: st.session_state.bookmarks = [b for b in st.session_state.bookmarks if b['url'] != video['url']]
                            else: st.session_state.bookmarks.append(video)
                            save_bookmarks(st.session_state.bookmarks)
                            st.rerun()
                    with b3:
                        active_f = st.session_state.active_format
                        if dl_key in st.session_state.get('ready_downloads', {}):
                            f_info = st.session_state.ready_downloads[dl_key]
                            st.download_button(
                                label=f"💾 기기에 저장 ({active_f})",
                                data=f_info['bytes'],
                                file_name=f_info['filename'],
                                mime=f_info['mime'],
                                key=f"save_btn_main_{dl_key}",
                                use_container_width=True
                            )
                        else:
                            if st.button(f"⬇ {active_f} 추출", key=f"dl_{dl_key}", use_container_width=True):
                                target_codec = 'flac' if active_f == 'FLAC' else 'mp3'
                                if i not in st.session_state.download_queue: st.session_state.download_queue.append(i)
                                st.session_state.download_status[i] = "⏳ 오디오 추출 및 분석 중..."
                                dl_prog = st.progress(0.0)
                                
                                def ytdl_hook(d):
                                    if d['status'] == 'downloading':
                                        t = d.get('total_bytes') or d.get('total_bytes_estimate')
                                        if t: dl_prog.progress(max(0.0, min(1.0, d.get('downloaded_bytes', 0) / t)))
                                try:
                                    down_dir = st.session_state.local_dir
                                    os.makedirs(down_dir, exist_ok=True)
                                    ydl_opts_dl = {
                                        'format': 'bestaudio/best',
                                        'outtmpl': os.path.join(down_dir, f'main_{dl_key}_%(title)s.%(ext)s'),
                                        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': target_codec}],
                                        'quiet': True, 'geo_bypass': True, 'progress_hooks': [ytdl_hook]
                                    }
                                    if target_codec == 'mp3': ydl_opts_dl['postprocessors'][0]['preferredquality'] = '320'
                                    
                                    with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl_dl:
                                        i_dict = ydl_dl.extract_info(video['url'], download=True)
                                        orig_file = ydl_dl.prepare_filename(i_dict)
                                        clean_t, final_file_path = process_downloaded_file(i_dict, target_codec, orig_file, down_dir)
                                        
                                        dl_prog.empty()
                                        bpm, rb_key, camelot, cues, _ = analyze_track_pro(final_file_path)
                                        
                                        if os.path.exists(final_file_path):
                                            with open(final_file_path, "rb") as f_bytes:
                                                st.session_state.ready_downloads[dl_key] = {
                                                    "bytes": f_bytes.read(),
                                                    "filename": f"{clean_t}.{target_codec}",
                                                    "mime": "audio/flac" if target_codec == "flac" else "audio/mpeg"
                                                }
                                            try: os.remove(final_file_path)
                                            except: pass
                                        
                                        if bpm and camelot:
                                            st.session_state.download_status[i] = f"✅ 준비 완료! 위 [💾 기기에 저장]을 누르세요 | <span style='color:{C_PURPLE}; font-weight:800;'>{bpm} BPM &nbsp;·&nbsp; {rb_key} ({camelot}🎧)</span>"
                                        else:
                                            st.session_state.download_status[i] = f"✅ 준비 완료: {clean_t}.{target_codec}"
                                        
                                    st.rerun()
                                except Exception as ex:
    dl_prog.empty()
    st.session_state.inline_dl_status[unique_k] = f"⚠️ 추출 실패 (원인: {str(ex)})"

                if i in st.session_state.download_status:
                    s_text = st.session_state.download_status[i]
                    c_code = C_SUCCESS if "완료" in s_text else (C_ACCENT_HOVER if "추출" in s_text else C_DANGER)
                    st.markdown(f"<div style='color: {c_code}; font-size: 16px; font-weight: 700; margin-top: 4px; text-align: right;'>{s_text}</div>", unsafe_allow_html=True)
                if st.session_state.active_preview == i and st.session_state.preview_url:
                    st.audio(st.session_state.preview_url, autoplay=True)
                if local_i < len(page_items) - 1:
                    st.markdown(f"<hr style='margin: 8px 0; border: none; border-top: 1px solid {C_BORDER};'>", unsafe_allow_html=True)

        if total_pages > 1:
            st.markdown(f"<br><div style='text-align: center; color: {C_TEXT_DARK}; font-weight: 600; font-size: 16px; margin-bottom: 6px;'>SELECT PAGE</div>", unsafe_allow_html=True)
            page_cols = st.columns(total_pages)
            for p in range(1, total_pages + 1):
                with page_cols[p - 1]:
                    if st.button(f"• {p} •" if p == st.session_state.page else f"{p}", key=f"bp_{st.session_state.current_view}_{p}", use_container_width=True):
                        if p != st.session_state.page:
                            st.session_state.page = p
                            st.rerun()