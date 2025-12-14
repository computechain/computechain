# ⚡ Quick Start - Validator Performance System

## 🚀 Запуск за 3 минуты

### Шаг 1: Запустите Node A (Terminal 1)

```bash
cd ~/128/computechain
./start_node_a.sh --clean
```

**Ожидаемый вывод:**
```
==========================================
🚀 Starting Node A (Primary Validator)
==========================================

✅ Node A initialized
   Data dir: .node_a
   RPC: http://localhost:8000
   P2P: 9000
   Dashboard: http://localhost:8000/

🔑 Validator Key:
   Address: cpcvalcons1...

🚀 Starting Node A...
```

**Дождитесь:** Несколько строк с "Block X added"

---

### Шаг 2: Откройте Dashboard (Terminal 2 или браузер)

Вариант A - Автоматически:
```bash
cd ~/128/computechain
./open_dashboard.sh
```

Вариант B - Вручную:
```
Откройте: http://localhost:8000/
```

**Что увидите:**
- Current Height: растёт
- Active Validators: 1
- Leaderboard с одним валидатором
- Performance Score: 100%

---

### Шаг 3: Запустите Node B (Terminal 3)

```bash
cd ~/128/computechain
./start_node_b.sh
```

**Важно!** Скрипт спросит:
```
📝 Create NEW validator for Node B? (y/n):
```

Выберите:
- **Y** - создать нового валидатора с автоматическим стейкингом (рекомендуется для теста)
- **N** - просто запустить ноду без валидатора

**Если выбрали Y**, скрипт автоматически:
1. ✅ Создаст alice key
2. ✅ Отправит 3000 CPC с faucet
3. ✅ Застейкает 2000 CPC
4. ✅ Запустит Node B

**Дождитесь:** Epoch transition (10 блоков) - alice появится в active set

---

## 🧪 Тестирование Jail Mechanism

### 1. Посмотрите текущее состояние в Dashboard

Должно быть 2 активных валидатора с performance score ~100%

### 2. Остановите Node B

В Terminal 3 нажмите **Ctrl+C**

### 3. Смотрите Dashboard

Обновляется каждые 10 секунд. Увидите:
- Missed blocks у Node B растут: 1, 2, 3...
- Performance score падает
- После 10 missed blocks → JAIL! 🔒

### 4. Проверьте Jailed Validators

На dashboard появится секция:
```
⚠️ Jailed Validators
- Node B validator
- Blocks remaining: 100
- Jail count: 1
- Penalty: 5% stake
```

---

## 📊 API Примеры

```bash
# Статус
curl -s http://localhost:8000/status | python3 -m json.tool

# Leaderboard
curl -s http://localhost:8000/validators/leaderboard | python3 -m json.tool

# Jailed
curl -s http://localhost:8000/validators/jailed | python3 -m json.tool
```

---

## 🔧 Troubleshooting

### Node A не запускается?
```bash
# Убить старые процессы
pkill -f run_node.py

# Очистить данные
rm -rf .node_a .node_b .test_node

# Запустить заново
./start_node_a.sh --clean
```

### Node B ошибка "validator key empty"?
```bash
# Очистить Node B
rm -rf .node_b

# Запустить заново (выбрать Y)
./start_node_b.sh
```

### Dashboard не открывается?
```bash
# Проверить что нода работает
curl http://localhost:8000/status

# Если работает - открыть вручную
firefox http://localhost:8000/
```

---

## 🔧 Новые возможности CLI (Phase 1-3)

### Обновить метаданные валидатора
```bash
python3 -m cli.main tx update-validator \
  --name "MyPool" \
  --website "https://mypool.com" \
  --description "Best validator in ComputeChain" \
  --commission 0.12 \
  --from alice
```

### Делегировать токены
```bash
# Делегировать 500 CPC валидатору
python3 -m cli.main tx delegate cpcvalcons1abc... 500 --from bob

# Отозвать 200 CPC
python3 -m cli.main tx undelegate cpcvalcons1abc... 200 --from bob
```

### Досрочно выйти из jail (1000 CPC fee)
```bash
python3 -m cli.main tx unjail --from alice
```

---

## 📚 Дальше

- **Детальное тестирование**: `TEST_GUIDE.md`
- **Описание системы**: `VALIDATOR_PERFORMANCE_GUIDE.md`
- **Changelog**: `CHANGELOG_SINCE_RESTRUCTURE.md` - Все изменения с момента реструктуризации

---

## 🎯 Чеклист успешного запуска

- [ ] Node A запущена и создаёт блоки
- [ ] Dashboard открывается на http://localhost:8000/
- [ ] Видно 1 активный валидатор
- [ ] Node B запущена (опционально)
- [ ] Видно 2 активных валидатора после epoch transition
- [ ] Missed blocks детектируются при остановке ноды
- [ ] Jail срабатывает после 10 missed blocks

**Всё работает?** Поздравляю! Система полностью функциональна! 🎉

---

## ⚡ One-liner для теста

```bash
# В одном терминале (для демо)
cd ~/128/computechain && \
./start_node_a.sh --clean & \
sleep 15 && \
./open_dashboard.sh
```

Затем в другом терминале:
```bash
cd ~/128/computechain && echo "y" | ./start_node_b.sh
```
