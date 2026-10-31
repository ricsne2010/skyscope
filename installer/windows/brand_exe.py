"""Gives SkyScope its own name in Task Manager (run by install.ps1 with the venv's Python).

Task Manager lists a program by the description inside its .exe, so a plain Python shows as "Python"
whatever it runs. This copies the installed Python's pythonw.exe (and the DLLs it needs) into the venv as
SkyScope.exe, with the description "SkyScope" and SkyScope's icon. Python finds the venv's packages through
pyvenv.cfg, as a venv made with --copies does.

    python brand_exe.py <SkyScope's folder>   prints the program to run SkyScope with: SkyScope.exe, or the
                                              venv's pythonw.exe if SkyScope.exe couldn't be made or doesn't work
Designed and Created by Project Moon Pi.
"""
import ctypes
import os
import shutil
import struct
import subprocess
import sys
from ctypes import wintypes

RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16
NEW_STRINGS = {"FileDescription": "SkyScope", "ProductName": "SkyScope (Python)",
               "InternalName": "SkyScope", "OriginalFilename": "SkyScope.exe"}

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.LoadLibraryExW.restype = wintypes.HMODULE
k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
k32.FindResourceExW.restype = wintypes.HRSRC
k32.FindResourceExW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD]
k32.SizeofResource.restype = wintypes.DWORD
k32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
k32.LoadResource.restype = wintypes.HGLOBAL
k32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
k32.LockResource.restype = ctypes.c_void_p
k32.LockResource.argtypes = [wintypes.HGLOBAL]
k32.FreeLibrary.argtypes = [wintypes.HMODULE]
k32.BeginUpdateResourceW.restype = wintypes.HANDLE
k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
k32.UpdateResourceW.restype = wintypes.BOOL
k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD,
                                ctypes.c_void_p, wintypes.DWORD]
k32.EndUpdateResourceW.restype = wintypes.BOOL
k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
ENUM_NAME = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
ENUM_LANG = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wintypes.WORD,
                               ctypes.c_void_p)
k32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ENUM_NAME, ctypes.c_void_p]
k32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ENUM_LANG,
                                       ctypes.c_void_p]


def resources(path: str, rtype: int) -> list[tuple[object, int, bytes]]:
    """(name, language, data) of each resource of one type; a name is an int or a str."""
    h = k32.LoadLibraryExW(path, None, 0x22)  # LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE
    if not h:
        raise OSError(ctypes.get_last_error(), "can't read " + path)
    names, found = [], []
    try:
        def on_name(_h, _t, name, _p):
            names.append(name if name < 0x10000 else ctypes.wstring_at(name))
            return True

        def on_lang(_h, _t, _n, lang, _p):
            found[-1][1].append(lang)
            return True

        cb_name, cb_lang = ENUM_NAME(on_name), ENUM_LANG(on_lang)
        k32.EnumResourceNamesW(h, rtype, cb_name, None)
        out = []
        for name in names:
            ref = name if isinstance(name, int) else ctypes.c_wchar_p(name)
            found.append((name, []))
            k32.EnumResourceLanguagesW(h, rtype, ref, cb_lang, None)
            for lang in found[-1][1]:
                r = k32.FindResourceExW(h, rtype, ref, lang)
                size = k32.SizeofResource(h, r)
                out.append((name, lang, ctypes.string_at(k32.LockResource(k32.LoadResource(h, r)), size)))
        return out
    finally:
        k32.FreeLibrary(h)


# VS_VERSIONINFO is a tree of blocks: length, value length, type (1 = text), key, value, child blocks,
# each lined up on 4 bytes.
def parse(buf: bytes, off: int = 0) -> list:
    length, vlen, vtype = struct.unpack_from("<HHH", buf, off)
    end = off + length
    pos = off + 6
    key_end = pos
    while buf[key_end:key_end + 2] != b"\0\0":
        key_end += 2
    key = buf[pos:key_end].decode("utf-16-le")
    pos = (key_end + 2 + 3) & ~3
    vbytes = min(vlen * 2 if vtype == 1 else vlen, end - pos)
    value = buf[pos:pos + vbytes]
    pos = (pos + vbytes + 3) & ~3
    children = []
    while pos < end:
        child = parse(buf, pos)
        children.append(child)
        pos = (pos + child[5] + 3) & ~3
    return [key, vtype, vlen, value, children, length]


def build(node: list) -> bytes:
    key, vtype, vlen, value, children, _ = node
    b = bytearray(struct.pack("<HHH", 0, vlen, vtype) + (key + "\0").encode("utf-16-le"))
    b += b"\0" * (-len(b) % 4) + value
    for child in children:
        b += b"\0" * (-len(b) % 4) + build(child)
    struct.pack_into("<H", b, 0, len(b))
    return bytes(b)


def rename(node: list) -> None:
    if node[1] == 1 and not node[4] and node[0] in NEW_STRINGS:
        text = NEW_STRINGS[node[0]]
        node[3] = (text + "\0").encode("utf-16-le")
        node[2] = len(text) + 1
    for child in node[4]:
        rename(child)


def icon_resources(ico_path: str, first_id: int) -> tuple[list[tuple[int, bytes]], bytes]:
    """The images of a .ico as RT_ICON resources, and the RT_GROUP_ICON that lists them."""
    data = open(ico_path, "rb").read()
    _, kind, count = struct.unpack_from("<HHH", data, 0)
    icons, group = [], bytearray(struct.pack("<HHH", 0, kind, count))
    for i in range(count):
        w, h, colors, res, planes, bits, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        icons.append((first_id + i, data[offset:offset + size]))
        group += struct.pack("<BBBBHHIH", w, h, colors, res, planes, bits, size, first_id + i)
    return icons, bytes(group)


def brand(exe: str, ico: str) -> None:
    versions = resources(exe, RT_VERSION)
    groups = resources(exe, RT_GROUP_ICON)
    icons, group = icon_resources(ico, 200)
    h = k32.BeginUpdateResourceW(exe, False)
    if not h:
        raise OSError(ctypes.get_last_error(), "can't change " + exe)
    ok = False
    try:
        for name, lang, data in versions:
            tree = parse(data)
            rename(tree)
            new = build(tree)
            k32.UpdateResourceW(h, RT_VERSION, name, lang, new, len(new))
        for name, lang, _ in groups:
            ref = name if isinstance(name, int) else ctypes.c_wchar_p(name)
            for icon_id, img in icons:
                k32.UpdateResourceW(h, RT_ICON, icon_id, lang, img, len(img))
            k32.UpdateResourceW(h, RT_GROUP_ICON, ref, lang, group, len(group))
        ok = True
    finally:
        if not k32.EndUpdateResourceW(h, not ok) and ok:
            raise OSError(ctypes.get_last_error(), "can't save " + exe)


def works(exe: str, app_dir: str) -> bool:
    check = "import sys, pygame; sys.exit(0 if sys.prefix != sys.base_prefix else 3)"
    try:
        return subprocess.run([exe, "-c", check], cwd=app_dir, timeout=60,
                              env=dict(os.environ, PYGAME_HIDE_SUPPORT_PROMPT="1")).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main() -> int:
    app_dir = os.path.abspath(sys.argv[1])
    scripts = os.path.join(app_dir, "venv", "Scripts")
    plain = os.path.join(scripts, "pythonw.exe")
    exe = os.path.join(scripts, "SkyScope.exe")
    try:
        for f in os.listdir(sys.base_prefix):  # python3XX.dll, python3.dll, vcruntime140(_1).dll
            if f.lower().endswith(".dll"):
                shutil.copy2(os.path.join(sys.base_prefix, f), scripts)
        tmp = exe + ".new"
        shutil.copy2(os.path.join(sys.base_prefix, "pythonw.exe"), tmp)
        brand(tmp, os.path.join(app_dir, "skyscope.ico"))
        os.replace(tmp, exe)
        if works(exe, app_dir):
            print(exe)
            return 0
        print("SkyScope.exe didn't run; using pythonw.exe", file=sys.stderr)
    except OSError as exc:
        print(f"Couldn't make SkyScope.exe ({exc}); using pythonw.exe", file=sys.stderr)
    print(plain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
