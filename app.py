import time
import datetime
# 🚨 _strptime 모듈 스레딩 충돌(미리듣기 에러) 방지를 위한 강제 초기화 (반드시 최상단에 위치해야 함)
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

st.set_page_config(page_title="Music Searcher", page_icon="🎧", layout="wide")
st.markdown('''
<div style="position: fixed; top: -10vh; left: -10vw; width: 120vw; height: 120vh; z-index: -999; pointer-events: none; background-color: #0A0A0C;">
    <iframe src="https://www.youtube.com/embed/c0-hvjV2A5Y?autoplay=1&mute=1&loop=1&playlist=c0-hvjV2A5Y&controls=0&showinfo=0&disablekb=1&modestbranding=1&playsinline=1" 
            frameborder="0" 
            allow="autoplay; fullscreen; encrypted-media"
            style="width: 100%; height: 100%; opacity: 0.45; filter: contrast(1.15) saturate(1.2); pointer-events: none;">
    </iframe>
</div>
''', unsafe_allow_html=True)


BOOKMARKS_FILE = "bookmarks.json"

def load_bookmarks():
    if os.path.exists(BOOKMARKS_FILE):
        try:
            with open(BOOKMARKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return []

def save_bookmarks(bms):
    with open(BOOKMARKS_FILE, "w", encoding="utf-8") as f:
        json.dump(bms, f, ensure_ascii=False, indent=4)

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
        
    if not valid_tracks:
        return []
        
    ordered = [min(valid_tracks, key=lambda x: x['bpm'])]
    remaining = [t for t in valid_tracks if t['name'] != ordered[0]['name']]
    
    current_time = ordered[0].get('duration', 210)
    
    while remaining:
        if target_time_sec and current_time >= target_time_sec:
            break
            
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

def analyze_audio(file_path):
    try:
        duration_sec = librosa.get_duration(path=file_path)
        
        offset_time = min(60.0, duration_sec * 0.2) if duration_sec else 0.0
        y_core, sr_core = librosa.load(file_path, sr=22050, offset=offset_time, duration=60.0)
        
        # 1. BPM 정밀 분석 (Direct Beat Interval)
        _, beats_core = librosa.beat.beat_track(y=y_core, sr=sr_core)
        if len(beats_core) > 10:
            beat_times = librosa.frames_to_time(beats_core, sr=sr_core)
            avg_beat_duration = (beat_times[-1] - beat_times[0]) / (len(beats_core) - 1)
            exact_bpm = 60.0 / avg_beat_duration
            bpm = int(round(exact_bpm))
        else:
            onset_env = librosa.onset.onset_strength(y=y_core, sr=sr_core)
            if hasattr(librosa.feature, 'tempo'):
                tempo_arr = librosa.feature.tempo(onset_envelope=onset_env, sr=sr_core)
            else:
                tempo_arr, _ = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr_core)
            bpm = int(round(tempo_arr[0])) if isinstance(tempo_arr, (np.ndarray, list)) else int(round(tempo_arr))
        
        # 2. Key 분석 (마스터 튜닝 편차 보정 + CQT 크로마 정밀 패치)
        tuning = librosa.estimate_tuning(y=y_core, sr=sr_core)
        y_harmonic, _ = librosa.effects.hpss(y_core)
        chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr_core, tuning=tuning, hop_length=512)
        chroma_sum = np.mean(chroma, axis=1)
        
        maj_profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
        min_profile = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
        
        keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        
        best_score = -999.0
        key_str = "Cm"
        
        total_chroma = np.sum(chroma_sum) + 1e-5
        
        for i, k in enumerate(keys):
            maj_third = (i + 4) % 12
            maj_fifth = (i + 7) % 12
            maj_triad_energy = (chroma_sum[i] + chroma_sum[maj_third] + chroma_sum[maj_fifth]) / total_chroma
            
            min_third = (i + 3) % 12
            min_fifth = (i + 7) % 12
            min_triad_energy = (chroma_sum[i] + chroma_sum[min_third] + chroma_sum[min_fifth]) / total_chroma
            
            rolled_maj = np.roll(maj_profile, i)
            corr_maj = np.corrcoef(chroma_sum, rolled_maj)[0,1]
            score_maj = (corr_maj * 0.6) + (maj_triad_energy * 0.4)
            
            rolled_min = np.roll(min_profile, i)
            corr_min = np.corrcoef(chroma_sum, rolled_min)[0,1]
            score_min = (corr_min * 0.5) + (min_triad_energy * 0.5) * 1.30
            
            if score_maj > best_score:
                best_score = score_maj
                key_str = k + "M"
            if score_min > best_score:
                best_score = score_min
                key_str = k + "m"
            
        camelot_map = {
            'G#m': '1A', 'D#m': '2A', 'A#m': '3A', 'Fm': '4A',
            'Cm': '5A', 'Gm': '6A', 'Dm': '7A', 'Am': '8A',
            'Em': '9A', 'Bm': '10A', 'F#m': '11A', 'C#m': '12A',
            'BM': '1B', 'F#M': '2B', 'C#M': '3B', 'G#M': '4B',
            'D#M': '5B', 'A#M': '6B', 'FM': '7B', 'CM': '8B',
            'GM': '9B', 'DM': '10B', 'AM': '11B', 'EM': '12B'
        }
        
        camelot = camelot_map.get(key_str, "")
        final_key = f"{key_str}({camelot})" if camelot else key_str
        
        # 3. 큐 포인트 추출 (전체 곡을 빠르게 스캔)
        y, sr = librosa.load(file_path, sr=11025)
        onset_env_full = librosa.onset.onset_strength(y=y, sr=sr)
        _, beats = librosa.beat.beat_track(onset_envelope=onset_env_full, sr=sr, start_bpm=float(bpm))
        
        rms = librosa.feature.rms(y=y)[0]
        smooth_rms = np.convolve(rms, np.ones(100)/100, mode='same')
        
        drop_idx = np.argmax(smooth_rms)
        last_quarter_idx = int(len(smooth_rms) * 0.75)
        threshold = smooth_rms[drop_idx] * 0.5
        outro_idx = len(smooth_rms) - 1
        for j in range(last_quarter_idx, len(smooth_rms)):
            if smooth_rms[j] < threshold:
                outro_idx = j
                break
                
        intro_idx = beats[0] if len(beats) > 0 else 0
        
        def get_bar_beat(frame_idx):
            if len(beats) == 0: return "1마디 1박", "00:00"
            beat_arr_idx = np.argmin(np.abs(beats - frame_idx))
            bar = (beat_arr_idx // 4) + 1
            beat_num = (beat_arr_idx % 4) + 1
            time_sec = librosa.frames_to_time(beats[beat_arr_idx], sr=sr)
            time_str = f"{int(time_sec//60):02d}:{int(time_sec%60):02d}"
            return f"{bar}마디 {beat_num}박", time_str

        intro_bb, intro_t = get_bar_beat(intro_idx)
        drop_bb, drop_t = get_bar_beat(drop_idx)
        outro_bb, outro_t = get_bar_beat(outro_idx)
        
        drop_beat_idx = np.argmin(np.abs(beats - drop_idx)) if len(beats) > 0 else 0
        build_beat_idx = max(0, drop_beat_idx - 16)
        build_bb, build_t = get_bar_beat(beats[build_beat_idx] if len(beats) > 0 else 0)
        
        cues = {
            "intro": {"bb": intro_bb, "t": intro_t},
            "build": {"bb": build_bb, "t": build_t},
            "drop": {"bb": drop_bb, "t": drop_t},
            "outro": {"bb": outro_bb, "t": outro_t}
        }
            
        return bpm, final_key, camelot, cues, duration_sec
    except Exception as e:
        return None, None, None, None, None


st.markdown('''
<style>
    [data-testid="stHeader"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    footer { display: none !important; }
    [class*="viewerBadge"] { display: none !important; visibility: hidden !important; opacity: 0 !important; pointer-events: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stAppViewContainer"] { background-color: transparent !important; position: relative; z-index: 1; }
    [data-testid="stHeader"] { background-color: transparent !important; z-index: 2; }
    .stApp { background-color: transparent !important; color: #f1f5f9; padding-top: 2rem; }
    
    div[data-testid="stForm"] {
        background-color: #121217 !important; border: 2px solid #17C8F0 !important;
        border-radius: 12px !important; padding: 4px 6px 4px 14px !important;
        box-shadow: 0 0 15px rgba(23, 200, 240, 0.25) !important;
    }
    div[data-testid="stForm"]:focus-within {
        border-color: #38bdf8 !important; box-shadow: 0 0 20px rgba(56, 189, 248, 0.5) !important;
    }
    div[data-testid="stForm"] > div[data-testid="stVerticalBlock"] {
        width: 100% !important; display: flex !important; flex-direction: row !important;
        align-items: center !important; gap: 12px !important; margin: 0 !important; padding: 0 !important;
    }
    .stTextInput { flex-grow: 1 !important; margin: 0 !important; padding: 0 !important; }
    .stTextInput div[data-baseweb="base-input"], .stTextInput div[data-baseweb="input"] {
        background-color: #121217 !important; border: none !important; box-shadow: none !important; outline: none !important;
    }
    .stTextInput input {
        background-color: #121217 !important; color: #ffffff !important; border: none !important;
        outline: none !important; box-shadow: none !important; font-size: 15px !important; height: 44px !important;
        padding-left: 36px !important;
        background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="%2317C8F0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>') !important;
        background-repeat: no-repeat !important; background-position: 4px center !important;
    }
    .stTextInput input::placeholder { color: #64748b !important; }
    .stFormSubmitButton { margin: 0 !important; width: auto !important; flex-shrink: 0 !important; }
    .stFormSubmitButton button {
        background-color: #17C8F0 !important; color: #0A0A0C !important; border: none !important;
        border-radius: 8px !important; font-weight: 800 !important; height: 38px !important; min-width: 84px !important;
        padding: 0 18px !important; font-size: 16px !important; transition: all 0.2s ease !important;
    }
    .stFormSubmitButton button:hover { background-color: #38bdf8 !important; box-shadow: 0 0 10px rgba(56, 189, 248, 0.4) !important; }
    .stButton button {
        background-color: #121217 !important; color: #ffffff !important; border: 1px solid #26262e !important;
        border-radius: 8px !important; font-weight: 700 !important; transition: all 0.2s ease; white-space: nowrap !important;
    }
    .stButton button:hover { background-color: #17C8F0 !important; color: #0A0A0C !important; border-color: #17C8F0 !important; }
    .format-badge {
        background-color: #121217; color: #17C8F0; font-size: 17px; font-weight: 700; padding: 2px 6px;
        border-radius: 4px; margin-left: 6px; border: 1px solid #26262e;
    }
    .meta-pill {
        background-color: #121217; color: #cbd5e1; font-size: 17px; padding: 8px 0px; border-radius: 8px;
        font-weight: 700; text-align: center; border: 1px solid #26262e; display: block; width: 100%;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }
    div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
        background-color: #121217; border: 1px solid #26262e; border-radius: 12px; padding: 10px;
    }
    
    .ai-box {
        background: linear-gradient(145deg, #121217 0%, #1a1a24 100%);
        border: 1px solid #17C8F0;
        border-radius: 12px;
        padding: 24px;
        margin-top: 20px;
        box-shadow: 0 0 20px rgba(23, 200, 240, 0.1);
    }
    .local-track {
        background-color: #121217; border: 1px solid #26262e; border-radius: 8px;
        padding: 10px 15px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center;
    }
    div[data-testid="stWidgetLabel"] p,
    div[data-testid="stWidgetLabel"] label,
    label {
        color: #17C8F0 !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        visibility: visible !important;
        display: block !important;
    }
    [data-testid="stFileUploader"] section {
        background-color: #121217 !important;
        border: 2px dashed #26262e !important;
        border-radius: 12px !important;
    }
    [data-testid="stFileUploader"] section:hover {
        border-color: #17C8F0 !important;
    }
    
    /* 업로드 박스 안의 안내 문구 및 버튼 텍스트 가독성 완벽 해결 */
    [data-testid="stFileUploader"] section span,
    [data-testid="stFileUploader"] section small,
    [data-testid="stFileUploader"] section p {
        color: #f1f5f9 !important;
    }
    
    /* 업로드 버튼 스타일 강제 (하얀색 배경 + 안 보이는 글씨 문제 해결) */
    [data-testid="stFileUploader"] button {
        background-color: #17C8F0 !important;
        color: #0A0A0C !important;
        border: none !important;
        font-weight: 800 !important;
    }
    [data-testid="stFileUploader"] button * {
        color: #0A0A0C !important;
    }
    /* 스트림릿 기본 파일 업로드 미리보기 칩(하얀색 네모들) 완벽 격리 및 숨김 */
    [data-testid="stUploadedFileList"],
    [data-testid="stFileUploader"] [data-testid="stVerticalBlock"] > div:not(:first-child),
    div[data-baseweb="file-uploader"] ~ div {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        max-height: 0 !important;
        overflow: hidden !important;
    }

    /* 🚨 스트림릿 기본 파일 업로드 칩 최후의 말살 🚨 */
    [data-testid="stFileUploader"] ul {
        display: none !important;
    }
    div[data-testid="stFileUploader"] section + div {
        display: none !important;
    }

</style>
''', unsafe_allow_html=True)

if 'bookmarks' not in st.session_state:
    st.session_state.bookmarks = load_bookmarks()
if 'current_view' not in st.session_state:
    st.session_state.current_view = "Search"
if 'search_query' not in st.session_state:
    st.session_state.search_query = ""
if 'search_results' not in st.session_state:
    st.session_state.search_results = []
if 'page' not in st.session_state:
    st.session_state.page = 1
if 'active_preview' not in st.session_state:
    st.session_state.active_preview = None
if 'preview_url' not in st.session_state:
    st.session_state.preview_url = None
if 'active_format' not in st.session_state:
    st.session_state.active_format = "MP3"
if 'download_queue' not in st.session_state:
    st.session_state.download_queue = []
if 'download_status' not in st.session_state:
    st.session_state.download_status = {}
if 'analyzed_cache' not in st.session_state:
    st.session_state.analyzed_cache = {}
if 'local_dir' not in st.session_state:
    st.session_state.local_dir = os.path.join(os.path.expanduser('~'), 'Downloads')

if 'search_input_value' not in st.session_state:
    st.session_state.search_input_value = st.session_state.search_query

with st.form(key='search_form'):
    user_input = st.text_input("Search", label_visibility="collapsed", placeholder="Search for songs, artists...", autocomplete="off", key="search_input_value")
    submit_button = st.form_submit_button(label="Search")

def fetch_tracks(platform, query):
    prefix = "ytsearch30:" if platform == 'YouTube' else "scsearch30:"
    opts = {'extract_flat': 'in_playlist', 'quiet': True, 'geo_bypass': True}
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

do_search = submit_button or st.session_state.get('auto_search', False)
if do_search:
    st.session_state.auto_search = False
    if st.session_state.search_input_value:
        st.session_state.search_query = st.session_state.search_input_value
        user_input = st.session_state.search_input_value
        st.session_state.page = 1
        st.session_state.current_view = "Search"
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
                    # 1. 사운드클라우드 유료(Go+) DRM 트랙 방어 (대부분 30초 미리듣기로 제공됨)
                    if platform == 'SoundCloud' and duration == 30:
                        continue
                        
                    # 2. 유튜브 DRM(저작권 철퇴) 확률 99%인 Vevo 및 자동생성 음원(Topic) 배제
                    if platform == 'YouTube':
                        if 'vevo' in uploader or uploader.endswith(' - topic'):
                            continue
                            
                    filtered_entries.append(video)

            st.session_state.search_results = filtered_entries
            st.session_state.active_preview = None
            st.session_state.preview_url = None
    else:
        st.warning("Please enter a search query!")

st.markdown("<br>", unsafe_allow_html=True)

c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1.5, 1.5, 2.0, 1.5])
with c1:
    is_mp3_active = st.session_state.active_format == "MP3"
    mp3_label = "● MP3" if is_mp3_active else "MP3"
    if st.button(mp3_label, use_container_width=True, key="filter_mp3"):
        if not is_mp3_active:
            st.session_state.active_format = "MP3"
            st.session_state.download_queue = []
            st.session_state.download_status = {}
            st.rerun()
with c2:
    is_flac_active = st.session_state.active_format == "FLAC"
    flac_label = "● FLAC" if is_flac_active else "FLAC"
    if st.button(flac_label, use_container_width=True, key="filter_flac"):
        if not is_flac_active:
            st.session_state.active_format = "FLAC"
            st.session_state.download_queue = []
            st.session_state.download_status = {}
            st.rerun()
with c3:
    is_tracklist_view = st.session_state.current_view == "Tracklist"
    t_label = "● TRACKS 🔗" if is_tracklist_view else "TRACKS 🔗"
    if st.button(t_label, use_container_width=True, key="view_tracklist"):
        if not is_tracklist_view:
            st.session_state.current_view = "Tracklist"
            st.session_state.page = 1
            st.rerun()
with c4:
    is_search_view = st.session_state.current_view == "Search"
    s_label = "● SEARCH" if is_search_view else "SEARCH"
    if st.button(s_label, use_container_width=True, key="view_search"):
        if not is_search_view:
            st.session_state.current_view = "Search"
            st.session_state.page = 1
            st.rerun()
with c5:
    is_bm_view = st.session_state.current_view == "Bookmarks"
    b_label = f"● BOOKMARKS ({len(st.session_state.bookmarks)})" if is_bm_view else f"BOOKMARKS ({len(st.session_state.bookmarks)})"
    if st.button(b_label, use_container_width=True, key="view_bm"):
        if not is_bm_view:
            st.session_state.current_view = "Bookmarks"
            st.session_state.page = 1
            st.rerun()
with c6:
    is_ai_view = st.session_state.current_view == "AI"
    ai_label = "● AI STUDIO 🎛️" if is_ai_view else "AI STUDIO 🎛️"
    if st.button(ai_label, use_container_width=True, key="view_ai"):
        if not is_ai_view:
            st.session_state.current_view = "AI"
            st.rerun()

if st.session_state.current_view == "AI":
    st.markdown('''
    <div class="ai-box">
        <h3 style="color:#17C8F0; margin-top:0;">🎛️ AI Harmonic Mix Studio</h3>
        <p style="color:#cbd5e1; font-size: 16px;">디깅부터 믹스 플레이리스트 자동 생성까지, 완벽한 DJ 어시스턴트 기능을 활용해보세요.</p>
    </div>
    ''', unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    if 'custom_playlist' not in st.session_state:
        st.session_state.custom_playlist = []
    if 'uploader_key' not in st.session_state:
        st.session_state.uploader_key = 0

    tab1, tab2 = st.tabs(["📂 로컬 폴더로 믹스셋 짜기", "🌐 새로운 음악 디깅하기"])

    with tab1:
        st.markdown("<br><p style='color:#17C8F0; font-weight:700; margin-bottom:10px;'>📁 로컬 음원 저장/스캔 폴더 설정</p>", unsafe_allow_html=True)
        col_path, col_btn = st.columns([8.5, 1.5])
        with col_path:
            st.markdown(f'<div style="background-color:#121217; padding:10px 15px; border-radius:8px; border:1px solid #26262e; color:#f1f5f9; font-size:15px; height:42px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{st.session_state.local_dir}</div>', unsafe_allow_html=True)
        with col_btn:
            if st.button("📁 변경", use_container_width=True, key="btn_select_folder"):
                import tkinter as tk
                from tkinter import filedialog
                root = tk.Tk()
                root.withdraw()
                root.wm_attributes('-topmost', 1)
                selected_folder = filedialog.askdirectory(master=root, initialdir=st.session_state.local_dir, title="음원을 스캔할 폴더를 선택하세요")
                root.destroy()
                if selected_folder:
                    st.session_state.local_dir = selected_folder
                    st.rerun()
                    
        if st.button("🔄 현재 폴더 전체 스캔하여 곡 불러오기", use_container_width=True):
            if os.path.exists(st.session_state.local_dir):
                files_to_scan = [f for f in os.listdir(st.session_state.local_dir) if f.endswith(('.mp3', '.flac'))]
                current_names = [t['name'] for t in st.session_state.custom_playlist]
                new_files = [f for f in files_to_scan if f not in current_names]
                
                if new_files:
                    progress_text = "폴더 내 음원을 스캔하고 분석 중입니다..."
                    my_bar = st.progress(0, text=progress_text)
                    for i, file in enumerate(new_files):
                        full_path = os.path.join(st.session_state.local_dir, file)
                        bpm, key_info, camelot, cues, duration = analyze_audio(full_path)
                        if bpm and camelot:
                            st.session_state.custom_playlist.append({
                                "name": file,
                                "bpm": bpm,
                                "key": key_info,
                                "camelot": camelot,
                                "comp_keys": get_compatible_keys(camelot),
                                "cues": cues,
                                "duration": duration
                            })
                        my_bar.progress((i + 1) / len(new_files), text=f"{progress_text} ({i+1}/{len(new_files)})")
                    my_bar.empty()
                    st.success(f"{len(new_files)}곡 불러오기 및 분석 완료!")
                    st.rerun()
                else:
                    st.info("해당 폴더에 새로 불러올 음원이 없습니다.")

        st.markdown("<br><p style='color:#17C8F0; font-weight:700; margin-bottom:10px;'>🎯 플레이리스트 생성 옵션</p>", unsafe_allow_html=True)
        
        default_min, default_max = 120, 128
        if st.session_state.custom_playlist:
            bpms = [t['bpm'] for t in st.session_state.custom_playlist if t.get('bpm')]
            if bpms:
                default_min = max(60, min(bpms) - 2)
                default_max = min(220, max(bpms) + 2)
                
        col_time, col_bpm = st.columns([1, 1])
        with col_time:
            target_time_str = st.selectbox("⏳ 목표 플레이 타임", ["15분 (Short Mix)", "30분 (Standard Mix)", "1시간 (Long Mix)", "제한 없음 (전체 곡)"])
        with col_bpm:
            target_bpm_range = st.slider("🎚️ 목표 BPM 범위", min_value=60, max_value=220, value=(default_min, default_max), step=1)
            
        st.markdown("<br>", unsafe_allow_html=True)

        uploaded_files = st.file_uploader("곡 추가 (여러 파일 동시 선택 및 드래그 가능)", type=["mp3", "flac", "wav"], accept_multiple_files=True, key=f"mix_uploader_{st.session_state.uploader_key}")
        
        if uploaded_files:
            current_names = [t['name'] for t in st.session_state.custom_playlist]
            for f in uploaded_files:
                if f.name not in current_names:
                    with st.spinner(f"스캔 중: {f.name}"):
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                            tmp.write(f.getvalue())
                            tmp_path = tmp.name
                            
                        bpm, key_info, camelot, cues, duration = analyze_audio(tmp_path)
                        try:
                            os.remove(tmp_path)
                        except:
                            pass
                            
                        if bpm and camelot:
                            st.session_state.custom_playlist.append({
                                "name": f.name,
                                "bpm": bpm,
                                "key": key_info,
                                "camelot": camelot,
                                "comp_keys": get_compatible_keys(camelot),
                                "cues": cues,
                                "duration": duration
                            })
            
            st.session_state.uploader_key += 1
            st.rerun()

        if st.session_state.custom_playlist:
            st.markdown("<p style='color:#17C8F0; font-weight:700; margin-bottom:10px;'>📋 업로드된 원본 트랙 리스트</p>", unsafe_allow_html=True)
            
            tracks_to_delete = []
            for idx, track in enumerate(st.session_state.custom_playlist):
                col_num, col_title, col_del = st.columns([0.6, 8.4, 1])
                with col_num:
                    st.markdown(f"<div style='color:#17C8F0; font-weight:800; padding-top:10px; font-size:17px;'>{idx+1}</div>", unsafe_allow_html=True)
                with col_title:
                    st.markdown(f'''
                    <div style="background-color:#121217; border:1px solid #26262e; border-radius:8px; padding:10px 14px; color:#f1f5f9; font-weight:600; font-size:16px; display:flex; justify-content:space-between; align-items:center;">
                        <span>{track['name']}</span>
                        <span style="color:#17C8F0; font-size:16px; font-weight:700; background-color:#1a1a24; padding:2px 8px; border-radius:4px; border:1px solid #26262e;">{track['bpm']} BPM &nbsp;|&nbsp; {track['camelot']}</span>
                    </div>
                    ''', unsafe_allow_html=True)
                with col_del:
                    if st.button("삭제", key=f"del_track_{idx}", use_container_width=True):
                        tracks_to_delete.append(idx)
                        
            if tracks_to_delete:
                for idx in sorted(tracks_to_delete, reverse=True):
                    st.session_state.custom_playlist.pop(idx)
                st.rerun()

            st.markdown("<br>", unsafe_allow_html=True)
            
            valid_data = st.session_state.custom_playlist
            if valid_data:
                st.markdown("<p style='color:#17C8F0; font-weight:700; margin-top:20px; margin-bottom:10px;'>🎛️ AI 추천 최종 믹싱 플레이리스트</p>", unsafe_allow_html=True)
                
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
                        cues = t.get('cues', {
                            'intro': {'bb': '1마디 1박', 't': '00:00'},
                            'build': {'bb': '1마디 1박', 't': '00:00'},
                            'drop': {'bb': '1마디 1박', 't': '00:00'},
                            'outro': {'bb': '1마디 1박', 't': '00:00'}
                        })
                        
                        if isinstance(cues.get('intro'), str):
                            cues = {
                                'intro': {'bb': cues['intro'], 't': cues['intro']},
                                'build': {'bb': '분석중', 't': '00:00'},
                                'drop': {'bb': cues['drop'], 't': cues['drop']},
                                'outro': {'bb': cues['outro'], 't': cues['outro']}
                            }

                        card = (
                            f'<div style="background-color:#121217; border: 1px solid #26262e; border-radius: 8px; padding: 12px 16px; margin-bottom: 4px;">'
                            f'<span style="color:#17C8F0; font-weight:800; margin-right:10px;">#{idx+1}</span>'
                            f'<span style="color:#f1f5f9; font-weight:600; font-size:16px;">{t["name"]}</span><br>'
                            f'<span style="color:#94a3b8; font-weight:700; font-size:16px; margin-left: 28px;">[{t["bpm"]} BPM | {t["camelot"]}]</span>'
                            f'<div style="margin-top: 10px; margin-left: 28px; padding: 10px; background-color: #0e0e13; border-radius: 6px; font-size: 17px; color: #94a3b8; border-left: 2px solid #17C8F0; line-height: 1.6;">'
                            f'📍 <b>추천 큐 포인트 (마디/박자)</b><br>'
                            f'<span style="color:#22c55e;">▶ Intro</span> {cues["intro"]["bb"]} ({cues["intro"]["t"]}) &nbsp;|&nbsp; '
                            f'<span style="color:#a855f7;">📈 Build-up</span> {cues["build"]["bb"]} ({cues["build"]["t"]}) &nbsp;|&nbsp; '
                            f'<span style="color:#f59e0b;">🔥 Drop</span> {cues["drop"]["bb"]} ({cues["drop"]["t"]}) &nbsp;|&nbsp; '
                            f'<span style="color:#ef4444;">⏬ Outro</span> {cues["outro"]["bb"]} ({cues["outro"]["t"]})'
                            f'</div>'
                            f'</div>'
                        )
                        seq_elements.append(card)
                        
                        if idx < len(mix_seq) - 1:
                            next_t = mix_seq[idx+1]
                            next_cues = next_t.get('cues', {
                                'intro': {'bb': '1마디 1박', 't': '00:00'},
                                'build': {'bb': '1마디 1박', 't': '00:00'},
                                'drop': {'bb': '1마디 1박', 't': '00:00'},
                                'outro': {'bb': '1마디 1박', 't': '00:00'}
                            })
                            if isinstance(next_cues.get('intro'), str):
                                next_cues = {
                                    'intro': {'bb': next_cues['intro'], 't': next_cues['intro']},
                                    'build': {'bb': '분석중', 't': '00:00'},
                                    'drop': {'bb': next_cues['drop'], 't': next_cues['drop']},
                                    'outro': {'bb': next_cues['outro'], 't': next_cues['outro']}
                                }
                            
                            key_match = next_t['camelot'] in t['comp_keys']
                            bpm_diff = next_t['bpm'] - t['bpm']
                            bpm_str = f"+{bpm_diff}" if bpm_diff >= 0 else f"{bpm_diff}"
                            
                            if key_match:
                                match_text = f"<span style='color:#22c55e; font-weight:700;'>✨ Perfect Match (Key 호환)</span> &nbsp;|&nbsp; <span style='color:#cbd5e1;'>BPM {bpm_str}</span>"
                            else:
                                match_text = f"<span style='color:#ef4444; font-weight:700;'>⚠️ Key 불일치 (루프/효과음 믹싱 권장)</span> &nbsp;|&nbsp; <span style='color:#cbd5e1;'>BPM {bpm_str}</span>"
                                
                            divider = (
                                f'<div style="text-align:center; background-color:#0e0e13; border-radius:6px; padding:12px 0; margin: 6px 0; font-size:17px;">'
                                f'⬇️ {match_text}<br>'
                                f'<div style="margin-top:12px; color:#f1f5f9; text-align:left; display:inline-block; line-height: 1.6;">'
                                f'<div style="background-color:#121217; padding:8px 14px; border-radius:6px; border:1px solid #26262e; margin-bottom: 6px;">'
                                f'🎧 <b>Option 1 (Standard Blend):</b> 윗 곡 <span style="color:#ef4444;">[Outro / {cues["outro"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:#22c55e;">[Intro / {next_cues["intro"]["bb"]}]</span> 매칭'
                                f'</div>'
                                f'<div style="background-color:#121217; padding:8px 14px; border-radius:6px; border:1px solid #26262e;">'
                                f'🎧 <b>Option 2 (Drop/Slam Mix):</b> 윗 곡 <span style="color:#a855f7;">[Build-up / {cues["build"]["bb"]}]</span> ➡️ 아래 곡 <span style="color:#f59e0b;">[Drop / {next_cues["drop"]["bb"]}]</span> 즉시 전환'
                                f'</div>'
                                f'</div>'
                                f'</div>'
                            )
                            seq_elements.append(divider)
                    st.markdown("".join(seq_elements), unsafe_allow_html=True)
                    
    with tab2:
        st.markdown("<br><p style='color:#17C8F0; font-weight:700; margin-bottom:10px;'>🌐 새로운 트랙 디깅 (인터넷 검색)</p>", unsafe_allow_html=True)
        st.markdown("<p style='color:#94a3b8; font-size:15px; margin-bottom:20px;'>유튜브 검색 특성상 Key 조건은 제외하고 장르와 BPM으로만 넓게 검색하여 DJ 리소스들을 찾습니다.</p>", unsafe_allow_html=True)
        
        genres = [
            "Acid House", "Acid Techno", "Afro House", "Afrobeat", "Amapiano", "Ambient",
            "Bass House", "Big Room EDM", "Chillout", "Dancehall", "Deep House", "Downtempo",
            "Drum & Bass", "Dub Techno", "Dubstep", "Electro House", "Frenchcore", "Funk",
            "Funky House", "Future Bass", "Future House", "Hard Techno", "Hardcore",
            "Hardstyle", "Hip Hop", "House", "Indie Dance", "Italo Disco", "Jackin House",
            "K-Pop", "Liquid Drum & Bass", "Lo-Fi House", "Lofi Hip Hop", "Melodic Techno",
            "Minimal House", "Minimal Techno", "Nu Disco", "Peak Time Techno", "Pop",
            "Progressive House", "Progressive Trance", "Psy-Trance", "R&B", "Reggaeton",
            "Retrowave", "Riddim", "Slap House", "Synthwave", "Tech House", "Techno",
            "Trance", "Trap", "Trip Hop", "Tropical House", "UK Garage", "Uplifting Trance",
            "Vaporwave", "Vocal Trance"
        ]
        
        col_genre_tab, col_bpm_tab = st.columns([3, 1])
        with col_genre_tab:
            genre_tab = st.selectbox("추천받을 장르 선택", genres)
        with col_bpm_tab:
            target_bpm_tab = st.number_input("추천받을 BPM 선택", min_value=60, max_value=220, value=120, step=1)
            
        if st.button("🚀 선택한 장르와 BPM으로 새로운 곡 디깅하기", use_container_width=True):
            with st.spinner(f"{genre_tab} {target_bpm_tab} BPM 디깅 중..."):
                query = f"{genre_tab} {target_bpm_tab} bpm"
                ai_results = fetch_tracks('YouTube', query)
                
                if ai_results:
                    st.session_state.search_results = ai_results
                    st.session_state.current_view = "Search"
                    st.session_state.search_query = query
                    st.session_state.page = 1
                    st.rerun()
                else:
                    st.warning("결과를 찾을 수 없습니다.")

elif st.session_state.current_view == "Tracklist":
    st.markdown("""
    <div class="ai-box">
        <h3 style="color:#17C8F0; margin-top:0;">🔗 YouTube Tracklist Extractor</h3>
        <p style="color:#cbd5e1; font-size: 16px;">DJ 믹스셋이나 페스티벌 영상의 유튜브 링크를 입력하면 수록곡(Tracklist)을 자동 추출합니다.</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    yt_link = st.text_input("YouTube 영상 링크를 입력하세요", placeholder="https://www.youtube.com/watch?v=...", key="yt_tracklist_input")
    if st.button("🚀 트랙리스트 추출", use_container_width=True):
        if yt_link:
            with st.spinner("트랙리스트를 분석 중입니다..."):
                ydl_opts = {'quiet': True, 'skip_download': True}
                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(yt_link, download=False)
                    
                    extracted = []
                    if info.get('chapters'):
                        for ch in info['chapters']:
                            extracted.append(ch.get('title'))
                    elif info.get('description'):
                        desc = info['description']
                        pattern = r'(?:(?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—]?\s*(.+)'
                        matches = re.findall(pattern, desc)
                        if matches:
                            extracted = [m.strip() for m in matches]
                    
                    if extracted:
                        st.session_state.extracted_tracks = extracted
                        st.rerun()
                    else:
                        st.warning("이 영상에서는 트랙리스트(챕터 또는 타임스탬프)를 찾을 수 없습니다.")
                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")
                    
    st.markdown("<br><p style='color:#94a3b8; font-size:15px; margin-bottom:5px;'>💡 영상에 목록이 없나요? 유튜브 댓글이나 1001Tracklists에서 복사해 직접 붙여넣으세요.</p>", unsafe_allow_html=True)
    manual_text = st.text_area("텍스트", placeholder="00:00 Artist - Title\n03:30 Artist2 - Title2", label_visibility="collapsed", height=120)
    if st.button("📝 붙여넣은 텍스트에서 트랙 추출", use_container_width=True):
        if manual_text:
            lines = manual_text.strip().split('\n')
            extracted = []
            for line in lines:
                if not line.strip(): continue
                # 시간(00:00, [00:00] 등) 제거
                clean_line = re.sub(r'\[?(?:(?:\d{1,2}:)?\d{1,2}:\d{2})\]?\s*[-–—]?\s*', '', line).strip()
                # 앞부분 번호(1. 01 - 등) 제거
                clean_line = re.sub(r'^\d+[\.\-\)][\s\-]*', '', clean_line).strip()
                # URL 등 불필요한 라인 스킵
                if clean_line and "http" not in clean_line:
                    extracted.append(clean_line)
            
            if extracted:
                st.session_state.extracted_tracks = extracted
                st.rerun()
            else:
                st.warning("유효한 트랙 텍스트를 찾을 수 없습니다.")

    st.markdown("<br><p style='color:#94a3b8; font-size:15px; margin-bottom:5px;'>🎧 텍스트마저 없다면? AI가 소리를 직접 듣고 찾아냅니다 (3~5분 소요).</p>", unsafe_allow_html=True)
    if st.button("🤖 AI 오디오 스캔 (Shazam) 실행", use_container_width=True):
        if not yt_link:
            st.warning("먼저 화면 상단에 YouTube 영상 링크를 입력해주세요.")
        else:
            try:
                import shazamio
                import nest_asyncio
            except ImportError:
                st.error("이 기능을 사용하려면 터미널에서 `pip install shazamio nest_asyncio` 를 실행해주세요.")
                st.stop()
            
            nest_asyncio.apply()
            from shazamio import Shazam
            
            with st.spinner("AI가 영상을 다운로드하고 스캔을 준비 중입니다... (최대 1~2분 소요)"):
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".m4a") as tmp_audio:
                        tmp_audio_path = tmp_audio.name
                        
                    ydl_opts_scan = {
                        'format': 'worstaudio/worst',
                        'outtmpl': tmp_audio_path,
                        'quiet': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts_scan) as ydl:
                        info_dict = ydl.extract_info(yt_link, download=True)
                        duration = info_dict.get('duration', 3600)
                        
                    async def scan_audio():
                        shazam = Shazam()
                        results = []
                        chunk_length = 180 # 3분 간격으로 추출
                        total_chunks = int(duration // chunk_length) + 1
                        
                        scan_prog = st.progress(0.0, text="AI 스캔 시작...")
                        
                        for i in range(total_chunks):
                            start_time = i * chunk_length
                            snippet_path = tmp_audio_path + f"_{i}.mp3"
                            cmd = ['ffmpeg', '-y', '-i', tmp_audio_path, '-ss', str(start_time), '-t', '15', '-c:a', 'libmp3lame', snippet_path]
                            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            
                            if os.path.exists(snippet_path):
                                try:
                                    if hasattr(shazam, 'recognize_song'):
                                        out = await shazam.recognize_song(snippet_path)
                                    else:
                                        out = await shazam.recognize(snippet_path)
                                        
                                    if 'track' in out:
                                        title = out['track'].get('title', '')
                                        artist = out['track'].get('subtitle', '')
                                        t_name = f"{artist} - {title}" if artist else title
                                        if t_name and t_name not in results:
                                            results.append(t_name)
                                except Exception as inner_e:
                                    pass
                                try: os.remove(snippet_path)
                                except: pass
                                
                            scan_prog.progress(min(1.0, (i + 1) / total_chunks), text=f"AI 스캔 중... ({i+1}/{total_chunks}) 구간 완료. 현재 {len(results)}곡 발견.")
                        
                        scan_prog.empty()
                        return results
                    
                    extracted_ai = asyncio.run(scan_audio())
                    
                    try: os.remove(tmp_audio_path)
                    except: pass
                    
                    if extracted_ai:
                        st.session_state.extracted_tracks = extracted_ai
                        st.rerun()
                    else:
                        st.warning("AI가 곡을 인식하지 못했습니다. (미발매곡이거나 음질이 너무 낮을 수 있습니다)")
                        
                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")

    if st.session_state.get('extracted_tracks'):
        st.markdown(f"<p style='color:#17C8F0; font-weight:700; margin-top:20px; margin-bottom:10px;'>📋 추출된 트랙 리스트 ({len(st.session_state.extracted_tracks)}곡)</p>", unsafe_allow_html=True)
        
        for idx, track in enumerate(st.session_state.extracted_tracks):
            col_num, col_name, col_btn = st.columns([0.6, 7.4, 2])
            with col_num:
                st.markdown(f"<div style='color:#17C8F0; font-weight:800; padding-top:10px; font-size:17px;'>{idx+1}</div>", unsafe_allow_html=True)
            with col_name:
                st.markdown(f"""
                <div style="background-color:#121217; border:1px solid #26262e; border-radius:8px; padding:10px 14px; color:#f1f5f9; font-weight:600; font-size:16px;">
                    {track}
                </div>
                """, unsafe_allow_html=True)
            with col_btn:
                if st.button("🔎 검색하기", key=f"search_track_{idx}", use_container_width=True):
                    clean_track = re.sub(r'^(?:(?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—]?\s*', '', track).strip()
                    st.session_state.search_input_value = clean_track
                    st.session_state.search_query = clean_track
                    st.session_state.auto_search = True
                    st.session_state.current_view = "Search"
                    st.rerun()

elif st.session_state.current_view in ["Search", "Bookmarks"]:
    active_list = st.session_state.search_results if st.session_state.current_view == "Search" else st.session_state.bookmarks
    total_tracks = len(active_list)
    
    if total_tracks == 0 and st.session_state.current_view == "Bookmarks":
        st.markdown("<p style='text-align: center; color: #64748b; margin-top: 40px;'>No bookmarks added yet. Search and star some tracks!</p>", unsafe_allow_html=True)
    elif total_tracks > 0:
        items_per_page = 50
        total_pages = max(1, (total_tracks - 1) // items_per_page + 1)
        
        if st.session_state.page > total_pages:
            st.session_state.page = total_pages

        title_prefix = "SEARCH RESULTS" if st.session_state.current_view == "Search" else "BOOKMARKS"
        st.markdown(f"<p style='color: #17C8F0; font-weight: 600; font-size: 16px; margin-top: 10px; margin-bottom: 12px;'>{title_prefix} ({total_tracks} tracks) - [{st.session_state.active_format} MODE]</p>", unsafe_allow_html=True)

        start_idx = (st.session_state.page - 1) * items_per_page
        end_idx = min(start_idx + items_per_page, total_tracks)
        page_items = active_list[start_idx:end_idx]

        with st.container(border=True):
            for local_i, video in enumerate(page_items):
                i = start_idx + local_i
                duration = video.get('duration')
                time_str = f"{int(duration) // 60}:{int(duration) % 60:02d}" if duration else "미상"
                
                if duration:
                    size_mb = (duration * 320 * 1000 / 8) / (1024 * 1024)
                    size_str = f"{size_mb:.1f} MB"
                else:
                    size_str = "- MB"

                platform = video.get('platform', 'Unknown')
                
                yt_icon = '<svg height="15" width="20" viewBox="0 0 24 24" style="fill: #ef4444; vertical-align: middle; margin-right: 6px;"><path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>'
                sc_icon = '<svg height="15" width="24" viewBox="0 0 24 24" style="fill: #f97316; vertical-align: middle; margin-right: 6px;"><path d="M19.36 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.64-4.96z"/></svg>'
                
                platform_html = yt_icon if platform == 'YouTube' else sc_icon
                badge_text = st.session_state.active_format
                
                col_info, col_meta, col_actions = st.columns([4, 3, 5])
                
                with col_info:
                    st.markdown(f"{platform_html} <span style='color: #f1f5f9; font-weight: 600;'>{video.get('title')}</span> <span class='format-badge'>{badge_text}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color: #64748b; font-size: 16px; margin-left: 26px;'>{video.get('uploader', '정보 없음')}</span>", unsafe_allow_html=True)
                    
                with col_meta:
                    m1, m2, m3 = st.columns(3)
                    with m1:
                        st.markdown(f"<div class='meta-pill'>{size_str}</div>", unsafe_allow_html=True)
                    with m2:
                        display_kbps = "Lossless" if st.session_state.active_format == "FLAC" else "320 kbps"
                        st.markdown(f"<div class='meta-pill'>{display_kbps}</div>", unsafe_allow_html=True)
                    with m3:
                        st.markdown(f"<div class='meta-pill'>{time_str}</div>", unsafe_allow_html=True)
                            
                with col_actions:
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("▶ Play", key=f"preview_{st.session_state.current_view}_{i}", help="Instant Preview", use_container_width=True):
                            with st.spinner("Loading stream..."):
                                try:
                                    ydl_stream_opts = {
                                        'format': 'bestaudio/best',
                                        'quiet': True,
                                        'geo_bypass': True,
                                        'nocheckcertificate': True
                                    }
                                    with yt_dlp.YoutubeDL(ydl_stream_opts) as ydl_s:
                                        info_s = ydl_s.extract_info(video['url'], download=False)
                                        st.session_state.active_preview = i
                                        st.session_state.preview_url = info_s.get('url')
                                        st.rerun()
                                except Exception as e:
                                    error_msg = str(e).replace('"', "'")
                                    error_msg = re.sub(r' \[[0-9;]*[a-zA-Z]', '', error_msg)
                                    st.warning(f"Preview unavailable. ({error_msg})")
                    with b2:
                        is_bookmarked = any(b['url'] == video['url'] for b in st.session_state.bookmarks)
                        bm_label = "🌟 Starred" if is_bookmarked else "⭐ Star"
                        if st.button(bm_label, key=f"bm_{st.session_state.current_view}_{i}", help="Bookmark Track", use_container_width=True):
                            if is_bookmarked:
                                st.session_state.bookmarks = [b for b in st.session_state.bookmarks if b['url'] != video['url']]
                            else:
                                st.session_state.bookmarks.append(video)
                            save_bookmarks(st.session_state.bookmarks)
                            st.rerun()
                    with b3:
                        is_flac = st.session_state.active_format == "FLAC"
                        dl_label = "⬇ Down"
                        
                        if st.button(dl_label, key=f"dl_{st.session_state.current_view}_{i}", help="Direct Download", use_container_width=True):
                            target_codec = 'flac' if is_flac else 'mp3'
                            if i not in st.session_state.download_queue:
                                st.session_state.download_queue.append(i)
                            queue_total = len(st.session_state.download_queue)
                            queue_current = st.session_state.download_queue.index(i) + 1
                            
                            st.session_state.download_status[i] = f"[{queue_current} of {queue_total}] Downloading & Analyzing..."
                            
                            dl_progress = st.progress(0.0, text="⏳ 다운로드 준비 중...")
                            
                            def ytdl_hook(d):
                                if d['status'] == 'downloading':
                                    total = d.get('total_bytes') or d.get('total_bytes_estimate')
                                    downloaded = d.get('downloaded_bytes', 0)
                                    if total and total > 0:
                                        pct = float(downloaded) / float(total)
                                        pct = max(0.0, min(1.0, pct))
                                        dl_progress.progress(pct, text=f"⬇ 다운로드 진행률: {int(pct*100)}%")
                                elif d['status'] == 'finished':
                                    dl_progress.progress(1.0, text="⚙️ 오디오 파일 변환 및 메타데이터 태그 저장 중...")

                            try:
                                downloads_dir = st.session_state.local_dir
                                if not os.path.exists(downloads_dir):
                                    os.makedirs(downloads_dir)
                                
                                ydl_opts_dl = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': os.path.join(downloads_dir, '%(title)s.%(ext)s'),
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': target_codec,
                                    }],
                                    'quiet': True,
                                    'geo_bypass': True,
                                    'nocheckcertificate': True,
                                    'progress_hooks': [ytdl_hook],
                                    'http_headers': {
                                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                                    }
                                }
                                if not is_flac:
                                    ydl_opts_dl['postprocessors'][0]['preferredquality'] = '320'

                                with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl_dl:
                                    info_dict = ydl_dl.extract_info(video['url'], download=True)
                                    orig_file_path = ydl_dl.prepare_filename(info_dict)
                                    base, _ = os.path.splitext(orig_file_path)
                                    downloaded_file = base + f".{target_codec}"
                                
                                if os.path.exists(downloaded_file):
                                    if True:
                                        artist = info_dict.get('artist')
                                        track = info_dict.get('track')
                                        raw_title = info_dict.get('title', '')
                                        
                                        # 1. 메타데이터(음원 공식 정보)가 최우선
                                        if artist and track:
                                            clean_title = f"{artist} - {track}"
                                        # 2. 영상 제목에 ' - ' 가 이미 있는 경우
                                        elif " - " in raw_title:
                                            clean_title = raw_title
                                        # 3. 메타데이터가 부족하면 채널명(업로더)을 아티스트로 대체
                                        else:
                                            uploader = info_dict.get('uploader', '')
                                            if uploader and uploader.lower() not in raw_title.lower():
                                                clean_title = f"{uploader} - {raw_title}"
                                            else:
                                                clean_title = raw_title
                                                
                                        # 앞에 붙은 불필요한 트랙 번호 제거 (예: "001. ", "01-", "1 " 등)
                                        clean_title = re.sub(r'^\d+[\.\-\s]+', '', clean_title).strip()
                                            
                                        # 슬래시(/)를 쉼표(,)로 변환하여 아티스트 구분 유지
                                        clean_title = clean_title.replace(' / ', ', ').replace('/', ', ')
                                        # 파일 시스템 금지 특수문자 제거
                                        clean_title = re.sub(r'[\\*?:"<>|]', "", clean_title)
                                        new_filename = f"{clean_title}.{target_codec}"
                                        new_filepath = os.path.join(downloads_dir, new_filename)
                                        
                                        if downloaded_file != new_filepath:
                                            if os.path.exists(new_filepath):
                                                try: os.remove(new_filepath)
                                                except: pass
                                            os.replace(downloaded_file, new_filepath)
                                        
                                        # 메타데이터(ID3 태그) 강제 주입 로직
                                        artist_tag = ""
                                        title_tag = clean_title
                                        if " - " in clean_title:
                                            parts = clean_title.split(" - ", 1)
                                            artist_tag = parts[0].strip()
                                            title_tag = parts[1].strip()
                                            
                                        temp_filepath = new_filepath + f".temp.{target_codec}"
                                        import subprocess
                                        cmd = ['ffmpeg', '-y', '-i', new_filepath]
                                        if artist_tag:
                                            cmd.extend(['-metadata', f'artist={artist_tag}'])
                                        cmd.extend(['-metadata', f'title={title_tag}', '-codec', 'copy', temp_filepath])
                                        
                                        try:
                                            # 윈도우 환경에서 콘솔 창이 깜빡이지 않도록 처리
                                            creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                                            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
                                            if os.path.exists(temp_filepath):
                                                os.replace(temp_filepath, new_filepath)
                                        except Exception:
                                            if os.path.exists(temp_filepath):
                                                try: os.remove(temp_filepath)
                                                except: pass
                                        st.session_state.download_status[i] = f"✅ Saved: {new_filename}"
                                    else:
                                        st.session_state.download_status[i] = "✅ Saved to Downloads!"
                                dl_progress.empty()
                                st.rerun()
                            except Exception as ex:
                                dl_progress.empty()
                                if platform == 'YouTube':
                                    st.session_state.download_status[i] = "⚠️ YouTube blocked."
                                else:
                                    st.session_state.download_status[i] = f"⚠️ Failed: {ex}"

                if i in st.session_state.download_status:
                    status_text = st.session_state.download_status[i]
                    color_code = "#17C8F0" if "Saved" in status_text else ("#38bdf8" if "Downloading" in status_text else "#ef4444")
                    st.markdown(f"<div style='color: {color_code}; font-size: 17px; font-weight: 700; margin-top: 4px; text-align: right;'>{status_text}</div>", unsafe_allow_html=True)
                                    
                if st.session_state.active_preview == i and st.session_state.preview_url:
                    st.audio(st.session_state.preview_url, autoplay=True)

                if local_i < len(page_items) - 1:
                    st.markdown("<hr style='margin: 8px 0; border: none; border-top: 1px solid #26262e;'>", unsafe_allow_html=True)

        if total_pages > 1:
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("<div style='text-align: center; color: #64748b; font-weight: 600; font-size: 16px; margin-bottom: 6px;'>SELECT PAGE</div>", unsafe_allow_html=True)
            
            page_cols = st.columns(total_pages)
            for p in range(1, total_pages + 1):
                with page_cols[p - 1]:
                    is_current = (p == st.session_state.page)
                    btn_label = f"• {p} •" if is_current else f"{p}"
                    if st.button(btn_label, key=f"bottom_page_{st.session_state.current_view}_{p}", use_container_width=True):
                        if not is_current:
                            st.session_state.page = p
                            st.rerun()