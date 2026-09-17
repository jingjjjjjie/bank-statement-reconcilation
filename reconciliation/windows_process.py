"""Create Windows process trees atomically inside kill-on-close Job Objects."""
import ctypes as C
from ctypes import wintypes as W
import msvcrt
import subprocess


class StartupInfo(C.Structure):
    """Native STARTUPINFOW layout, including redirected standard handles."""
    _fields_ = [("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR),
                ("title", W.LPWSTR), ("x", W.DWORD), ("y", W.DWORD),
                ("width", W.DWORD), ("height", W.DWORD), ("chars_x", W.DWORD),
                ("chars_y", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
                ("show", W.WORD), ("reserved_size", W.WORD), ("reserved_ptr", C.c_void_p),
                ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE)]


class StartupInfoEx(C.Structure):
    """Extended startup layout for atomic job assignment and handle allowlists."""
    _fields_ = [("startup", StartupInfo), ("attributes", C.c_void_p)]


class ProcessInfo(C.Structure):
    """Handles and IDs returned by CreateProcessW."""
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE),
                ("pid", W.DWORD), ("tid", W.DWORD)]


class BasicLimits(C.Structure):
    """Job limit layout used by JOBOBJECT_EXTENDED_LIMIT_INFORMATION."""
    _fields_ = [("process_time", C.c_int64), ("job_time", C.c_int64), ("flags", W.DWORD),
                ("min_working_set", C.c_size_t), ("max_working_set", C.c_size_t),
                ("active_limit", W.DWORD), ("affinity", C.c_size_t),
                ("priority", W.DWORD), ("scheduling", W.DWORD)]


class ExtendedLimits(C.Structure):
    """Extended job limits; only KILL_ON_JOB_CLOSE is enabled."""
    _fields_ = [("basic", BasicLimits), ("io_counters", C.c_uint64 * 6),
                ("process_memory", C.c_size_t), ("job_memory", C.c_size_t),
                ("peak_process_memory", C.c_size_t), ("peak_job_memory", C.c_size_t)]


class Accounting(C.Structure):
    """Job accounting exposes the number of processes still running."""
    _fields_ = [("times", C.c_int64 * 4), ("page_faults", W.DWORD),
                ("total", W.DWORD), ("active", W.DWORD), ("terminated", W.DWORD)]


def api(name, result, *arguments):
    """Bind explicit Win32 signatures so 64-bit handles are never truncated."""
    function = getattr(C.WinDLL("kernel32", use_last_error=True), name)
    function.restype, function.argtypes = result, arguments
    return function


create_job = api("CreateJobObjectW", W.HANDLE, C.c_void_p, W.LPCWSTR)
set_job = api("SetInformationJobObject", W.BOOL, W.HANDLE, C.c_int, C.c_void_p, W.DWORD)
query_job = api("QueryInformationJobObject", W.BOOL, W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p)
terminate_job = api("TerminateJobObject", W.BOOL, W.HANDLE, W.UINT)
close_handle = api("CloseHandle", W.BOOL, W.HANDLE)
duplicate = api("DuplicateHandle", W.BOOL, W.HANDLE, W.HANDLE, W.HANDLE,
                C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD)
initialize = api("InitializeProcThreadAttributeList", W.BOOL, C.c_void_p, W.DWORD,
                 W.DWORD, C.POINTER(C.c_size_t))
update = api("UpdateProcThreadAttribute", W.BOOL, C.c_void_p, W.DWORD, C.c_size_t,
             C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p)
delete = api("DeleteProcThreadAttributeList", None, C.c_void_p)
create_process = api("CreateProcessW", W.BOOL, W.LPCWSTR, W.LPWSTR, C.c_void_p,
                     C.c_void_p, W.BOOL, W.DWORD, C.c_void_p, W.LPCWSTR,
                     C.POINTER(StartupInfoEx), C.POINTER(ProcessInfo))
wait = api("WaitForSingleObject", W.DWORD, W.HANDLE, W.DWORD)
exit_code = api("GetExitCodeProcess", W.BOOL, W.HANDLE, C.POINTER(W.DWORD))


def checked(success):
    """Surface native failures instead of weakening process containment."""
    if not success:
        raise C.WinError(C.get_last_error())
    return success


class WindowsProcess:
    """Own one process and all descendants inherited into its Job Object."""

    def __init__(self, command, stdin, stdout, stderr, cwd=None):
        """Assign the job at creation, before any child instructions can run."""
        self.job = checked(create_job(None, None))
        self.handle, self.returncode = None, None
        handles, attributes = [], None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            checked(set_job(self.job, 9, C.byref(limits), C.sizeof(limits)))
            for stream in (stdin, stdout, stderr):
                handle = W.HANDLE()
                checked(duplicate(W.HANDLE(-1), msvcrt.get_osfhandle(stream.fileno()),
                                  W.HANDLE(-1), C.byref(handle), 0, True, 2))
                handles.append(handle.value)
            size = C.c_size_t()
            initialize(None, 2, 0, C.byref(size))
            buffer = C.create_string_buffer(size.value)
            checked(initialize(buffer, 2, 0, C.byref(size)))
            attributes = buffer
            jobs = (W.HANDLE * 1)(self.job)
            inherited = (W.HANDLE * 3)(*handles)
            checked(update(buffer, 0, 0x2000D, jobs, C.sizeof(jobs), None, None))
            checked(update(buffer, 0, 0x20002, inherited, C.sizeof(inherited), None, None))
            startup = StartupInfoEx()
            startup.startup.cb = C.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
            startup.attributes = C.cast(buffer, C.c_void_p)
            info = ProcessInfo()
            command_line = C.create_unicode_buffer(subprocess.list2cmdline([str(arg) for arg in command]))
            checked(create_process(None, command_line, None, None, True,
                                   0x08080000, None, str(cwd) if cwd else None,
                                   C.byref(startup), C.byref(info)))
            self.handle, self.pid = info.process, info.pid
            close_handle(info.thread)
        except BaseException:
            self.close()
            raise
        finally:
            if attributes is not None:
                delete(attributes)
            for handle in handles:
                close_handle(handle)

    def poll(self):
        """Read the main process exit code only after its handle is signalled."""
        if self.returncode is not None:
            return self.returncode
        state = wait(self.handle, 0)
        if state == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        if state == 0:
            code = W.DWORD()
            checked(exit_code(self.handle, C.byref(code)))
            self.returncode = code.value
        return self.returncode

    def alive(self):
        """Query the entire job, including children whose parent has exited."""
        info = Accounting()
        checked(query_job(self.job, 1, C.byref(info), C.sizeof(info), None))
        return bool(info.active)

    def terminate(self, force=False):
        """Windows job termination forcibly stops every contained process."""
        checked(terminate_job(self.job, 1))

    def close(self):
        """Release native handles; the job also protects against owner failure."""
        for name in ("handle", "job"):
            handle = getattr(self, name, None)
            if handle:
                close_handle(handle)
                setattr(self, name, None)
