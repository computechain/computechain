def calculate_block_reward(height: int) -> int:
    """
    Returns block reward in minimal units (e.g. 10 CPC).
    Simple logic: fixed reward, maybe halving later.
    """
    initial_reward = 10 * 10**18 # 10 CPC
    
    # Halving every 1M blocks (example)
    halvings = height // 1000000
    reward = initial_reward >> halvings
    
    return reward

