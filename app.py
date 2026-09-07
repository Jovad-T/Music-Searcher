import streamlit as st
import yt_dlp
import os
import tempfile

st.set_page_config(page_title="Music Searcher", page_icon="🎧", layout="wide")

st.markdown("""
<style>
    /* Streamlit 기본 헤더, 툴바, 푸터, 우측 하단 배지 완전히 숨기기 */
    [data-testid="stHeader"] { display: none !important; }
    [data-testid="stToolbar"] { display: none !important; }
    footer { display: none !important; }
    div.viewerBadge_container__1QSob { display: none !important; }
    [data-testid="stStatusWidget"] { display: none !important; }

    .stApp { 
        background-color: #0A0A0C; 
        color: #f1f5f9;
        padding-top: 2rem;
    }
    
    div[data-testid="InputInstructions"] { display: none !important; }
    
    /* 통합된 네온 검색바 컨테이너 디자인 */
    div[data-testid="stForm"] {
        background-color: #121217 !important;
        border: 2px solid #17C8F0 !important;
        border-radius: 12px !important;
        padding: 6px 8px 6px 14px !important;
        display: flex !important;
        align-items: center !important;
        box-shadow: 0 0 15px rgba(23, 200, 240, 0.3) !important;
    }
    div[data-testid="stForm"]:focus-within {
        border-color: #38bdf8 !important;
        box-shadow: 0 0 20px rgba(56, 189, 248, 0.5) !important;
    }

    div[data-testid="stForm"] > div[data-testid="stVerticalBlock"] {
        width: 100% !important;
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        gap: 10px !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    .stTextInput {
        flex-grow: 1 !important;
        margin: 0 !important;
    }
    .stTextInput input {
        background-color: transparent !important;
        color: #ffffff !important;
        border: none !important;
        box-shadow: none !important;
        padding-left: 36px !important;
        height: 42px !important;
        background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="%2317C8F0" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>') !important;
        background-repeat: no-repeat !important;
        background-position: 8px center !important;
    }
    .stTextInput input::placeholder { color: #94a3b8 !important; }

    .stFormSubmitButton {
        margin: 0 !important;
        width: auto !important;
    }
    .stFormSubmitButton button {
        background-color: #17C8F0 !important;
        color: #0A0A0C !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 800 !important;
        height: 38px !important;
        padding: 0 20px !important;
        font-size: 14px !important;
        transition: all 0.2s ease;
    }
    .stFormSubmitButton button:hover {
        background-color: #38bdf8 !important;
        color: #0A0A0C !important;
        box-shadow: 0 0 10px rgba(56, 189, 248, 0.4);
    }

    .stButton button {
        background-color: #121217 !important;
        color: #ffffff !important;
        border: 1px solid #26262e !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
        transition: all 0.2s ease;
    }
    .stButton button:hover {
        background-color: #17C8F0 !important;
        color: #0A0A0C !important;
        border-color: #17C8F0 !important;
    }

    .format-badge {
        background-color: #121217; color: #17C8F0; font-size: 11px; 
        font-weight: 700; padding: 2px 6px; border-radius: 4px; margin-left: 6px;
        border: 1px solid #26262e;
    }
    
    .meta-pill {
        background-color: #121217; color: #cbd5e1; font-size: 13px; 
        padding: 8px 0px; border-radius: 8px; font-weight: 700; text-align: center;
        border: 1px solid #26262e; display: block; width: 100%;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }

    div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
        background-color: #121217;
        border: 1px solid #26262e;
        border-radius: 12px;
        padding: 10px;
    }
</style>
""", unsafe_allow_html=True)

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
if 'download_ready' not in st.session_state:
    st.session_state.download_ready = {}
if 'active_format' not in st.session_state:
    st.session_state.active_format = "MP3"

with st.form(key='search_form'):
    user_input = st.text_input("Search", label_visibility="collapsed", value=st.session_state.search_query, placeholder="Search for songs, artists...")
    submit_button = st.form_submit_button(label="Search")

if submit_button:
    if user_input:
        st.session_state.search_query = user_input
        st.session_state.page = 1
        st.session_state.download_ready = {}
        with st.spinner("Searching tracks... Please wait!"):
            ydl_opts = {
                'extract_flat': 'in_playlist',
                'quiet': True,
                'extractor_args': {'youtube': {'player_client': ['android', 'mweb']}}
            }
            combined_entries = []
            
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    yt_info = ydl.extract_info(f"ytsearch100:{user_input}", download=False)
                    for entry in yt_info.get('entries', []):
                        if entry:
                            entry['platform'] = 'YouTube'
                            combined_entries.append(entry)
            except Exception:
                pass

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    sc_info = yt_dlp.YoutubeDL(ydl_opts).extract_info(f"scsearch100:{user_input}", download=False)
                    for entry in sc_info.get('entries', []):
                        if entry:
                            entry['platform'] = 'SoundCloud'
                            combined_entries.append(entry)
            except Exception:
                pass

            filtered_entries = []
            for video in combined_entries:
                duration = video.get('duration')
                if duration is None or duration < 600:
                    filtered_entries.append(video)

            st.session_state.search_results = filtered_entries
            st.session_state.active_preview = None
            st.session_state.preview_url = None
    else:
        st.warning("Please enter a search query!")

if st.session_state.search_results:
    st.markdown("<br>", unsafe_allow_html=True)
    
    f_col1, f_col2, f_col_rest = st.columns([1, 1, 8])
    with f_col1:
        is_mp3_active = st.session_state.active_format == "MP3"
        mp3_label = "● MP3" if is_mp3_active else "MP3"
        if st.button(mp3_label, use_container_width=True, key="filter_mp3"):
            if not is_mp3_active:
                st.session_state.active_format = "MP3"
                st.session_state.download_ready = {}
                st.rerun()
    with f_col2:
        is_flac_active = st.session_state.active_format == "FLAC"
        flac_label = "● FLAC" if is_flac_active else "FLAC"
        if st.button(flac_label, use_container_width=True, key="filter_flac"):
            if not is_flac_active:
                st.session_state.active_format = "FLAC"
                st.session_state.download_ready = {}
                st.rerun()

    total_tracks = len(st.session_state.search_results)
    items_per_page = 50
    total_pages = max(1, (total_tracks - 1) // items_per_page + 1)
    
    if st.session_state.page > total_pages:
        st.session_state.page = total_pages

    st.markdown(f"<p style='color: #17C8F0; font-weight: 600; font-size: 14px; margin-top: 10px; margin-bottom: 12px;'>SEARCH RESULTS ({total_tracks} tracks) - [{st.session_state.active_format} MODE]</p>", unsafe_allow_html=True)

    start_idx = (st.session_state.page - 1) * items_per_page
    end_idx = min(start_idx + items_per_page, total_tracks)
    page_items = st.session_state.search_results[start_idx:end_idx]

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
            
            col_info, col_meta, col_actions = st.columns([5, 4, 3])
            
            with col_info:
                st.markdown(f"{platform_html} <span style='color: #f1f5f9; font-weight: 600;'>{video.get('title')}</span> <span class='format-badge'>{badge_text}</span>", unsafe_allow_html=True)
                st.markdown(f"<span style='color: #64748b; font-size: 12px; margin-left: 26px;'>{video.get('uploader', '정보 없음')}</span>", unsafe_allow_html=True)
                
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
                b1, b2 = st.columns(2)
                with b1:
                    if st.button("▶ Play", key=f"preview_{i}", help="Instant Preview", use_container_width=True):
                        with st.spinner("Loading stream..."):
                            try:
                                ydl_stream_opts = {
                                    'format': 'bestaudio',
                                    'quiet': True,
                                    'extractor_args': {'youtube': {'player_client': ['android', 'mweb']}}
                                }
                                with yt_dlp.YoutubeDL(ydl_stream_opts) as ydl_s:
                                    info_s = ydl_s.extract_info(video['url'], download=False)
                                    st.session_state.active_preview = i
                                    st.session_state.preview_url = info_s.get('url')
                            except Exception as e:
                                st.error(f"Failed: {e}")
                with b2:
                    is_flac = st.session_state.active_format == "FLAC"
                    dl_label = "⬇ FLAC" if is_flac else "⬇ Download"
                    if st.button(dl_label, key=f"dl_prep_{i}", help="Prepare Download", use_container_width=True):
                        target_codec = 'flac' if is_flac else 'mp3'
                        with st.spinner(f"Converting to {target_codec.upper()}..."):
                            try:
                                temp_dir = tempfile.gettempdir()
                                ydl_opts_dl = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': target_codec,
                                    }],
                                    'quiet': True,
                                    'extractor_args': {'youtube': {'player_client': ['android', 'mweb']}}
                                }
                                if not is_flac:
                                    ydl_opts_dl['postprocessors'][0]['preferredquality'] = '320'

                                with yt_dlp.YoutubeDL(ydl_opts_dl) as ydl_dl:
                                    info_dict = ydl_dl.extract_info(video['url'], download=True)
                                    file_path = ydl_dl.prepare_filename(info_dict)
                                    base, _ = os.path.splitext(file_path)
                                    final_ext = ".flac" if is_flac else ".mp3"
                                    audio_path = base + final_ext
                                    
                                    if os.path.exists(audio_path):
                                        with open(audio_path, "rb") as f:
                                            st.session_state.download_ready[i] = {
                                                "data": f.read(),
                                                "filename": f"{video.get('title', 'track')}{final_ext}"
                                            }
                            except Exception as e:
                                st.error(f"Failed: {e}")

            if i in st.session_state.download_ready:
                item = st.session_state.download_ready[i]
                st.download_button(
                    label=f"💾 Save '{item['filename']}' to PC",
                    data=item['data'],
                    file_name=item['filename'],
                    mime="audio/flac" if item['filename'].endswith('.flac') else "audio/mpeg",
                    key=f"save_file_{i}"
                )
                                
            if st.session_state.active_preview == i and st.session_state.preview_url:
                st.audio(st.session_state.preview_url, autoplay=True)

            if local_i < len(page_items) - 1:
                st.markdown("<hr style='margin: 8px 0; border: none; border-top: 1px solid #26262e;'>", unsafe_allow_html=True)

    if total_pages > 1:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("<div style='text-align: center; color: #64748b; font-weight: 600; font-size: 12px; margin-bottom: 6px;'>SELECT PAGE</div>", unsafe_allow_html=True)
        
        page_cols = st.columns(total_pages)
        for p in range(1, total_pages + 1):
            with page_cols[p - 1]:
                is_current = (p == st.session_state.page)
                btn_label = f"• {p} •" if is_current else f"{p}"
                if st.button(btn_label, key=f"bottom_page_{p}", use_container_width=True):
                    if not is_current:
                        st.session_state.page = p
                        st.rerun()
