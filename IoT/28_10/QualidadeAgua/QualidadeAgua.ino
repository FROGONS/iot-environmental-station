#include <Wire.h>
#include <SPI.h>
#include <Adafruit_Sensor.h>
#include "Adafruit_BME680.h"
#include <OneWire.h>
#include <DallasTemperature.h>
#include "driver/gpio.h"
#include <Adafruit_NeoPixel.h>

// Importa as configurações/segredos locais (crie o arquivo config.h)
#include "config.h"

// ============================
// Definições de Hardware (Pinos)
// ============================

// SPI - Sensor BME680
#define BME_SCK_PIN 14
#define BME_MISO_PIN 13
#define BME_MOSI_PIN 12
#define BME_CS_PIN 11

// OneWire & Analógicos
#define ONE_WIRE_BUS_PIN 2
#define DO_PIN 1
#define PH_PIN 3

// Módulo LoRa (UART & Controle)
#define LORA_M0_PIN 18
#define LORA_M1_PIN 17
#define LORA_RX_PIN 16
#define LORA_TX_PIN 15

// Configuração do LED RGB
#define NEOPIXEL_PIN 38
#define NUM_PIXELS 1
Adafruit_NeoPixel pixels(NUM_PIXELS, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

// ============================
// Constantes do Oxigênio Dissolvido
// ============================
#define VREF 3300     // mV
#define ADC_RES 4095  // Resolução 12-bits
#define TWO_POINT_CALIBRATION 0
#define READ_TEMP 25  // Temperatura de referência (℃)

#define CAL1_V 1600  // mV
#define CAL1_T 25    // ℃
#define CAL2_V 1300  // mV
#define CAL2_T 15    // ℃

const uint16_t DO_TABLE[41] = {
  14460, 14220, 13820, 13440, 13090, 12740, 12420, 12110, 11810, 11530,
  11260, 11010, 10770, 10530, 10300, 10080, 9860, 9660, 9460, 9270,
  9080, 8900, 8730, 8570, 8410, 8250, 8110, 7960, 7820, 7690,
  7560, 7430, 7300, 7180, 7070, 6950, 6840, 6730, 6630, 6530, 6410
};

// ============================
// Instâncias dos Sensores
// ============================
Adafruit_BME680 bme(BME_CS_PIN, BME_MOSI_PIN, BME_MISO_PIN, BME_SCK_PIN);
OneWire oneWire(ONE_WIRE_BUS_PIN);
DallasTemperature sensors(&oneWire);
HardwareSerial loraSerial(1);

// ============================
// Variáveis Globais de Calibração
// ============================
float calibracaoPh7 = 2.58;
float calibracaoPh4 = 3.26;
float mCoeficiente;
float bCoeficiente;

// ============================
// Deep Sleep: Constantes
// ============================
#define US_TO_S_FACTOR 1000000ULL
#define TIME_TO_SLEEP 3600  // Duração do sono (segundos)

// Protótipos das funções
void inicializarLoRa();
void inicializarBME680();
float lerTemperaturaAgua();
float lerOxigenioDissolvido();
float lerPH();
void enviarMensagem(float tempAgua, float oxigenioDissolvido, float ph);
void acordaLora();
void economiaLora();
int16_t readDO(uint32_t voltage_mv, uint8_t temperature_c);

void setup() {
  Serial.begin(115200);

  pixels.begin();
  pixels.setBrightness(20);
  pixels.fill(0x000000);
  pixels.show();

  sensors.begin();
  inicializarLoRa();
  inicializarBME680();

  // Configura M0 e M1 para manter o LoRa em Sleep durante o arranque
  digitalWrite(LORA_M0_PIN, HIGH);
  digitalWrite(LORA_M1_PIN, HIGH);
  pinMode(LORA_M0_PIN, OUTPUT);
  pinMode(LORA_M1_PIN, OUTPUT);

  // Libera a trava do RTC
  gpio_hold_dis((gpio_num_t)LORA_M0_PIN);
  gpio_hold_dis((gpio_num_t)LORA_M1_PIN);

  // Calibração do pH (Equação da reta y = mx + b)
  mCoeficiente = (4.0 - 7.0) / (calibracaoPh4 - calibracaoPh7);
  bCoeficiente = 7.0 - mCoeficiente * calibracaoPh7;

  Serial.println("Sistema iniciado e pronto para leitura.");
}

void loop() {
  if (!bme.performReading()) {
    loraSerial.println("Falha ao realizar leitura do BME680.");
    return;
  }

  float temperaturaAgua = lerTemperaturaAgua();
  float oxigenioDissolvido = lerOxigenioDissolvido();
  float ph = lerPH();

  acordaLora();

  if (!bme.endReading()) {
    Serial.println("Falha na leitura final do BME!");
    economiaLora();
    esp_sleep_enable_timer_wakeup(TIME_TO_SLEEP * US_TO_S_FACTOR);
    Serial.println("Indo dormir por " + String(TIME_TO_SLEEP) + " segundos...");
    Serial.flush();
    esp_deep_sleep_start();
  }

  enviarMensagem(temperaturaAgua, oxigenioDissolvido, ph);

  delay(500);
  
  economiaLora();

  esp_sleep_enable_timer_wakeup(TIME_TO_SLEEP * US_TO_S_FACTOR);
  Serial.println("Indo dormir por " + String(TIME_TO_SLEEP) + " segundos...");
  Serial.flush();
  esp_deep_sleep_start();
}

void inicializarLoRa() {
  loraSerial.begin(9600, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);
  Serial.println("Comunicação LoRa configurada.");
}

void inicializarBME680() {
  Serial.println("Inicializando sensor BME680...");
  
  if (!bme.begin()) {
    Serial.println("Sensor BME680 não detectado! Verifique as conexões.");
    while (1) {
      pixels.fill(0xFF0000); // Vermelho em caso de erro
      pixels.show();
      delay(500);
      pixels.fill(0x000000);
      pixels.show();
      delay(500);
    }
  }
  
  bme.setTemperatureOversampling(BME680_OS_8X);
  bme.setHumidityOversampling(BME680_OS_2X);
  bme.setPressureOversampling(BME680_OS_4X);
  bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
  bme.setGasHeater(0, 0);
  Serial.println("Sensor BME680 pronto para uso.");
}

float lerTemperaturaAgua() {
  sensors.requestTemperatures();
  return sensors.getTempCByIndex(0);
}

float lerOxigenioDissolvido() {
  uint8_t tempReferencia = (uint8_t)READ_TEMP;
  uint16_t adcRaw = analogRead(DO_PIN);
  uint16_t adcVoltage = uint32_t(VREF) * adcRaw / ADC_RES;
  return readDO(adcVoltage, tempReferencia);
}

float lerPH() {
  int bufferLeituraPh[10];
  
  for (int i = 0; i < 10; i++) {
    bufferLeituraPh[i] = analogRead(PH_PIN);
    delay(10);
  }
  
  // Ordenação para filtro de mediana
  for (int i = 0; i < 9; i++) {
    for (int j = i + 1; j < 10; j++) {
      if (bufferLeituraPh[i] > bufferLeituraPh[j]) {
        int temp = bufferLeituraPh[i];
        bufferLeituraPh[i] = bufferLeituraPh[j];
        bufferLeituraPh[j] = temp;
      }
    }
  }

  int valorMedio = 0;
  for (int i = 2; i < 8; i++) {
    valorMedio += bufferLeituraPh[i];
  }
  
  float tensao = (valorMedio * 3.3) / 4095.0 / 6.0;
  return mCoeficiente * tensao + bCoeficiente;
}

void enviarMensagem(float tempAgua, float oxigenioDissolvido, float ph) {
  // Concatena a URL base importada do config.h com os parâmetros dos sensores
  String url = String(GOOGLE_SCRIPT_URL) +
    "?UniqueID=BME680-2025-Lora"
    "&temperatureC=" + String(bme.temperature) +
    "&humidity=" + String(bme.humidity) +
    "&pressure=" + String(bme.pressure / 100.0) +
    "&temperatureA=" + String(tempAgua) +
    "&oxiDissol=" + String(oxigenioDissolvido) +
    "&ph=" + String(ph);

  loraSerial.println(url);
  Serial.print("URL enviada via LoRa: ");
  Serial.println(url);
}

void acordaLora() {
  Serial.println("Acordando LoRa...");
  digitalWrite(LORA_M0_PIN, LOW);
  digitalWrite(LORA_M1_PIN, LOW);

  Serial.println("LoRa acordou.");-
}

void economiaLora() {
  loraSerial.flush();
  delay(150);

  digitalWrite(LORA_M0_PIN, HIGH);
  digitalWrite(LORA_M1_PIN, HIGH);

  gpio_hold_en((gpio_num_t)LORA_M0_PIN);
  gpio_hold_en((gpio_num_t)LORA_M1_PIN);
  gpio_deep_sleep_hold_en();

  loraSerial.end();

  pinMode(LORA_TX_PIN, INPUT);
  pinMode(LORA_RX_PIN, INPUT);

  Serial.println("LoRa em modo de baixo consumo.");
}

int16_t readDO(uint32_t voltage_mv, uint8_t temperature_c) {
#if TWO_POINT_CALIBRATION == 0
  uint16_t vSaturation = (uint32_t)CAL1_V + (uint32_t)35 * temperature_c - (uint32_t)CAL1_T * 35;
  return (voltage_mv * DO_TABLE[temperature_c] / vSaturation);
#else
  uint16_t vSaturation = (int16_t)((int8_t)temperature_c - CAL2_T) * ((uint16_t)CAL1_V - CAL2_V) / ((uint8_t)CAL1_T - CAL2_T) + CAL2_V;
  return (voltage_mv * DO_TABLE[temperature_c] / vSaturation);
#endif
}