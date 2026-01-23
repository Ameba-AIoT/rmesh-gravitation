import json
import re
from pathlib import Path
from typing import List, Dict, Optional


class ColorGroup:
    def __init__(self, color: str, name: str, macs: List[str]):
        self.color = color
        self.name = name
        self.macs = macs

    def to_dict(self) -> Dict:
        return {
            "color": self.color,
            "name": self.name,
            "macs": self.macs
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ColorGroup':
        required_keys = ['color', 'name', 'macs']
        if not all(key in data for key in required_keys):
            raise ValueError("Invalid ColorGroup data format")

        if not isinstance(data['macs'], list) or \
                not all(isinstance(m, str) for m in data['macs']):
            raise ValueError("macs should be a list of strings")

        return cls(
            color=data['color'],
            name=data['name'],
            macs=data['macs']
        )


class ColorConfigManager:
    def __init__(self, groups: List[ColorGroup]):
        self.groups = groups
        self.mac_color_map: Dict[str, str] = {}
        self._build_mac_color_map()

    def _normalize_mac(self, mac: str) -> str:
        """统一 MAC 地址格式：去除分隔符并转为小写"""
        # 移除所有非十六进制字符（保留字母数字）
        cleaned = re.sub(r'[^0-9a-fA-F]', '', mac).lower()
        if len(cleaned) != 12:
            raise ValueError(f"Invalid MAC address format: {mac}")
        return cleaned

    def _build_mac_color_map(self):
        """构建 MAC 到颜色的哈希映射"""
        self.mac_color_map.clear()
        seen_macs = set()

        for group in self.groups:
            for raw_mac in group.macs:
                try:
                    mac = self._normalize_mac(raw_mac)
                except ValueError as e:
                    raise ValueError(f"Invalid MAC in group '{group.name}': {e}")

                if mac in seen_macs:
                    raise ValueError(f"Duplicate MAC address: {raw_mac} (normalized: {mac})")

                self.mac_color_map[mac] = group.color
                seen_macs.add(mac)

    def get_color_by_mac(self, mac: str) -> Optional[str]:
        """根据任意格式的 MAC 地址查询颜色 (O(1) 时间复杂度)"""
        try:
            normalized_mac = self._normalize_mac(mac)
        except ValueError:
            return None
        return self.mac_color_map.get(normalized_mac, None)

    @classmethod
    def load_from_file(cls, file_path: Path) -> 'ColorConfigManager':
        """从文件加载配置并创建管理器"""
        try:
            with open(file_path, encoding='UTF-8') as f:
                data = json.load(f)
                groups = [ColorGroup.from_dict(item) for item in data]
                return cls(groups)
        except FileNotFoundError:
            raise FileNotFoundError(f"Config file {file_path} not found")
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON format")

    @staticmethod
    def save_to_file(file_path: Path, groups: List[ColorGroup]):
        """保存配置到文件"""
        data = [group.to_dict() for group in groups]
        with open(file_path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
