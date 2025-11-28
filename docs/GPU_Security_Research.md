# Исследование безопасности GPU
## Продвинутые техники анти-виртуализации и анти-Sybil

**Версия:** 1.2  
**Дата:** 16 ноября 2025  
**Статус:** Исследование и предложения  
**Аудитория:** Исследователи безопасности, продвинутые разработчики

---

## 📋 Содержание

1. [Цели исследования](#цели-исследования)
2. [Стратегия белого списка GPU](#стратегия-белого-списка-gpu)
3. [Обнаружение виртуализации](#обнаружение-виртуализации)
4. [Fingerprinting на основе времени](#fingerprinting-на-основе-времени)
5. [Статистическое обнаружение аномалий](#статистическое-обнаружение-аномалий)
6. [Экономический анти-Sybil](#экономический-анти-sybil)
7. [Частичные ZK compute-доказательства](#частичные-zk-compute-доказательства)
8. [Стратегия источников заданий](#стратегия-источников-заданий)
9. [Комплексное решение](#комплексное-решение)
10. [Roadmap реализации](#roadmap-реализации)

---

## 🎯 Цели исследования

### Основная цель

**Обеспечить "1 физическая GPU = 1 воркер" для карт RTX 4090/5090**, сделав экономически и технически невыгодным:
- Использовать виртуальные GPU (vGPU, MIG)
- Запуск в контейнеризованных средах (Docker, Kubernetes)
- Клонирование/дублирование GPU идентичностей (прошивка VBIOS)
- Аренду облачных GPU инстансов

### Ограничения

```python
CONSTRAINTS = {
    "gpu_whitelist": ["RTX 4090", "RTX 5090"],
    "environment": "Только bare metal (без Docker/VM)",
    "identity": "1 физическая GPU = 1 уникальная идентичность",
    "verification": "Криптографически доказуемо + экономически обеспечено"
}
```

### Критерии успеха

```python
SUCCESS_METRICS = {
    "false_positive_rate": "< 1%",     # Честные майнеры не отклоняются
    "false_negative_rate": "< 5%",     # Атакующие не обнаруживаются
    "cost_of_attack": "> $10,000",     # Экономический барьер
    "detection_time": "< 24 часа",     # Быстрое обнаружение
}
```

---

## 🎯 Стратегия белого списка GPU

### Почему белый список?

Ограничение конкретными моделями GPU позволяет **более точный fingerprinting** и уменьшает поверхность атаки.

### Реализация

```python
# blockchain/compute/gpu_whitelist.py

ALLOWED_GPUS = {
    "NVIDIA GeForce RTX 4090": {
        "cuda_cores": 16384,
        "memory_gb": 24,
        "memory_bus_width": 384,
        "boost_clock_mhz": 2520,
        "tdp_watts": 450,
        "pci_device_id": "0x2684"
    },
    
    "NVIDIA GeForce RTX 5090": {
        "cuda_cores": 21760,
        "memory_gb": 32,
        "memory_bus_width": 512,
        "boost_clock_mhz": 2750,
        "tdp_watts": 575,
        "pci_device_id": "0x2704"
    }
}

def verify_gpu_model(gpu_info: dict) -> bool:
    """Проверить что GPU в белом списке"""
    gpu_name = gpu_info.get("name")
    
    if gpu_name not in ALLOWED_GPUS:
        return False
    
    expected = ALLOWED_GPUS[gpu_name]
    
    # Проверить соответствие спецификаций
    if gpu_info["cuda_cores"] != expected["cuda_cores"]:
        return False
    
    if gpu_info["memory_total"] < expected["memory_gb"] * 1024:  # MB
        return False
    
    return True
```

### Проверка PCI Device ID

```python
import subprocess

def get_pci_device_id(gpu_index: int) -> str:
    """Получить PCI device ID из lspci"""
    # Пример: 01:00.0 VGA compatible controller: NVIDIA Corporation AD102 [GeForce RTX 4090] (rev a1)
    
    result = subprocess.run(
        ["lspci", "-nn", "-d", "10de:"],  # 10de = NVIDIA vendor ID
        capture_output=True,
        text=True
    )
    
    for line in result.stdout.split('\n'):
        if f"GPU {gpu_index}" in line or "VGA" in line:
            # Извлечь device ID: [10de:2684]
            match = re.search(r'\[10de:(\w+)\]', line)
            if match:
                return match.group(1)
    
    return None

def verify_pci_id(gpu_index: int, expected_model: str) -> bool:
    """Проверить что PCI device ID соответствует ожидаемому"""
    actual_id = get_pci_device_id(gpu_index)
    expected_id = ALLOWED_GPUS[expected_model]["pci_device_id"]
    
    return actual_id == expected_id
```

---

## 🔍 Обнаружение виртуализации

### Слой 1: Обнаружение гипервизора

```python
# blockchain/compute/virtualization_check.py

import subprocess
import os

def detect_hypervisor() -> dict:
    """Обнаружить работу под гипервизором"""
    
    checks = {}
    
    # Проверка 1: CPU флаги
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()
            checks["hypervisor_flag"] = "hypervisor" in cpuinfo
    except:
        checks["hypervisor_flag"] = None
    
    # Проверка 2: DMI системная информация
    try:
        result = subprocess.run(
            ["dmidecode", "-s", "system-manufacturer"],
            capture_output=True,
            text=True,
            timeout=5
        )
        manufacturer = result.stdout.strip().lower()
        
        virtualization_vendors = [
            "vmware", "virtualbox", "qemu", "kvm",
            "xen", "microsoft corporation",  # Hyper-V
            "parallels", "amazon ec2"
        ]
        
        checks["dmi_vendor"] = any(v in manufacturer for v in virtualization_vendors)
    except:
        checks["dmi_vendor"] = None
    
    # Проверка 3: Systemd detect-virt
    try:
        result = subprocess.run(
            ["systemd-detect-virt"],
            capture_output=True,
            text=True,
            timeout=5
        )
        checks["systemd_virt"] = result.stdout.strip() != "none"
    except:
        checks["systemd_virt"] = None
    
    return checks

def is_virtualized() -> bool:
    """Проверить виртуализована ли система"""
    checks = detect_hypervisor()
    
    # Если любая проверка указывает на виртуализацию, пометить как подозрительное
    return any(v == True for v in checks.values() if v is not None)
```

### Слой 2: Обнаружение Docker/контейнеров

```python
def detect_docker() -> bool:
    """Обнаружить запуск в Docker контейнере"""
    
    # Проверка 1: файл .dockerenv
    if os.path.exists("/.dockerenv"):
        return True
    
    # Проверка 2: cgroup
    try:
        with open("/proc/1/cgroup", "r") as f:
            cgroup = f.read()
            if "docker" in cgroup or "containerd" in cgroup:
                return True
    except:
        pass
    
    # Проверка 3: /proc/self/mountinfo
    try:
        with open("/proc/self/mountinfo", "r") as f:
            mountinfo = f.read()
            if "/docker/" in mountinfo or "/var/lib/docker/" in mountinfo:
                return True
    except:
        pass
    
    return False

def detect_kubernetes() -> bool:
    """Обнаружить запуск в Kubernetes"""
    return os.path.exists("/var/run/secrets/kubernetes.io")

def is_containerized() -> bool:
    """Проверить запуск в контейнере"""
    return detect_docker() or detect_kubernetes()
```

### Слой 3: Обнаружение NVIDIA MIG

```python
import pynvml

def detect_mig() -> dict:
    """Обнаружить NVIDIA Multi-Instance GPU"""
    
    pynvml.nvmlInit()
    
    results = {}
    device_count = pynvml.nvmlDeviceGetCount()
    
    for i in range(device_count):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
        
        # Проверить включен ли режим MIG
        try:
            mig_mode = pynvml.nvmlDeviceGetMigMode(handle)
            results[f"gpu_{i}"] = {
                "mig_enabled": mig_mode[0] == 1,
                "mig_pending": mig_mode[1] == 1
            }
        except pynvml.NVMLError:
            # GPU не поддерживает MIG (хорошо для 4090/5090)
            results[f"gpu_{i}"] = {
                "mig_enabled": False,
                "mig_pending": False
            }
    
    pynvml.nvmlShutdown()
    return results

def is_mig_gpu(gpu_index: int) -> bool:
    """Проверить является ли конкретная GPU MIG инстансом"""
    mig_info = detect_mig()
    gpu_key = f"gpu_{gpu_index}"
    
    if gpu_key in mig_info:
        return mig_info[gpu_key]["mig_enabled"]
    
    return False
```

### Слой 4: Анализ PCI топологии

```python
def analyze_pci_topology(gpu_index: int) -> dict:
    """Анализ PCI топологии для обнаружения виртуализации"""
    
    # В bare metal, GPU должна быть напрямую подключена к CPU через PCIe
    # В VM, обычно есть мост/виртуальная шина
    
    result = subprocess.run(
        ["lspci", "-tv"],
        capture_output=True,
        text=True
    )
    
    topology = result.stdout
    
    checks = {
        "has_pci_bridge": "PCI bridge" in topology,
        "has_virtual_bus": "Virtual" in topology or "VirtualBox" in topology,
        "direct_pcie_connection": False
    }
    
    # Искать прямое PCIe подключение
    # Пример: +-00.0-[01]----00.0  NVIDIA Corporation AD102
    if re.search(r'\+-\d+\.\d+-\[\d+\]----\d+\.\d+.*NVIDIA', topology):
        checks["direct_pcie_connection"] = True
    
    return checks

def is_pci_suspicious(gpu_index: int) -> bool:
    """Проверить подозрительна ли PCI топология"""
    topo = analyze_pci_topology(gpu_index)
    
    # Красные флаги:
    if topo["has_virtual_bus"]:
        return True
    
    if not topo["direct_pcie_connection"]:
        return True
    
    return False
```

---

## ⏱️ Fingerprinting на основе времени

### Концепция

Каждая физическая GPU имеет **уникальные характеристики производительности**, которые сложно воспроизвести в виртуальных средах.

### Набор бенчмарков

```python
# blockchain/compute/gpu_fingerprint.py

import numpy as np
import time
import pycuda.driver as cuda
import pycuda.autoinit

class GPUFingerprint:
    """Сбор отпечатка производительности GPU"""
    
    def __init__(self, gpu_index: int):
        self.gpu_index = gpu_index
        self.device = cuda.Device(gpu_index)
        self.context = self.device.make_context()
    
    def benchmark_memory_bandwidth(self) -> float:
        """Измерить пропускную способность памяти (GB/s)"""
        # Выделить большой массив
        size = 1024 * 1024 * 1024  # 1 GB
        
        # GPU выделение
        d_array = cuda.mem_alloc(size)
        
        # Измерить время копирования
        h_array = np.random.randint(0, 255, size, dtype=np.uint8)
        
        start = time.perf_counter()
        cuda.memcpy_htod(d_array, h_array)
        cuda.Context.synchronize()
        end = time.perf_counter()
        
        elapsed = end - start
        bandwidth_gbps = size / elapsed / (1024**3)
        
        d_array.free()
        
        return bandwidth_gbps
    
    def benchmark_kernel_latency(self) -> float:
        """Измерить задержку запуска ядра (микросекунды)"""
        from pycuda.compiler import SourceModule
        
        # Минимальное ядро
        mod = SourceModule("""
        __global__ void empty_kernel() {
            // Ничего не делать
        }
        """)
        
        kernel = mod.get_function("empty_kernel")
        
        # Разогрев
        for _ in range(10):
            kernel(block=(1, 1, 1), grid=(1, 1))
        
        cuda.Context.synchronize()
        
        # Измерение
        iterations = 1000
        start = time.perf_counter()
        
        for _ in range(iterations):
            kernel(block=(1, 1, 1), grid=(1, 1))
        
        cuda.Context.synchronize()
        end = time.perf_counter()
        
        avg_latency_us = (end - start) / iterations * 1e6
        
        return avg_latency_us
    
    def benchmark_matmul_performance(self, size: int = 4096) -> float:
        """Измерить TFLOPS умножения матриц"""
        import pycuda.gpuarray as gpuarray
        import skcuda.linalg as linalg
        
        linalg.init()
        
        # Создать случайные матрицы
        A = gpuarray.to_gpu(np.random.randn(size, size).astype(np.float32))
        B = gpuarray.to_gpu(np.random.randn(size, size).astype(np.float32))
        
        # Разогрев
        C = linalg.dot(A, B)
        cuda.Context.synchronize()
        
        # Измерение
        iterations = 10
        start = time.perf_counter()
        
        for _ in range(iterations):
            C = linalg.dot(A, B)
        
        cuda.Context.synchronize()
        end = time.perf_counter()
        
        # Вычислить TFLOPS
        # Умножение матриц: 2 * size^3 операций на умножение
        ops = 2 * size**3 * iterations
        elapsed = end - start
        tflops = ops / elapsed / 1e12
        
        return tflops
    
    def benchmark_concurrent_streams(self) -> int:
        """Тест максимальных конкурентных CUDA потоков"""
        max_concurrent = 0
        
        try:
            streams = []
            for i in range(256):  # Попытка до 256 потоков
                stream = cuda.Stream()
                streams.append(stream)
                max_concurrent = i + 1
        except cuda.Error:
            pass
        finally:
            for stream in streams:
                del stream
        
        return max_concurrent
    
    def collect_full_fingerprint(self) -> dict:
        """Собрать полный отпечаток GPU"""
        
        fingerprint = {
            "gpu_index": self.gpu_index,
            "timestamp": time.time(),
            
            # Метрики производительности
            "memory_bandwidth_gbps": self.benchmark_memory_bandwidth(),
            "kernel_latency_us": self.benchmark_kernel_latency(),
            "matmul_tflops": self.benchmark_matmul_performance(),
            "max_concurrent_streams": self.benchmark_concurrent_streams(),
            
            # Свойства устройства
            "compute_capability": self.device.compute_capability(),
            "total_memory_mb": self.device.total_memory() // (1024**2),
            "multiprocessor_count": self.device.get_attribute(cuda.device_attribute.MULTIPROCESSOR_COUNT),
            "clock_rate_khz": self.device.get_attribute(cuda.device_attribute.CLOCK_RATE),
        }
        
        self.context.pop()
        return fingerprint
```

### Ожидаемые базовые линии (RTX 4090)

```python
RTX_4090_BASELINE = {
    "memory_bandwidth_gbps": (850, 1050),    # Диапазон: 850-1050 GB/s
    "kernel_latency_us": (2, 8),             # Диапазон: 2-8 микросекунд
    "matmul_tflops": (60, 85),               # Диапазон: 60-85 TFLOPS (FP32)
    "max_concurrent_streams": (128, 256),    # Диапазон: 128-256 потоков
}

def is_fingerprint_valid(fingerprint: dict, model: str) -> bool:
    """Проверить соответствие отпечатка ожидаемой базовой линии"""
    
    if model == "NVIDIA GeForce RTX 4090":
        baseline = RTX_4090_BASELINE
    else:
        return False  # Неизвестная модель
    
    # Проверить каждую метрику
    for key, (min_val, max_val) in baseline.items():
        if key not in fingerprint:
            return False
        
        value = fingerprint[key]
        
        # Разрешить 10% отклонение
        tolerance = 0.10
        lower = min_val * (1 - tolerance)
        upper = max_val * (1 + tolerance)
        
        if not (lower <= value <= upper):
            return False
    
    return True
```

---

## 📊 Статистическое обнаружение аномалий

### Подход на основе машинного обучения

Использовать ML для обнаружения **необычных паттернов**, указывающих на виртуализацию или спуфинг.

```python
# blockchain/compute/anomaly_detection.py

from sklearn.ensemble import IsolationForest
import numpy as np

class GPUAnomalyDetector:
    """ML-based обнаружение аномалий для поведения GPU"""
    
    def __init__(self):
        self.model = IsolationForest(
            contamination=0.05,  # Ожидаем 5% аномалий
            random_state=42
        )
        self.is_trained = False
    
    def extract_features(self, fingerprint: dict) -> np.ndarray:
        """Извлечь вектор признаков из отпечатка"""
        features = [
            fingerprint["memory_bandwidth_gbps"],
            fingerprint["kernel_latency_us"],
            fingerprint["matmul_tflops"],
            fingerprint["max_concurrent_streams"],
            fingerprint["multiprocessor_count"],
            fingerprint["clock_rate_khz"] / 1000,  # Конвертировать в MHz
        ]
        return np.array(features)
    
    def train(self, fingerprints: list):
        """Обучить на известных хороших GPU отпечатках"""
        X = np.array([self.extract_features(fp) for fp in fingerprints])
        self.model.fit(X)
        self.is_trained = True
    
    def is_anomalous(self, fingerprint: dict) -> bool:
        """Проверить аномален ли отпечаток"""
        if not self.is_trained:
            raise Exception("Модель не обучена")
        
        X = self.extract_features(fingerprint).reshape(1, -1)
        prediction = self.model.predict(X)
        
        # -1 = аномалия, 1 = нормально
        return prediction[0] == -1
    
    def get_anomaly_score(self, fingerprint: dict) -> float:
        """Получить оценку аномальности (ниже = более аномальный)"""
        if not self.is_trained:
            raise Exception("Модель не обучена")
        
        X = self.extract_features(fingerprint).reshape(1, -1)
        score = self.model.score_samples(X)[0]
        
        return score
```

### Поведенческий мониторинг

```python
class GPUBehaviorMonitor:
    """Мониторинг поведения GPU со временем"""
    
    def __init__(self, gpu_uuid: str):
        self.gpu_uuid = gpu_uuid
        self.challenge_history = []
    
    def record_challenge(self, challenge_result: dict):
        """Записать результат челленджа"""
        self.challenge_history.append({
            "timestamp": time.time(),
            "completion_time": challenge_result["elapsed_seconds"],
            "matrix_size": challenge_result["matrix_size"],
            "tflops": challenge_result["tflops"],
        })
    
    def detect_suspicious_patterns(self) -> dict:
        """Обнаружить подозрительные поведенческие паттерны"""
        
        if len(self.challenge_history) < 100:
            return {"suspicious": False, "reason": "Недостаточно данных"}
        
        recent = self.challenge_history[-100:]
        
        # Проверка 1: Производительность слишком постоянная (вероятно софтверная эмуляция)
        completion_times = [c["completion_time"] for c in recent]
        std_dev = np.std(completion_times)
        mean_time = np.mean(completion_times)
        coefficient_of_variation = std_dev / mean_time
        
        if coefficient_of_variation < 0.01:  # Менее 1% вариации
            return {
                "suspicious": True,
                "reason": "Производительность слишком постоянная (возможная софтверная эмуляция)",
                "cv": coefficient_of_variation
            }
        
        # Проверка 2: Деградация производительности (должен происходить thermal throttling)
        first_50 = completion_times[:50]
        last_50 = completion_times[50:]
        
        if np.mean(last_50) < np.mean(first_50) * 0.95:
            # Производительность улучшилась (подозрительно - должна немного деградировать из-за нагрева)
            return {
                "suspicious": True,
                "reason": "Не наблюдается thermal throttling"
            }
        
        # Проверка 3: Внезапные скачки производительности
        for i in range(1, len(completion_times)):
            change = abs(completion_times[i] - completion_times[i-1]) / completion_times[i-1]
            if change > 0.3:  # 30% внезапное изменение
                return {
                    "suspicious": True,
                    "reason": f"Внезапное изменение производительности на челлендже {i}"
                }
        
        return {"suspicious": False}
```

---

## 💰 Экономический анти-Sybil

### Требование стейка

```python
# Экономический барьер для атаки

ECONOMIC_PARAMETERS = {
    "stake_per_gpu": 10_000 * 10**18,  # 10,000 CPC на GPU
    "slashing_percentage": 0.20,       # 20% slash за мошенничество
    "minimum_challenges": 1000,        # Перед полным доверием
}

def calculate_attack_cost(num_fake_gpus: int, cpc_price_usd: float) -> dict:
    """Вычислить стоимость атаки"""
    
    stake_required = ECONOMIC_PARAMETERS["stake_per_gpu"] * num_fake_gpus
    stake_usd = stake_required / 10**18 * cpc_price_usd
    
    # Если обнаружено, потеря 20% стейка
    potential_loss = stake_usd * ECONOMIC_PARAMETERS["slashing_percentage"]
    
    # Дополнительные затраты
    development_cost = 50_000  # Разработка обхода виртуализации
    hardware_cost = 2_000 * num_fake_gpus  # RTX 4090 ~$2000 каждая
    
    total_cost = stake_usd + development_cost + hardware_cost
    
    return {
        "stake_required_cpc": stake_required / 10**18,
        "stake_required_usd": stake_usd,
        "potential_loss_usd": potential_loss,
        "development_cost_usd": development_cost,
        "hardware_cost_usd": hardware_cost,
        "total_cost_usd": total_cost,
        "num_fake_gpus": num_fake_gpus
    }

# Пример: Атака с 10 фейковыми GPU
attack_cost = calculate_attack_cost(10, cpc_price_usd=5.0)
print(f"""
Анализ стоимости атаки:
- Требуемый стейк: ${attack_cost['stake_required_usd']:,.0f}
- Потенциальная потеря: ${attack_cost['potential_loss_usd']:,.0f}
- Общая стоимость: ${attack_cost['total_cost_usd']:,.0f}
""")
```

### Система постепенного доверия

```python
class TrustLevel:
    """Постепенное доверие для новых майнеров"""
    
    def __init__(self, gpu_uuid: str):
        self.gpu_uuid = gpu_uuid
        self.challenges_completed = 0
        self.challenges_failed = 0
        self.registration_timestamp = time.time()
    
    def get_trust_level(self) -> str:
        """Получить текущий уровень доверия"""
        total = self.challenges_completed + self.challenges_failed
        success_rate = self.challenges_completed / total if total > 0 else 0
        
        if total < 100:
            return "untrusted"
        elif total < 500:
            return "low_trust"
        elif total < 1000:
            return "medium_trust"
        elif success_rate > 0.95:
            return "high_trust"
        else:
            return "medium_trust"
    
    def get_verification_frequency(self) -> str:
        """Получить как часто верифицировать эту GPU"""
        trust = self.get_trust_level()
        
        frequencies = {
            "untrusted": "every_challenge",      # 100% верификация
            "low_trust": "every_5_challenges",   # 20% верификация
            "medium_trust": "every_20_challenges", # 5% верификация
            "high_trust": "every_100_challenges"  # 1% верификация
        }
        
        return frequencies[trust]
    
    def get_reward_multiplier(self) -> float:
        """Меньше наград для недоверенных майнеров"""
        trust = self.get_trust_level()
        
        multipliers = {
            "untrusted": 0.5,      # 50% награды
            "low_trust": 0.75,     # 75% награды
            "medium_trust": 0.90,  # 90% награды
            "high_trust": 1.0      # 100% награды
        }
        
        return multipliers[trust]
```

---

## 🔐 Частичные ZK compute-доказательства

### Концепция: Гибридный challenge-response

Вместо полных результатов вычислений, использовать **выборочную верификацию с zero-knowledge-подобными свойствами**.

```python
# blockchain/compute/partial_zk_proof.py

class PartialZKMatrixProof:
    """Частичное zero-knowledge доказательство для умножения матриц"""
    
    def __init__(self, seed: bytes, size: int):
        self.seed = seed
        self.size = size
        
        # Генерировать матрицы A, B детерминистически из seed
        np.random.seed(int.from_bytes(seed, 'big') % (2**32))
        self.A = np.random.randn(size, size).astype(np.float32)
        self.B = np.random.randn(size, size).astype(np.float32)
    
    def compute_full_result(self) -> np.ndarray:
        """Майнер вычисляет полное C = A × B"""
        return np.matmul(self.A, self.B)
    
    def create_commitment(self, result: np.ndarray) -> dict:
        """Создать Merkle коммитмент к результату"""
        from blockchain.crypto.merkle import MerkleTree
        
        tree = MerkleTree()
        
        # Добавить каждую строку как лист
        for i in range(self.size):
            row_hash = hashlib.sha256(result[i].tobytes()).digest()
            tree.add_leaf(row_hash)
        
        tree.build()
        
        return {
            "merkle_root": tree.get_root().hex(),
            "size": self.size,
            "seed": self.seed.hex()
        }
    
    def request_selective_proof(self, commitment: dict, sample_size: int = 10) -> list:
        """Валидатор запрашивает случайные строки"""
        import random
        random.seed(int(time.time()))
        
        row_indices = random.sample(range(self.size), sample_size)
        return row_indices
    
    def generate_proof(self, result: np.ndarray, requested_rows: list) -> dict:
        """Майнер предоставляет доказательства для запрошенных строк"""
        from blockchain.crypto.merkle import MerkleTree
        
        # Перестроить Merkle дерево
        tree = MerkleTree()
        for i in range(self.size):
            row_hash = hashlib.sha256(result[i].tobytes()).digest()
            tree.add_leaf(row_hash)
        tree.build()
        
        # Сгенерировать доказательства
        proofs = {}
        for row_idx in requested_rows:
            proofs[row_idx] = {
                "row_data": result[row_idx].tolist(),
                "merkle_proof": tree.get_proof(row_idx)
            }
        
        return proofs
    
    def verify_proof(self, commitment: dict, proofs: dict) -> bool:
        """Валидатор верифицирует выборочные доказательства"""
        
        # Пересчитать ожидаемые строки
        for row_idx, proof_data in proofs.items():
            # Локально вычислить ожидаемую строку
            expected_row = np.dot(self.A[row_idx], self.B)
            provided_row = np.array(proof_data["row_data"])
            
            # Проверить совпадение значений (в пределах толерантности плавающей точки)
            if not np.allclose(expected_row, provided_row, rtol=1e-5):
                return False
            
            # Проверить Merkle proof
            row_hash = hashlib.sha256(provided_row.tobytes()).digest()
            if not self._verify_merkle_proof(
                row_hash,
                row_idx,
                bytes.fromhex(commitment["merkle_root"]),
                proof_data["merkle_proof"]
            ):
                return False
        
        return True
    
    def _verify_merkle_proof(self, leaf: bytes, index: int, root: bytes, proof: list) -> bool:
        """Проверить единичное Merkle доказательство"""
        current = leaf
        
        for sibling in proof:
            if index % 2 == 0:
                current = hashlib.sha256(current + sibling).digest()
            else:
                current = hashlib.sha256(sibling + current).digest()
            index //= 2
        
        return current == root
```

### Преимущества

```python
PARTIAL_ZK_ADVANTAGES = {
    "bandwidth": "Отправить только ~0.1% результата (10 строк из 8192)",
    "verification_cost": "Валидатор пересчитывает только 10 строк",
    "security": "Вероятность обмана < 0.001 с 10 образцами",
    "privacy": "Результат в основном скрыт (как ZK)",
}
```

---

## 📋 Стратегия источников заданий

### Двухрежимная архитектура

```python
class TaskManager:
    """Управление реальными и синтетическими compute-заданиями"""
    
    def __init__(self):
        self.real_job_queue = []
        self.synthetic_challenge_rate = 0.2  # 20% челленджей синтетические
    
    def get_next_task(self, miner_address: str) -> dict:
        """Получить следующее задание для майнера"""
        
        # Приоритет 1: Реальные клиентские задания
        if self.real_job_queue:
            job = self.real_job_queue.pop(0)
            return {
                "type": "real_job",
                "job_id": job["id"],
                "task": job["task"],
                "payment": job["payment"],
                "deadline": job["deadline"]
            }
        
        # Приоритет 2: Синтетические челленджи
        else:
            return {
                "type": "synthetic_challenge",
                "challenge_id": self._generate_challenge_id(),
                "seed": os.urandom(32),
                "matrix_size": 8192,
                "timeout": 60
            }
    
    def submit_client_job(self, job: dict):
        """Клиент отправляет платное compute-задание"""
        self.real_job_queue.append(job)
```

### Источники реальных заданий

```python
REAL_JOB_SOURCES = {
    "ai_training": {
        "description": "Распределенное ML обучение",
        "typical_payment": "100-1000 CPC",
        "duration": "1-24 часа"
    },
    
    "3d_rendering": {
        "description": "Рендеринг кадров для анимаций",
        "typical_payment": "10-100 CPC за кадр",
        "duration": "1-60 минут на кадр"
    },
    
    "scientific_compute": {
        "description": "Молекулярная динамика, климатическое моделирование",
        "typical_payment": "500-5000 CPC",
        "duration": "1-168 часов"
    },
    
    "inference_api": {
        "description": "Real-time AI inference",
        "typical_payment": "0.01-1 CPC за запрос",
        "duration": "100-1000ms"
    }
}
```

---

## 🛡️ Комплексное решение

### 5-слойная стратегия защиты

```python
class ComprehensiveGPUSecurity:
    """Многослойная верификация подлинности GPU"""
    
    def __init__(self):
        self.whitelist_checker = GPUWhitelistChecker()
        self.virt_detector = VirtualizationDetector()
        self.fingerprinter = GPUFingerprint()
        self.anomaly_detector = GPUAnomalyDetector()
        self.trust_manager = TrustManager()
    
    def verify_miner_gpu(self, miner_address: str, gpu_info: dict) -> dict:
        """Комплексная верификация GPU"""
        
        results = {
            "layer_1_whitelist": False,
            "layer_2_virtualization": False,
            "layer_3_fingerprint": False,
            "layer_4_anomaly": False,
            "layer_5_economic": False,
            "overall_score": 0.0,
            "approved": False
        }
        
        # Слой 1: Белый список GPU
        if self.whitelist_checker.verify(gpu_info):
            results["layer_1_whitelist"] = True
            results["overall_score"] += 0.20
        else:
            return results  # Немедленное отклонение
        
        # Слой 2: Обнаружение виртуализации
        virt_checks = self.virt_detector.check_all()
        if not virt_checks["is_virtualized"]:
            results["layer_2_virtualization"] = True
            results["overall_score"] += 0.20
        
        # Слой 3: Timing Fingerprint
        fingerprint = self.fingerprinter.collect_full_fingerprint()
        if self.fingerprinter.is_valid(fingerprint, gpu_info["model"]):
            results["layer_3_fingerprint"] = True
            results["overall_score"] += 0.20
        
        # Слой 4: Обнаружение аномалий
        if not self.anomaly_detector.is_anomalous(fingerprint):
            results["layer_4_anomaly"] = True
            results["overall_score"] += 0.20
        
        # Слой 5: Экономический стейк
        stake = self.trust_manager.get_stake(miner_address)
        if stake >= ECONOMIC_PARAMETERS["stake_per_gpu"]:
            results["layer_5_economic"] = True
            results["overall_score"] += 0.20
        
        # Решение: Требуется 80%+ оценка
        results["approved"] = results["overall_score"] >= 0.80
        
        return results
```

---

## 🗺️ Roadmap реализации

### Фаза 1: MVP (Месяц 1-3)
- ✅ Белый список GPU (4090/5090)
- ✅ Базовое обнаружение виртуализации
- ✅ Экономический стейк (10k CPC)
- ⏳ Простой fingerprinting

### Фаза 2: Улучшенная безопасность (Месяц 4-6)
- ⏳ Полный timing fingerprinting
- ⏳ Анализ PCI топологии
- ⏳ Система постепенного доверия
- ⏳ Частичные ZK доказательства

### Фаза 3: ML и продвинутое (Месяц 7-12)
- ⏳ ML обнаружение аномалий
- ⏳ Поведенческий мониторинг
- ⏳ Интеграция маркетплейса реальных заданий
- ⏳ Исследование TEE (SGX/SEV)

---

**Версия 1.2** | Исследование безопасности GPU  
**Последнее обновление:** 16 ноября 2025

*Этот исследовательский документ будет развиваться по мере обнаружения новых техник.*

---

# Приложение X. ComputeChain GPU Security MVP

**Название:** ComputeChain_GPU_Security_MVP

**Версия:** 1.0

**Дата:** 16 ноября 2025

**Статус:** Обязательные требования для первой версии сети

---

## 1. Цель и границы MVP

**Цель:**

Сделать так, чтобы в первой версии сети:

* участие было **ограничено физическими RTX 4090 / RTX 5090** на bare metal;

* использование **облаков, vGPU, Docker/Kubernetes** было минимально выгодно или прямо отрезано на уровне официального софта;

* экономическая модель и проверки делали массовый Sybil по GPU **дорогим и рискованным**.

**Важно:**

Это **не абсолютная защита**, а набор практических мер, которые:

* усложняют жизнь атакующему;

* делают атаку заметной;

* повышают её стоимость.

Продвинутые техники (ML-анализ, TEE, сложные ZK-схемы) **в этот MVP не входят** и считаются Phase 2+.

---

## 2. Обязательный белый список GPU (4090 / 5090)

### Требование

В протоколе и официальном майнере/воркере:

* **разрешены только**:

  * `NVIDIA GeForce RTX 4090`

  * `NVIDIA GeForce RTX 5090`

* все остальные устройства отклоняются.

### Минимальная проверка

1. Считать информацию о GPU через NVML / nvidia-smi:

   * имя модели,

   * объём памяти,

   * количество SM / CUDA cores (если доступно).

2. Проверить соответствие ожидаемым значениям для 4090/5090 (с небольшим допуском по памяти/частоте).

3. Дополнительно сверить PCI Device ID с allowlist'ом (4090/5090).

**Результат:** майнер с 3060/3080/A100 и прочими картами просто **не регистрируется** в сети через официальный софт.

---

## 3. Базовая анти-виртуализация и анти-контейнер

### Требование

Официальный воркер/майнер **не должен запускаться**, если:

* обнаружен гипервизор,

* обнаружен Docker/Kubernetes-контейнер,

* явные признаки виртуальной машины/облака.

### Минимальные проверки (MVP)

**VM / Hypervisor:**

* чек флага `hypervisor` в `/proc/cpuinfo`;

* `systemd-detect-virt` (если != `none` → считаем виртуализацией);

* `dmidecode` / аналог для:

  * `Amazon EC2`, `Google Compute Engine`, `Microsoft Corporation`, `VMware`, `VirtualBox`, `QEMU`, `KVM`, `Xen` и т.п.

**Контейнеры:**

* если существует `/.dockerenv` → считать Docker;

* если `/proc/1/cgroup` содержит `docker`, `containerd`, `kubepods` → считать контейнером;

* если есть `/var/run/secrets/kubernetes.io` → считать Kubernetes.

**Политика:**

* При обнаружении любого из вышеописанного:

  * официальный клиент выводит понятное сообщение,

  * завершает работу и не регистрирует воркер.

*Атакующий может форкнуть код и выпилить проверки — это нормально. Цель MVP: отрезать честные облака/контейнеры «из коробки» и усложнить жизнь злоумышленнику.*

---

## 4. System PoC-задания с Merkle + sampling

### Требование

Сеть должна иметь **встроенный тип задач** (system PoC), которые:

* генерируются детерминированно от `hash(prev_block)` / слота;

* исполняются **всеми майнерами**;

* используются для:

  * baseline compute-скоринга,

  * проверки честности.

### Минимальный дизайн (MVP)

* тип задачи: матричное умножение или аналогичная вычислительно тяжёлая операция;

* входные данные (матрицы) генерируются детерминированно от seed, известного всем;

* майнер:

  * считает результат на GPU,

  * строит Merkle-дерево по строкам результата,

  * отправляет `merkle_root` + базовую тайминговую статистику;

* валидатор:

  * случайно выбирает небольшой набор строк/элементов,

  * запрашивает их значения + Merkle proof,

  * пересчитывает эти строки локально и сверяет;

**Это обязательно для MVP** и используется как:

* источник «полезного PoC» даже при отсутствии реальных клиентских задач;

* источник данных для оценки перфоманса GPU.

---

## 5. Экономический барьер: stake-per-GPU + slashing

### Требование

Каждый воркер (GPU) должен быть привязан к **определённому объёму стейка**, чтобы:

* массовый Sybil по GPU был экономически дорогим;

* обнаруженный обман → ощутимый финансовый удар.

### MVP-параметры (пример)

* `stake_per_gpu = 10 000 CPC` (configurable);

* минимальный стейк для регистрации одной GPU: `stake_per_gpu`;

* slashing при доказанном мошенничестве (фейковые пруфы, обход протокола):

  * не менее **20%** стейка, привязанного к данной GPU/адресу.

**Принцип:**

* хочешь заявить 10 «GPU» → заблокируй 100k CPC;

* при детекте мошенничества теряешь значимую сумму, что делает атаку **дорогим казино**.

---

## 6. Простая модель доверия (Trust Levels) для GPU

### Требование

Для каждой GPU/воркера должна вестись **история челленджей** и вычисляться **уровень доверия**, влияющий на:

* частоту выборочной проверки;

* возможный множитель наград.

### MVP-модель

Категории:

* `untrusted` — меньше 100 челленджей,

* `low_trust` — 100–500 челленджей,

* `medium_trust` — 500–1000,

* `high_trust` — > 1000 и успех > 95%.

Для каждой категории:

* `untrusted`:

  * верификация почти каждого челленджа (или очень часто),

  * reward-множитель ≤ 0.5–0.75.

* `low_trust`:

  * выборочная проверка (например, 1 из 5),

  * reward-множитель ≤ 0.75–0.9.

* `medium_trust`:

  * 1 из 20 или реже,

  * reward-множитель около 0.9–1.0.

* `high_trust`:

  * редкая проверка (1 из 50–100),

  * 100% наград.

Это:

* снижает профит короткоживущих Sybil-воркеров,

* поощряет долгоживущие честные GPU.

---

## 7. Минимальный timing-fingerprint (без жёстких банов)

### Требование

В MVP необходимо **собирать базовые метрики производительности** для 4090/5090, но **не банить по ним агрессивно**, пока нет большого объёма реальных данных.

### Минимальный набор метрик

* пропускная способность памяти (GB/s) для большого буфера;

* время запуска простого CUDA-ядра (микросекунды);

* производительность матричного умножения (TFLOPS) на матрицах фиксированного размера.

На этапе MVP:

* эти метрики:

  * логируются,

  * используются в диагностике и отладке,

  * могут влиять **только на дополнительные флаги/эвристику**, а не на мгновенный бан;

* никакого ML/сложной статистики пока не применять.

---

## 8. Чёткая позиция по облакам и контейнерам

### В протоколе/документации должно быть явно сказано:

1. **Поддерживается только bare metal** для официального майнера/воркера.

2. Использование:

   * облачных GPU (AWS/GCP/Azure и др.),

   * виртуализации,

   * контейнеров (Docker/K8s)

   официально **не поддерживается** и может приводить к:

   * отказу в участии,

   * повышенной вероятности дополнительных проверок,

   * потенциальному бану/слэшингу при обнаружении обхода.

Это важно не столько технически, сколько социально/юридически:

ты официально фиксируешь, что сеть ориентирована на **домашние/фермерские bare-metal 4090/5090**, а не на облачных реселлеров.

---

## 9. Что *не входит* в MVP (Phase 2+)

Чтобы не раздувать scope первой версии, фиксируем, что:

* ML-анализ аномалий (IsolationForest и т.п.);

* сложный поведенческий мониторинг (thermal patterns, long-term анализ);

* полноценные ZK/SNARK/STARK-протоколы для любых задач;

* интеграция с аппаратным TEE (SGX/SEV/TDX);

**откладываются на Phase 2+** и описываются в отдельном research-документе

(например, `GPU_Security_Research_v1.2`).

---

## MVP-резюме

**Обязательный минимум для первого релиза:**

1. ✅ **Только RTX 4090/5090** (whitelist + базовая валидация)

2. ✅ **Жёсткий отказ** официального софта при явной виртуализации/контейнерах

3. ✅ **Обязательные системные PoC-задачи** с Merkle+sampling

4. ✅ **Stake-per-GPU + slashing ≥20%** как экономический барьер

5. ✅ **Trust levels для GPU** → влияют на частоту проверки и награды

6. ✅ **Сбор timing-фингерпринта** (для анализа и будущих улучшений)

7. ✅ **Четкая политика**: bare metal only, никаких облаков/контейнеров

Этот набор мер можно реально реализовать в рамках первого релиза и сразу получить **ощутимое усиление безопасности и анти-Sybil**, не уходя в бесконечный ресёрч.

---

**Конец приложения X**

