# IoT Environmental & Water Quality Telemetry System

## Visão Geral
Sistema de telemetria sem fio (WSN) desenvolvido para monitoramento ambiental e de qualidade da água em tempo real. O projeto utiliza microcontroladores ESP32 comunicando-se via rádio LoRa, com foco em alta eficiência energética (*power profiling*) e envio de dados para a nuvem via webhooks HTTPS (Google Apps Script).

Nota: Este é um repositório focado na documentação da arquitetura e organização do projeto, contendo os firmwares principais para referência.

## Arquitetura do Sistema

A rede é composta por três nós principais:

1. **Nó 1: Monitoramento de Água (Transmissor)**
   - Lê parâmetros críticos: temperatura da água (DS18B20), oxigênio dissolvido, pH e dados atmosféricos (BME680 via SPI).
   - Realiza a formatação da string de dados e a envia via LoRa (UART).
   - **Eficiência Energética:** Controla a alimentação periférica (3.2V) através de uma chave MOSFET, gerencia o estado dos pinos (alta impedância) e entra em *Deep Sleep* entre os ciclos.

2. **Nó 2: Estação Meteorológica (Transmissor)**
   - Processa um buffer serial de 35 bytes de uma central meteorológica externa.
   - Extrai variáveis como direção e velocidade do vento, índice pluviométrico, temperatura, umidade e pressão.
   - Transmite um *payload* CSV otimizado via LoRa e utiliza as mesmas técnicas de isolamento elétrico e *Deep Sleep*.

3. **Nó 3: Gateway Central (Receptor LoRa ➔ Wi-Fi)**
   - Atua como ponte entre a rede RF local e a Internet.
   - Escuta continuamente os pacotes LoRa recebidos e implementa roteamento dinâmico baseado na assinatura do *payload*.
   - Injeta os dados na nuvem através de requisições `HTTPS GET` estritas usando `WiFiClientSecure`.

##  Stack de Tecnologia e Hardware

- **Microcontroladores:** ESP32-S3
- **Comunicação:** LoRa (Módulos Ebyte E22/E32), Wi-Fi (802.11 b/g/n), SPI, I2C, UART, OneWire
- **Sensores:**
  - BME680 (Temperatura, Umidade, Pressão, Gás)
  - DS18B20 (Temperatura da água)
  - Sensores analógicos de pH e Oxigênio Dissolvido
  - Anemômetro e Pluviômetro
- **Integração Cloud:** Google Apps Script (Webhooks p/ Google Sheets)

## Power Profiling & Eficiência

Para garantir a durabilidade das baterias nas estações remotas, o firmware implementa rigorosas rotinas de economia de energia:
- **Isolamento de Pinos:** Conversão de barramentos de comunicação (TX/RX) para estados de entrada (alta impedância) durante o repouso para evitar drenagem de corrente parasita.
- **Sleep Mode do LoRa:** Manipulação dos pinos `M0` e `M1` com retenção de estado (`gpio_hold_en`) durante o *Deep Sleep* do ESP32.

## Estrutura do Código

- `QualidadeAgua.ino`: Firmware do nó de qualidade da água (Sensores I2C/SPI/OneWire/Analógicos + LoRa + Deep Sleep).
- `EstacaoMeteorologica.ino`: Firmware do nó meteorológico (Parsing Serial + LoRa + Deep Sleep).
- `Rec_EstacaoEQualidade.ino`: Firmware do Gateway Central (Recepção LoRa + Roteamento + HTTPS REST Request).
