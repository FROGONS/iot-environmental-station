# Validação Energética e Profiling (PPK2)

Esta pasta contém a infraestrutura de testes de consumo de energia dos nós sensores (ESP32/LoRa) utilizando o **Nordic Power Profiler Kit II (PPK2)**. 

Os scripts automatizam a coleta contínua de dados, aplicam processamento digital de sinais (DSP) para filtragem de ruídos (spike filter) e geram relatórios estatísticos.

## Arquitetura dos Scripts

* `script.py`: Motor principal de coleta. Roda em background por até 24h contínuas, decodificando a telemetria serial do PPK2 e salvando os logs em CSV.
* `resumo.py`: Script de análise de dados (NumPy). Consome os CSVs diários e consolida métricas críticas (médias, medianas, picos de microampères e perda de pacotes).
* `filtro_nordic.py`: Validação de DSP. Reproduz matematicamente o *spike filter* oficial do aplicativo da Nordic, garantindo a integridade dos dados coletados cruamente.
* `com.ppk2.log.plist`: Tarefa do `launchd` (macOS) utilizando `caffeinate` para agendar a execução autônoma das medições sem interrupção pelo gerenciamento de energia do SO.

## Como utilizar

### 1. Pré-requisitos
Instale as dependências Python necessárias:
```bash
pip install numpy ppk2-api
```
*Nota: Antes de rodar, atualize a variável `PORTA` nos scripts (`/dev/cu.usbmodem...` no macOS ou `COMx` / `/dev/ttyACM0` no Windows/Linux).*

### 2. Coleta de Dados Contínua
Para iniciar o profiling em tempo real:
```bash
python script.py
```
*(Os dados serão salvos diariamente na pasta `~/ppk_logs`).*

### 3. Análise dos Resultados
Para gerar o resumo estatístico do arquivo mais recente:
```bash
python resumo.py
```
Para analisar um arquivo de um dia específico:
```bash
python resumo.py ~/ppk_logs/2026-10-28.csv
```

### 4. Automação no macOS (Opcional)
Para habilitar a coleta diária automática via `launchd`:
```bash
cp com.ppk2.log.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ppk2.log.plist
```
