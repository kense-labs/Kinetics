"""Kense Industrial Sim (`kense_sim`): Decision-model interfacing & control SDK.

Unified Python API, OpenAI tool schema exporter, and REST/WebSocket client for
MuJoCo robotic arms and industrial equipment digital-twin simulation.
"""
from __future__ import annotations

from embodied_jev.equipment_sim import (
    EQUIPMENT_SPECS,
    EquipmentSession,
    EquipmentSpec,
    EquipmentWorld,
    run_equipment_headless,
)
from embodied_jev.policies import DecisionPolicy

from .client import KenseSimClient, KenseWebSocketClient
from .env import (
    ENV_REGISTRY,
    EnvSpec,
    IndustrialEnv,
    SafetyInterlockError,
    list_environments,
    make,
    run_episode,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "ENV_REGISTRY",
    "EQUIPMENT_SPECS",
    "DecisionPolicy",
    "EnvSpec",
    "EquipmentSession",
    "EquipmentSpec",
    "EquipmentWorld",
    "IndustrialEnv",
    "KenseSimClient",
    "KenseWebSocketClient",
    "SafetyInterlockError",
    "list_environments",
    "make",
    "run_episode",
    "run_equipment_headless",
]
