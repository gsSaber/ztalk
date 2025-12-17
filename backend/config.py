from pathlib import Path
from types import SimpleNamespace

import yaml


def _dict_to_namespace(data):
	if isinstance(data, dict):
		return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in data.items()})
	if isinstance(data, list):
		return [
			_dict_to_namespace(item)
			for item in data
		]
	return data


_CONFIG_DICT = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text())
config = _dict_to_namespace(_CONFIG_DICT)

def get_config():
	return config
__all__ = ["get_config"]

