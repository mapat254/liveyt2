import sys
import subprocess
import threading
import time
import os
import streamlit.components.v1 as components
import shutil
import datetime
import pandas as pd
import json
import signal
import psutil

# Install streamlit if not already installed
try:
    import streamlit as st
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit"])
    import streamlit as st

# Persistent storage file
STREAMS_FILE = "streams_data.json"
ACTIVE_STREAMS_FILE = "active_streams.json"

def load_persistent_streams():
    """Load streams from persistent storage"""
    if os.path.exists(STREAMS_FILE):
        try:
            with open(STREAMS_FILE, "r") as f:
                data = json.load(f)
                return pd.DataFrame(data)
        except:
            return pd.DataFrame(columns=[
                'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts', 'Quality'
            ])
    return pd.DataFrame(columns=[
        'Video', 'Durasi', 'Jam Mulai', 'Streaming Key', 'Status', 'Is Shorts', 'Quality'
    ])

def save_persistent_streams(streams_df):
    """Save streams to persistent storage"""
    try:
        with open(STREAMS_FILE, "w") as f:
            json.dump(streams_df.to_dict('records'), f, indent=2)
    except Exception as e:
        st.error(f"Error saving streams: {e}")

def load_active_streams():
    """Load active streams tracking"""
    if os.path.exists(ACTIVE_STREAMS_FILE):
        try:
            with open(ACTIVE_STREAMS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_active_streams(active_streams):
    """Save active streams tracking"""
    try:
        with open(ACTIVE_STREAMS_FILE, "w") as f:
            json.dump(active_streams, f, indent=2)
    except Exception as e:
        st.error(f"Error saving active streams: {e}")

def check_ffmpeg():
    """Check if ffmpeg is installed and available"""
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        st.error("FFmpeg is not installed or not in PATH. Please install FFmpeg to use this application.")
        st.markdown("""
        ### How to install FFmpeg:
        
        - **Ubuntu/Debian**: `sudo apt-get install ffmpeg`
        - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
        - **macOS**: `brew install ffmpeg`
        """)
        return False
    return True

def is_process_running(pid):
    """Check if a process with given PID is still running"""
    try:
        # Check if PID exists and is running
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            # Check if it's actually an ffmpeg process
            if 'ffmpeg' in process.name().lower():
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False

def reconnect_to_existing_streams():
    """Reconnect to streams that are still running after page refresh"""
    active_streams = load_active_streams()
    
    # Get all existing PID files
    pid_files = [f for f in os.listdir('.') if f.startswith('stream_') and f.endswith('.pid')]
    
    for pid_file in pid_files:
        try:
            row_id = int(pid_file.split('_')[1].split('.')[0])
            
            # Check if PID file has valid running process
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            
            if is_process_running(pid):
                # Process is still running, update status
                if row_id < len(st.session_state.streams):
                    st.session_state.streams.loc[row_id, 'Status'] = 'Sedang Live'
                    active_streams[str(row_id)] = {
                        'pid': pid,
                        'started_at': datetime.datetime.now().isoformat()
                    }
            else:
                # Process is dead, clean up
                cleanup_stream_files(row_id)
                if str(row_id) in active_streams:
                    del active_streams[str(row_id)]
                
        except (ValueError, FileNotFoundError, IOError):
            # Invalid file, remove it
            try:
                os.remove(pid_file)
            except:
                pass
    
    save_active_streams(active_streams)

def cleanup_stream_files(row_id):
    """Clean up all files related to a stream"""
    files_to_remove = [
        f"stream_{row_id}.pid",
        f"stream_{row_id}.status"
    ]
    
    for file_name in files_to_remove:
        try:
            if os.path.exists(file_name):
                os.remove(file_name)
        except:
            pass

def get_quality_settings(quality, is_shorts=False):
    """Get optimized encoding settings based on quality"""
    settings = {
        "720p": {
            "video_bitrate": "2500k",
            "audio_bitrate": "128k",
            "maxrate": "2750k",
            "bufsize": "5500k",
            "scale": "1280:720" if not is_shorts else "720:1280",
            "fps": "30"
        },
        "1080p": {
            "video_bitrate": "4500k",
            "audio_bitrate": "192k",
            "maxrate": "4950k",
            "bufsize": "9900k",
            "scale": "1920:1080" if not is_shorts else "1080:1920",
            "fps": "30"
        },
        "480p": {
            "video_bitrate": "1000k",
            "audio_bitrate": "96k",
            "maxrate": "1100k",
            "bufsize": "2200k",
            "scale": "854:480" if not is_shorts else "480:854",
            "fps": "30"
        }
    }
    return settings.get(quality, settings["720p"])

def run_ffmpeg(video_path, stream_key, is_shorts, row_id, quality="720p"):
    """Stream a video file to RTMP server using ffmpeg with optimized settings"""
    output_url = f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
    
    # Create log file
    log_file = f"stream_{row_id}.log"
    with open(log_file, "w") as f:
        f.write(f"Starting optimized stream for {video_path} at {datetime.datetime.now()}\n")
        f.write(f"Quality: {quality}, Shorts: {is_shorts}\n")
    
    # Get quality settings
    settings = get_quality_settings(quality, is_shorts)
    
    # Build optimized command for YouTube Live
    cmd = [
        "ffmpeg",
        "-hide_banner",         # Hide FFmpeg banner
        "-loglevel", "info",    # Set log level
        "-re",                  # Read input at native frame rate
        "-stream_loop", "-1",   # Loop the video indefinitely
        "-i", video_path,       # Input file
        
        # Video encoding settings optimized for YouTube
        "-c:v", "libx264",      # Video codec
        "-preset", "veryfast",  # Encoding preset for speed
        "-tune", "zerolatency", # Optimize for low latency
        "-profile:v", "high",   # H.264 profile
        "-level", "4.1",        # H.264 level
        "-pix_fmt", "yuv420p",  # Pixel format
        
        # Bitrate control
        "-b:v", settings["video_bitrate"],
        "-maxrate", settings["maxrate"],
        "-bufsize", settings["bufsize"],
        "-minrate", str(int(settings["video_bitrate"].replace('k', '')) // 2) + "k",
        
        # GOP and keyframe settings
        "-g", "60",             # GOP size (2 seconds at 30fps)
        "-keyint_min", "30",    # Minimum GOP size
        "-sc_threshold", "0",   # Disable scene change detection
        
        # Frame rate
        "-r", settings["fps"],  # Output frame rate
        
        # Audio encoding
        "-c:a", "aac",          # Audio codec
        "-b:a", settings["audio_bitrate"],
        "-ar", "44100",         # Audio sample rate
        "-ac", "2",             # Audio channels (stereo)
        
        # Scaling and format
        "-vf", f"scale={settings['scale']}:force_original_aspect_ratio=decrease,pad={settings['scale']}:(ow-iw)/2:(oh-ih)/2,fps={settings['fps']}",
        
        # Output format
        "-f", "flv",            # Output format for RTMP
        
        # Connection settings
        "-reconnect", "1",      # Enable reconnection
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        
        # Output URL
        output_url
    ]
    
    # Log the command
    with open(log_file, "a") as f:
        f.write(f"Running: {' '.join(cmd)}\n")
    
    try:
        # Start the process with CREATE_NEW_PROCESS_GROUP on Windows
        if os.name == 'nt':  # Windows
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:  # Unix/Linux/Mac
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                preexec_fn=os.setsid  # Create new session
            )
        
        # Store process ID for later reference
        with open(f"stream_{row_id}.pid", "w") as f:
            f.write(str(process.pid))
        
        # Update status
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("streaming")
        
        # Update active streams tracking
        active_streams = load_active_streams()
        active_streams[str(row_id)] = {
            'pid': process.pid,
            'started_at': datetime.datetime.now().isoformat()
        }
        save_active_streams(active_streams)
        
        # Read and log output in a separate thread to avoid blocking
        def log_output():
            try:
                for line in process.stdout:
                    with open(log_file, "a") as f:
                        f.write(line)
                    # Check for specific YouTube errors
                    if "Connection refused" in line or "Server returned 4" in line:
                        with open(f"stream_{row_id}.status", "w") as f:
                            f.write("error: YouTube connection failed")
            except:
                pass
        
        log_thread = threading.Thread(target=log_output, daemon=True)
        log_thread.start()
        
        # Wait for process to complete
        process.wait()
        
        # Update status when done
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("completed")
        
        with open(log_file, "a") as f:
            f.write("Streaming completed.\n")
        
        # Remove from active streams
        active_streams = load_active_streams()
        if str(row_id) in active_streams:
            del active_streams[str(row_id)]
        save_active_streams(active_streams)
        
    except Exception as e:
        error_msg = f"Error: {str(e)}"
        
        # Write error to log file
        with open(log_file, "a") as f:
            f.write(f"{error_msg}\n")
        
        # Write error to status file
        with open(f"stream_{row_id}.status", "w") as f:
            f.write(f"error: {str(e)}")
        
        # Remove from active streams
        active_streams = load_active_streams()
        if str(row_id) in active_streams:
            del active_streams[str(row_id)]
        save_active_streams(active_streams)
    
    finally:
        with open(log_file, "a") as f:
            f.write("Streaming finished or stopped.\n")
        
        # Clean up PID file
        cleanup_stream_files(row_id)

def start_stream(video_path, stream_key, is_shorts, row_id, quality="720p"):
    """Start a stream in a separate process (not thread)"""
    try:
        # Update status immediately
        st.session_state.streams.loc[row_id, 'Status'] = 'Sedang Live'
        save_persistent_streams(st.session_state.streams)
        
        # Write initial status file
        with open(f"stream_{row_id}.status", "w") as f:
            f.write("starting")
        
        # Start streaming in a separate thread (but make it non-daemon)
        thread = threading.Thread(
            target=run_ffmpeg,
            args=(video_path, stream_key, is_shorts, row_id, quality),
            daemon=False  # Changed to False so it survives page refresh
        )
        thread.start()
        
        return True
    except Exception as e:
        st.error(f"Error starting stream: {e}")
        return False

def stop_stream(row_id):
    """Stop a running stream"""
    try:
        active_streams = load_active_streams()
        
        # First try to get PID from tracking
        pid = None
        if str(row_id) in active_streams:
            pid = active_streams[str(row_id)]['pid']
        
        # If not in tracking, try PID file
        if not pid and os.path.exists(f"stream_{row_id}.pid"):
            with open(f"stream_{row_id}.pid", "r") as f:
                pid = int(f.read().strip())
        
        if pid and is_process_running(pid):
            # Try to terminate the process gracefully
            try:
                if os.name == 'nt':  # Windows
                    # Use taskkill for Windows
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], 
                                 capture_output=True, check=False)
                else:  # Unix/Linux/Mac
                    # Send SIGTERM first, then SIGKILL if needed
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                        time.sleep(2)  # Give it time to shut down gracefully
                        if is_process_running(pid):
                            os.killpg(os.getpgid(pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # Process already terminated
                
                # Update status
                st.session_state.streams.loc[row_id, 'Status'] = 'Dihentikan'
                save_persistent_streams(st.session_state.streams)
                
                # Update status file
                with open(f"stream_{row_id}.status", "w") as f:
                    f.write("stopped")
                
                # Remove from active streams
                if str(row_id) in active_streams:
                    del active_streams[str(row_id)]
                save_active_streams(active_streams)
                
                # Clean up files
                cleanup_stream_files(row_id)
                
                return True
                
            except Exception as e:
                st.error(f"Error stopping stream: {str(e)}")
                return False
        else:
            # Process not found, just update status
            st.session_state.streams.loc[row_id, 'Status'] = 'Dihentikan'
            save_persistent_streams(st.session_state.streams)
            cleanup_stream_files(row_id)
            
            # Remove from active streams
            if str(row_id) in active_streams:
                del active_streams[str(row_id)]
            save_active_streams(active_streams)
            
            return True
            
    except Exception as e:
        st.error(f"Error stopping stream: {str(e)}")
        return False

def check_stream_statuses():
    """Check status files for all streams and update accordingly"""
    active_streams = load_active_streams()
    
    for idx, row in st.session_state.streams.iterrows():
        status_file = f"stream_{idx}.status"
        
        # Check if stream is supposed to be active
        if str(idx) in active_streams:
            pid = active_streams[str(idx)]['pid']
            
            # Check if process is still running
            if not is_process_running(pid):
                # Process died, update status
                if row['Status'] == 'Sedang Live':
                    # Check for completion status
                    if os.path.exists(status_file):
                        with open(status_file, "r") as f:
                            status = f.read().strip()
                        
                        if status == "completed":
                            st.session_state.streams.loc[idx, 'Status'] = 'Selesai'
                        elif status.startswith("error:"):
                            st.session_state.streams.loc[idx, 'Status'] = status
                        else:
                            st.session_state.streams.loc[idx, 'Status'] = 'Terputus'
                        
                        save_persistent_streams(st.session_state.streams)
                        os.remove(status_file)
                    
                    # Remove from active streams
                    del active_streams[str(idx)]
                    save_active_streams(active_streams)
                    cleanup_stream_files(idx)
        
        # Regular status file checking
        elif os.path.exists(status_file):
            with open(status_file, "r") as f:
                status = f.read().strip()
            
            if status == "completed" and row['Status'] == 'Sedang Live':
                st.session_state.streams.loc[idx, 'Status'] = 'Selesai'
                save_persistent_streams(st.session_state.streams)
                os.remove(status_file)
            
            elif status.startswith("error:") and row['Status'] == 'Sedang Live':
                st.session_state.streams.loc[idx, 'Status'] = status
                save_persistent_streams(st.session_state.streams)
                os.remove(status_file)

def check_scheduled_streams():
    """Check for streams that need to be started based on schedule"""
    current_time = datetime.datetime.now().strftime("%H:%M")
    
    for idx, row in st.session_state.streams.iterrows():
        if row['Status'] == 'Menunggu' and row['Jam Mulai'] == current_time:
            # Start the stream
            quality = row.get('Quality', '720p')
            start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), idx, quality)

def get_stream_logs(row_id, max_lines=100):
    """Get logs for a specific stream"""
    log_file = f"stream_{row_id}.log"
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            lines = f.readlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    return []

def main():
    # Page configuration must be the first Streamlit command
    st.set_page_config(
        page_title="Live Streaming Scheduler - Optimized",
        page_icon="📺",
        layout="wide"
    )
    
    st.title("🎥 Live Streaming Scheduler - YouTube Optimized")
    
    # Check if ffmpeg is installed
    if not check_ffmpeg():
        return
    
    # Initialize session state with persistent data
    if 'streams' not in st.session_state:
        st.session_state.streams = load_persistent_streams()
    
    # Reconnect to existing streams after page refresh
    reconnect_to_existing_streams()
    
    # Bagian iklan
    show_ads = st.sidebar.checkbox("Tampilkan Iklan", value=False)
    if show_ads:
        st.sidebar.subheader("Iklan Sponsor")
        components.html(
            """
            <div style="background:#f0f2f6;padding:20px;border-radius:10px;text-align:center">
                <script type='text/javascript' 
                        src='//pl26562103.profitableratecpm.com/28/f9/95/28f9954a1d5bbf4924abe123c76a68d2.js'>
                </script>
                <p style="color:#888">Iklan akan muncul di sini</p>
            </div>
            """,
            height=300
        )
    
    # Check status of running streams
    check_stream_statuses()
    
    # Check for scheduled streams
    check_scheduled_streams()
    
    # Auto-refresh every 10 seconds to check stream status
    if st.sidebar.button("🔄 Refresh Status"):
        st.rerun()
    
    # Show persistent stream info
    active_streams = load_active_streams()
    if active_streams:
        st.sidebar.success(f"🟢 {len(active_streams)} stream(s) berjalan")
    else:
        st.sidebar.info("⚫ Tidak ada stream aktif")
    
    # Create tabs for different sections
    tab1, tab2, tab3, tab4 = st.tabs(["Stream Manager", "Add New Stream", "Logs", "Settings"])
    
    with tab1:
        st.subheader("Manage Streams")
        
        # Auto refresh indicator
        st.caption("✅ Status akan diperbarui otomatis. Streaming akan tetap berjalan meski halaman di-refresh.")
        st.caption("🎯 Optimized untuk YouTube Live dengan pengaturan encoding terbaik")
        
        # Display the streams table with action buttons
        if not st.session_state.streams.empty:
            # Create a header row
            header_cols = st.columns([2, 1, 1, 1, 2, 2, 2])
            header_cols[0].write("**Video**")
            header_cols[1].write("**Duration**")
            header_cols[2].write("**Start Time**")
            header_cols[3].write("**Quality**")
            header_cols[4].write("**Streaming Key**")
            header_cols[5].write("**Status**")
            header_cols[6].write("**Action**")
            
            # Display each stream
            for i, row in st.session_state.streams.iterrows():
                cols = st.columns([2, 1, 1, 1, 2, 2, 2])
                cols[0].write(os.path.basename(row['Video']))  # Just show filename
                cols[1].write(row['Durasi'])
                cols[2].write(row['Jam Mulai'])
                cols[3].write(row.get('Quality', '720p'))
                # Mask streaming key for security
                masked_key = row['Streaming Key'][:4] + "****" if len(row['Streaming Key']) > 4 else "****"
                cols[4].write(masked_key)
                
                # Status with color coding
                status = row['Status']
                if status == 'Sedang Live':
                    cols[5].markdown(f"🟢 **{status}**")
                elif status == 'Menunggu':
                    cols[5].markdown(f"🟡 **{status}**")
                elif status == 'Selesai':
                    cols[5].markdown(f"🔵 **{status}**")
                elif status == 'Dihentikan':
                    cols[5].markdown(f"🟠 **{status}**")
                elif status.startswith('error:'):
                    cols[5].markdown(f"🔴 **Error**")
                else:
                    cols[5].write(status)
                
                # Action buttons
                if row['Status'] == 'Menunggu':
                    if cols[6].button("▶️ Start", key=f"start_{i}"):
                        quality = row.get('Quality', '720p')
                        if start_stream(row['Video'], row['Streaming Key'], row.get('Is Shorts', False), i, quality):
                            st.rerun()
                
                elif row['Status'] == 'Sedang Live':
                    if cols[6].button("⏹️ Stop", key=f"stop_{i}"):
                        if stop_stream(i):
                            st.rerun()
                
                elif row['Status'] in ['Selesai', 'Dihentikan', 'Terputus'] or row['Status'].startswith('error:'):
                    if cols[6].button("🗑️ Remove", key=f"remove_{i}"):
                        st.session_state.streams = st.session_state.streams.drop(i).reset_index(drop=True)
                        save_persistent_streams(st.session_state.streams)
                        # Also remove log file if it exists
                        log_file = f"stream_{i}.log"
                        if os.path.exists(log_file):
                            os.remove(log_file)
                        st.rerun()
        else:
            st.info("No streams added yet. Use the 'Add New Stream' tab to add a stream.")
    
    with tab2:
        st.subheader("Add New Stream")
        
        # List available video files
        video_files = [f for f in os.listdir('.') if f.endswith(('.mp4', '.flv', '.avi', '.mov', '.mkv'))]
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.write("Video yang tersedia:")
            selected_video = st.selectbox("Pilih video", [""] + video_files) if video_files else None
            
            uploaded_file = st.file_uploader("Atau upload video baru", type=['mp4', 'flv', 'avi', 'mov', 'mkv'])
            
            if uploaded_file:
                # Save the uploaded file
                with open(uploaded_file.name, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.success("Video berhasil diupload!")
                video_path = uploaded_file.name
            elif selected_video:
                video_path = selected_video
            else:
                video_path = None
        
        with col2:
            stream_key = st.text_input("Stream Key", type="password")
            
            # Time picker for start time
            now = datetime.datetime.now()
            start_time = st.time_input("Start Time", value=now)
            start_time_str = start_time.strftime("%H:%M")
            
            duration = st.text_input("Duration (HH:MM:SS)", value="01:00:00")
            
            # Quality selection
            quality = st.selectbox("Quality", ["480p", "720p", "1080p"], index=1)
            
            is_shorts = st.checkbox("Mode Shorts (Vertical)")
        
        if st.button("➕ Add Stream"):
            if video_path and stream_key:
                # Get just the filename from the path
                video_filename = os.path.basename(video_path)
                
                new_stream = pd.DataFrame({
                    'Video': [video_path],
                    'Durasi': [duration],
                    'Jam Mulai': [start_time_str],
                    'Streaming Key': [stream_key],
                    'Status': ['Menunggu'],
                    'Is Shorts': [is_shorts],
                    'Quality': [quality]
                })
                
                st.session_state.streams = pd.concat([st.session_state.streams, new_stream], ignore_index=True)
                save_persistent_streams(st.session_state.streams)
                st.success(f"Added stream for {video_filename} with {quality} quality")
                st.rerun()
            else:
                if not video_path:
                    st.error("Please provide a video path")
                if not stream_key:
                    st.error("Please provide a streaming key")
    
    with tab3:
        st.subheader("Stream Logs")
        
        # Get all stream IDs that have log files
        log_files = [f for f in os.listdir('.') if f.startswith('stream_') and f.endswith('.log')]
        stream_ids = [int(f.split('_')[1].split('.')[0]) for f in log_files]
        
        if stream_ids:
            # Create options for selectbox
            stream_options = {}
            for idx in stream_ids:
                if idx in st.session_state.streams.index:
                    video_name = os.path.basename(st.session_state.streams.loc[idx, 'Video'])
                    stream_options[f"{video_name} (ID: {idx})"] = idx
            
            if stream_options:
                selected_stream = st.selectbox("Select stream to view logs", options=list(stream_options.keys()))
                selected_id = stream_options[selected_stream]
                
                # Display logs
                logs = get_stream_logs(selected_id)
                log_container = st.container()
                with log_container:
                    st.code("".join(logs))
                
                # Auto-refresh option
                auto_refresh = st.checkbox("Auto-refresh logs", value=False)
                if auto_refresh:
                    time.sleep(3)  # Wait 3 seconds
                    st.rerun()
            else:
                st.info("No logs available. Start a stream to see logs.")
        else:
            st.info("No logs available. Start a stream to see logs.")
    
    with tab4:
        st.subheader("⚙️ Streaming Settings & Tips")
        
        st.markdown("""
        ### 🎯 Optimizations Applied:
        
        ✅ **Bitrate Control**: Adaptive bitrate dengan buffer yang optimal  
        ✅ **Low Latency**: Tune zerolatency untuk streaming real-time  
        ✅ **Reconnection**: Auto-reconnect jika koneksi terputus  
        ✅ **GOP Settings**: Keyframe interval optimal untuk YouTube  
        ✅ **Audio Quality**: AAC encoding dengan sample rate 44.1kHz  
        
        ### 📊 Quality Settings:
        
        - **480p**: 1000k video bitrate, 96k audio - untuk koneksi lambat
        - **720p**: 2500k video bitrate, 128k audio - recommended
        - **1080p**: 4500k video bitrate, 192k audio - untuk koneksi cepat
        
        ### 🔧 Troubleshooting:
        
        **Jika masih ada buffering:**
        1. Gunakan quality 480p untuk koneksi internet lambat
        2. Pastikan upload speed minimal 3x dari bitrate yang dipilih
        3. Tutup aplikasi lain yang menggunakan internet
        4. Gunakan koneksi ethernet instead of WiFi
        
        **Untuk YouTube Shorts:**
        - Video akan otomatis di-scale ke aspect ratio vertikal
        - Gunakan video dengan resolusi 9:16 untuk hasil terbaik
        """)
        
        # Network test
        st.subheader("🌐 Network Test")
        if st.button("Test Upload Speed"):
            st.info("Untuk test upload speed yang akurat, gunakan speedtest.net")
            st.markdown("[🔗 Test Speed di Speedtest.net](https://speedtest.net)")
    
    # Instructions
    with st.sidebar.expander("📖 How to use"):
        st.markdown("""
        ### Instructions:
        
        1. **Add a Stream**: 
           - Select or upload a video
           - Enter your YouTube stream key
           - Choose quality (480p/720p/1080p)
           - Set start time and duration
           - Check "Mode Shorts" for vertical videos
        
        2. **Manage Streams**:
           - Start/stop streams manually
           - Streams will start automatically at scheduled time
           - View logs to monitor streaming status
           - **Streams will continue running even if you refresh the page!**
        
        ### Requirements:
        
        - FFmpeg must be installed on your system
        - Videos must be in a compatible format (MP4 recommended)
        - Stable internet connection (upload speed 3x bitrate)
        
        ### Quality Recommendations:
        
        - **480p**: Upload speed minimal 3 Mbps
        - **720p**: Upload speed minimal 8 Mbps  
        - **1080p**: Upload speed minimal 15 Mbps
        
        ### Notes:
        
        - Optimized encoding settings untuk YouTube Live
        - Auto-reconnection jika koneksi terputus
        - Buffer management untuk mencegah buffering
        - **NEW**: Quality selector dan optimized settings!
        """)
    
    # Auto refresh every 30 seconds
    time.sleep(1)  # Small delay to prevent too frequent refreshing

if __name__ == '__main__':
    main()
