"""Stable local ports for the agreed worktree branches."""
import subprocess

PORTS = {
    'feat/product-base-GPT': 8100,
    'feat/walking-records-GPT': 8101,
    'feat/activity-modes-GPT': 8102,
    'feat/personal-memory-GPT': 8103,
    'feat/growth-badges-GPT': 8104,
    'feat/glasses-guide-GPT': 8105,
    'integration/product-GPT': 8110,
}


def default_port(root):
    try:
        branch = subprocess.check_output(['git', '-C', str(root), 'branch', '--show-current'],
                                         text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return 8100
    return PORTS.get(branch, 8100)
