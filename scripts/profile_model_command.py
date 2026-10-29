"""Bound an isolated model command by footprint, RSS, free disk and wall time."""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import time

import psutil


class RUsageV0(ctypes.Structure):
    # Darwin sys/resource.h, rusage_info_v0, verified against the installed SDK.
    _fields_ = [('uuid', ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
        'user', 'system', 'pkg', 'interrupt', 'pageins', 'wired', 'resident',
        'footprint', 'start', 'exit')]


def macos_footprint(pid):
    library = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    library.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(RUsageV0)]
    library.proc_pid_rusage.restype = ctypes.c_int
    usage = RUsageV0()
    if library.proc_pid_rusage(pid, 0, ctypes.byref(usage)) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot read macOS physical footprint')
    return int(usage.footprint)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--footprint-limit-gib', type=float, default=10.)
    parser.add_argument('--rss-limit-gib', type=float, default=10.)
    parser.add_argument('--disk-reserve-gib', type=float, default=8.)
    parser.add_argument('--wall-limit-seconds', type=float, default=2400.)
    parser.add_argument('--sample-seconds', type=float, default=.5)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or min(args.footprint_limit_gib, args.rss_limit_gib,
                          args.wall_limit_seconds, args.sample_seconds) <= 0:
        parser.error('A command and positive limits are required.')
    args.record.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    record = dict(status='running', started_at=datetime.now(timezone.utc).isoformat(),
        command=command, cwd=os.getcwd(), host=platform.platform(),
        driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        footprint_measure='Sum of proc_pid_rusage ri_phys_footprint for owned process tree on macOS; RSS on other platforms.',
        footprint_limit_gib=args.footprint_limit_gib, rss_limit_gib=args.rss_limit_gib,
        wall_limit_seconds=args.wall_limit_seconds, disk_reserve_gib=args.disk_reserve_gib,
        peak_footprint_bytes=0, peak_rss_bytes=0, min_free_disk_bytes=shutil.disk_usage(args.record.parent).free)
    def save():
        record['wall_seconds'] = time.monotonic() - started
        temporary = args.record.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
        temporary.replace(args.record)
    reason = None
    with args.log.open('w') as log, args.record.with_suffix('.samples.jsonl').open('w') as samples:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        record['pid'] = child.pid
        root = psutil.Process(child.pid)
        save()
        while child.poll() is None:
            rss = footprint = 0
            try:
                for process in [root, *root.children(recursive=True)]:
                    try:
                        rss += process.memory_info().rss
                        footprint += (macos_footprint(process.pid) if platform.system() == 'Darwin'
                                      else process.memory_info().rss)
                    except psutil.NoSuchProcess:
                        continue
            except (OSError, psutil.AccessDenied, psutil.NoSuchProcess) as exc:
                if child.poll() is None:
                    reason = 'footprint_measurement_unavailable'
                    record['measurement_error'] = str(exc)
            elapsed = time.monotonic() - started
            free_disk = shutil.disk_usage(args.record.parent).free
            record.update(current_footprint_bytes=footprint, current_rss_bytes=rss,
                peak_footprint_bytes=max(record['peak_footprint_bytes'], footprint),
                peak_rss_bytes=max(record['peak_rss_bytes'], rss),
                min_free_disk_bytes=min(record['min_free_disk_bytes'], free_disk))
            if footprint > args.footprint_limit_gib * 1024**3:
                reason = 'footprint_limit'
            elif rss > args.rss_limit_gib * 1024**3:
                reason = 'rss_limit'
            elif free_disk < args.disk_reserve_gib * 1024**3:
                reason = 'free_disk_limit'
            elif elapsed > args.wall_limit_seconds:
                reason = 'wall_time_limit'
            samples.write(json.dumps(dict(seconds=elapsed, rss=rss, footprint=footprint, free_disk=free_disk)) + '\n')
            samples.flush()
            save()
            if reason:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                break
            time.sleep(args.sample_seconds)
        code = child.wait()
    record.update(status='resource_stopped' if reason else ('completed' if code == 0 else 'failed'),
                  stop_reason=reason, exit_code=code, finished_at=datetime.now(timezone.utc).isoformat())
    save()
    print(json.dumps(record, indent=2), flush=True)
    return (128-code if code < 0 else code) or (1 if reason else 0)


if __name__ == '__main__':
    raise SystemExit(main())
