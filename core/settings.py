# -*- coding: utf-8 -*-
"""极小的本地偏好存储：只存「用户每次开窗口都要手动调」的那几项。

程序本来就零第三方依赖，所以不引配置框架，直接一个 JSON 放在程序目录里：
看得见、随时删掉就回到默认。读写失败一律当「没有偏好」处理——
偏好文件坏了不能连累界面打不开。
"""
from __future__ import annotations

import json
import os

from .util import APP_ROOT

FILE_NAME = "settings.json"


def default_path() -> str:
    return os.path.join(APP_ROOT, FILE_NAME)


def load(path: str = "") -> dict:
    """读偏好；文件缺失 / 不是 JSON / 不是对象都返回空表。"""
    path = path or default_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(values: dict, path: str = "") -> bool:
    """先写临时文件再改名替换：中途断电也不会留下半个坏文件。"""
    path = path or default_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(values, fh, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
