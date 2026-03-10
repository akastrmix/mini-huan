#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

IS_WINDOWS = os.name == "nt"

JOIN_RE = re.compile(r"joined the game")
LEAVE_RE = re.compile(r"left the game")
CHAT_RE = re.compile(r"^<([^>]+)> (.+)$")
LOG_PREFIX_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+:\s*")
PLAYER_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")


def extract_payload(line: str) -> str:
    m = LOG_PREFIX_RE.match(line)
    if m:
        return line[m.end():].strip()
    return line.strip()


def parse_event(line: str):
    payload = extract_payload(line)

    chat_match = CHAT_RE.search(payload)
    if chat_match:
        player, message = chat_match.groups()
        return {
            "type": "chat",
            "player": player,
            "message": message,
            "raw": line.strip(),
            "ts": datetime.now().isoformat(timespec="seconds"),
        }

    if JOIN_RE.search(payload):
        before = payload.split(" joined the game", 1)[0].strip()
        if PLAYER_NAME_RE.fullmatch(before):
            return {
                "type": "join",
                "player": before,
                "raw": line.strip(),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }

    if LEAVE_RE.search(payload):
        before = payload.split(" left the game", 1)[0].strip()
        if PLAYER_NAME_RE.fullmatch(before):
            return {
                "type": "leave",
                "player": before,
                "raw": line.strip(),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }

    return None


def emit_event(event, output_json: bool):
    if output_json:
        print(json.dumps(event, ensure_ascii=False), flush=True)
        return

    if event["type"] == "chat":
        print(f"[chat] {event['player']}: {event['message']}", flush=True)
    else:
        print(f"[{event['type']}] {event['player']}", flush=True)


def open_log_file(path: str):
    if not IS_WINDOWS:
        return open(path, "r", encoding="utf-8", errors="ignore")

    import ctypes
    import msvcrt

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    CreateFileW = ctypes.windll.kernel32.CreateFileW
    CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    CreateFileW.restype = ctypes.c_void_p

    handle = CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        raise FileNotFoundError(path)

    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    return open(fd, "r", encoding="utf-8", errors="ignore", closefd=True)


def follow_file(path: str, poll_interval: float, start_from_end: bool, output_json: bool):
    while True:
        try:
            with open_log_file(path) as f:
                if start_from_end:
                    f.seek(0, os.SEEK_END)
                else:
                    f.seek(0, os.SEEK_SET)

                last_inode = os.fstat(f.fileno()).st_ino

                while True:
                    line = f.readline()
                    if line:
                        event = parse_event(line)
                        if event:
                            emit_event(event, output_json)
                        continue

                    time.sleep(poll_interval)

                    try:
                        stat = os.stat(path)
                    except FileNotFoundError:
                        break

                    current_pos = f.tell()
                    same_file = stat.st_ino == last_inode
                    truncated = stat.st_size < current_pos
                    if not same_file or truncated:
                        break

        except FileNotFoundError:
            print(f"[wait] log file not found: {path}", file=sys.stderr, flush=True)
            time.sleep(max(poll_interval, 1.0))
        except PermissionError:
            print(f"[error] permission denied: {path}", file=sys.stderr, flush=True)
            time.sleep(max(poll_interval, 1.0))
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[error] {exc}", file=sys.stderr, flush=True)
            time.sleep(max(poll_interval, 1.0))

        start_from_end = False


def build_parser():
    parser = argparse.ArgumentParser(
        description="Tail a Minecraft latest.log file and emit join/chat/leave events."
    )
    parser.add_argument(
        "logfile",
        help="Path to Minecraft logs/latest.log",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Read the existing file from the beginning instead of only new lines.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON lines.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.2,
        help="Polling interval in seconds when waiting for new log lines (default: 0.2).",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    log_path = os.path.abspath(args.logfile)
    print(f"[listen] {log_path}", file=sys.stderr, flush=True)
    follow_file(
        path=log_path,
        poll_interval=max(args.poll_interval, 0.05),
        start_from_end=not args.from_start,
        output_json=args.json,
    )


if __name__ == "__main__":
    main()
