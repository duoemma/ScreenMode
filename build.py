# -*- coding: utf-8 -*-
"""打包脚本：把程序打成单文件绿色 exe。

    python build.py              打包 dist/屏效助手.exe
    python build.py --checkup    只打包「屏幕体检」dist/屏幕体检.exe
    python build.py --all        两个都打

**没有安装程序，也没有卸载程序。** 只发两个绿色 exe：
双击就运行，配置/日志/补偿基线全写在 exe 旁边，删掉整个文件夹就等于卸载。

依赖：pip install -r requirements.txt
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "2.5.0"
APP_NAME = "屏效助手"


def _ver_tuple():
    """把 "2.5.0" 拆成 (2, 5, 0, 0) 给 exe 的版本资源用。

    以前这里写死成 (2, 3, 0, 0)，版本号一升属性页就停在旧值 ——
    反馈问题时用户报的版本和实际跑的不是一回事。改成从 APP_VERSION 算，
    两处永远同步。
    """
    parts = []
    for seg in APP_VERSION.split(".")[:4]:
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)


def version_info(desc, internal, original):
    """生成 PyInstaller 的版本资源。

    两个 exe 要分开写：体检工具是**装之前**给人跑的，右键属性里如果
    写着"屏效助手"，用户会以为这就是主程序；没有版本号则更糟 ——
    反馈问题时连自己跑的是哪版都说不清。
    """
    return """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(vtuple)s,
    prodvers=%(vtuple)s,
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('080404b0', [
        StringStruct('CompanyName', 'ScreenMode'),
        StringStruct('FileDescription', '%(desc)s'),
        StringStruct('FileVersion', '%(ver)s'),
        StringStruct('InternalName', '%(internal)s'),
        StringStruct('OriginalFilename', '%(original)s'),
        StringStruct('ProductName', '屏效助手'),
        StringStruct('ProductVersion', '%(ver)s')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""" % {"ver": APP_VERSION, "desc": desc, "internal": internal,
       "original": original, "vtuple": _ver_tuple()}


def write_version_file(desc, internal, original):
    """把版本资源写到 build/ 下，返回路径。"""
    vfile = os.path.join(ROOT, "build", "version_info_%s.txt" % internal)
    os.makedirs(os.path.dirname(vfile), exist_ok=True)
    with open(vfile, "w", encoding="utf-8") as f:
        f.write(version_info(desc, internal, original))
    return vfile


def icon_args():
    """图标相关的命令行参数；图标不存在就整段跳过。

    以前是硬写 `--icon assets/icon.ico`：文件一缺，PyInstaller 跑了几百行才
    报一句 icon file not found，还夹在一堆日志中间。体积和原因完全不成比例，
    不如自己先判断 —— 没图标就用默认的，照样能出包。
    """
    icon = os.path.join(ROOT, "assets", "icon.ico")
    if not os.path.exists(icon):
        print("提示：没有 assets/icon.ico，这次打包用默认图标")
        return []
    return ["--icon", icon, "--add-data", "%s%sassets" % (icon, os.pathsep)]


def sh(cmd):
    print("\n$ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def pyinstaller(args):
    return sh([sys.executable, "-m", "PyInstaller"] + args)


def build_app():
    manifest = os.path.join(ROOT, "assets", "app.manifest")
    vfile = write_version_file("屏效助手 · 显示器情景模式自动切换",
                               "ScreenMode", "ScreenMode.exe")
    args = [
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", APP_NAME,
        "--manifest", manifest,
        "--version-file", vfile,
    ] + icon_args() + [
        "--hidden-import", "pystray._win32",
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build"),
        "--specpath", os.path.join(ROOT, "build"),
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pytest",
        os.path.join(ROOT, "main.py"),
    ]
    return pyinstaller(args)


def build_checkup():
    """「屏幕体检」独立小工具 —— 让用户**装之前**就知道自己这台屏行不行。

    单独打一个 exe（而不是塞进主程序菜单）是有意的：
    用户还没装、甚至还在犹豫要不要装的时候，就能双击跑一遍。
    """
    vfile = write_version_file("屏效助手 · 屏幕体检（安装前自检）",
                               "ScreenCheckup", "屏幕体检.exe")
    args = [
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "屏幕体检",
        "--manifest", os.path.join(ROOT, "assets", "app.manifest"),
        "--version-file", vfile,
    ] + icon_args() + [
        "--distpath", os.path.join(ROOT, "dist"),
        "--workpath", os.path.join(ROOT, "build", "checkup"),
        "--specpath", os.path.join(ROOT, "build", "checkup"),
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pytest",
        "--exclude-module", "pystray",
        os.path.join(ROOT, "checkup_main.py"),
    ]
    return pyinstaller(args)


if __name__ == "__main__":
    args = sys.argv[1:]
    rc = 0
    if "--checkup" in args or "--all" in args:
        rc = build_checkup()
    # 只给 --checkup 时别顺带打主程序，省时间
    if rc == 0 and ("--checkup" not in args or "--all" in args):
        rc = build_app()
    sys.exit(rc)
