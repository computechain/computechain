from pydantic import BaseModel

class Account(BaseModel):
    address: str
    balance: int = 0
    nonce: int = 0
    
    # Future fields for staking/locking can be added here
    # staked_balance: int = 0 

