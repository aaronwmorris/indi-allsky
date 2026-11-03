"""System Hardware Profiling and Configuration Preset Optimization.

Introspects host hardware resources (RAM, CPU cores, swap) and provides
empirically calibrated configuration presets to prevent Out-Of-Memory (OOM)
terminations and high load on resource-constrained platforms.
"""

from dataclasses import dataclass
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger('indi_allsky')


@dataclass(frozen=True)
class HardwareProfile:
    ram_bytes: int
    ram_gb: float
    swap_bytes: int
    swap_gb: float
    cpu_cores: int
    tier: int
    tier_name: str
    config_overrides: Dict[str, Any]


def get_memory_total_bytes() -> int:
    """Detect total system physical RAM in bytes."""
    # 1. Read /proc/meminfo (Linux standard)
    try:
        if os.path.exists('/proc/meminfo'):
            with open('/proc/meminfo', 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
    except Exception as e:
        logger.debug('Failed to read /proc/meminfo for MemTotal: %s', e)

    # 2. Try sysconf (POSIX standard)
    try:
        pages = os.sysconf('SC_PHYS_PAGES')
        page_size = os.sysconf('SC_PAGE_SIZE')
        if pages > 0 and page_size > 0:
            return pages * page_size
    except Exception as e:
        logger.debug('Failed to read sysconf for memory: %s', e)

    # 3. Default fallback: 4 GB
    return 4 * 1024 * 1024 * 1024


def get_swap_total_bytes() -> int:
    """Detect total system swap space in bytes."""
    try:
        if os.path.exists('/proc/meminfo'):
            with open('/proc/meminfo', 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('SwapTotal:'):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
    except Exception as e:
        logger.debug('Failed to read /proc/meminfo for SwapTotal: %s', e)

    return 0


def get_system_hardware_profile(
    override_ram_bytes: Optional[int] = None,
    override_cpu_cores: Optional[int] = None,
    override_swap_bytes: Optional[int] = None,
) -> HardwareProfile:
    """Evaluate host specifications and determine the optimal operational tier.

    Tiers:
    - Tier 1 (Constrained): < 1.5 GB RAM (RPi 3, RPi Zero 2W, 1GB RPi 4)
    - Tier 2 (Moderate): 1.5 GB <= RAM < 3.5 GB (2GB RPi 4)
    - Tier 3 (Standard): 3.5 GB <= RAM < 6.0 GB (4GB RPi 4/5)
    - Tier 4 (High Performance): >= 6.0 GB RAM (8GB RPi 5, x86_64 servers)
    """
    ram_bytes = override_ram_bytes if override_ram_bytes is not None else get_memory_total_bytes()
    ram_gb = ram_bytes / (1024 ** 3)

    swap_bytes = override_swap_bytes if override_swap_bytes is not None else get_swap_total_bytes()
    swap_gb = swap_bytes / (1024 ** 3)

    cpu_cores = override_cpu_cores if override_cpu_cores is not None else (os.cpu_count() or 1)

    if ram_gb < 1.5:
        tier = 1
        tier_name = 'Constrained'
        overrides: Dict[str, Any] = {
            'FFMPEG_VFSCALE': '-2:720',
            'FFMPEG_VFSCALE_DAY': '-2:720',
            'FFMPEG_VFSCALE_STARTRAIL': '-2:720',
            'FFMPEG_BITRATE': '2500k',
            'FFMPEG_BITRATE_DAY': '2500k',
            'IMAGE_QUEUE_MAX': 3,
            'IMAGE_QUEUE_MIN': 1,
            'UPLOAD_WORKERS': 1,
        }
        if ram_gb < 1.0:
            overrides['LIBCAMERA'] = {
                'IMAGE_FILE_TYPE': 'jpg',
                'IMAGE_FILE_TYPE_DAY': 'jpg',
            }
    elif ram_gb < 3.5:
        tier = 2
        tier_name = 'Moderate'
        overrides = {
            'FFMPEG_VFSCALE': '-2:1080',
            'FFMPEG_VFSCALE_DAY': '-2:1080',
            'FFMPEG_VFSCALE_STARTRAIL': '-2:1080',
            'FFMPEG_BITRATE': '4000k',
            'FFMPEG_BITRATE_DAY': '4000k',
            'IMAGE_QUEUE_MAX': 5,
            'IMAGE_QUEUE_MIN': 2,
            'UPLOAD_WORKERS': 1,
        }
    elif ram_gb < 6.0:
        tier = 3
        tier_name = 'Standard'
        overrides = {
            'FFMPEG_VFSCALE': '-2:1440',
            'FFMPEG_VFSCALE_DAY': '-2:1440',
            'FFMPEG_VFSCALE_STARTRAIL': '-2:1440',
            'FFMPEG_BITRATE': '5000k',
            'FFMPEG_BITRATE_DAY': '5000k',
            'IMAGE_QUEUE_MAX': 8,
            'IMAGE_QUEUE_MIN': 4,
            'UPLOAD_WORKERS': 2,
        }
    else:
        tier = 4
        tier_name = 'High Performance'
        overrides = {
            'FFMPEG_VFSCALE': '',
            'FFMPEG_VFSCALE_DAY': '',
            'FFMPEG_VFSCALE_STARTRAIL': '',
            'FFMPEG_BITRATE': '6000k',
            'FFMPEG_BITRATE_DAY': '6000k',
            'IMAGE_QUEUE_MAX': 10,
            'IMAGE_QUEUE_MIN': 5,
            'UPLOAD_WORKERS': 3,
        }

    return HardwareProfile(
        ram_bytes=ram_bytes,
        ram_gb=ram_gb,
        swap_bytes=swap_bytes,
        swap_gb=swap_gb,
        cpu_cores=cpu_cores,
        tier=tier,
        tier_name=tier_name,
        config_overrides=overrides,
    )
