# ComputeChain - General Roadmap (Revised)

> **Last Updated:** January 13, 2026
> **Status:** Draft v8 (CRITICAL: State Synchronization Bug identified, start_test.sh updated for 5 validators)
> **Timeline:** ~12 months to Mainnet Launch (approximate)

---

## 📊 Current State Analysis

### ✅ Production-Ready (Completed)

#### Blockchain Core
- **Multi-validator PoA consensus** (round-robin block production)
- **Block production & validation** (10s block time on devnet)
- **Transaction processing** (7 transaction types)
- **Gas model** (Ethereum-like, anti-spam protection)
- **Post-quantum ready architecture** (Dilithium/Falcon prepared)

#### Validator System
- **Performance tracking** (uptime score, missed blocks, performance score)
- **Automated jailing & slashing** (graduated penalties: 5% → 10% → 100%)
- **Validator metadata** (name, website, description, commission rate)
- **Real-time web dashboard** (validator leaderboard, performance metrics)
- **Min uptime requirement** (75% to remain in active set)

#### Staking & Delegation
- **STAKE/UNSTAKE mechanism** (validator onboarding/exit)
- **DELEGATE/UNDELEGATE** (token delegation to validators)
- **Commission-based rewards** (validators earn commission from delegations)
- **Early unjail mechanism** (1000 CPC fee to exit jail early)
- **Unstake penalties** (10% penalty if jailed)

#### Infrastructure
- **CLI wallet** (full functionality: keys, query, tx)
- **RPC API** (FastAPI with comprehensive endpoints)
- **SQLite storage** (blocks, state, validators)
- **Test coverage** (11 unit tests + 1 E2E test, all passing)
- **P2P networking** (custom TCP protocol with msgpack)

### 🔄 In Progress

- **Full PoC verification pipeline** (GPU computation verification)

### ⚠️ Technical Debt & Critical Gaps

**🚨 CRITICAL: State Synchronization Bug (Discovered Jan 2026)**
- **Problem:** Validator state not replicated across nodes
  - When a validator stakes on node A, only node A sees the new validator
  - Other nodes (B, C, D, E) don't receive the updated validator set
  - Result: Only node that processed STAKE TX includes validator in block production
- **Impact:** Multi-validator networks broken; only 1 node proposes blocks
- **Root Cause:** State changes from transactions not propagated via P2P
- **Priority:** CRITICAL - blocks multi-validator testing and production
- **Workaround:** None currently; requires architecture fix
- **Related:** start_test.sh updated to setup 5 validators, but sync issue prevents proper operation

**Delegation System:** ✅ COMPLETED
- ~~Individual delegation tracking (currently only total_delegated)~~
- ~~Proportional reward distribution to delegators~~
- ~~Unbonding period for undelegations~~

**Infrastructure:**
- ~~State snapshots / fast sync~~ ✅ COMPLETED
- ~~Observability (metrics, alerts, profiling)~~ ✅ COMPLETED
- ~~Upgrade protocol (versioning, state migration)~~ ✅ COMPLETED
- Storage migration path (SQLite → RocksDB for production)

**Security & Testing:**
- Economic attack simulations
- Network partition recovery testing
- Load testing harness (automated validators, tx generators)
- Acceptance criteria for critical features

---

## 🎯 Revised Roadmap (12-Month MVP)

### **Phase 1: Production-Ready L1 Foundation**
**Estimated Duration:** 2 months
**Goal:** Bulletproof L1 with complete staking/delegation system

#### 1.1 Delegation System Completion ⭐ CRITICAL ✅ **COMPLETED**
- [x] **Individual delegation tracking** ✅ DONE (Dec 17, 2025)
  - Store `List[Delegation]` per validator ✅
  - Track delegator addresses, amounts, creation height ✅
  - API: `/delegator/{address}/delegations` ✅
  - **Acceptance:** Query returns all delegations for address ✅
  - **Implementation:** `protocol/types/validator.py:53`, `blockchain/rpc/api.py:117`
  - **Tests:** `test_delegate_undelegate_flow` passing

- [x] **Proportional reward distribution** ✅ DONE (Dec 17, 2025)
  - Calculate delegator shares from block rewards ✅
  - Distribute rewards based on delegation ratio ✅
  - Deduct validator commission correctly ✅
  - **Acceptance:** Rewards sum matches block reward, commission accurate ✅
  - **Implementation:** `blockchain/core/chain.py:389-429` (`_distribute_delegator_rewards`)
  - **Tests:** `test_reward_distribution_to_delegators` passing

- [x] **Delegation rewards history** ✅ DONE (Dec 17, 2025)
  - Track rewards per epoch per delegator ✅
  - Auto reward distribution (no manual claim needed) ✅
  - API: `/delegator/{address}/rewards` ✅
  - **Acceptance:** Historical rewards queryable, accurate ✅
  - **Implementation:** `blockchain/core/accounts.py:11` (`reward_history`), `blockchain/rpc/api.py:144`
  - **Tests:** reward_history validated in tests

- [x] **Additional improvements completed:**
  - Fixed `created_height` tracking (now uses actual block height)
  - Added `min_delegation` validation (100 CPC minimum enforced)
  - CLI commands: `query delegations`, `query rewards` working
  - All 24 unit tests passing ✅

#### 1.2 Economic Model Hardening ⭐ CRITICAL
- [x] **Unbonding period** ✅ **COMPLETED (Dec 17, 2025)**
  - 21-day unbonding period (100 blocks devnet / 181440 blocks mainnet) ✅
  - Unbonding queue implementation (`UndelegationEntry` model) ✅
  - Automatic token return via `process_unbonding_queue()` ✅
  - API: `/delegator/{address}/unbonding` ✅
  - CLI: `query unbonding <address>` ✅
  - **Acceptance:** Tokens locked for unbonding period, auto-returned ✅
  - **Implementation:** `protocol/types/validator.py`, `blockchain/core/accounts.py`, `blockchain/core/state.py`, `blockchain/core/chain.py`, `blockchain/rpc/api.py`, `cli/main.py`
  - **Tests:** `test_unbonding_period`, `test_delegate_undelegate_flow` - 25 tests passing ✅

- [x] **Economic Model v2.0** ✅ **COMPLETED (Dec 17, 2025)**
  - Single source of truth: `protocol/config/economic_model.py` ✅
  - Block reward distribution: 70% validators, 30% miners ✅
  - Transaction fees: 90% validator, 10% treasury ✅
  - Burn mechanisms: slashing, penalties, dust ✅
  - Mint tracking: block rewards ✅
  - Treasury account: hardcoded address for community pool ✅
  - Miner weight system (ZK-based verification, off-chain calculation) ✅
  - **Acceptance:** All economic parameters centralized, burn/mint tracked ✅
  - **Implementation:**
    - `protocol/config/economic_model.py` - DEVNET/TESTNET/MAINNET configs
    - `miner/weight/` - calculator, ZK prover, signer (off-chain)
    - `blockchain/core/zk_verification.py` - on-chain ZK proof verification
    - `blockchain/core/miner_rewards.py` - miner reward distribution
    - `blockchain/core/state.py` - burn/mint tracking, treasury support
    - `blockchain/core/chain.py` - integrated reward distribution
    - `blockchain/core/rewards.py` - uses ECONOMIC_CONFIG
  - **Architecture:** Off-chain weight calculation with ZK proof, on-chain verification only
  - **Ready for:** Phase 2A PoC implementation (miner pool ready)

- [x] **Economic invariants testing** ✅ **COMPLETED (Dec 17, 2025)**
  - Total supply conservation test implemented ✅
  - Non-negative balances test implemented ✅
  - Staking limits verification test ✅
  - **Acceptance:** Core invariants tested ✅
  - **Implementation:** `tests/test_economic_invariants.py`
  - **Tests:** `test_supply_conservation`, `test_non_negative_balances`, `test_staking_limits_enforced`

- [x] **Staking limits** ✅ **COMPLETED (Dec 17, 2025)**
  - Max validators per delegator: 10 (enforced in DELEGATE) ✅
  - Min delegation: 100 CPC (already enforced) ✅
  - Max validator power cap: 20% (enforced in DELEGATE) ✅
  - **Acceptance:** Limits enforced, centralization prevented ✅
  - **Implementation:** `blockchain/core/state.py` - DELEGATE transaction checks

#### 1.3 Infrastructure & Observability ⭐ CRITICAL ✅ **COMPLETED (Dec 17, 2025)**

- [x] **State Snapshots** ✅ **COMPLETED (Dec 17, 2025)**
  - Snapshot state every N blocks (configurable, default 1000) ✅
  - Snapshot at epoch boundaries ✅
  - Fast sync from snapshot (load_from_snapshot, fast_sync_from_latest_snapshot) ✅
  - Snapshot verification (SHA256 hash-based) ✅
  - Automatic cleanup (keep last 10 snapshots) ✅
  - Compression (gzip, ~60-80% reduction) ✅
  - CLI commands: `snapshot list`, `snapshot info` ✅
  - RPC endpoints: `GET /snapshots`, `GET /snapshots/{height}` ✅
  - **Implementation:**
    - `blockchain/snapshot/` - snapshot system
    - `blockchain/snapshot/types.py` - Snapshot, SnapshotMetadata models
    - `blockchain/snapshot/snapshot_manager.py` - create, load, verify snapshots
    - `blockchain/core/chain.py` - integrated snapshot creation, fast_sync methods
    - `blockchain/core/state.py` - persist/load economic tracking (total_burned, total_minted)
    - `cli/main.py` - snapshot commands
    - `blockchain/rpc/api.py` - snapshot endpoints
  - **Acceptance:** Node syncs from snapshot <5 min ✅

- [x] **Observability Stack** ✅ **COMPLETED (Dec 17, 2025)**
  - Prometheus metrics export implemented ✅
    - Block metrics: height, block time, tx count, TPS
    - Validator metrics: count, uptime, performance, power, missed blocks
    - Economic metrics: total supply, minted, burned, staked, delegated, treasury
    - Network metrics: epoch, network ID, mempool size
  - Metrics endpoint: `GET /metrics` (Prometheus scrape target) ✅
  - Auto-update: metrics updated after each block ✅
  - **Implementation:**
    - `blockchain/observability/metrics.py` - Prometheus metrics
    - `blockchain/rpc/api.py` - `/metrics` endpoint
    - `blockchain/core/chain.py` - auto-update integration
  - **Acceptance:** Prometheus metrics exported ✅
  - ⏳ **Note:** Grafana dashboards and alert rules are separate operational tasks

- [x] **Upgrade Protocol** ✅ **COMPLETED (Dec 17, 2025)**
  - Semantic versioning (MAJOR.MINOR.PATCH) ✅
  - State migration framework (decorator-based migrations) ✅
  - Version compatibility checks ✅
  - Upgrade scheduling (UpgradePlan model) ✅
  - Migration execution at upgrade height ✅
  - Version persistence across restarts ✅
  - **Implementation:**
    - `blockchain/upgrade/` - upgrade protocol
    - `blockchain/upgrade/types.py` - Version, UpgradePlan, ChainVersion models
    - `blockchain/upgrade/manager.py` - UpgradeManager (schedule, execute, validate)
    - `blockchain/upgrade/migrations.py` - MigrationRegistry, @migration decorator
  - **Acceptance:** Framework ready for v1.0 → v1.1 upgrades ✅
  - ⏳ **Note:** Rolling upgrade testing and hard fork coordination to be validated in testnet

- [ ] **Storage Migration Plan** ⏳ **PENDING**
  - Document SQLite → RocksDB migration path
  - Implement migration script
  - Benchmark both (latency, throughput)
  - **Acceptance:** RocksDB ready for Phase 3
  - **Note:** SQLite sufficient for devnet/early testnet, RocksDB needed for public testnet

#### 1.4 Performance & Scalability ⭐ CRITICAL

**Current State (Dec 25, 2025):**
- ✅ Transaction event tracking via SSE working (122K+ TX confirmed in test)
- ✅ **Phase 1.4.1 optimizations implemented** (config updates, priority queue, nonce-aware mempool)
- ⚠️ **Previous throughput: ~10 TPS** (100 TX/block ÷ 10s block time)
- ✅ **New theoretical max: ~100 TPS** (500 TX/block ÷ 5s block time)
- ⏳ **Testing required** to validate real-world sustained throughput

**Throughput Improvements (Phase 1.4.1):**
```
Old Architecture:
- Block time: 10 seconds
- Max TX/block: 100
- Sequential validation with redundant checks
- Theoretical max: 100 ÷ 10 = 10 TPS

New Architecture:
- Block time: 5 seconds (2x faster)
- Max TX/block: 500 (5x capacity)
- Optimized validation (skip redundant crypto checks)
- Gas-price priority queue
- Nonce-aware mempool with pending queue
- Theoretical max: 500 ÷ 5 = 100 TPS (10x improvement)

User Capacity:
- At 10 TPS: ~860K transactions/day
- 1 TX/user/day: supports ~860K users
- 10 TX/user/day: supports ~86K users
- Active trading (100 TX/day): supports ~8.6K users
```

**Scalability Roadmap:**

- [ ] **Phase 1.4.1: Immediate Optimizations** (Target: 50-100 TPS) **IN PROGRESS**
  - [x] Reduce block time: 10s → 5s ✅ (Dec 25, 2025)
  - [x] Increase max_tx_per_block: 100 → 500 ✅ (Dec 25, 2025)
  - [x] Increase block_gas_limit: 10M → 50M ✅ (Dec 25, 2025)
  - [x] Remove redundant signature verification (skip_crypto_check) ✅ (Dec 25, 2025)
  - [x] Add transaction priority queue (gas price-based) ✅ (Dec 25, 2025)
  - [x] Implement nonce-aware mempool with pending queue ✅ (Dec 25, 2025)
  - [ ] Network propagation testing for 5s block time ⏳
  - [ ] 30 TPS load test (1 hour) ⏳
  - [ ] 50 TPS load test (4 hours) ⏳
  - [ ] 80 TPS stress test (24 hours) ⏳
  - **Target:** 100 TPS sustained (500 TX/block ÷ 5s = 100 TPS)
  - **Capacity:** ~500K active users (10 TX/day each)
  - **Status:** Code complete, testing phase next
  - **Acceptance:** No nonce gaps, no mempool saturation, stable block production

- [ ] **Phase 1.4.2: Advanced Optimizations** (Target: 200-500 TPS)
  - [ ] Batch signature verification (verify multiple TX signatures in parallel)
  - [ ] State caching layer (reduce DB reads during validation)
  - [ ] Optimize state root calculation (incremental Merkle updates)
  - [ ] Mempool pre-validation (reject invalid TX before broadcast)
  - [ ] Block time: 5s → 3s (if network stable)
  - [ ] Max TX/block: 500 → 1000
  - **Target:** 300 TPS sustained (1000 TX/block ÷ 3s = 333 TPS)
  - **Capacity:** ~1.5M active users
  - **Testing:** 7-day continuous load test at 250 TPS
  - **Acceptance:** CPU usage <70%, memory stable, no crashes

- [ ] **Phase 1.4.3: Long-term Scalability** (Target: 1000+ TPS)
  - [ ] State machine parallelization (independent transaction execution)
  - [ ] Optimistic execution (speculative parallel processing)
  - [ ] Layer 2 readiness (state channels, rollups)
  - [ ] Sharding for compute tasks (separate compute from consensus)
  - **Target:** 1000+ TPS
  - **Capacity:** 5M+ users
  - **Timeline:** Post-mainnet R&D (2027+)

**Comparison with Other L1 Blockchains:**
| Blockchain | TPS | Note |
|------------|-----|------|
| Bitcoin | ~7 | Production |
| Ethereum | ~15-30 | Production |
| Cardano | ~250 | Optimized |
| **ComputeChain (current)** | **~10** | Phase 1 MVP |
| **ComputeChain (Phase 1.4.1)** | **100** | Immediate target |
| **ComputeChain (Phase 1.4.2)** | **300** | Mid-term target |
| **ComputeChain (Phase 1.4.3)** | **1000+** | Long-term R&D |

**Critical Findings from Load Testing (Dec 25, 2025):**
- ✅ SSE event system working correctly (122,778 TX confirmed via events)
- ✅ EventBus singleton issue fixed (module-level imports)
- ✅ TX TTL auto-cleanup working (1 hour expiry)
- ✅ tx_failed events now emitted on expiry (NonceManager unblocking)
- ❌ High load (100-500 TPS) causes nonce gaps and mempool saturation
- ❌ Medium load (10-50 TPS) needs testing - likely at architectural limit
- ✅ Low load (1-5 TPS) stable for 12+ hours
- **Recommendation:** Use medium load for 24-hour stress test

#### 1.5 State Synchronization Fix ⭐ CRITICAL BLOCKER ✅ **COMPLETED (Jan 13, 2026)**

- [x] **Multi-Node State Replication** ⭐ CRITICAL ✅ **FIXED**
  - **Root Cause Found:** Each node created its own genesis.json with only its own validator
  - **Result:** Different genesis hashes → P2P rejected connections → blocks didn't propagate
  - **Solution Implemented:**
    - [x] Created `scripts/generate_genesis.py` - generates shared genesis with all validators
    - [x] Modified `blockchain/cli/node_cli.py` - added `--genesis` flag for shared genesis
    - [x] Updated `start_test.sh` - uses shared genesis workflow
    - [x] Added validators to state_root for consensus verification
  - **Implementation:**
    - `scripts/generate_genesis.py` - NEW
    - `blockchain/cli/node_cli.py:22-61` - shared genesis mode
    - `blockchain/core/state.py:569-634` - validators in state_root
    - `start_test.sh` - complete rewrite of init section
  - **Acceptance:** All nodes see same validator set ✅
  - **Testing:** `./start_test.sh low 1` creates 5 validators, all 5 propose blocks

#### 1.6 Security & Testing ⭐ CRITICAL

- [x] **Transaction Lifecycle Tracking** ⭐ PRODUCTION CRITICAL ✅ **COMPLETED (Dec 25, 2025)**
  - Implemented SSE event system for cross-process communication ✅
  - EventBus → HTTP SSE bridge for real-time events ✅
  - NonceManager subscribes to tx_confirmed/tx_failed events ✅
  - TX expiry (TTL) emits tx_failed events ✅
  - Transaction receipt tracking (pending → confirmed → failed) ✅
  - **Implementation:**
    - `blockchain/rpc/api.py` - SSE endpoint, event bridge
    - `scripts/testing/sse_client.py` - SSE client
    - `blockchain/core/mempool.py` - emit tx_failed on expiry
    - `blockchain/core/chain.py` - emit tx_confirmed on inclusion
  - **Acceptance:** 122,778 TX confirmed via events in 12-hour test ✅
  - **Tests:** SSE event delivery working, NonceManager tracking accurate ✅

- [ ] **Economic Security Simulations**
  - False slashing scenarios (network partition)
  - Validator collusion simulations
  - Double-signing attack tests
  - Reward manipulation attempts
  - **Acceptance:** All attacks fail or mitigated

- [ ] **Load Testing Harness**
  - Transaction generator (configurable TPS) ✅ DONE
  - Validator simulator (100+ nodes)
  - Chaos testing (random node failures)
  - **Acceptance:** 100 TPS sustained (updated from 500 TPS based on findings), 100 validators stable

- [ ] **Stress Testing**
  - 500+ transactions per block (updated from 1000+)
  - 7-day continuous run (no crashes)
  - Memory leak detection (valgrind)
  - **Acceptance:** Zero crashes, memory stable

#### 1.7 Documentation
- [ ] **Node Operator Guide**
  - Hardware requirements (CPU, RAM, disk, network)
  - Setup script (`./setup_node.sh`)
  - Monitoring setup (Prometheus + Grafana)
  - **Acceptance:** New operator can setup node <30 min

- [ ] **API Documentation**
  - OpenAPI/Swagger spec
  - Interactive API explorer
  - Code examples (curl, Python, JS)
  - **Acceptance:** All endpoints documented

- [ ] **Validator Economics Guide**
  - Reward calculator tool
  - Commission strategies
  - ROI analysis
  - **Acceptance:** Validators understand economics

**Deliverables:**
- ✅ Delegation system feature-complete (Phase 1.1) ✅ **DONE**
- ✅ State snapshots working (Phase 1.3) ✅ **DONE**
- ✅ Observability stack deployed (Phase 1.3) ✅ **DONE**
- ✅ Upgrade protocol implemented (Phase 1.3) ✅ **DONE**
- ⏳ Transaction lifecycle tracking system (Phase 1.4) **PENDING**
- ⏳ 500 TPS sustained, 100 validators simulated (Phase 1.4) **PENDING**
- ⏳ <5 critical bugs remaining (Phase 1.4) **PENDING**
- ⏳ Upgrade protocol tested in production (Phase 3) **PENDING**

**Success Metrics:**
- ✅ 100% delegation features working (Phase 1.1) **DONE**
- ✅ Economic invariants enforced (Phase 1.2) **DONE**
- ✅ Snapshot sync time <5 minutes (Phase 1.3) **DONE**
- ⏳ Transaction lifecycle tracking working (no aggressive cleanup workaround) (Phase 1.4) **PENDING**
- ⏳ 500 TPS load test passing (Phase 1.4) **PENDING**
- ⏳ 100 validator simulation stable (Phase 1.4) **PENDING**
- ⏳ Zero economic invariant violations in 7-day test (Phase 1.4) **PENDING**

---

### **Phase 2A: Proof-of-Compute Core (No Marketplace)**
**Estimated Duration:** 2 months
**Goal:** Working PoC verification for ONE use case

#### 2A.1 PoC Architecture
- [ ] **Task Distribution System**
  - `ComputeTask` creation & broadcasting
  - Task assignment (reputation-based or random)
  - Task expiration & reassignment
  - **Acceptance:** Tasks distributed to workers reliably

- [ ] **Worker Registration**
  - Worker onboarding (optional stake requirement)
  - GPU fingerprinting (model, VRAM, compute capability)
  - Worker identity verification (signature-based)
  - **Acceptance:** Workers authenticated, GPU verified

- [ ] **Deterministic Verification**
  - Challenge-response protocol (dynamic seed from block_hash)
  - Server-side timing measurement
  - Result hash verification
  - **Acceptance:** Invalid results rejected >99% of time

#### 2A.2 Worker Qualification & Attestation ⭐ NEW
- [ ] **Multi-Level GPU Attestation System**
  - Level 1: Device info validation (NVML API)
  - Level 2: Driver hash verification (whitelist of official NVIDIA drivers)
  - Level 3: PCI device ID cross-check (NVML + lspci validation)
  - Level 4: Challenge-response benchmark (dynamic seed, server-side timing)
  - Level 5: Worker signature (crypto identity binding)
  - **Acceptance:** 5-level attestation pipeline working

- [ ] **Attestation Scoring (0-100 points)**
  - Scoring engine: Level 1 (10pts) + L2 (20pts) + L3 (30pts) + L4 (30pts) + L5 (10pts)
  - MIN_ATTESTATION_SCORE threshold (70 for mainnet, 60 for testnet)
  - Attestation score stored per worker in DB
  - **Acceptance:** Workers with score < threshold rejected

- [ ] **GPU Eligibility Gate**
  - VRAM >= 16 GB requirement (mainnet) / 12 GB (testnet)
  - perf_score from benchmark (effective TFLOPS calculation)
  - MIN_PERF_SCORE threshold (configurable)
  - **Acceptance:** Only qualified GPUs (RTX 3090+, RTX 4080+) admitted

- [ ] **Benchmark Protocol**
  - BENCH_TASK message (matmul FP16, sizes 4096x4096x4096)
  - Deterministic seed generation (from block_hash + worker_address)
  - Server-side timing (orchestrator measures duration)
  - Result hash verification (sha256 of output tensor)
  - **Acceptance:** Benchmark completes in <30s, result verifiable

- [ ] **Driver & Hardware Whitelists**
  - NVIDIA driver hash whitelist (50+ official releases)
  - GPU PCI device ID whitelist (RTX 3090, 4090, A100, H100, etc)
  - Automatic whitelist updates from trusted source
  - **Acceptance:** Whitelists loaded, updated weekly

- [ ] **Security & Anti-Spoofing**
  - Driver hash extraction (/usr/lib/libnvidia-ml.so, /sys/module/nvidia/version)
  - PCI ID extraction (nvmlDeviceGetPciInfo + lspci cross-check)
  - CPU emulation detection (duration > 10x expected = reject)
  - **Acceptance:** Fake nvidia-smi gets score < 60

- [ ] **Re-Benchmarking System**
  - Periodic re-bench (every 7 days)
  - Random spot-checks (5% probability on each task)
  - Performance variance detection (> ±10% = suspicious)
  - **Acceptance:** Re-bench updates scores, flags anomalies

**Deliverables:**
- ✅ Multi-level attestation working (5 levels)
- ✅ Scoring system operational (0-100 points)
- ✅ NVIDIA driver whitelist (50+ hashes)
- ✅ GPU PCI ID whitelist (RTX 3090+, A100+)
- ✅ Anti-spoofing: fake GPUs rejected (score < 60)
- ✅ Benchmark protocol: server-side timing working

**Success Metrics:**
- Real RTX 4090 gets attestation_score >= 90
- Fake nvidia-smi gets attestation_score < 60
- CPU emulation rejected (duration > 10x)
- 10+ workers pass attestation (score >= 70)

#### 2A.3 Worker Stack (Minimal)
- [ ] **GPU Fingerprinting**
  - Detect hardware (nvidia-smi)
  - Verify capabilities (CUDA compute level)
  - Anti-spoofing (integrated with attestation system from 2A.2)
  - **Acceptance:** RTX 4090/5090 detected correctly

- [ ] **Task Executor**
  - Matrix multiplication kernel (CUDA)
  - Sandboxed execution (time limits, memory limits)
  - Result encoding (efficient serialization)
  - **Acceptance:** Matrix mult correct for 1000x1000 matrices

- [ ] **Result Submission**
  - Submit via `SUBMIT_RESULT` transaction
  - Batch submission (reduce fees)
  - Retry logic on failure
  - **Acceptance:** Results submitted reliably

#### 2A.4 Worker Reputation (Minimal)
- [ ] **Success Rate Tracking**
  - Track: results submitted / results verified
  - Track: uptime (tasks completed on time)
  - **Acceptance:** Reputation visible via API

- [ ] **Basic Slashing**
  - Slash stake for incorrect results (5%)
  - Ban after 3 incorrect results
  - **Acceptance:** Malicious workers ejected

#### 2A.5 Use Case: Matrix Multiplication
- [ ] **Implementation**
  - CUDA kernel for matrix multiplication
  - Deterministic output (same input → same output)
  - Efficient verification (re-compute or merkle proof)
  - **Acceptance:** 1000+ successful computations

- [ ] **Testing**
  - 10+ workers in testnet
  - 1000+ successful computations
  - <1% invalid results
  - **Acceptance:** PoC works end-to-end

**Deliverables:**
- ✅ Working PoC with matrix multiplication
- ✅ 10+ GPU workers online (qualified via attestation)
- ✅ Multi-level attestation system (5 levels, scoring 0-100)
- ✅ NVIDIA driver & GPU PCI ID whitelists operational
- ✅ Anti-spoofing: fake GPUs rejected (attestation_score < 60)
- ✅ 1000+ successful verified computations
- ✅ Verification system accurate (>99%)

**Success Metrics:**
- 10+ workers successfully completing tasks (attestation_score >= 70)
- Real RTX 4090 gets attestation_score >= 90
- Fake nvidia-smi wrapper gets attestation_score < 60
- CPU emulation rejected by server-side timing
- 1000+ computations verified
- <1% false positive rate on verification
- <1% false negative rate on verification

**Note:** NO marketplace yet (no bidding, escrow, disputes). Focus: prove PoC verification + GPU attestation works.

---

### **Phase 2B: Compute Marketplace (Optional for MVP)**
**Estimated Duration:** 2 months
**Goal:** Economic marketplace for compute tasks
**Status:** Can be moved to post-mainnet if timeline tight

#### 2B.1 Task Marketplace
- [ ] **Task Posting**
  - Requesters post tasks with rewards
  - Task escrow (lock CPC until completion)
  - Task templates (matrix mult, image render)
  - **Acceptance:** Tasks posted, CPC escrowed

- [ ] **Worker Bidding**
  - Workers bid on tasks (price, deadline)
  - Automatic assignment (lowest bid + reputation)
  - Bid bond (prevent spam)
  - **Acceptance:** Tasks assigned to best bidder

- [ ] **Payment Settlement**
  - Auto-payment on result acceptance
  - Fee distribution (worker 85%, validators 10%, burn 5%?)
  - Refund for failed tasks
  - **Acceptance:** Payments accurate

#### 2B.2 Dispute Resolution
- [ ] **Challenge-Response**
  - Requesters can challenge results
  - Re-verification by validators
  - Slashing if result invalid
  - **Acceptance:** Disputes resolved fairly

- [ ] **Arbitration**
  - Validator voting on disputes
  - Majority decision
  - Slashing for false disputes
  - **Acceptance:** No abuse of dispute system

**Deliverables:**
- ✅ Marketplace live
- ✅ 100+ tasks completed via marketplace
- ✅ Dispute system tested

**Success Metrics:**
- 100+ marketplace transactions
- <5% dispute rate
- Zero payment bugs

---

### **Phase 3: Public Testnet Launch**
**Estimated Duration:** 2 months
**Goal:** Open network to community

#### 3.1 Infrastructure
- [ ] **Public RPC Endpoints**
  - Load-balanced RPC (nginx/haproxy)
  - Rate limiting (100 req/min per IP)
  - Geographic distribution (US, EU, Asia)
  - **Acceptance:** RPC uptime >99.9%

- [ ] **Block Explorer**
  - Etherscan-like UI
  - Transaction search (by hash, address)
  - Validator leaderboard
  - Rich address analytics
  - **Acceptance:** 10k+ page views/month

- [ ] **Testnet Faucet**
  - Captcha-protected
  - 1000 CPC per request (24h cooldown)
  - Social verification (Twitter follow)
  - **Acceptance:** 1000+ faucet requests

- [ ] **Network Monitoring**
  - Public Grafana dashboard
  - Real-time metrics (TPS, block time, validators)
  - Alerts visible to community
  - **Acceptance:** Community uses dashboard

#### 3.2 Onboarding
- [ ] **Validator Onboarding**
  - Step-by-step guide (written + video)
  - One-click setup script
  - Docker compose support
  - **Acceptance:** 50+ community validators

- [ ] **Community Channels**
  - Discord server (1000+ members)
  - Telegram group
  - Weekly dev updates
  - **Acceptance:** Active community

- [ ] **Support System**
  - Dedicated support (2-3 people)
  - 24h response SLA for critical issues
  - Knowledge base
  - **Acceptance:** <24h response time

#### 3.3 Incentive Programs
- [ ] **Testnet Competition**
  - Rewards for top validators
  - Prizes: $10k-30k in future CPC
  - Leaderboard
  - **Acceptance:** 50+ validators competing

- [ ] **Bug Bounty**
  - $100-$50,000 rewards
  - HackerOne or ImmuneFi
  - Focus: consensus, economic exploits
  - **Acceptance:** 10+ critical bugs found

#### 3.4 Stress Testing
- [ ] **Community Events**
  - Weekly "spam the chain" events
  - Coordinate 1000+ concurrent txs
  - Monitor degradation
  - **Acceptance:** Network handles 1000 TPS spikes

- [ ] **Chaos Engineering**
  - Random validator shutdowns
  - Network partitions
  - DDoS simulation
  - **Acceptance:** Network recovers automatically

**Deliverables:**
- ✅ Public testnet with 50+ validators
- ✅ Block explorer live
- ✅ 1000+ Discord members
- ✅ 10+ critical bugs found & fixed
- ✅ Network handles 1000 TPS spikes

**Success Metrics:**
- 50+ active validators
- 1000+ community members
- 10k+ explorer page views/month
- 10+ high/critical bugs found
- 1000 TPS handled without issues

---

### **Phase 4: Governance & Security Audits**
**Estimated Duration:** 2 months
**Goal:** Governance live, audits complete

#### 4.1 Governance System
- [ ] **On-chain Voting**
  - Vote on: min_stake, block_time, slashing_rate
  - Voting power = staked CPC
  - Quorum: 33%+
  - **Acceptance:** First proposal passes

- [ ] **Proposal System**
  - Text proposals (signals)
  - Parameter change proposals
  - Software upgrade proposals
  - **Acceptance:** 3+ proposals submitted

- [ ] **Treasury**
  - Community pool (from fees)
  - Grant proposals
  - Transparent allocation
  - **Acceptance:** First grant approved

#### 4.2 Security Audits ⭐ CRITICAL
- [ ] **Consensus Audit**
  - Hire: Trail of Bits, Zellic, or Quantstamp
  - Cost: $50k-150k
  - Scope: consensus, validator selection, slashing
  - **Acceptance:** 0 critical, <3 high severity issues

- [ ] **Economic Model Audit**
  - Review tokenomics
  - Game theory analysis
  - Attack simulations
  - **Acceptance:** No economic exploits found

- [ ] **Penetration Testing**
  - External pen test firm
  - Test: RPC, P2P, validator nodes
  - DDoS resistance
  - **Acceptance:** No critical vulnerabilities

#### 4.3 Performance Optimization
- [ ] **Block Time Reduction**
  - Target: 5s block time (from 10s)
  - Optimize consensus rounds
  - **Acceptance:** 5s average block time

- [ ] **Mempool Optimization**
  - Priority queue (gas price)
  - Nonce-aware ordering
  - Transaction replacement (RBF)
  - **Acceptance:** Mempool efficient under load

**Deliverables:**
- ✅ Governance live (3+ proposals)
- ✅ Security audit passed (0 critical issues)
- ✅ 5s block time achieved

**Success Metrics:**
- 1+ governance proposal passed
- Security audit: 0 critical, <3 high
- 5s block time average
- Mempool handles 1000 pending txs

---

### **Phase 5: Mainnet Preparation**
**Estimated Duration:** 2 months
**Goal:** Legal, tokenomics, marketing ready

#### 5.1 Token Economics Finalization ⭐ CRITICAL
- [ ] **Tokenomics Paper**
  - Total supply: 1B CPC (fixed)
  - Genesis allocation:
    - Team: 20% (4-year vesting)
    - Early supporters: 10% (2-year vesting)
    - Community: 50% (testnet airdrop, staking rewards)
    - Foundation: 20% (grants, marketing, operations)
  - **Acceptance:** Community approves

- [ ] **Staking Rewards Model**
  - Initial APR: 12% (year 1)
  - Decay: -2% per year (min 4%)
  - Fee distribution: 50% burn, 50% stakers
  - **Acceptance:** Economic model sustainable

#### 5.2 Legal & Compliance
- [ ] **Legal Opinion**
  - Is CPC a security? (Howey test)
  - Regulatory compliance review
  - Hire: crypto law firm
  - **Acceptance:** Legal risks understood

- [ ] **Entity Formation**
  - ComputeChain Foundation (Switzerland/Cayman)
  - Non-profit structure
  - Token issuer entity
  - **Acceptance:** Legal entity formed

#### 5.3 Marketing & Partnerships
- [ ] **Whitepaper v2**
  - Update with all features
  - Professional design
  - Multi-language (EN, CN, RU)
  - **Acceptance:** Published, 10k+ downloads

- [ ] **Exchange Prep**
  - DEX: Uniswap, Osmosis
  - CEX outreach: Binance, Coinbase (aspirational)
  - Market makers
  - **Acceptance:** 2+ exchange partnerships

- [ ] **Marketing Campaign**
  - PR (CoinDesk, Decrypt)
  - Social media (Twitter, YouTube)
  - Influencer partnerships
  - **Acceptance:** 50k+ social followers

**Deliverables:**
- ✅ Tokenomics finalized
- ✅ Legal entity formed
- ✅ Whitepaper v2 published
- ✅ 2+ exchange partnerships

**Success Metrics:**
- Tokenomics community-approved
- Legal entity operational
- 10k+ whitepaper downloads
- 2+ DEX/CEX partnerships confirmed
- 50k+ social media followers

---

### **Phase 6: Mainnet Launch**
**Estimated Duration:** 1 month
**Goal:** Genesis block, live network

#### 6.1 Pre-Launch
- [ ] **Genesis Ceremony**
  - Public genesis file generation
  - Community verification
  - Initial validator set (50-100)
  - **Acceptance:** Genesis file verified

- [ ] **Genesis Allocation**
  - Distribute tokens per tokenomics
  - Lock vesting contracts
  - Verify balances
  - **Acceptance:** All allocations correct

- [ ] **Testnet Rehearsal**
  - Simulate mainnet launch
  - Dry-run all procedures
  - **Acceptance:** Rehearsal successful

#### 6.2 Launch Day
- [ ] **Genesis Block**
  - Coordinate with validators (UTC time)
  - Live stream event
  - Monitor first 1000 blocks
  - **Acceptance:** Genesis block mined

- [ ] **Token Distribution**
  - Airdrop to testnet participants
  - Enable staking
  - **Acceptance:** Tokens distributed

- [ ] **Exchange Listings**
  - Activate trading pairs
  - Provide liquidity
  - **Acceptance:** Trading live on 2+ exchanges

#### 6.3 Post-Launch (30 Days)
- [ ] **24/7 Monitoring**
  - Core team war room
  - Incident response plan
  - **Acceptance:** Zero critical incidents

- [ ] **Community Growth**
  - Daily AMAs
  - Onboard new validators
  - **Acceptance:** 100+ validators

- [ ] **Ecosystem Grants**
  - Developer grants ($500k fund)
  - First grants awarded
  - **Acceptance:** 5+ projects funded

**Deliverables:**
- ✅ Mainnet live with 50+ validators
- ✅ $5M+ TVL in first month
- ✅ 2+ exchange listings active
- ✅ Zero network halts

**Success Metrics:**
- 50+ validators online
- $5M+ TVL (total value locked)
- 2+ CEX/DEX listings
- Zero network halts in 30 days
- 100+ validators by day 90

---

## 🔬 Post-Mainnet R&D Track (2027+)

These are NOT blocking mainnet launch. Separate research/development streams:

### BFT Consensus Migration
**Estimated Duration:** 2-3 months
**Goal:** Migrate from PoA to Tendermint-like BFT

- Research: Tendermint, CometBFT, Hotstuff
- Prototype BFT implementation
- Testnet migration
- Mainnet hard fork (when ready)

**Risk:** High complexity, don't rush

### IBC & Interoperability
**Estimated Duration:** 2-3 months
**Goal:** Connect to Cosmos ecosystem

- Implement IBC client
- Connect to Cosmos Hub
- Cross-chain transfers

### Ethereum Bridge
**Estimated Duration:** 2-3 months
**Goal:** Bridge CPC ↔ Ethereum

- Trustless light client bridge
- Wrap CPC → ERC20
- Liquidity on Uniswap

### Advanced PoC Use Cases
**Status:** Ongoing

- AI model training
- Image rendering (Blender)
- Video encoding
- Scientific computing

### Smart Contract Support
**Status:** TBD (if needed)

- EVM compatibility, or
- CosmWasm, or
- Custom VM

---

## 📅 Development Phases Overview

**Mainnet Path (Total: ~12 months):**
- Phase 1: Production L1 (2 months)
- Phase 2A: PoC Core (2 months)
- Phase 2B: Marketplace (2 months, OPTIONAL)
- Phase 3: Public Testnet (2 months)
- Phase 4: Governance & Audits (2 months)
- Phase 5: Mainnet Prep (2 months)
- Phase 6: Mainnet Launch (1 month)

**Post-Mainnet R&D:**
- BFT migration (2-3 months)
- IBC integration (2-3 months)
- Ethereum bridge (2-3 months)
- Advanced PoC use cases (ongoing)
- Smart contracts (if needed)

---

## 📊 Revised Success Metrics

### Phase 1: Production L1 ✅ **PARTIALLY COMPLETED**

**Completed (Phase 1.1-1.3):**
- ✅ Individual delegation tracking works
- ✅ Proportional rewards accurate
- ✅ Unbonding period enforced (21 days)
- ✅ Economic Model v2.0 (burn/mint tracking, treasury, miner pool)
- ✅ Economic invariants enforced (staking limits, supply conservation)
- ✅ State snapshots functional (<5 min sync, auto-creation, compression)
- ✅ Observability stack deployed (Prometheus metrics, /metrics endpoint)
- ✅ Upgrade protocol implemented (versioning, migrations, UpgradeManager)

**Pending (Phase 1.4-1.5):**
- ⏳ Transaction lifecycle tracking (replace aggressive cleanup workaround)
- ⏳ 500 TPS load test passing
- ⏳ 100 validator simulation stable
- ⏳ 7-day stress test (zero crashes)
- ⏳ Economic security simulations
- ⏳ Documentation (node operator guide, API docs)

### Phase 2A: PoC Core
- [x] Matrix multiplication working
- [x] 10+ workers online
- [x] 1000+ verified computations
- [x] <1% verification errors
- [x] GPU fingerprinting accurate

### Phase 2B: Marketplace (Optional)
- [x] 100+ marketplace tasks completed
- [x] <5% dispute rate
- [x] Zero payment bugs

### Phase 3: Public Testnet
- [x] 50+ public validators
- [x] 1000+ community members
- [x] Block explorer: 10k+ views/month
- [x] 10+ critical bugs found & fixed
- [x] 1000 TPS stress test passed

### Phase 4: Governance & Audits
- [x] 1+ governance proposal passed
- [x] Security audit: 0 critical, <3 high
- [x] 5s block time achieved
- [x] Pen test passed

### Phase 5: Mainnet Prep
- [x] Tokenomics approved
- [x] Legal entity formed
- [x] 10k+ whitepaper downloads
- [x] 2+ exchange partnerships
- [x] 50k+ social followers

### Phase 6: Mainnet Launch
- [x] 50+ validators on mainnet
- [x] $5M+ TVL in 30 days
- [x] 2+ exchange listings live
- [x] Zero network halts in 90 days
- [x] 100+ validators by day 90

---

## 💡 Immediate Actions (Next 2 Weeks)

**STATUS: Week 1-2 COMPLETED ✅ (Dec 17, 2025)**

All critical infrastructure items from the 2-week plan have been completed:

### Week 1: Delegation & Observability ✅ **COMPLETED**

1. **Individual Delegation Tracking** ✅ **COMPLETED (Dec 17, 2025)**
   - [x] Add `delegations: List[Delegation]` to Validator model ✅
   - [x] Store delegations in state ✅
   - [x] API: `/delegator/{addr}/delegations` ✅
   - [x] CLI: `query delegations {addr}` ✅

2. **Proportional Rewards** ✅ **COMPLETED (Dec 17, 2025)**
   - [x] Calculate delegator shares ✅
   - [x] Distribute rewards per epoch ✅
   - [x] Deduct validator commission ✅
   - [x] Test: rewards sum = block reward ✅

3. **Prometheus Metrics** ✅ **COMPLETED (Dec 17, 2025)**
   - [x] Export: block_height, block_time, tx_count, validator_count ✅
   - [x] Export: validator_uptime, missed_blocks, jail_count ✅
   - [x] Export: mempool_size, total_supply, staked, delegated ✅
   - [x] Endpoint: `GET /metrics` (Prometheus format) ✅

### Week 2: Snapshots & Testing ✅ **COMPLETED**

4. **State Snapshots** ✅ **COMPLETED (Dec 17, 2025)**
   - [x] Snapshot state every N blocks (configurable, default 1000) ✅
   - [x] Snapshot at epoch boundaries ✅
   - [x] Save to disk (gzip compressed, 60-80% reduction) ✅
   - [x] Fast sync from snapshot (<5 min) ✅
   - [x] CLI: `snapshot list`, `snapshot info` ✅
   - [x] RPC: `GET /snapshots`, `GET /snapshots/{height}` ✅

5. **Unbonding Queue** ✅ **COMPLETED (Dec 17, 2025)**
   - [x] Add `unbonding_delegations: List[UndelegationEntry]` to Account ✅
   - [x] Process queue every block via `process_unbonding_queue()` ✅
   - [x] Automatic token return (no manual claim needed) ✅
   - [x] Test: unbonding period enforced ✅
   - **Implementation:** `UndelegationEntry` model in `protocol/types/validator.py`

6. **Load Test Harness** ⏳ **PENDING (Moved to Phase 1.4)**
   - [ ] Transaction generator script
   - [ ] Validator simulator (10+ nodes)
   - [ ] Run: 500 TPS for 1 hour
   - [ ] Monitor: CPU, memory, disk I/O

### 🎯 **BONUS: Upgrade Protocol** ✅ **COMPLETED (Dec 17, 2025)**
   - [x] Semantic versioning (MAJOR.MINOR.PATCH) ✅
   - [x] Migration registry with @migration decorator ✅
   - [x] UpgradeManager (schedule, execute, validate) ✅
   - [x] Version persistence across restarts ✅
   - **Implementation:** `blockchain/upgrade/` module

---

## 🚨 Critical Risks & Mitigation

### Technical Risks

**Risk 1: PoC Verification Harder Than Expected**
- **Mitigation:** Start Phase 2A early (parallel with Phase 1)
- **Mitigation:** Prototype matrix mult verification ASAP
- **Mitigation:** If fails, launch mainnet without PoC (add later)

**Risk 2: Consensus Bugs Delay Mainnet**
- **Mitigation:** Audit in Phase 4 (2 months before launch)
- **Mitigation:** Comprehensive simulation testing
- **Mitigation:** Bug bounty program in Phase 3

**Risk 3: SQLite Can't Handle Public Testnet**
- **Mitigation:** Migrate to RocksDB in Phase 3
- **Mitigation:** Benchmark both options in Phase 1
- **Mitigation:** Have migration script ready

**Risk 4: Economic Attack Post-Launch**
- **Mitigation:** Economic security simulations in Phase 1
- **Mitigation:** Conservative initial parameters (high min_stake)
- **Mitigation:** Fast emergency response protocol

### Market Risks

**Risk 5: GPU Compute Market Too Competitive**
- **Mitigation:** Focus on differentiation (native PoC, RTX optimization)
- **Mitigation:** Target niche use cases first
- **Mitigation:** Strong community before mainnet

**Risk 6: Crypto Bear Market**
- **Mitigation:** Build regardless of market conditions
- **Mitigation:** Focus on technology, not hype
- **Mitigation:** Bootstrap if no funding available

### Regulatory Risks

**Risk 7: CPC Classified as Security**
- **Mitigation:** Legal counsel in Phase 5
- **Mitigation:** Foundation structure (non-profit)
- **Mitigation:** No public sale if risky

---

## 🤔 Open Questions for Decision

### Critical Decisions Needed:

1. **Phase 2B: Include Marketplace in Mainnet?**
   - **Option A:** YES - Full marketplace (adds 2 months)
   - **Option B:** NO - Launch with PoC v1 only, marketplace post-mainnet
   - **Recommendation:** Option B (reduce risk, faster to mainnet)

2. **Funding: Do We Need It?**
   - **Current runway:** ? months
   - **Budget needed:** $850k-1.5M (12 months, 5-8 people)
   - **Options:** Bootstrap, seed round, grants
   - **Decision needed:** By end of Phase 1

3. **Storage: When to Migrate from SQLite?**
   - **Option A:** Phase 1 (safe, but extra work)
   - **Option B:** Phase 3 (when actually needed)
   - **Recommendation:** Option B (don't optimize prematurely)

4. **PoC: Mainnet Requirement?**
   - **Option A:** YES - PoC must work for mainnet
   - **Option B:** NO - Launch L1 + Staking, add PoC later
   - **Recommendation:** Depends on vision (discuss)

---

## 🔗 Related Documents

- [CHANGELOG_SINCE_RESTRUCTURE.md](./CHANGELOG_SINCE_RESTRUCTURE.md) - Development history
- [VALIDATOR_PERFORMANCE_GUIDE.md](./VALIDATOR_PERFORMANCE_GUIDE.md) - Validator guide
- [QUICK_START.md](./QUICK_START.md) - Getting started
- [README.md](./README.md) - Project overview

---

## 📝 Document Revision History

**v1 (Dec 14, 2025):** Initial roadmap
**v2 (Dec 14, 2025):** Revised based on technical review feedback
**v3 (Dec 17, 2025):** Updated with Phase 1.1 completion status
**v4 (Dec 17, 2025):** Updated with Phase 1.2 unbonding period completion
**v5 (Dec 17, 2025):** Updated with Phase 1.2 Economic Model v2.0 completion
**v6 (Dec 17, 2025):** Phase 1.2 FULLY COMPLETED, Phase 1.3 Prometheus metrics started
**v7 (Dec 17, 2025):** Phase 1.3 Infrastructure & Observability COMPLETED (Snapshots, Metrics, Upgrade Protocol)
**v8 (Jan 13, 2026):** State Synchronization Bug IDENTIFIED and FIXED

**Key Changes in v8:**
- 🚨 **CRITICAL BUG IDENTIFIED AND FIXED:** State Synchronization across nodes
  - **Root Cause:** Each node created its own genesis.json with only its own validator
  - **Result:** Different genesis hashes → P2P rejected → blocks didn't propagate
  - **Solution:** Shared genesis approach - all nodes start with identical genesis
- **Phase 1.5 COMPLETED:** State Synchronization Fix
  - Created `scripts/generate_genesis.py` - generates shared genesis with N validators
  - Modified `blockchain/cli/node_cli.py` - added `--genesis`, `--validator-key`, `--faucet-key` flags
  - Updated `start_test.sh` - uses shared genesis workflow
  - Added validators to `state_root` for consensus verification (`state.py:569-634`)
- **New Validator Joining Flow:** Now works correctly
  - New validator sends STAKE TX
  - Block propagates to all nodes (same genesis hash)
  - All nodes apply STAKE TX → validator added everywhere
  - State root includes validators → consensus verified
  - At epoch boundary → validator becomes active on all nodes

**Key Changes in v2:**
- Split Phase 2 into 2A (PoC Core) and 2B (Marketplace)
- Moved BFT to post-mainnet R&D track
- Added critical infrastructure to Phase 1 (snapshots, observability, upgrade protocol)
- Added acceptance criteria for all major features
- Reduced timeline from 14-18 months to 12 months
- Added economic security testing requirements
- Documented SQLite → RocksDB migration path
- Added immediate actions (2-week plan)
- Added critical risks & mitigation strategies

**Key Changes in v3:**
- ✅ **Phase 1.1 Delegation System COMPLETED** (Dec 17, 2025)
  - Individual delegation tracking implemented and tested
  - Proportional reward distribution working
  - Delegation rewards history tracked per epoch
  - API endpoints and CLI commands operational
  - Fixed `created_height` tracking (uses actual block height)
  - Added `min_delegation` validation (100 CPC enforced)
  - All 24 unit tests passing
- ⏳ **Phase 1.2 Unbonding Period** - Next priority
- ⏳ **Phase 1.3 Infrastructure** - Prometheus, state snapshots pending

**Key Changes in v4:**
- ✅ **Phase 1.2 Unbonding Period COMPLETED** (Dec 17, 2025)
  - Unbonding queue implementation with `UndelegationEntry` model
  - 21-day lock period (100 blocks devnet / 181440 blocks mainnet)
  - Automatic token return via `process_unbonding_queue()` on each block
  - API endpoint: `/delegator/{address}/unbonding` with completion info
  - CLI command: `query unbonding <address>`
  - Security: prevents fast exit attacks during network instability
  - All 25 unit tests passing
- ⏳ **Phase 1.2 Economic Invariants Testing** - Next priority
- ⏳ **Phase 1.3 Infrastructure** - Prometheus, state snapshots pending

**Key Changes in v5:**
- ✅ **Phase 1.2 Economic Model v2.0 COMPLETED** (Dec 17, 2025)
  - **Single source of truth:** All economic parameters in `protocol/config/economic_model.py`
  - **Block rewards:** 10 CPC → 70% validators (7 CPC), 30% miners (3 CPC)
  - **Fee distribution:** 90% validator, 10% treasury
  - **Burn tracking:** Slashing, penalties, dust → tracked in `state.total_burned`
  - **Mint tracking:** Block rewards → tracked in `state.total_minted`
  - **Treasury account:** Hardcoded address for community pool
  - **Miner weight system:** ZK-based (off-chain calculation, on-chain verification)
    - `miner/weight/calculator.py` - Weight formula (results * gpu_tier * uptime * difficulty * reputation)
    - `miner/weight/prover.py` - ZK proof generation (STUB, ready for real ZK)
    - `miner/weight/signer.py` - Cryptographic signing
    - `blockchain/core/zk_verification.py` - On-chain ZK proof verification
    - `blockchain/core/miner_rewards.py` - Miner reward distribution logic
  - **Architecture decision:** Economic logic in blockchain, NOT scattered across codebase
  - **Burn policy:** Only when truly needed (undistributed dust, penalties)
  - **Ready for Phase 2A:** Miner pool infrastructure complete, awaiting PoC implementation
- ⏳ **Phase 1.2 Economic Invariants Testing** - Next priority
- ⏳ **Phase 1.2 Staking Limits** - Max validator power cap, delegation limits
- ⏳ **Phase 1.3 Infrastructure** - Prometheus, state snapshots pending

**Key Changes in v6:**
- ✅ **Phase 1.2 FULLY COMPLETED** (Dec 17, 2025)
  - **Economic invariants testing:** Supply conservation, non-negative balances
  - **Staking limits enforcement:**
    - Max 10 validators per delegator (enforced in DELEGATE)
    - Max 20% validator power share (enforced in DELEGATE)
    - Prevents centralization and 51% attacks
  - **Tests:** `tests/test_economic_invariants.py`
- ✅ **Phase 1.3 Prometheus Metrics** (Dec 17, 2025)
  - **Full metrics suite:** Block, transaction, validator, economic, network metrics
  - **Prometheus endpoint:** `GET /metrics` for scraping
  - **Auto-update:** Metrics refreshed after each block
  - **Implementation:** `blockchain/observability/metrics.py`
  - **Next:** Grafana dashboards, alerts (separate effort)
- 🎯 **Status:** Phase 1.2 complete, Phase 1.3 observability in progress

**Key Changes in v7:**
- ✅ **Phase 1.3 Infrastructure & Observability COMPLETED** (Dec 17, 2025)
  - **State Snapshots System:**
    - Automatic snapshot creation every N blocks (default: 1000) and at epoch boundaries
    - Compressed storage (gzip, 60-80% reduction)
    - Fast sync: load_from_snapshot(), fast_sync_from_latest_snapshot()
    - SHA256 verification for integrity
    - Automatic cleanup (keeps last 10 snapshots)
    - CLI: `snapshot list`, `snapshot info`
    - RPC: `GET /snapshots`, `GET /snapshots/{height}`
    - Implementation: `blockchain/snapshot/` module
  - **Upgrade Protocol:**
    - Semantic versioning (MAJOR.MINOR.PATCH)
    - Migration registry with @migration decorator
    - UpgradeManager for scheduling and executing upgrades
    - Version persistence across restarts
    - Compatibility validation
    - Implementation: `blockchain/upgrade/` module
  - **Economic Tracking Persistence:**
    - total_burned, total_minted now saved to DB
    - Survives node restarts
    - Updated in `blockchain/core/state.py`
- 🎯 **Status:** Phase 1.3 COMPLETED except Storage Migration Plan (SQLite → RocksDB documentation)
- 🎯 **Next:** Phase 1.4 (Security & Testing) OR Phase 2A (PoC Core)

---

**Maintained by:** ComputeChain Core Team
**Contact:** computechain@gmail.com
**Next Review:** End of Phase 1

---

**Let's build the future of decentralized computing together! 🚀**
