from protocol.config.economic_model import ECONOMIC_CONFIG


def calculate_block_reward(height: int) -> int:
    """
    Calculate block reward using economic model.

    Uses ECONOMIC_CONFIG for:
    - Initial block reward
    - Halving period

    Args:
        height: Block height

    Returns:
        Block reward in minimal units
    """
    return ECONOMIC_CONFIG.calculate_block_reward(height)

