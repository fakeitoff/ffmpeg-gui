# -*- coding: utf-8 -*-
"""功能页注册表。"""
from .base import BaseTab
from .tab_audio import AudioTab
from .tab_capture import CaptureTab
from .tab_compress import CompressTab
from .tab_convert import ConvertTab
from .tab_custom import CustomTab
from .tab_effects import EffectsTab
from .tab_info import InfoTab
from .tab_merge import MergeTab
from .tab_trim import TrimTab

TAB_CLASSES = [
    ConvertTab,
    CompressTab,
    TrimTab,
    MergeTab,
    AudioTab,
    EffectsTab,
    CaptureTab,
    InfoTab,
    CustomTab,
]

__all__ = ["BaseTab", "TAB_CLASSES", "ConvertTab", "CompressTab", "TrimTab", "MergeTab",
           "AudioTab", "EffectsTab", "CaptureTab", "InfoTab", "CustomTab"]
