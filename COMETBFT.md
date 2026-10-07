# ComputeChain v3: CometBFT staking devnet

Это первый рабочий этап перехода на CometBFT: собственное Python ABCI-приложение
с подписанными переводами CPC, атомарным состоянием, full/catch-up sync и
проверяемыми снапшотами. Старая Python-нода остаётся отдельным legacy-прототипом.

## Как устроена нода

На каждой ноде два процесса:

1. **CometBFT** соединяется с peers, предлагает блоки, обменивается голосами,
   проверяет commits и хранит сетевую историю/WAL/signing state.
2. **CPC application** проверяет и исполняет транзакции, сохраняет application
   state и возвращает его hash. Доступ CometBFT к приложению — ABCI по gRPC.

Набор валидаторов и voting power управляются ABCI staking: updates с H действуют
в native consensus на H+2. Genesis начинает с четырёх валидаторов. CometBFT
финализирует блок при precommit quorum строго больше 2/3 мощности. Четыре
равных валидатора продолжают при отказе одного; в partition 2+2 обе половины
останавливаются. Python-приложение не пишет собственную замену этим правилам.

GPU workers/compute scoring — будущий прикладной слой: тяжёлую задачу не должны
исполнять все L1 валидаторы. Их работа — согласовать проверяемые данные и состояние.

Источники: [ABCI specification](https://github.com/cometbft/cometbft/blob/v0.40.0/spec/abci/abci%2B%2B_methods.md),
[block sync](https://docs.cosmos.network/cometbft/latest/docs/core/block-sync),
[state sync](https://docs.cosmos.network/cometbft/latest/docs/core/state-sync).

## Зафиксированные компоненты

- Upstream source tag: `v0.40.0`.
- Source commit: `0880b4d378f347ab16e54ec677ff50d803f37d62`.
- ABCI schema: `proto/tendermint/abci/types.proto` из этого commit.
- Local build toolchain: Go `1.26.8` (Linux amd64).
- Python: 3.12; зависимости — `requirements-comet.txt`.
- Generated bindings и original protocol files включены в `blockchain/comet/`;
  namespaces Python изменены механически, gRPC routes и wire schema сохранены.

Особенность upstream tag: `version.TMCoreSemVer` в исходниках содержит fallback
`0.39.0`. Поэтому наш бинарник выводит `0.39.0+0880b4d...`, хотя собран из tag
`v0.40.0`. Источником идентичности сборки служат source commit и binary SHA256,
сохранённые в `.tools/comet-build.json`, а не только fallback version string.

## Установка и запуск

### Обычный стенд, мониторинг и нагрузка

Из `/root/computechain/computechain`:

```bash
./start_test.sh                    # всё: 4 validators + full node + Prometheus/Grafana
./start_test.sh status
./start_test.sh load --mode low --duration 60
./start_test.sh load --mode medium --duration 60
./start_test.sh load --mode high --duration 60
./start_test.sh load-stop          # только нагрузка; стенд остаётся работать
./cleanup.sh                      # safe stop всех компонентов этой сети
```

Запускайте один load process за раз; следующий — после завершения предыдущего
или load-stop. По умолчанию `up` без нагрузки; команда `load` по умолчанию на 1 час,
поэтому для первой проверки лучше явно задать `--duration 60`.
Удобный совместимый синтаксис: `./start_test.sh low 24` — поднять стенд и начать
24-часовую нагрузку. `low/medium/high` — целевые 3/25/100 TPS, не обещание throughput.
Короткий локальный прогон high/100 достиг около 36 confirmed TPS без ошибок;
этот результат не является capacity benchmark или доказательством 24h стабильности.

Custom:

```bash
./start_test.sh load --tps 50 --duration 600 --accounts 16 --window 8
./start_test.sh up --no-monitoring
./start_test.sh monitoring-up
./start_test.sh monitoring-status
./start_test.sh monitoring-down
```

Флаги `--dir`, `--base-port`, `--prometheus-port`, `--grafana-port` позволяют
использовать другой каталог/свободные порты. Первый init создаёт новую цепь;
повторный up возобновляет существующую, без reset. Для отдельного стенда после
experiments выбирайте новый --dir, а не стирайте validator signing state.

Grafana: http://192.168.0.100:3000/d/computechain-v2, логин `admin`;
случайный пароль — в `../.runtime/comet-staking-devnet/monitoring/monitoring.env` (0600).
Prometheus: http://192.168.0.100:9090. Доступ с другой LAN-машины — без SSH tunnel.
По умолчанию выбирается private LAN IPv4; адрес можно указать явно:

```bash
./start_test.sh monitoring-up --monitoring-host 192.168.0.100
```

Monitoring репозиторий должен лежать рядом с blockchain repo; нужен Linux Docker
Engine + Compose. Только мониторинг привязан к LAN; ABCI/RPC/P2P/exporter остаются
loopback. Grafana требует пароль; Prometheus рассчитан на доверенную LAN без auth.
Не пробрасывать эти HTTP-порты в Интернет. Детали: `../monitoring/README.md`.

Генератор найден и перенастроен: `scripts/testing/tx_generator.py` теперь запускает
`scripts/comet_load.py`. Только canonical signed TRANSFER, отдельные 0600 кошельки
в `<devnet>/load-wallets/`, funding от devnet faucet. Личный `~/.computechain/keys`
не используется. Ring transfers сохраняют principal в test accounts; сжигаются fees.
Ключи не передаются через argv, не попадают в логи/отчёты. Старый generator сохранён
как `tx_generator_legacy.py`, но его прямой запуск отключён.

Nonce allocation ограничено per-account window; CheckTx != successful commit.
`load-latest.json`/per-run JSON отдельно показывают submitted, confirmed,
CheckTx rejection, execution failure, RPC uncertainty и unresolved. При неизвестном
RPC результате повторяются те же bytes/hash/nonce. Нагрузка не подменяет unknown
result новым переводом. Одновременно использовать faucet transfer и load запрещает
writer lock. Funding/drain идут дополнительно к sending duration.
SIGTERM/Ctrl-C прекращает отправку и даёт до 30s на drain; load-stop ждёт завершения.
Незавершённые TX не объявляются потерянными/неуспешными только из-за таймаута.

PID/argv registry ограничивает остановку процессами выбранного --dir. Controller
lock защищает параллельные CLI mutations; metadata обновляется атомарно. `cleanup.sh`
больше не использует pkill/rm и сохраняет keys/chain/logs и monitoring volumes.
Нагрузка автоматически заканчивается; ноды/мониторинг продолжают работать до stop.

Проверки tooling/security без затрагивания data directories:

```bash
./run_tests.sh tests/test_devnet_tools.py tests/test_security.py tests/test_comet.py ../monitoring/tests -q
```

`run_tests.sh` использует локальный venv и временный cwd. Полный core suite
теперь проходит, включая исправленные legacy fixtures и новые staking regressions.

### Низкоуровневые команды движка

Из workspace `/root/computechain`:

```bash
# Все tools устанавливаются локально; старые node directories не трогаются.
python3 computechain/scripts/setup_comet.py

# Создаёт отдельный genesis и случайные testnet keys. Повторный init запрещён.
.tools/blockchain-venv/bin/python computechain/scripts/comet_devnet.py init
.tools/blockchain-venv/bin/python computechain/scripts/comet_devnet.py up
.tools/blockchain-venv/bin/python computechain/scripts/comet_devnet.py status
.tools/blockchain-venv/bin/python computechain/scripts/comet_devnet.py transfer --amount 1000000000000000000
.tools/blockchain-venv/bin/python computechain/scripts/comet_devnet.py down
```

В обычном `up` запускаются 4 валидатора и 1 full node. Шестая directory
предназначена для отдельного теста state sync. Все RPC/ABCI/P2P/proxy endpoints
на loopback. По умолчанию RPC нод: `28601`, `28611`, `28621`, `28631`, `28641`;
Prometheus: `28603`, `28613`, `28623`, `28633`, `28643`.

Стенд использует per-link TCP proxies, чтобы воспроизводить сетевые partitions
без изменений firewall хоста. Это тестовая инфраструктура; production P2P
должен соединять ноды напрямую, с независимыми bootstrap/sentry операторами.

Data/logs/keys: `.runtime/comet-staking-devnet/` вне Git-клонов. Root directory имеет
mode 0700, wallet/validator/node keys — 0600. Ключи не печатаются и не коммитятся.
`down` останавливает только проверенные по argv/PID процессы этого стенда;
data и signing state сохраняются. Команды reset/wipe намеренно не используются.

Свой путь и свободный диапазон портов можно выбрать через `--dir` и `--base-port`.
Для node i P2P/RPC/ABCI/metrics используют base+i*10+[0,1,2,3]; TCP proxies занимают
base+99 и base+100..base+145. Меняя ports, выбирать весь диапазон свободным.

## Автоматическая многонодовая проверка

```bash
# Требует НОВУЮ directory. После проверки все запущенные процессы останавливаются.
.tools/blockchain-venv/bin/python computechain/scripts/comet_devnet.py verify \
  --dir /root/computechain/.runtime/comet-check-new --base-port 28600

# Изолированные application regression tests:
.tools/blockchain-venv/bin/python -m pytest computechain/tests/test_comet.py -q
```

Сценарии проверки:

- Совпадение block hash и application commitment у 4 валидаторов.
- Настоящий подписанный перевод 1 CPC через native CometBFT RPC.
- Запуск новой full node и загрузка истории.
- Offline/restart follower и catch-up без сброса БД.
- Прогресс сети с одним offline validator, затем его возвращение.
- Настоящий разрыв cross-partition TCP links: 2+2 валидатора; прекращение
  финализации в обеих половинах; восстановление общей цепи после healing.
- Fresh state-sync follower: trusted checkpoint, 2 RPC witnesses, восстановление
  snapshot и автоматическая проверка AppHash через native CometBFT light client.
- Совпадение block/application hashes и recipient balance у всех 6 нод.
- Вступление двух новых native validators строго на H+2, delegation/undelegation,
  native validator removal и возврат principal только после двух unbond gates.

Результат и точные hashes: `<devnet>/verification.json`. Верификатор не считает
state sync успешным без фактического сообщения native engine `Snapshot restored`.
CometBFT block header на H+1 содержит AppHash результата исполнения H; сравнение
commitments выполняется с этой семантикой, а не с legacy CPC header.

## Application state и transactions

Devnet поддерживает TRANSFER, STAKE/UNSTAKE, DELEGATE/UNDELEGATE,
UPDATE_VALIDATOR. Каждая TX имеет version=3 и строго типизированный payload,
chain_id, sender/recipient, decimal-string amount/gas_price, nonce, compressed
secp256k1 key и deterministic low-S ECDSA signature. Canonical JSON с точным
набором полей и signing domain `ComputeChain/tx/v3` предотвращает неоднозначную
склейку и cross-chain replay. Raw wire bytes должны быть canonical; неизвестные
поля, duplicate JSON keys, high-S signatures и неверные addresses отклоняются.

1 CPC = 10^18 базовых единиц. Для transfer gas=21000, gas_price>=1000. В этом
прототипе комиссии сжигаются и учитываются в state; block rewards/minting пока
выключены. Это ограниченная модель стенда, а не утверждённая итоговая токеномика.

AppHash — SHA256 полного canonical application state, включая chain/version,
height/time/block hash, accounts/nonces, supply/burn counters, fee policy, bonded
cohorts, unbonding, commissions, historical validator sets и evidence deduplication. Он меняется
после полного перехода блока. Query Merkle proofs не реализованы: `prove=true`
явно отклоняется; не выдаём hash всего state за доказательство отдельного account.

CheckTx/PrepareProposal/ProcessProposal работают на изолированном состоянии.
FinalizeBlock готовит результат; Commit одной SQLite transaction сохраняет
state, height/hash, receipts и snapshot. SQLite использует WAL + synchronous FULL.
Exclusive process lock запрещает двум application writers открыть одну directory.
Тест инъекции ошибки между обновлением state и receipt подтверждает rollback
единой transaction; результат не публикуется до успешного Commit.
Info возвращает только durable state: если приложение упало до Commit, native
handshake/replay повторяет исполнение; половинчатые account updates не публикуются.

## State sync и доверие

Snapshots: format=3, canonical JSON без compression, chunks<=256 KiB,
snapshot<=16 MiB, последние 10 snapshot heights. В тестовом стенде snapshot
создаётся каждые 5 блоков. Данные chunks поступают в отдельную staging SQLite БД;
durable application state меняется только после полного decode/schema/supply
checks и совпадения с AppHash, проверенным light client.

Checksum snapshot помогает обнаружить повреждение, но корень доверия — checkpoint
и проверка native headers/commits. Для local test checkpoint выбирает контроллер
из собственных нод; это не механизм доверенного bootstrap публичной сети.
В production нужны явно распространённый checkpoint, independent RPC witnesses,
trust period, связанный с unbonding, и политика обновления после долгого offline.
В v3 trust period — 30s, ниже минимального 60s unbonding. Evidence window —
20 блоков/30s; native evidence истекает только после ОБОИХ сроков. Долгий offline
требует свежего проверенного checkpoint, а не увеличения trust period.

## Что ещё предстоит

- Определить/внедрить rewards; legacy денежные handlers не подключены к ABCI.
- Длительные отказные прогоны с меняющимся stake и multi-host topology.
- Определить окончательную экономику, PoC/task verification и upgrade protocol.
- Multi-host deployment, независимые peers/witnesses, operator key management.
- Большие states/истории, задержки/потери, hostile peer matrix, длительный soak test.
- Производительная state structure/Merkle proofs: текущий полный JSON commitment
  и deep-copy рассчитаны на первый devnet, не на большое production state.
- Обновить explorer/wallet/API: старый FastAPI backend и legacy CLI не являются
  клиентами нового ABCI ledger.

Полный suite проходит без legacy import bridge. Исправлены устаревшие вызовы,
единицы и funded fixtures без ослабления security checks.

## Security pass — 7 октября 2026

ABCI — привилегированный интерфейс движка: он может финализировать блоки и
записывать состояние. Plaintext listener разрешён только на literal loopback IP
(`127.0.0.1` / `[::1]`); публичный доступ недопустим. Не доверять другим локальным
пользователям хоста: для multi-host deployment нужны отдельные процессы/права,
защищённая сеть или аутентифицированный транспорт. Публичный query API не заменяет ABCI.
Лимит входящего gRPC сообщения — 4 MiB, одновременных RPC — 16.

Store запрещает конфликтующий commit той же высоты, пропуск высот и restore
поверх живой цепи. Ошибка открытия/декодирования БД освобождает writer lock.
Snapshot hash должен совпасть с проверенным AppHash уже на OfferSnapshot;
при конфликте chunk индекс очищается для настоящего refetch, а snapshot metadata
копируется. Строго проверяются schema, высота и canonical block-hash encoding.

Также закрыты воспроизведённые F01–F09 в legacy execution/storage: owner/self-stake
checks, canonical versioned/domain-separated signatures, deep isolation, полный
post-block root, единый strict replay, atomic state/block/index commit и anchored
snapshot replacement. Это не делает custom legacy consensus BFT-safe: его запуск
требует `--allow-unsafe-legacy-devnet`; remote snapshot bootstrap и peer-driven
rollback отключены. `SUBMIT_RESULT`, miner payouts и несогласованные изменения
commission fail closed. Legacy v1 БД сохранена, её автоматическая миграция запрещена.

Негативные проверки запускаются из корня workspace:

```bash
.tools/blockchain-venv/bin/python tools/check_findings.py
.tools/blockchain-venv/bin/python tools/check_baseline.py
```

Первый runner использует canonical imports и временные БД; второй запускает весь
текущий набор без прежнего import bridge. Полный набор пока сохраняет 8 старых
failures (устаревшие API/fixtures и economics scenarios), не скрытых skips/xfails.
Новый fault-прогон: `.runtime/comet-security-verification-01/verification.json` —
full/catch-up sync, 3/4 progress, 2+2 halt/recovery, verified state sync, agreement
всех 6 узлов; процессы после теста остановлены.

## Staking и целочисленная экономика v3

Полная спецификация: [ECONOMICS.md](blockchain/comet/ECONOMICS.md). Все суммы
целочисленные; self stake, delegation и очередь вывода не смешиваются.
Supply = liquid + bonded + unbonding + burned; новой эмиссии нет. Genesis:
1M CPC всего, 40k bonded, 4k liquid owner funds, 956k faucet. Consensus key
Ed25519 привязан к secp256k1 owner через chain-bound proof of possession.

Минимумы: self stake 1000 CPC, delegation 10 CPC. Power = floor(bonded/CPC),
self stake ниже минимума исключает голосование. Лимит повышения power share 20%:
genesis 25% grandfathered, но увеличивать такие доли нельзя. Поэтому для проверки
делегации на первом стенде используйте новый validator node4.

```bash
./start_test.sh stake --validator-node 4 --amount 6000000000000000000000
./start_test.sh delegate --validator-node 4 --amount 100000000000000000000
./start_test.sh undelegate --validator-node 4 --amount 100000000000000000000
./start_test.sh unstake --validator-node 4 --amount 6000000000000000000000
```

STAKE автоматически финансирует только локальный devnet owner из faucet.
UNSTAKE подписывает owner; DELEGATE/UNDELEGATE — локальный faucet. Все пишущие
операции сериализованы с load. Вывод требует H+2+100 блоков И 60s consensus time.
Это короткие тестовые сроки, не production policy. Последний validator выйти
не может. CometBFT-verified duplicate vote/light-client evidence приводит к burn
5% ответственного principal, включая очередь вывода, и permanent key tombstone;
новые cohorts не отвечают за нарушения до их вступления. Комиссия только
планируется (max20%, step+5pp, cooldown100, announce20); наград пока нет.

Queries: `/state`, `/account/<address>`, `/validators`, `/unbondings/<address>`.
Схема state/transactions/snapshots v3 несовместима с v2. Default directory —
`.runtime/comet-staking-devnet`, chain ID `cpc-comet-staking-devnet-1`.
Старый стенд остановите явно с его `--dir`; его данные/keys сохраняются,
автоматической миграции/reset нет. Перед запуском v3 освободите занятые порты.
