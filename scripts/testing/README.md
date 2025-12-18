# Phase 1.4 Testing Scripts

Скрипты для автоматизированного тестирования ComputeChain.

## 🚀 Быстрый старт

### Простой тест (1 час)

```bash
cd /home/pc205/128/computechain
./scripts/testing/full_test.sh --mode quick --clean
```

### Полный тест (7 дней)

```bash
./scripts/testing/full_test.sh --mode full --clean
```

---

## 📁 Файлы

### `run_validators.sh`
Запуск множественных валидаторов

**Примеры:**
```bash
# 5 валидаторов с интервалом 30 секунд
./scripts/testing/run_validators.sh --count 5 --interval 30

# Со случайными интервалами (staggered)
./scripts/testing/run_validators.sh --count 5 --staggered

# Очистка данных перед запуском
./scripts/testing/run_validators.sh --count 5 --clean
```

### `tx_generator.py`
Генератор транзакций для нагрузочного тестирования

**Примеры:**
```bash
# Low load (1-5 TPS)
python3 scripts/testing/tx_generator.py --mode low --duration 3600

# Medium load (10-50 TPS)
python3 scripts/testing/tx_generator.py --mode medium --duration 7200

# High load (100-500 TPS)
python3 scripts/testing/tx_generator.py --mode high --duration 1800

# Custom (250 TPS)
python3 scripts/testing/tx_generator.py --mode custom --tps 250 --duration 3600
```

### `monitor.py`
Мониторинг метрик системы и blockchain

**Примеры:**
```bash
# Мониторинг каждые 60 секунд
python3 scripts/testing/monitor.py --interval 60

# С сохранением в CSV
python3 scripts/testing/monitor.py --interval 60 --output logs/metrics.csv

# С custom alert thresholds
python3 scripts/testing/monitor.py --alert-cpu 85 --alert-ram 95
```

### `full_test.sh`
Полный автоматический тестовый стек

**Опции:**
- `--mode quick|full` - режим теста
- `--clean` - очистить данные перед запуском
- `--validators N` - количество валидаторов

---

## 📊 Мониторинг

### Проверка статуса

```bash
# Blockchain status
curl http://localhost:8000/status | jq

# Validators
curl http://localhost:8000/validators | jq

# Metrics (Prometheus format)
curl http://localhost:8000/metrics
```

### Логи

```bash
# TX Generator
tail -f logs/tx_generator.log

# Monitor
tail -f logs/monitor.log

# Validator 1
tail -f logs/validator_1.log

# Все валидаторы
tail -f logs/validator_*.log
```

### Процессы

```bash
# Проверить running processes
ps aux | grep -E "run_node|tx_generator|monitor"

# Остановить все
pkill -f 'run_node.py|tx_generator.py|monitor.py'
```

---

## 🎯 Результаты

После завершения теста:

**Логи:** `logs/`
- `validator_*.log` - логи валидаторов
- `tx_generator.log` - логи генератора транзакций
- `monitor.log` - логи мониторинга

**Метрики:** `logs/metrics_*.csv`
- Все метрики в CSV формате
- Можно импортировать в Excel/Google Sheets

**PIDs:** `logs/*.pid`
- PID файлы для управления процессами

---

## ⚠️ Troubleshooting

### Валидатор не запускается

```bash
# Проверить логи
tail -f logs/validator_1.log

# Проверить порт
lsof -i :8000

# Убить процесс
pkill -f validator_1
```

### High CPU/RAM

```bash
# Остановить TX generator
pkill -f tx_generator.py

# Снизить нагрузку
python3 scripts/testing/tx_generator.py --mode low
```

### Database locked

```bash
# Остановить все
pkill -f run_node.py

# Подождать 10 секунд
sleep 10

# Перезапустить
./scripts/testing/run_validators.sh --count 1
```

---

## 📚 Дополнительная информация

См. **PHASE_1_4_TESTING_GUIDE.md** (internal only) для полного руководства.
