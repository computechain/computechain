# CPC v3 — local devnet monetary/staking contract

This is a versioned development policy, not final/mainnet tokenomics. It deliberately
preserves zero emission, zero staking/compute rewards and 100% fee burn. No APY is implied.
V2 history is not migrated or reinterpreted; v3 requires a separate genesis/data directory.

## Amounts and conservation

1 CPC = 10^18 integer base units. Rates use integer basis points (10,000 = 100%).
No float is permitted in consensus state. For every committed block:

`liquid balances + bonded self stake + bonded delegations + pending unbondings + burned = genesis supply`

Voting power is floor(bonded tokens / 1 CPC), with a total bound of
`(2^63-1)//8` matching the pinned CometBFT implementation. Self stake and delegation
principal remain distinct. Fees are charged only on successful execution; failed
transactions do not consume balances, fees or nonce.

## Ownership and participation

- Validator self stake minimum: 1,000 CPC; minimum delegation: 10 CPC.
- At most 64 registered keys, one validator per owner, ten delegated validators
  per delegator, 64 deposit cohorts per relationship and 64 pending withdrawals per owner.
- Registration requires the owner's secp256k1 transaction signature and an Ed25519
  proof of consensus-key possession bound to owner, chain and key. Keys/owners cannot
  be reassigned. Small-order/non-prime-subgroup consensus keys are rejected.
- Voting uses eligible, non-tombstoned validators. At least one must remain; stake
  operations that would empty the set are rejected.
- A stake/delegation increase cannot push its target above 20% of eligible power.
  An initially larger genesis share is grandfathered, but cannot increase. Four
  genesis validators start at 25% each: add new validators before increasing their
  stake/delegations. This is a per-key concentration rule, not a Sybil-proof identity system.

## Withdrawal and evidence

Requests remove principal from bonded stake and queue it; never refund immediately.
Funds release only after BOTH 100 blocks beyond the H+2 update boundary and 60
seconds of consensus block time. Local wall clocks/peer claims do not unlock funds.
Consensus updates emitted at H are effective at H+2, per the pinned ABCI contract.

The genesis engine evidence window is 20 blocks/30 seconds. The application checks
it at InitChain. Deposit cohorts start liability at H+2 (genesis at 1); evidence
is matched to historical voting power. Verified duplicate-vote/light-client evidence
burns 5% of each liable bonded or withdrawing cohort and tombstones the key.
New deposits after the infraction are not retroactively slashed. Replay/dedup state,
cohorts and validator history are committed/snapshotted. Process evidence BEFORE
releasing withdrawals. History/dedup retention follows the configured evidence window.
State-sync trust period in the local harness is 30 seconds, below the 60-second
minimum lock; this is not a public checkpoint distribution mechanism.

## Commission and disabled functions

Commission is metadata only while rewards are disabled: max 20%, increase at most
5 percentage points, 100-block cooldown and 20-block advance announcement. Only
the owner schedules one change at a time; it applies deterministically at its height.
Genesis default is 10%. No miner payouts, arbitrary minting, local uptime penalties
or GPU scoring are connected to consensus. Real rewards/PoC and production parameters
need a separately reviewed protocol change.

All policy fields are fixed by this version, included in AppHash, and validated
on genesis, commit, restart and snapshot restore. Genesis supply includes locked
stake, not just the faucet balance. The devnet distributes 1,000,000 test CPC total.
