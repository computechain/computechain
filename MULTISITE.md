# Three-location devnet: direct WAN P2P

Status: a separate seven-node devnet is running on three real hosts (2026-10-08).
Full sync, signed transfer and controlled validator restart/quorum checks passed.
The original six native peers form a mesh; the new full-a3 connects only to the
two remote validators. Cross-location sockets use public WAN addresses, not private
tunnels. Signed accelerated WAN state sync passed; physical outage tests remain
pending. **This is not a production-ready network**.
The original local stand is unchanged, not migrated.
The current devnet economics/trust window remain test-only. No real funds.

Grafana now observes all seven nodes at
http://192.168.0.100:3000/d/computechain-fleet (same login/password/volumes).
The local read-only observer polls remote pinned TLS readers, not public native
RPC or SSH. All-node status/power/common block/AppHash; native metrics/ABCI only
on the five local nodes. TPS/supply count one replica. Prometheus alerts are visible
locally; no external notification channel. Details: `../monitoring/README.md`.
Website/explorer now observe the new chain via full-a1, with pinned node ID/genesis
and a separate index at `<old-stand>/explorer/indexes/CHAIN/GENESIS_SHA256/`.
The old local-chain index is preserved, never merged/reset. One synchronized full
node is sufficient for observed chain state; no independent light proof is claimed.
Explicit switch: `scripts/web_services.py explorer up --observer-home APPROVED_FULL_HOME`.
Ordinary explorer-up preserves source selection; native RPC and keys remain private.

## Inventory and failure domains

`deploy/multisite.example.json` contains **example addresses, not discovered hosts**.
Copy it outside Git and fill the real addresses before generating registrations.
The intended locations are 192.168.0.0/24, 192.168.1.0/24 and 192.168.2.0/24.
Initial deployment used WireGuard/AmneziaWG; live cross-location P2P now uses WAN.
Tunnels remain for administration/private read RPC. This tool does not
edit tunnels, routers, host firewall, accounts, systemd or SSH configuration.
`scripts/install_multisite.py` is a SEPARATE, explicitly invoked root installer
for the approved home-contained profile; it installs only scoped accounts/units/ACL.

Initial layout: four validators, 2+1+1 across locations, and two full nodes.
`machine` identifies the physical failure domain: VMs on one box use the SAME
machine name even if their IPs differ. `witness` approves read-only checkpoint
sources; at least two hosts/locations are required. `readers` explicitly allows
observer/Prometheus addresses. Credentials never belong in this inventory.

From the core checkout:

```bash
../.tools/blockchain-venv/bin/python scripts/multisite.py plan --inventory deploy/multisite.example.json
```

`./multisite.sh` is the same preparation entrypoint using the local Python environment.

The report calculates loss of each IP endpoint, physical machine and location
using `remaining_power * 3 > total_power * 2`. Losing the two-validator location
halts finalization; different external IPs alone do not ensure failure tolerance.
This is genesis arithmetic, not live staking power or proof of independent routes.

## Current installation and operator commands

Chain: `cpc-multisite-devnet-1`, base port27600. Local host192.168.0.100 runs
validator-a1/a2 and full-a1/a2/a3. pc205@192.168.1.205 runs validator-b1; root@192.168.2.3
runs validator-c1. All four validators start with10000 power each. No remote load,
frontend, monitoring stack or compiler was installed. Docker was already present.

Each host keeps source, local Python wheels, binary, keys and DBs in
`~/computechain-node/`. Engine/app have separate locked service accounts and0700
homes; systemd mounts only their own data home plus read-only runtime. Only small
root-owned gateway/firewall files live in `/etc/computechain/CHAIN/NODE/` and scoped
units in `/etc/systemd/system/`. Docker NEVER reads node-writable Compose.

Run on the desired host (sudo is optional when already root):

```bash
sudo ~/computechain-node/node.sh status
sudo ~/computechain-node/node.sh logs
sudo ~/computechain-node/node.sh down
sudo ~/computechain-node/node.sh up
```

On the local five-node host, append a node name to select only one, for example
`sudo ~/computechain-node/node.sh down full-a2`. No name selects only this host's
installed fleet nodes, NEVER the old local stand. `down` preserves keys/data and
does not remove firewall or disable boot activation. `up` requires host doctor.
Reboot activation is enabled; host reboot itself has not been exercised.

Each engine/app/read-adapter shares a30%-of-one-core CPU cap and448MiB RAM ceiling;
gateway adds at most10%-of-one-core and64MiB. These are upper bounds, not reserved
memory. After TLS bootstrap the short idle sample measured about133–149MiB per
remote slice plus2MiB gateway and
under2% of one core, not capacity/load evidence. Blocks use a2s commit wait.

Public TCP forwards (external port = internal port):

| WAN | Internal host | P2P ports |
|---|---|---|
| 78.29.35.87 | 192.168.0.100 | 27600, 27610 |
| 178.72.89.199 | 192.168.1.205 | 27620 |
| 93.171.44.155 | 192.168.2.3 | 27630 |

Separate TLS read-only services are forwarded on27626 at site-b and27636 at site-c.
No UDP, native RPC/ABCI, private gateway or monitoring forwards. Full-a1/a2/a3 initiate
outbound WAN connections and need no public port. Co-hosted nodes use local sockets;
cross-location peers use `node_id@WAN:port`, with PEX disabled and no private fallback.
P2P ACL permits only these three public sources plus the node's own host address;
private read-gateway ACL is unchanged. Existing UI/monitoring still show the OLD chain.

Site-b's HTTP IP checks initially reported31.77.195.224 because of PBR/VPN routing.
Controlled TCP capture proved the actual forwarded WAN178.72.89.199. The operator
excluded pc205 TCP destination27600/27610/27630 and source27620 replies from PBR;
both-direction TCP probes and all native remote peer IPs now match the three WANs.
The old private ingress SNAT remains an administration/read-witness issue, not a
P2P dependency. Never permit the VPN exit or widen a whole subnet to mask it.

`scripts/fleet_network.py` prepares approved network-only bundles from the current
public manifests. `apply` requires old/new manifest SHA, exact stopped node services,
unchanged identity/genesis and trusted root firewall path; it changes only P2P fields,
P2P source set and manifest. The scoped nft table is replaced in one transaction.
Atomic writes retain owner/mode; public-only backup and rollback preserve all keys,
signer state and DBs. Do not use fresh `configure` or reset to update a live node.
Run `plan --bundles CURRENT_PUBLIC_BUNDLES --profile PROFILE_JSON --output NEW_DIR`,
then scoped `node.sh down NODE`, approved `apply`, and `node.sh up NODE`.

Operator inventory/approved bundles/preflight/verification remain outside Git at
`../.runtime/multisite-live/`. Native common commitments, four signatures,1CPC
transfer on all six apps, single remote validator restarts and halt at50% power
were verified. WAN rollout/mesh/transfer/restart evidence is `wan-rollout.json` and
`wan-verification.json`; TCP headers/probes are `wan-tcp-probe-b-direct.json`.
These were PROCESS stops, not actual host/route/location failures.

For a new host-contained bundle, `assemble --home-roots /path/node-roots.json`
accepts an explicit per-node map to `/root/computechain-node` or
`/home/USER/computechain-node`; it is included in the approved manifest. Build the
compact runtime locally with `scripts/build_multisite_runtime.py --wheels WHEELS
--output NEW_OUTPUT`, using `requirements-comet-runtime.txt` for matching Python
wheels. Ubuntu22.04 uses process-local `OPENSSL_CONF=runtime/openssl.cnf` for
[early OpenSSL3 RIPEMD160 compatibility](https://docs.openssl.org/3.0/man7/OSSL_PROVIDER-legacy/);
the system OpenSSL configuration is untouched. `register-identity` can finish an
interrupted NEW init only when there is no signed/history state or registration;
all existing keys are preserved. It is NOT a live identity replacement command.

## Signed accelerated bootstrap (verified over WAN)

TLS-only bootstrap read services run on validator-b1 port27626 and
validator-c1 port27636, with WAN forwarding verified. They do NOT expose native RPC: only validated
status/block/commit/validators/consensus_params/genesis reads, including native
JSON-RPC POST. No broadcast/ABCI/WebSocket/metrics. Source ACL is the three fleet
WANs plus the provider's own host. TLS1.3, four workers, bounded headers/body/reply,
10 requests/s burst20 per allowed IP, and96MiB memory cap; shares the node's existing
CPU/RAM slice. Dedicated cbr-user sees only runtime and its own TLS key, not signers.

Confirmed additional forwards: TCP27626 →192.168.1.205:27626 and TCP27636
→192.168.2.3:27636. pc205 replies from source27626 must bypass PBR/VPN.
Existing validators were not restarted for this bootstrap.

Operator CA private key and separate Ed25519 attestation key stay in
`/root/computechain-node/bootstrap-controller/`; provider TLS keys are created
on their own hosts and never exported. The approved profile pins CA hash,
operator public key, provider leaf fingerprints, node IDs and declared locations.
Bootstrap checks TLS hostname/CA/leaf and both providers' genesis/block identity.
Native Go validates CA/IP and consensus light blocks (not separate leaf pinning).
CA365days/leaf30days need explicit rotation; no automatic renewal implemented.
Source ACL is NOT mutual TLS; the operator remains the initial trust authority.

Checkpoints are signed with a domain-separated Ed25519 signature and keep the
fixed30s devnet trust window. Wrong authority, changed fields, expiry/future time,
weak keys and mismatching witnesses abort. Native start also verifies the signature
and external root-owned trust pin. Even a partially created empty blockstore does
not bypass expiry. Trust files are local to the follower, never system-wide;
native process proxies are disabled. Nothing rewrites existing genesis/history.

NEW full-a3 is running on the current host, outbound P2P only to the two remote
providers. Original six registrations/genesis are unchanged; the extra full node
signs a separate admission inventory, with zero genesis power. It restored snapshot
4515 and caught up in about14s; all seven nodes agreed on block/AppHash and account
balances/nonces/staking. Its restart after checkpoint expiry passed without a new
anchor or replacing keys/data. Boot activation is enabled. Generic `node.sh up`
skips uncompleted bootstrap followers; explicit `up full-a3` still requires doctor.

Core entrypoint `scripts/bootstrap_follower.py` provides create/capture/configure/
complete with explicit profile SHA, CA, home and checkpoint paths. Capture uses the
operator's LOCAL signing key. Configure accepts only a fresh full home, verified
signature and two matching TLS witnesses. Completion requires THIS systemd engine
invocation's `Snapshot restored`, post-snapshot block/AppHash matching both sources,
then disables bootstrap for normal restarts. A full-sync fallback is not success.

Native RPC may trim trailing zeroes from genesis_time: compare this field as exact
integer nanoseconds, while keeping every other field exact and the local genesis
file SHA pinned. Atomic config changes preserve the service UID/GID and0600 mode.
The first launch exposed this ownership bug before native history was created;
it was stopped and corrected. An explicit `configure --resume-uninitialized`
may reuse a stopped, entirely empty app SQLite after authenticated prior-attempt
and empty-table checks; it never deletes/replaces that DB. Native DBs, committed
state, receipts, snapshots, staging data or live writers require manual inspection
and are refused. Never use this option to reset or migrate existing history.

Real WAN restore/restart evidence: `../.runtime/multisite-live/bootstrap/live-verification.json`.
Snapshot4515 and THIS invocation's restore were checked before retiring bootstrap;
full-a3 has only B/C WAN peers. Physical path independence/long soak remain unproven.

Local actual Comet HTTPS restore proof: `../.runtime/bootstrap-tls-native-02/verification.json`
(passed, all owned processes stopped). It is NOT a real WAN restore claim.
Real provider service/profile evidence: `../.runtime/multisite-live/bootstrap/`.
Run isolated local QA with `python -m computechain.scripts.verify_bootstrap_tls
--dir NEW_OUTSIDE_GIT_DIR --base-port UNUSED_BASE` using the core Python environment.

## Two-stage identity/genesis workflow

Linux amd64, the pinned Comet build, Python environment and Docker/Compose are
required. Source/tools under `/opt/computechain-workspace` must be root-owned and
not writable by node service users. The binary SHA256 must match the build metadata
and the approved public bundle; the current builder is Linux amd64-specific.

1. Approve one immutable inventory. On EACH intended node host, run local
   `init-identity` against a NEW engine home. It creates a node transport key,
   consensus key and secp256k1 owner key locally, all private keys mode0600.
   Do not initialize several production identities centrally and ship their keys.
2. Collect only `registration.json` over an authenticated operator channel.
   Both transport and consensus keys sign the public registration, including the
   chain/inventory hash. Signatures prove possession, not operator authorization.
3. The controller approves registrations and runs `assemble` with a PUBLIC faucet
   address it controls. The assembler exports no private keys: one common genesis,
   per-node config/gateway/firewall/service templates and SHA256 manifests.
4. Approve each node's manifest SHA256 through the operator channel. Send only its
   public bundle back to that host and `configure` its existing local identity.
   Configure refuses live DB/signing history, wrong identity, symlinks and damaged
   artifacts. Private keys are neither replaced nor copied.

Commands below use a `validator-a1` example; replace the inventory/home paths:

```bash
../.tools/blockchain-venv/bin/python scripts/multisite.py init-identity --inventory /path/inventory.json --node validator-a1 --home /var/lib/computechain/cpc-multisite-devnet-1/validator-a1
../.tools/blockchain-venv/bin/python scripts/multisite.py assemble --inventory /path/inventory.json --registrations /path/registrations/*.json --output /path/new-public-bundles --faucet-address PUBLIC_CPC_ADDRESS
../.tools/blockchain-venv/bin/python scripts/multisite.py configure --home /var/lib/computechain/cpc-multisite-devnet-1/validator-a1 --bundle /path/new-public-bundles/validator-a1 --manifest-sha256 APPROVED_NODE_MANIFEST_SHA256
```

Genesis contains exactly 1,000,000 test CPC: bonded stake, 1,000 liquid CPC per
genesis owner, and the remainder at the selected faucet address. These allocations
are explicit bootstrap test policy; supply conservation is validated by the app.
Do not change inventory/addresses after signing registrations silently. This is an
initial-fleet builder, not a live key rotation/upgrade/topology migration manager.

## Host installation gates (after access is provided)

- Create separate locked-down users `cpc-NODE` for the engine and `cpa-NODE` for
  application/read-adapter services. Neither belongs to the Docker group.
- Engine home: `/var/lib/computechain/CHAIN/NODE`, mode0700, owned by `cpc-NODE`.
  App state: `/var/lib/computechain-app/CHAIN/NODE`, mode0700, owned by `cpa-NODE`.
  The application cannot access the engine/key home. Both accounts/dirs are
  explicitly installed by the operator; the preparation command does not create them.
- Install the approved service files root-owned into `/etc/systemd/system/`.
  Install `docker-compose.yml` and `rpc-nginx.conf` root-owned, non-user-writable
  into `/etc/computechain/CHAIN/NODE/` (public Nginx config must be readable, mode0644).
  **Root Docker must never execute a Compose file writable by a node user.**
- Review `firewall.nft` against existing rules; it creates only a scoped table and
  never flushes the ruleset. Apply explicitly, not during bundle generation. Native
  P2P and the read gateway permit only approved peers/readers. ABCI/RPC/metrics
  listeners themselves stay loopback. Local host/root trust is still required;
  loopback TCP is not authentication against arbitrary hostile local users.
- `doctor --home ENGINE_HOME` checks artifact/key identity, pinned binary, local
  assigned IP, peer routes and NTP synchronization. It does not prove that a route
  crosses the intended encrypted tunnel. Test MTU, latency, packet loss, observed
  source IPs and loss of the hub/location before accepting the deployment.
- Source addresses must survive tunnel routing for the per-host ACL. If SNAT
  rewrites them, inspect the topology; do not widen ACLs to whole subnets by default.
- Resource caps in service templates are provisional, not capacity measurements.
  Review RAM/CPU/disk and existing workloads on the actual hosts before enabling.

Only after these gates: daemon-reload and start the generated RPC service (it
requires the read adapter, engine and app). Stop preserves keys/data. No reset or
automatic signing-state migration is provided. Partial bootstrap requires inspection.

## Restricted RPC and optional state sync

The private Nginx gateway allows approved source IPs and applies rate/connection
limits. It exposes GET reads, metrics, and **JSON-RPC POST read methods** because
the native [Comet client uses POST](https://github.com/cometbft/cometbft/blob/v0.40.0/rpc/jsonrpc/client/http_json_client.go).
The loopback adapter parses bounded JSON and validates method, parameters and ID;
it translates to REST GET only. Allowed: status, block, commit, validators,
consensus_params, genesis. No batch, broadcast, abci_query, WebSocket or unsafe RPC.
Responses are bounded; redirects/environment proxies are disabled. Public website/
explorer gateways remain unchanged GET/HEAD-only.

Full sync is the default. Before starting a fresh FULL node, optional explicit
checkpoint/state-sync configuration uses approved witnesses in different locations:

```bash
../.tools/blockchain-venv/bin/python scripts/multisite.py checkpoint --home ENGINE_HOME --checkpoint /path/new-anchor.json --witnesses validator-b1 validator-c1
../.tools/blockchain-venv/bin/python scripts/multisite.py bootstrap --home ENGINE_HOME --checkpoint /path/new-anchor.json --witnesses validator-b1 validator-c1
```

Both replies must match approved node IDs, genesis and anchor. Expired anchors
are refused; trust30s is not increased. `bootstrap` only prepares configuration,
**not a claim that restore succeeded**. Confirm this attempt's native Snapshot
restored log and equal block/AppHash at an available post-snapshot height.

## Local verification (no multi-host claim)

```bash
./run_tests.sh tests/test_multisite.py tests/test_rpc_read_gateway.py tests/test_fleet_rpc_gateway.py -q
../.tools/blockchain-venv/bin/python scripts/verify_multisite.py --dir ../.runtime/new-fleet-verification --base-port 31600
```

The native exercise uses NEW scratch identities/genesis, public bundles, signed
transfer, full sync and real Comet state sync through the restricted RPC adapter.
For QA ONLY it replaces planned site addresses with loopback, bypassing production
host preflight. It stops its exact child processes/containers and preserves reports
and data. It does not verify real WireGuard routes, systemd installation or sites.
Do not reuse exercise identities or bundles for the actual deployment.

## Кратко по-русски

Отдельный devnet уже работает на трёх хостах; ключи и данные в ~/computechain-node.
Между локациями P2P теперь работает через Интернет:78.29.35.87,178.72.89.199,
93.171.44.155; не через WG. Для pc205 пользователь добавил WAN-исключения PBR.
31.77.195.224 — VPN-выход, не адрес узла. Проверены full sync, mesh всех6узлов,
перевод и рестарты. Native RPC/ABCI/метрики наружу не открыты. Ключи/genesis/история
сохранены. Ускоренный state sync и физические отказы маршрутов ещё не доказаны.
Адреса `.201/.202` — примеры, заменить до создания identities. `machine` — физическая
машина: её VM не считаются независимыми отказными доменами. Ключи создаются на самом
узле; в общий genesis/пакеты входят только публичные регистрации. Manifest SHA256
нужно согласовать через доверенный канал. Engine/app — разные пользователи и
каталоги; root Docker использует только root-owned конфиги из `/etc`, не файлы узла.
Installer устанавливает только scoped accounts/systemd/ACL после явного вызова;
WG/роутеры/SSH не меняются. RPC POST допускает только
проверенные методы чтения, broadcast/ABCI закрыты. NTP, ресурсы и source IP проверены
на хостах; authenticated state-sync gateway/checkpoints и физические отказы впереди.
