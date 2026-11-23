import os
import sys
import json
import re
import time
import shutil
import signal
import urllib.parse
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

def get_subprocess_kwargs(**kwargs):
    kwargs["close_fds"] = True
    if sys.platform == "win32":
        flags = kwargs.get("creationflags", 0)
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        kwargs["creationflags"] = flags | DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB
        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs

def run_cmd(*args, **kwargs):
    return subprocess.run(*args, **get_subprocess_kwargs(**kwargs))

def popen_cmd(*args, **kwargs):
    return subprocess.Popen(*args, **get_subprocess_kwargs(**kwargs))

CACHE_DIR = os.environ.get("PIXEL_HQ_CACHE_DIR") or ("/mnt/c/Users/ADMIN/.cache/pixel-hq/music" if (sys.platform != "win32" and os.path.isdir("/mnt/c/Users/ADMIN")) else os.path.expanduser("~/.cache/pixel-hq/music"))
STATE_FILE = os.path.join(CACHE_DIR, "state.json")
QUEUE_FILE = os.path.join(CACHE_DIR, "queue.json")
PREFETCH_PID_FILE = os.path.join(CACHE_DIR, "prefetch.pid")
HISTORY_FILE = os.path.join(CACHE_DIR, "history.json")
POSITION_FILE = os.path.join(CACHE_DIR, "position.log")
MODE_FILE = os.path.join(CACHE_DIR, "mode.json")
MODES = ("order", "loop", "one", "shuffle")
COOKIES_FILE = os.path.join(CACHE_DIR, "cookies.txt")
LOG_FILE = os.path.join(CACHE_DIR, "player.log")

def log_debug(msg):
    try:
        ensure_cache_dir()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{os.getpid()}] {msg}\n")
    except Exception:
        pass

def set_cache_dir(new_dir):
    global CACHE_DIR, STATE_FILE, QUEUE_FILE, PREFETCH_PID_FILE, HISTORY_FILE, POSITION_FILE, MODE_FILE, COOKIES_FILE, LOG_FILE
    CACHE_DIR = new_dir
    STATE_FILE = os.path.join(CACHE_DIR, "state.json")
    QUEUE_FILE = os.path.join(CACHE_DIR, "queue.json")
    PREFETCH_PID_FILE = os.path.join(CACHE_DIR, "prefetch.pid")
    HISTORY_FILE = os.path.join(CACHE_DIR, "history.json")
    POSITION_FILE = os.path.join(CACHE_DIR, "position.log")
    MODE_FILE = os.path.join(CACHE_DIR, "mode.json")
    COOKIES_FILE = os.path.join(CACHE_DIR, "cookies.txt")
    LOG_FILE = os.path.join(CACHE_DIR, "player.log")

def spawn_player_process(player_bin, stream_url, ua, start_seconds=0, page_url=None):
    is_ffplay = "ffplay" in os.path.basename(player_bin).lower()
    # Bilibili's CDN refuses audio requests without a bilibili Referer.
    bilibili = is_bilibili_url(page_url) or is_bilibili_url(stream_url)
    if is_ffplay:
        args = [
            player_bin,
            "-nodisp",
            "-autoexit",
            "-loglevel", "quiet",
            "-stats",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-reconnect_on_network_error", "1",
            "-user_agent", ua
        ]
        if bilibili:
            args.extend(["-headers", "Referer: https://www.bilibili.com/\r\n"])
        if start_seconds > 0:
            args.extend(["-ss", f"{float(start_seconds):.2f}"])
        args.append(stream_url)
    else:
        args = [player_bin, "--no-video", "--really-quiet", f"--user-agent={ua}"]
        if bilibili:
            args.append("--referrer=https://www.bilibili.com/")
        if start_seconds > 0:
            args.extend([f"--start={float(start_seconds):.2f}"])
        args.append(stream_url)

    env = os.environ.copy()
    env["SDL_VIDEODRIVER"] = "dummy"

    try:
        proc = popen_cmd(
            args,
            stdout=subprocess.DEVNULL,
            stderr=position_log(),
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True if sys.platform != "win32" else False
        )
        return proc, None
    except Exception as e:
        return None, str(e)
POOL_SIZE = 1
MAX_HISTORY = 3

DEFAULT_PRESETS = [
    {"title": "SomaFM Groove Salad", "url": "https://ice2.somafm.com/groovesalad-128-mp3"},
    {"title": "Nightwave Plaza", "url": "https://radio.plaza.one/mp3"},
    {"title": "SomaFM DEF CON", "url": "https://ice1.somafm.com/defcon-128-mp3"},
    {"title": "SomaFM Drone Zone", "url": "https://ice6.somafm.com/dronezone-128-mp3"},
]

def ensure_cache_dir():
    try:
        os.makedirs(CACHE_DIR, mode=0o700, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(CACHE_DIR, 0o700)
    except OSError:
        pass

def validate_url(raw_url):
    if not isinstance(raw_url, str):
        return False, "URL must be a string."
    url = raw_url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False, "Only http:// and https:// URLs are allowed."
    if any(c in url for c in ("\r", "\n", "\0", "\t")):
        return False, "URL contains illegal characters."
    return True, url

def is_valid_player_proc(pid):
    if not pid or pid <= 0:
        return False
    if sys.platform.startswith("linux"):
        exe_path = f"/proc/{pid}/exe"
        try:
            target = os.path.realpath(exe_path)
            base = os.path.basename(target).lower()
            if base in ("ffplay", "mpv"):
                return True
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            pass
        cmd_path = f"/proc/{pid}/cmdline"
        try:
            with open(cmd_path, "rb") as f:
                parts = [p.decode("utf-8", errors="ignore").strip().lower() for p in f.read().split(b"\x00") if p]
                if parts:
                    base0 = os.path.basename(parts[0])
                    if base0 in ("ffplay", "mpv"):
                        return True
                    if base0 in ("python", "python3", "sh", "bash", "dash", "env") and len(parts) > 1:
                        target_arg = parts[1]
                        if base0 == "env" and target_arg in ("python", "python3", "sh", "bash") and len(parts) > 2:
                            target_arg = parts[2]
                        base_script = os.path.basename(target_arg)
                        if base_script in ("ffplay", "mpv"):
                            return True
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            return False
        return False
    elif sys.platform == "darwin":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:
            r = run_cmd(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                out = r.stdout.lower()
                return "ffplay" in out or "mpv" in out
        except Exception:
            pass
        return True
    elif sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1400
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            exit_code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code)):
                ctypes.windll.kernel32.CloseHandle(h)
                STILL_ACTIVE = 259
                if exit_code.value != STILL_ACTIVE:
                    return False
            else:
                ctypes.windll.kernel32.CloseHandle(h)
                return False
            return True
        except Exception:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def read_state():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_state(data):
    ensure_cache_dir()
    tmp_file = f"{STATE_FILE}.tmp.{os.getpid()}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(tmp_file, flags, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_file, STATE_FILE)
        if sys.platform != "win32":
            try:
                os.chmod(STATE_FILE, 0o600)
            except OSError:
                pass
    except Exception:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass

def clear_state():
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass

def read_queue():
    if not os.path.exists(QUEUE_FILE):
        return None
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_queue(data):
    ensure_cache_dir()
    tmp_file = f"{QUEUE_FILE}.tmp.{os.getpid()}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(tmp_file, flags, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp_file, QUEUE_FILE)
        if sys.platform != "win32":
            try:
                os.chmod(QUEUE_FILE, 0o600)
            except OSError:
                pass
    except Exception:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass

def kill_prefetch_worker():
    if os.path.exists(PREFETCH_PID_FILE):
        try:
            with open(PREFETCH_PID_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                pid = int(content) if content.isdigit() else None
            if pid and pid > 0:
                if sys.platform == "win32":
                    run_cmd(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=2)
                else:
                    os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            os.remove(PREFETCH_PID_FILE)
        except OSError:
            pass

def clear_queue():
    kill_prefetch_worker()
    if os.path.exists(QUEUE_FILE):
        try:
            os.remove(QUEUE_FILE)
        except OSError:
            pass

def suspend_process(pid):
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_SUSPEND_RESUME = 0x0800
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
            if handle:
                try:
                    res = ctypes.windll.ntdll.NtSuspendProcess(handle)
                    return res == 0
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
        return False
    else:
        try:
            os.kill(pid, signal.SIGSTOP)
            return True
        except OSError:
            return False

def resume_process(pid):
    if not pid or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_SUSPEND_RESUME = 0x0800
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
            if handle:
                try:
                    res = ctypes.windll.ntdll.NtResumeProcess(handle)
                    return res == 0
                finally:
                    ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
        return False
    else:
        try:
            os.kill(pid, signal.SIGCONT)
            return True
        except OSError:
            return False

def stop_process(pid, is_paused=False):
    if not is_valid_player_proc(pid):
        return
    if is_paused:
        resume_process(pid)
    if sys.platform != "win32":
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        deadline = time.time() + 1.2
        while time.time() < deadline:
            if not is_valid_player_proc(pid):
                return
            time.sleep(0.08)
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    else:
        try:
            run_cmd(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=3)
        except Exception:
            pass

def find_running_player_pid():
    if sys.platform == "win32":
        try:
            r = run_cmd(["tasklist", "/FI", "IMAGENAME eq ffplay.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=2)
            for line in r.stdout.splitlines():
                parts = [p.strip(' "') for p in line.split(",") if p.strip()]
                if len(parts) >= 2 and parts[0].lower() == "ffplay.exe":
                    try:
                        return int(parts[1])
                    except ValueError:
                        pass
        except Exception:
            pass
    elif sys.platform.startswith("linux") or sys.platform == "darwin":
        try:
            r = run_cmd(["pgrep", "-f", "ffplay"], capture_output=True, text=True, timeout=2)
            pids = [int(p) for p in r.stdout.splitlines() if p.strip().isdigit() and int(p) != os.getpid()]
            if pids:
                return pids[0]
        except Exception:
            pass
        try:
            r = run_cmd(["pgrep", "-f", "mpv"], capture_output=True, text=True, timeout=2)
            pids = [int(p) for p in r.stdout.splitlines() if p.strip().isdigit() and int(p) != os.getpid()]
            if pids:
                return pids[0]
        except Exception:
            pass
    return None

def stop_all_players(keep_queue=False):
    kill_prefetch_worker()
    current = read_state()
    pid = current.get("pid") if current else None
    is_paused = current.get("status") == "paused" if current else False
    if not keep_queue:
        clear_queue()
        clear_state()
    if pid:
        stop_process(pid, is_paused)
    orphan = find_running_player_pid()
    if orphan and orphan != pid:
        stop_process(orphan)
    if sys.platform == "win32":
        try:
            run_cmd(["taskkill", "/F", "/IM", "ffplay.exe"], capture_output=True, timeout=2)
            run_cmd(["taskkill", "/F", "/IM", "mpv.exe"], capture_output=True, timeout=2)
        except Exception:
            pass
    elif sys.platform == "darwin" or sys.platform.startswith("linux"):
        try:
            run_cmd(["pkill", "-x", "ffplay"], capture_output=True, timeout=2)
            run_cmd(["pkill", "-x", "mpv"], capture_output=True, timeout=2)
        except Exception:
            pass

def find_player_bin():
    for name in ("ffplay", "mpv"):
        p = shutil.which(name)
        if p:
            return p
    if sys.platform == "win32":
        candidates = [
            os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffplay.exe"),
            os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\mpv.exe"),
            r"C:\Program Files\ffmpeg\bin\ffplay.exe",
            r"C:\ProgramData\chocolatey\bin\ffplay.exe",
            os.path.expanduser(r"~\scoop\shims\ffplay.exe"),
        ]
        winget_pkgs = os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages")
        if os.path.isdir(winget_pkgs):
            try:
                for root, _dirs, files in os.walk(winget_pkgs):
                    if "ffplay.exe" in files:
                        candidates.append(os.path.join(root, "ffplay.exe"))
                        break
            except Exception:
                pass
        for path in candidates:
            if os.path.isfile(path):
                return path
    elif sys.platform == "darwin":
        for path in ("/opt/homebrew/bin/ffplay", "/usr/local/bin/ffplay", os.path.expanduser("~/.Homebrew/bin/ffplay"),
                     "/opt/homebrew/bin/mpv", "/usr/local/bin/mpv", os.path.expanduser("~/.Homebrew/bin/mpv")):
            if os.path.isfile(path):
                return path
    return None

def find_ytdlp_bin():
    p = shutil.which("yt-dlp")
    if p:
        return p
    exe_name = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"
    scripts_dir = os.path.join(os.path.dirname(sys.executable), "Scripts" if sys.platform == "win32" else "bin")
    cand = os.path.join(scripts_dir, exe_name)
    if os.path.isfile(cand):
        return cand
    try:
        import site
        if hasattr(site, "USER_BASE") and site.USER_BASE:
            cand = os.path.join(site.USER_BASE, "Scripts" if sys.platform == "win32" else "bin", exe_name)
            if os.path.isfile(cand):
                return cand
    except Exception:
        pass
    if sys.platform == "win32":
        candidates = [
            os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\yt-dlp.exe"),
            os.path.expanduser(r"~\scoop\shims\yt-dlp.exe"),
        ]
        local_py = os.path.expanduser(r"~\AppData\Local\Programs\Python")
        if os.path.isdir(local_py):
            for entry in os.listdir(local_py):
                c = os.path.join(local_py, entry, "Scripts", "yt-dlp.exe")
                if os.path.isfile(c):
                    return c
        for path in candidates:
            if os.path.isfile(path):
                return path
    elif sys.platform == "darwin":
        for path in ("/opt/homebrew/bin/yt-dlp", "/usr/local/bin/yt-dlp", os.path.expanduser("~/.Homebrew/bin/yt-dlp")):
            if os.path.isfile(path):
                return path
    try:
        import yt_dlp
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass
    return None

def is_bilibili_url(url):
    u = (url or "").lower()
    return "bilibili.com" in u or "b23.tv" in u or "bilivideo." in u

def is_extractor_url(url):
    u = url.lower()
    return "youtube.com" in u or "youtu.be" in u or "soundcloud.com" in u or is_bilibili_url(u)

def position_log():
    """ffplay -stats writes its audio clock (seconds played) here; a new track starts a new file."""
    ensure_cache_dir()
    return open(POSITION_FILE, "wb")

def read_position():
    """The playing track's real position in seconds, from ffplay's last stats line; None when unknown."""
    try:
        with open(POSITION_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 400))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    found = re.findall(r"(-?\d+\.\d+)\s+M-A:", tail)
    return float(found[-1]) if found else None

def extract_stream_info(url):
    yt_dlp = find_ytdlp_bin()
    if not yt_dlp:
        return None, None, 0, "yt-dlp is required for YouTube and SoundCloud streams. Install via pip install yt-dlp or your package manager."
    clean_url = url
    if "youtube.com/watch" in clean_url and "&list=" in clean_url:
        try:
            parsed = urllib.parse.urlparse(clean_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if "v" in qs:
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?v={qs['v'][0]}"
        except Exception:
            pass
    cmd = yt_dlp if isinstance(yt_dlp, list) else [yt_dlp]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    extra_args = []
    if os.path.isfile(COOKIES_FILE):
        extra_args.extend(["--cookies", COOKIES_FILE])
    try:
        r = run_cmd(
            [*cmd, "--encoding", "utf-8", "--no-warnings", "--no-playlist", *extra_args, "--extractor-args", "youtube:player_client=ios,android,web", "-f", "ba/b", "--print", "%(title)s", "--print", "%(duration)s", "-g", clean_url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=22
        )
        if r.returncode == 0 and r.stdout.strip():
            lines = [line.strip() for line in r.stdout.strip().splitlines() if line.strip()]
            stream_url = next((line for line in reversed(lines) if line.startswith("http://") or line.startswith("https://")), None)
            if stream_url:
                non_url = [l for l in lines if not (l.startswith("http://") or l.startswith("https://"))]
                duration = 0
                title_parts = []
                for l in non_url:
                    if duration == 0 and (l.isdigit() or (l.replace(".", "", 1).isdigit() and "." in l)):
                        try:
                            duration = int(float(l))
                            continue
                        except Exception:
                            pass
                    title_parts.append(l)
                title = " ".join(title_parts).strip() if title_parts else derive_direct_title(url)
                if is_bilibili_url(url):
                    # Bilibili's Akamai mirror answers 5XX for some tracks; its overseas COS mirror serves the same signed path.
                    stream_url = re.sub(r"^https://[^/]*akamaized\.net/", "https://upos-sz-mirrorcosov.bilivideo.com/", stream_url)
                return title, stream_url, duration, None
        err_msg = r.stderr.strip() if r.stderr else ""
        if "Sign in to confirm you're not a bot" in err_msg or "Sign in to confirm you’re not a bot" in err_msg:
            log_debug(f"cmd_extract_stream_info bot_check: {err_msg}")
            return None, None, 0, "YouTube anti-bot challenge: YouTube temporarily blocked this IP due to continuous playback ('Sign in to confirm you're not a bot'). You can switch networks/VPN or wait 30-60 minutes."
        log_debug(f"cmd_extract_stream_info error: returncode={r.returncode}, stderr={err_msg}")
    except Exception as e:
        log_debug(f"cmd_extract_stream_info exception: {e}")
        return None, None, 0, f"Failed to extract stream: {str(e)}"

    return None, None, 0, "Extractor error. YouTube or SoundCloud stream could not be resolved. Try running 'yt-dlp -U'."

def derive_direct_title(url):
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.rstrip("/")
        name = os.path.basename(path)
        if name:
            clean = os.path.splitext(name)[0].replace("-", " ").replace("_", " ")
            if clean:
                return clean.title()
        if parsed.netloc:
            return parsed.netloc
    except Exception:
        pass
    return "Audio Stream"

def is_playlist_url(url):
    u = url.lower()
    if is_bilibili_url(u):
        return "/list/ml" in u or "/medialist/" in u or "favlist" in u
    return ("youtube.com" in u or "youtu.be" in u) and ("list=" in u)

def extract_video_id(url):
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if "youtube.com" in netloc or "youtu.be" in netloc:
            if "youtu.be" in netloc:
                path = parsed.path.strip("/")
                if path:
                    return path.split("/")[0].split("?")[0]
            qs = urllib.parse.parse_qs(parsed.query)
            if "v" in qs and qs["v"]:
                return qs["v"][0]
            path = parsed.path.strip("/").split("/")
            if len(path) >= 2 and path[0] in ("shorts", "embed", "v"):
                return path[1]
    except Exception:
        pass
    return None

def bilibili_fav_id(url):
    m = re.search(r"/(?:list|medialist/detail)/ml(\d+)", url or "") or re.search(r"[?&]fid=(\d+)", url or "")
    return m.group(1) if m else None

def bilibili_fav(url, limit=500):
    """A public Bilibili favorites list's name and tracks, with titles and durations, from Bilibili's web API."""
    fid = bilibili_fav_id(url)
    if not fid:
        return None, []
    import urllib.request
    name, items, page = None, [], 1
    while len(items) < limit:
        api = f"https://api.bilibili.com/x/v3/fav/resource/list?media_id={fid}&pn={page}&ps=20&platform=web"
        try:
            req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
        except Exception:
            break
        data = d.get("data") or {}
        if d.get("code") != 0:
            break
        name = name or (data.get("info") or {}).get("title")
        for m in data.get("medias") or []:
            if m.get("attr") or not m.get("bvid"):
                continue
            items.append({
                "id": m["bvid"],
                "title": m.get("title") or m["bvid"],
                "duration": int(m.get("duration") or 0),
                "url": f"https://www.bilibili.com/video/{m['bvid']}",
                "stream_url": None,
                "resolved_at": 0
            })
        if not data.get("has_more"):
            break
        page += 1
    return name, items[:limit]

def extract_playlist_items(url, limit=25):
    if bilibili_fav_id(url):
        _name, items = bilibili_fav(url, limit)
        if items:
            return items
    yt_dlp = find_ytdlp_bin()
    if not yt_dlp:
        return []
    cmd = yt_dlp if isinstance(yt_dlp, list) else [yt_dlp]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    extra_args = []
    if os.path.isfile(COOKIES_FILE):
        extra_args.extend(["--cookies", COOKIES_FILE])
    try:
        r = run_cmd(
            [*cmd, "--encoding", "utf-8", "--no-warnings", "--flat-playlist", "--playlist-end", str(limit), *extra_args, "--print", "%(id)s\t%(title)s\t%(duration)s\t%(url)s", url],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=90 if is_bilibili_url(url) else 18
        )
        items = []
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].strip():
                    v_id = parts[0].strip()
                    t = parts[1].strip() if parts[1].strip() not in ("", "NA") else "YouTube Track"
                    d_str = parts[2].strip() if len(parts) > 2 else ""
                    dur = 0
                    try:
                        if d_str and d_str != "NA":
                            dur = int(float(d_str))
                    except Exception:
                        pass
                    items.append({
                        "id": v_id,
                        "title": t,
                        "duration": dur,
                        "url": parts[3].strip() if len(parts) > 3 and parts[3].strip().startswith("http") else f"https://www.youtube.com/watch?v={v_id}",
                        "stream_url": None,
                        "resolved_at": 0
                    })
        return items
    except Exception:
        return []

def launch_prefetch_worker():
    if os.path.exists(PREFETCH_PID_FILE):
        try:
            with open(PREFETCH_PID_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                pid = int(content) if content.isdigit() else None
            if pid and pid == os.getpid():
                return
            if pid and pid > 0:
                try:
                    os.kill(pid, 0)
                    return
                except OSError:
                    pass
        except Exception:
            pass
    kill_prefetch_worker()
    py = sys.executable
    if sys.platform == "win32" and py.lower().endswith("python.exe"):
        pyw = py[:-4] + "w.exe"
        if os.path.isfile(pyw):
            py = pyw
    script = os.path.abspath(__file__)
    args = [py, script, "prefetch"]
    try:
        ensure_cache_dir()
        proc = popen_cmd(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True if sys.platform != "win32" else False
        )
        with open(PREFETCH_PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(proc.pid))
    except Exception:
        pass

def cmd_prefetch():
    idle_count = 0
    while True:
        queue = read_queue()
        if not queue:
            break

        if queue.get("needs_expansion") and queue.get("playlist_url"):
            p_url = queue["playlist_url"]
            full_items = extract_playlist_items(p_url, limit=500 if is_bilibili_url(p_url) else 25)
            q_fresh = read_queue()
            if q_fresh and q_fresh.get("needs_expansion"):
                if full_items:
                    cur_items = q_fresh.get("items", [])
                    cur_id = cur_items[0]["id"] if cur_items else None
                    matched_idx = 0
                    if cur_id:
                        for idx, it in enumerate(full_items):
                            if it["id"] == cur_id:
                                matched_idx = idx
                                if cur_items:
                                    full_items[idx] = cur_items[0]
                                break
                    q_fresh["items"] = full_items + q_fresh.get("extra", [])
                    q_fresh["current_index"] = matched_idx
                    if bilibili_fav_id(p_url):
                        q_fresh["name"] = bilibili_fav(p_url, 1)[0]
                    q_fresh["needs_expansion"] = False
                    write_queue(q_fresh)

                    st = read_state()
                    if st and st.get("playing"):
                        title = full_items[matched_idx].get("title") or "YouTube Track"
                        st["playlist"] = {
                            "index": matched_idx + 1,
                            "total": len(full_items)
                        }
                        st["title"] = f"[{matched_idx + 1}/{len(full_items)}] {title}"
                        write_state(st)
                        update_history_title(p_url, f"Playlist: {title}")
                else:
                    q_fresh["needs_expansion"] = False
                    write_queue(q_fresh)
            queue = read_queue()
            if not queue:
                break

        if not queue.get("items"):
            break

        cur_idx = queue.get("current_index", 0)
        items = queue.get("items", [])
        now = int(time.time())

        target_indices = list(range(cur_idx + 1, min(len(items), cur_idx + 1 + POOL_SIZE)))
        for idx in target_indices:
            q_now = read_queue()
            if not q_now or q_now.get("current_index") != cur_idx:
                break
            it = q_now["items"][idx]
            if it.get("stream_url") and (now - it.get("resolved_at", 0) < 14400):
                continue
            time.sleep(3)
            ext_title, ext_stream, ext_dur, err = extract_stream_info(it["url"])
            if ext_stream:
                q_update = read_queue()
                if not q_update or q_update.get("current_index") != cur_idx:
                    break
                q_update["items"][idx]["stream_url"] = ext_stream
                q_update["items"][idx]["resolved_at"] = int(time.time())
                if ext_title:
                    q_update["items"][idx]["title"] = ext_title
                if ext_dur:
                    q_update["items"][idx]["duration"] = ext_dur
                write_queue(q_update)

        time.sleep(2)
        current = read_state()
        if not current:
            idle_count += 1
            if idle_count > 5:
                break
            continue
        idle_count = 0

    return {"status": "ok"}

def cmd_play_queue_index(index, start_seconds=0):
    queue = read_queue()
    if not queue or not queue.get("items") or index < 0 or index >= len(queue["items"]):
        return {"status": "error", "error": "Invalid queue index", "playing": False}

    item = queue["items"][index]
    queue["current_index"] = index
    write_queue(queue)

    stream_url = item.get("stream_url")
    title = item.get("title") or "YouTube Track"
    url = item.get("url")
    duration = item.get("duration", 0)
    now = int(time.time())

    write_state({
        "pid": None,
        "startTime": now,
        "elapsed": start_seconds,
        "duration": duration,
        "currentElapsed": start_seconds,
        "url": url,
        "title": f"[{index + 1}/{len(queue['items'])}] {title}",
        "status": "buffering",
        "playing": False,
        "source": "youtube",
        "playlist": {
            "index": index + 1,
            "total": len(queue["items"])
        },
        "history": read_history()
    })

    stop_all_players(keep_queue=True)

    write_state({
        "pid": None,
        "startTime": now,
        "elapsed": start_seconds,
        "duration": duration,
        "currentElapsed": start_seconds,
        "url": url,
        "title": f"[{index + 1}/{len(queue['items'])}] {title}",
        "status": "buffering",
        "playing": False,
        "source": "youtube",
        "playlist": {
            "index": index + 1,
            "total": len(queue["items"])
        },
        "history": read_history()
    })

    if not stream_url or (now - item.get("resolved_at", 0) >= 14400):
        ext_title, ext_stream, ext_dur, err = extract_stream_info(url)
        if err or not ext_stream:
            clear_state()
            return {"status": "error", "error": err or "Failed to extract stream", "playing": False}
        stream_url = ext_stream
        if ext_title:
            title = ext_title
        if ext_dur:
            duration = ext_dur
        queue = read_queue()
        if queue and index < len(queue["items"]):
            queue["items"][index]["stream_url"] = stream_url
            queue["items"][index]["title"] = title
            queue["items"][index]["duration"] = duration
            queue["items"][index]["resolved_at"] = int(time.time())
            write_queue(queue)

    player_bin = find_player_bin()
    if not player_bin:
        clear_state()
        return {"status": "error", "error": "Neither ffplay nor mpv found. Install ffmpeg or mpv to enable playback.", "playing": False}

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    proc, err = spawn_player_process(player_bin, stream_url, ua, start_seconds=start_seconds, page_url=url)
    if err or not proc:
        clear_state()
        return {"status": "error", "error": f"Failed to start player process: {err}", "playing": False}

    display_title = f"[{index + 1}/{len(queue['items'])}] {title}"
    state = {
        "pid": proc.pid,
        "startTime": int(time.time()),
        "elapsed": start_seconds,
        "duration": duration,
        "currentElapsed": start_seconds,
        "url": url,
        "title": display_title,
        "status": "playing",
        "playing": True,
        "source": "youtube",
        "playlist": {
            "index": index + 1,
            "total": len(queue["items"])
        },
        "history": read_history()
    }
    state["stream_url"] = stream_url
    state["streamAt"] = int(time.time())
    write_state(state)
    launch_prefetch_worker()
    launch_lyrics(url)
    return state

def cmd_enqueue(url):
    """Adds a link (one track, or a whole playlist / Bilibili favorites) to the end of the play queue."""
    valid, res = validate_url(url)
    if not valid:
        return {"status": "error", "error": res, "playing": False}
    st = cmd_status()
    if not st.get("playing") and st.get("status") not in ("paused", "buffering"):
        return cmd_play(res)
    if is_playlist_url(res):
        new = extract_playlist_items(res, limit=500 if is_bilibili_url(res) else 200)
    else:
        if is_extractor_url(res):
            title, stream, dur, err = extract_stream_info(res)
            if err or not stream:
                return {"status": "error", "error": err or "Could not read this link", "playing": st.get("playing", False)}
        else:
            title, stream, dur = derive_direct_title(res), res, 0
        new = [{"id": res, "title": title, "duration": dur or 0, "url": res, "stream_url": stream, "resolved_at": int(time.time())}]
    if not new:
        return {"status": "error", "error": "Nothing to add from this link", "playing": st.get("playing", False)}
    queue = read_queue()
    if not queue or not queue.get("items"):
        cur = read_state() or {}
        queue = {"playlist_url": None, "current_index": 0, "needs_expansion": False, "items": [{
            "id": cur.get("url"), "title": re.sub(r"^\[\d+/\d+\] ", "", cur.get("title") or ""),
            "duration": cur.get("duration", 0), "url": cur.get("url"), "stream_url": None, "resolved_at": 0}]}
    queue["items"].extend(new)
    if queue.get("needs_expansion"):
        queue.setdefault("extra", []).extend(new)
    write_queue(queue)
    cur = read_state()
    if cur:
        total = len(queue["items"])
        idx = queue.get("current_index", 0)
        cur["playlist"] = {"index": idx + 1, "total": total}
        cur["title"] = f"[{idx + 1}/{total}] " + re.sub(r"^\[\d+/\d+\] ", "", cur.get("title") or "")
        write_state(cur)
    if st.get("playing"):
        launch_prefetch_worker()
    return {"status": "ok", "added": len(new), "total": len(queue["items"]), "playing": st.get("playing", False)}

ARTIST_ALIASES = {"taylor swift": ["霉霉"], "rosé": ["rose", "朴彩英"], "jj lin": ["林俊杰"], "eason chan": ["陈奕迅"], "jay chou": ["周杰伦"]}

def clean_title(title):
    t = re.sub(r"^\[\d+/\d+\] ", "", title or "")
    return re.sub(r"【[^】]*】|\[[^\]]*\]", " ", t).strip()

def song_candidates(title):
    """Song names a video title may carry: the text in 《》, or either side of " - "."""
    t = clean_title(title)
    out = []
    for m in re.finditer(r"《([^》]+)》", t):
        out += [m.group(1).strip(), re.sub(r"[（(][^)）]*[)）]", "", m.group(1)).strip()]
    if " - " in t:
        left, right = [x.strip() for x in t.split(" - ", 1)]
        out += [left, re.sub(r"[（(].*$", "", right).strip(), re.sub(r"\s*(官方|MV|Official).*$", "", right, flags=re.I).strip()]
    lead = re.match(r"^[A-Za-z0-9][A-Za-z0-9' ,.&!?-]*[A-Za-z0-9]", t)
    if lead and len(lead.group(0)) >= 4:
        out.append(lead.group(0).strip())
    seen = []
    for c in out:
        if c and c not in seen:
            seen.append(c)
    return seen

def artist_in_title(artist, title):
    """The singer a lyrics hit names must also appear in the video title (by name or a common nickname)."""
    t = (title or "").lower()
    names = [n.strip().lower() for n in re.split(r"\s*[/、&,，;×]\s*|\s+x\s+|\s+feat\.?\s+|\s+ft\.?\s+", artist or "") if n.strip()]
    for n in names:
        if n in t or any(a.lower() in t for a in ARTIST_ALIASES.get(n, [])):
            return True
    return False

def parse_lrc(text):
    lines = []
    for raw in (text or "").splitlines():
        stamps = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw)
        words = re.sub(r"\[[^\]]*\]", "", raw).strip()
        for mm, ss in stamps:
            if words:
                lines.append([round(int(mm) * 60 + float(ss), 2), words])
    return sorted(lines)

def find_lyrics(title, dur):
    """Synced lyrics whose singer appears in the title and whose length is within 5 s of the track; else []."""
    if dur <= 0:
        return []
    import urllib.request
    for song in song_candidates(title):
        q = urllib.parse.urlencode({"track_name": song})
        try:
            req = urllib.request.Request(f"https://lrclib.net/api/search?{q}", headers={"User-Agent": "pixel-hq-musicbox"})
            with urllib.request.urlopen(req, timeout=10) as r:
                hits = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        for h in hits:
            if h.get("syncedLyrics") and abs(float(h.get("duration") or 0) - dur) <= 5 and artist_in_title(h.get("artistName"), re.sub(r"^\[\d+/\d+\] ", "", title or "")):
                lines = parse_lrc(h["syncedLyrics"])
                if lines:
                    return lines
    return []

def cmd_lyrics(url):
    """Looks up synced lyrics on LRCLIB for the track now playing; keeps none unless singer and length match."""
    cur = read_state()
    if not cur or cur.get("url") != url or "lyrics" in cur:
        return {"status": "ok"}
    found = find_lyrics(cur.get("title"), float(cur.get("duration") or 0))
    cur = read_state()
    if cur and cur.get("url") == url:
        cur["lyrics"] = found
        write_state(cur)
    return {"status": "ok", "lines": len(found)}

def launch_lyrics(url):
    try:
        popen_cmd([sys.executable, os.path.abspath(__file__), "lyrics", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  stdin=subprocess.DEVNULL, start_new_session=True if sys.platform != "win32" else False)
    except Exception:
        pass

def cmd_seek(seconds):
    """Restarts the current track's player at `seconds`; the queue and the rest of the state stay."""
    cur = read_state()
    if not cur or not cur.get("url") or not (cur.get("pid") or cur.get("status") == "paused"):
        return {"status": "error", "error": "Nothing is playing", "playing": False}
    dur = float(cur.get("duration") or 0)
    pos = max(0.0, min(float(seconds), dur - 1 if dur > 1 else float(seconds)))
    stream = cur.get("stream_url")
    if not stream or int(time.time()) - int(cur.get("streamAt") or 0) > 5400:
        if is_extractor_url(cur["url"]):
            _t, stream, _d, err = extract_stream_info(cur["url"])
            if err or not stream:
                return {"status": "error", "error": err or "Could not reopen this track", "playing": cur.get("playing", False)}
        else:
            stream = cur["url"]
        cur["streamAt"] = int(time.time())
    player_bin = find_player_bin()
    if not player_bin:
        return {"status": "error", "error": "Neither ffplay nor mpv found. Install ffmpeg or mpv to enable playback.", "playing": False}
    if cur.get("pid"):
        stop_process(cur["pid"])
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    proc, err = spawn_player_process(player_bin, stream, ua, start_seconds=pos, page_url=cur["url"])
    if err or not proc:
        return {"status": "error", "error": f"Failed to start player process: {err}", "playing": False}
    cur.update({"pid": proc.pid, "startTime": int(time.time()), "elapsed": int(pos), "currentElapsed": int(pos),
                "status": "playing", "playing": True, "stream_url": stream})
    cur.pop("pausedAt", None)
    cur.pop("position", None)
    write_state(cur)
    cur.update({"position": pos, "positionAt": time.time()})
    cur["history"] = read_history()
    return cur

def read_mode():
    try:
        with open(MODE_FILE, "r", encoding="utf-8") as f:
            m = json.load(f).get("mode")
        return m if m in MODES else "order"
    except Exception:
        return "order"

def cmd_mode(mode):
    """Play order: order (stop at the end), loop (the list), one (the current track), shuffle."""
    if mode == "next":
        mode = MODES[(MODES.index(read_mode()) + 1) % len(MODES)]
    if mode not in MODES:
        return {"status": "error", "error": f"mode is one of {', '.join(MODES)}"}
    ensure_cache_dir()
    with open(MODE_FILE, "w", encoding="utf-8") as f:
        json.dump({"mode": mode}, f)
    queue = read_queue()
    if queue and queue.get("items"):
        queue["played"] = [queue.get("current_index", 0)]
        write_queue(queue)
    return {"status": "ok", "mode": mode}

def next_index(queue, auto):
    """The track to play after the current one, by play mode; None when an ordered list has ended."""
    items = queue.get("items") or []
    n, cur, mode = len(items), queue.get("current_index", 0), read_mode()
    if not n:
        return None
    if mode == "one" and auto:
        return cur
    if mode == "shuffle" and n > 1:
        import random
        played = [i for i in queue.get("played") or [] if i < n]
        if cur not in played:
            played.append(cur)
        left = [i for i in range(n) if i not in played]
        if not left:
            played, left = [cur], [i for i in range(n) if i != cur]
        nxt = random.choice(left)
        queue["played"] = played + [nxt]
        write_queue(queue)
        return nxt
    if cur + 1 < n:
        return cur + 1
    return 0 if (mode in ("loop", "shuffle") or not auto) else None

def cmd_queue():
    """The play queue: its name, the current index and every track's title and duration."""
    queue = read_queue() or {}
    items = queue.get("items") or []
    missing = lambda it: (it.get("title") or "NA") in ("NA", "YouTube Track")
    # The prefetch worker is still expanding the list: leave the file to it, or this write would undo its work.
    if not queue.get("needs_expansion") and bilibili_fav_id(queue.get("playlist_url")) and (not queue.get("name") or any(missing(it) for it in items)):
        name, fav = bilibili_fav(queue["playlist_url"])
        by_id = {f["id"]: f for f in fav}
        fresh = read_queue() or {}
        if [it.get("id") for it in fresh.get("items") or []] == [it.get("id") for it in items]:
            for it in fresh["items"]:
                f = by_id.get(it.get("id"))
                if f and missing(it):
                    it["title"] = f["title"]
                    it["duration"] = it.get("duration") or f["duration"]
            if name:
                fresh["name"] = name
            write_queue(fresh)
            queue, items = fresh, fresh["items"]
    return {
        "status": "ok",
        "name": queue.get("name"),
        "playlist_url": queue.get("playlist_url"),
        "current_index": queue.get("current_index", 0),
        "expanding": bool(queue.get("needs_expansion")),
        "mode": read_mode(),
        "items": [{"title": it.get("title") or "", "duration": it.get("duration") or 0} for it in items],
    }

def read_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data[:MAX_HISTORY]
            return []
    except Exception:
        return []

def write_history(data):
    ensure_cache_dir()
    tmp_file = f"{HISTORY_FILE}.tmp.{os.getpid()}"
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(tmp_file, flags, 0o600)
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(data[:MAX_HISTORY], f)
        os.replace(tmp_file, HISTORY_FILE)
        if sys.platform != "win32":
            try:
                os.chmod(HISTORY_FILE, 0o600)
            except OSError:
                pass
    except Exception:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass

def clear_history():
    if os.path.exists(HISTORY_FILE):
        try:
            os.remove(HISTORY_FILE)
        except OSError:
            pass

def add_history(url, title=None, item_type=None):
    if not url:
        return
    if not item_type:
        if is_playlist_url(url):
            item_type = "playlist"
        elif is_extractor_url(url):
            item_type = "youtube"
        else:
            item_type = "direct"
    if not title:
        title = derive_direct_title(url) or "Audio Stream"

    current = read_history()
    filtered = [item for item in current if item.get("url") != url]
    entry = {
        "url": url,
        "title": title,
        "type": item_type,
        "played_at": int(time.time())
    }
    updated = [entry] + filtered
    write_history(updated[:MAX_HISTORY])

def update_history_title(url, title):
    if not url or not title:
        return
    current = read_history()
    updated = False
    for item in current:
        if item.get("url") == url:
            item["title"] = title
            updated = True
            break
    if updated:
        write_history(current)

def expand_queue(queue):
    """Fills in a playlist queue that still holds only its first track."""
    if not (queue.get("needs_expansion") and queue.get("playlist_url")):
        return
    full_items = extract_playlist_items(queue["playlist_url"], limit=500 if is_bilibili_url(queue["playlist_url"]) else 25)
    if full_items:
        cur_items = queue.get("items", [])
        cur_id = cur_items[0]["id"] if cur_items else None
        matched_idx = 0
        if cur_id:
            for idx, it in enumerate(full_items):
                if it["id"] == cur_id:
                    matched_idx = idx
                    if cur_items:
                        full_items[idx] = cur_items[0]
                    break
        queue["items"] = full_items + queue.get("extra", [])
        queue["current_index"] = matched_idx
    queue["needs_expansion"] = False
    write_queue(queue)

def play_in_queue(url, preset_title, queue):
    """Plays a link while a queue exists: tracks the queue lacks go in after the current one, the queue stays."""
    expand_queue(queue)
    items = queue["items"]
    single = not is_playlist_url(url)
    if single:
        direct = not is_extractor_url(url)
        title = preset_title or (derive_direct_title(url) if direct else "YouTube Track")
        add_history(url, title, "direct" if direct else "youtube")
        wanted = [{"id": url, "title": title, "duration": 0, "url": url, "stream_url": url if direct else None, "resolved_at": int(time.time()) if direct else 0}]
    else:
        add_history(url, preset_title or "YouTube Playlist", "playlist")
        wanted = extract_playlist_items(url, limit=500 if is_bilibili_url(url) else 200)
        if not wanted:
            return {"status": "error", "error": "Nothing to play from this link", "playing": False, "history": read_history()}
    keys = lambda it: {k for k in (it.get("id"), it.get("url")) if k}
    have = set().union(*(keys(it) for it in items))
    at = queue.get("current_index", 0) + 1
    new = [it for it in wanted if not (keys(it) & have)]
    if new:
        items[at:at] = new
        queue.pop("played", None)
        write_queue(queue)
    index = next(i for i, it in enumerate(items) if keys(it) & keys(wanted[0]))
    res = cmd_play_queue_index(index)
    if single and res.get("status") == "playing":
        update_history_title(url, re.sub(r"^\[\d+/\d+\] ", "", res.get("title") or ""))
    res["history"] = read_history()
    return res

def cmd_play(url, preset_title=None):
    valid, res = validate_url(url)
    if not valid:
        return {"status": "error", "error": res, "playing": False, "history": read_history()}

    queue = read_queue()
    if queue and queue.get("items"):
        return play_in_queue(res, preset_title, queue)

    if is_playlist_url(res):
        add_history(res, preset_title or "YouTube Playlist", "playlist")
        stop_all_players(keep_queue=False)
        write_state({
            "pid": None,
            "startTime": int(time.time()),
            "url": res,
            "title": "Buffering stream...",
            "status": "buffering",
            "playing": False,
            "source": "youtube",
            "history": read_history()
        })
        video_id = extract_video_id(res)
        init_items = extract_playlist_items(res, limit=20 if is_bilibili_url(res) else 25)
        if init_items:
            first_url = init_items[0]["url"]
            video_id = init_items[0]["id"]
            first_title = init_items[0]["title"]
            first_dur = init_items[0]["duration"]
        elif video_id:
            first_url = f"https://www.youtube.com/watch?v={video_id}"
            first_title = "YouTube Track"
            first_dur = 0
            init_items = [{
                "id": video_id,
                "title": first_title,
                "duration": first_dur,
                "url": first_url,
                "stream_url": None,
                "resolved_at": 0
            }]
        else:
            first_url = res
            first_title = "YouTube Track"
            first_dur = 0
            init_items = []

        ext_title, ext_stream, ext_dur, err = extract_stream_info(first_url)
        if err or not ext_stream:
            clear_state()
            return {"status": "error", "error": err or "Failed to extract stream", "playing": False, "history": read_history()}

        if init_items:
            init_items[0]["stream_url"] = ext_stream
            if ext_title:
                init_items[0]["title"] = ext_title
            if ext_dur:
                init_items[0]["duration"] = ext_dur
            init_items[0]["resolved_at"] = int(time.time())

        player_bin = find_player_bin()
        if not player_bin:
            clear_state()
            return {"status": "error", "error": "Neither ffplay nor mpv found. Install ffmpeg or mpv to enable playback.", "playing": False, "history": read_history()}

        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        proc, err = spawn_player_process(player_bin, ext_stream, ua, page_url=first_url)
        if err or not proc:
            clear_state()
            return {"status": "error", "error": f"Failed to start player process: {err}", "playing": False, "history": read_history()}

        queue_data = {
            "playlist_url": res,
            "current_index": 0,
            "items": init_items if init_items else [{
                "id": video_id or "track-1",
                "title": ext_title or "YouTube Track",
                "duration": ext_dur or 0,
                "url": first_url,
                "stream_url": ext_stream,
                "resolved_at": int(time.time())
            }],
            "needs_expansion": is_bilibili_url(res)
        }
        write_queue(queue_data)

        display_title = ext_title or (init_items[0]["title"] if init_items else "YouTube Track")
        total_count = len(init_items) if init_items else 1
        state = {
            "pid": proc.pid,
            "startTime": int(time.time()),
            "elapsed": 0,
            "duration": ext_dur or (init_items[0]["duration"] if init_items else 0),
            "currentElapsed": 0,
            "url": first_url,
            "title": f"[1/{total_count}] {display_title}",
            "status": "playing",
            "playing": True,
            "source": "youtube",
            "playlist": {
                "index": 1,
                "total": total_count
            },
            "history": read_history()
        }
        state["stream_url"] = ext_stream
        state["streamAt"] = int(time.time())
        write_state(state)
        update_history_title(res, f"Playlist: {display_title}")
        launch_prefetch_worker()
        launch_lyrics(first_url)
        return state

    item_type = "youtube" if is_extractor_url(res) else "direct"
    init_title = preset_title or (derive_direct_title(res) if item_type == "direct" else "YouTube Track")
    add_history(res, init_title, item_type)

    stop_all_players(keep_queue=False)

    write_state({
        "pid": None,
        "startTime": int(time.time()),
        "url": res,
        "title": preset_title or "Buffering stream...",
        "status": "buffering",
        "playing": False,
        "source": item_type,
        "history": read_history()
    })

    player_bin = find_player_bin()
    if not player_bin:
        clear_state()
        return {"status": "error", "error": "Neither ffplay nor mpv found. Install ffmpeg or mpv to enable playback.", "playing": False, "history": read_history()}

    source = "direct"
    title = preset_title
    stream_url = res
    duration = 0

    if is_extractor_url(res):
        source = "youtube" if "youtu" in res.lower() else "bilibili" if is_bilibili_url(res) else "soundcloud"
        ext_title, ext_stream, ext_dur, err = extract_stream_info(res)
        if err:
            clear_state()
            return {"status": "error", "error": err, "playing": False, "history": read_history()}
        stream_url = ext_stream
        title = ext_title or title or derive_direct_title(res)
        if ext_dur:
            duration = ext_dur
        if ext_title:
            update_history_title(res, ext_title)
    else:
        if not title:
            title = derive_direct_title(res)
            update_history_title(res, title)

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    proc, err = spawn_player_process(player_bin, stream_url, ua, page_url=res)
    if err or not proc:
        clear_state()
        return {"status": "error", "error": f"Failed to start player process: {err}", "playing": False, "history": read_history()}

    state = {
        "pid": proc.pid,
        "startTime": int(time.time()),
        "elapsed": 0,
        "duration": duration,
        "currentElapsed": 0,
        "url": res,
        "title": title,
        "status": "playing",
        "playing": True,
        "source": source,
        "history": read_history()
    }
    state["stream_url"] = stream_url
    state["streamAt"] = int(time.time())
    write_state(state)
    launch_lyrics(res)
    return state

def cmd_pause():
    """Ends the player at its real position: a frozen (SIGSTOP) ffplay keeps looping its last audio buffer on macOS."""
    current = read_state()
    if not current or not current.get("pid"):
        return {"status": "idle", "playing": False, "title": "", "url": "", "elapsed": 0, "duration": 0, "currentElapsed": 0, "history": read_history()}
    if not is_valid_player_proc(current["pid"]):
        clear_state()
        return {"status": "idle", "playing": False, "title": "", "url": "", "elapsed": 0, "duration": 0, "currentElapsed": 0, "history": read_history()}
    pos = read_position()
    kill_prefetch_worker()
    stop_process(current["pid"])
    if pos is None:
        pos = float(current.get("elapsed", 0) + max(0, int(time.time()) - current.get("startTime", int(time.time()))))
    current.pop("position", None)
    current.update({"pid": None, "pausedAt": pos, "elapsed": int(pos), "currentElapsed": int(pos), "startTime": int(time.time()),
                    "status": "paused", "playing": False})
    write_state(current)
    current.update({"position": pos, "positionAt": time.time(), "mode": read_mode(), "history": read_history()})
    return current

def cmd_resume():
    """Starts the player again from where Pause left it."""
    current = read_state()
    if not current or current.get("status") != "paused":
        return cmd_status()
    res = cmd_seek(float(current.get("pausedAt") or current.get("elapsed") or 0))
    if res.get("status") != "error":
        cur = read_state() or {}
        cur.pop("pausedAt", None)
        write_state(cur)
        if read_queue():
            launch_prefetch_worker()
    res["mode"] = read_mode()
    return res

def cmd_clear_queue():
    stop_all_players(keep_queue=False)
    return {"status": "idle", "playing": False, "title": "", "url": "", "source": "direct", "elapsed": 0, "duration": 0, "currentElapsed": 0, "history": read_history()}

def cmd_stop():
    stop_all_players(keep_queue=True)
    clear_state()
    return {"status": "idle", "playing": False, "title": "", "url": "", "source": "direct", "elapsed": 0, "duration": 0, "currentElapsed": 0, "history": read_history()}

def default_output_device():
    """Current CoreAudio default output device id on macOS, None elsewhere or on failure."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")

        class Addr(ctypes.Structure):
            _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]

        fourcc = lambda s: int.from_bytes(s.encode(), "big")
        addr = Addr(fourcc("dOut"), fourcc("glob"), 0)
        dev = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(dev))
        err = ca.AudioObjectGetPropertyData(1, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(dev))
        return dev.value if err == 0 and dev.value else None
    except Exception:
        return None

def cmd_status():
    current = read_state()
    if not current:
        orphan_pid = find_running_player_pid()
        if orphan_pid:
            state = {
                "pid": orphan_pid,
                "startTime": int(time.time()),
                "elapsed": 0,
                "duration": 0,
                "currentElapsed": 0,
                "url": "",
                "title": "Audio Stream",
                "status": "playing",
                "playing": True,
                "source": "direct",
                "history": read_history()
            }
            write_state(state)
            return state
        return {"status": "idle", "playing": False, "title": "", "url": "", "source": "direct", "elapsed": 0, "duration": 0, "currentElapsed": 0, "history": read_history()}

    status = current.get("status")
    if status == "buffering":
        if int(time.time()) - current.get("startTime", 0) <= 35:
            current["currentElapsed"] = current.get("elapsed", 0)
            current["history"] = read_history()
            return current

    if status == "paused":
        current["currentElapsed"] = current.get("elapsed", 0)
        current.update({"position": current.get("pausedAt", current.get("elapsed")), "positionAt": time.time(), "mode": read_mode(), "history": read_history()})
        return current

    if status == "playing" and current.get("pid"):
        now = int(time.time())
        base = current.get("elapsed", 0)
        dur = current.get("duration", 0)
        current_elapsed = base + max(0, now - current.get("startTime", now))
        current["currentElapsed"] = current_elapsed
        current["history"] = read_history()

        current["mode"] = read_mode()
        current["position"] = read_position()
        current["positionAt"] = time.time()
        proc_alive = is_valid_player_proc(current["pid"])
        is_expired = dur > 0 and current_elapsed >= dur + 1.5

        if proc_alive and not is_expired:
            dev = default_output_device()
            if dev is not None:
                if current.get("outputPid") != current["pid"]:
                    current.update({"outputPid": current["pid"], "outputDevice": dev})
                    write_state({k: v for k, v in current.items() if k not in ("history", "mode", "position", "positionAt")})
                elif current.get("outputDevice") != dev:
                    return cmd_pause()
            return current

        orphan = find_running_player_pid()
        if orphan:
            current["pid"] = orphan
            write_state(current)
            return current

        is_completed = is_expired or (dur > 0 and current_elapsed >= max(15, min(dur - 3, int(dur * 0.95)))) or (dur == 0 and current_elapsed >= 15)

        queue = read_queue()
        if queue and queue.get("items"):
            cur_idx = queue.get("current_index", 0)
            items = queue.get("items", [])
            if is_completed:
                nxt = next_index(queue, auto=True)
                if nxt is not None:
                    res = cmd_play_queue_index(nxt)
                    res["history"] = read_history()
                    return res
            else:
                retry_count = current.get("retry_count", 0)
                if retry_count < 1 and cur_idx < len(items):
                    current["retry_count"] = retry_count + 1
                    items[cur_idx]["stream_url"] = None
                    items[cur_idx]["resolved_at"] = 0
                    queue["items"] = items
                    write_queue(queue)
                    res = cmd_play_queue_index(cur_idx, start_seconds=current_elapsed)
                    res["retry_count"] = retry_count + 1
                    write_state(res)
                    return res
        elif is_completed and current.get("url") and read_mode() in ("one", "loop"):
            res = cmd_play(current["url"], re.sub(r"^\[\d+/\d+\] ", "", current.get("title") or "") or None)
            res["history"] = read_history()
            return res

    clear_state()
    return {"status": "idle", "playing": False, "title": "", "url": "", "source": "direct", "elapsed": 0, "duration": 0, "currentElapsed": 0, "history": read_history()}

def cmd_next():
    queue = read_queue()
    if queue and queue.get("items"):
        expand_queue(queue)
        nxt = next_index(queue, auto=False)
        return cmd_play_queue_index(nxt if nxt is not None else 0)

    current = read_state()
    cur_url = current.get("url") if current else None
    idx = -1
    for i, p in enumerate(DEFAULT_PRESETS):
        if p["url"] == cur_url:
            idx = i
            break
    next_idx = (idx + 1) % len(DEFAULT_PRESETS)
    return cmd_play(DEFAULT_PRESETS[next_idx]["url"], DEFAULT_PRESETS[next_idx]["title"])

def cmd_prev():
    queue = read_queue()
    if queue and queue.get("items"):
        expand_queue(queue)
        cur_idx = queue.get("current_index", 0)
        played = queue.get("played") or []
        if read_mode() == "shuffle" and len(played) > 1 and played[-1] == cur_idx:
            played.pop()
            queue["played"] = played
            write_queue(queue)
            return cmd_play_queue_index(played[-1])
        if cur_idx > 0:
            return cmd_play_queue_index(cur_idx - 1)
        else:
            return cmd_play_queue_index(0)

    current = read_state()
    cur_url = current.get("url") if current else None
    idx = 0
    for i, p in enumerate(DEFAULT_PRESETS):
        if p["url"] == cur_url:
            idx = i
            break
    prev_idx = (idx - 1) % len(DEFAULT_PRESETS)
    return cmd_play(DEFAULT_PRESETS[prev_idx]["url"], DEFAULT_PRESETS[prev_idx]["title"])

def cmd_toggle():
    current = read_state()
    if not current or current.get("status") == "idle":
        return cmd_play(DEFAULT_PRESETS[0]["url"], DEFAULT_PRESETS[0]["title"])
    if current.get("status") == "paused":
        return cmd_resume()
    if current.get("status") == "playing":
        return cmd_pause()
    return current

def cmd_check():
    player_bin = find_player_bin()
    yt_dlp = find_ytdlp_bin()
    return {
        "status": "ok",
        "has_player": bool(player_bin),
        "player": player_bin,
        "has_ytdlp": bool(yt_dlp),
        "platform": sys.platform
    }

def main():
    if len(sys.argv) < 2:
        out = cmd_status()
        json.dump(out, sys.stdout, ensure_ascii=True)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return

    action = sys.argv[1].lower()
    if action == "play":
        url = sys.argv[2] if len(sys.argv) > 2 else ""
        preset = sys.argv[3] if len(sys.argv) > 3 else None
        out = cmd_play(url, preset)
    elif action == "prefetch":
        out = cmd_prefetch()
    elif action == "enqueue":
        out = cmd_enqueue(sys.argv[2] if len(sys.argv) > 2 else "")
    elif action == "lyrics":
        out = cmd_lyrics(sys.argv[2] if len(sys.argv) > 2 else "")
    elif action == "seek":
        try:
            out = cmd_seek(float(sys.argv[2]))
        except (IndexError, ValueError):
            out = {"status": "error", "error": "seek needs a position in seconds", "playing": False}
    elif action == "mode":
        out = cmd_mode(sys.argv[2] if len(sys.argv) > 2 else "next")
    elif action == "queue":
        out = cmd_queue()
    elif action == "jump":
        try:
            out = cmd_play_queue_index(int(sys.argv[2]))
        except (IndexError, ValueError):
            out = {"status": "error", "error": "jump needs a track index", "playing": False}
    elif action == "pause":
        out = cmd_pause()
    elif action == "resume":
        out = cmd_resume()
    elif action == "stop":
        out = cmd_stop()
    elif action == "clear-queue":
        out = cmd_clear_queue()
    elif action == "next":
        out = cmd_next()
    elif action == "prev":
        out = cmd_prev()
    elif action == "toggle":
        out = cmd_toggle()
    elif action == "status":
        out = cmd_status()
    elif action == "check":
        out = cmd_check()
    elif action == "history":
        out = {"status": "ok", "history": read_history()}
    elif action == "clear-history":
        clear_history()
        out = {"status": "ok", "history": []}
    else:
        out = {"status": "error", "error": f"Unknown action: {action}", "playing": False}

    json.dump(out, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
