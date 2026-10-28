#include <Wire.h>
#include <SPI.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// Comunicação LoRa via UART1
HardwareSerial loraSerial(1);

// Credenciais da rede Wi-Fi
const char* ssid  = "RedLab";
const char* senha = "Coltec2026-Red";

// Pinos UART para o módulo LoRa
#define LORA_RX 16
#define LORA_TX 15

void setup() {
  Serial.begin(115200);
  inicializarLoRaSerial();
  conectarWiFi();
}

void loop() {
  receberMensagemLoRa();
  delay(50);
}

// ============================
// Funções 
// ============================

void inicializarLoRaSerial() {
  loraSerial.begin(9600, SERIAL_8N1, LORA_RX, LORA_TX);
}

void conectarWiFi() {
  WiFi.begin(ssid, senha);
  Serial.println("Conectando ao Wi-Fi...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nConectado! Endereço IP: ");
  Serial.println(WiFi.localIP());
}

// Função para separar strings
String getValue(String data, char separator, int index) {
  int found = 0;
  int strIndex[] = {0, -1};
  int maxIndex = data.length() - 1;

  for (int i = 0; i <= maxIndex && found <= index; i++) {
    if (data.charAt(i) == separator || i == maxIndex) {
      found++;
      strIndex[0] = strIndex[1] + 1;
      strIndex[1] = (i == maxIndex) ? i + 1 : i;
    }
  }
  return found > index ? data.substring(strIndex[0], strIndex[1]) : "";
}

void receberMensagemLoRa() {
  if (loraSerial.available()) {
    String dadosRecebidos = loraSerial.readStringUntil('\n');
    dadosRecebidos.trim();

    if (dadosRecebidos.length() > 0) {
      Serial.print("Payload bruto recebido: ");
      Serial.println(dadosRecebidos);

      // O IF QUE DECIDE O ROTEAMENTO
      // Verifica se a mensagem começa com "http" (Padrão atual do Transmissor 1 - Água)
      if (dadosRecebidos.startsWith("http")) {
        
        Serial.println(">> Identificado: Estação de Água. URL já veio pronta.");
        enviarParaPlanilha(dadosRecebidos);

      } 
      // Caso contrário, assume que é o Transmissor 2 (Estação Meteorológica)
      else if (dadosRecebidos.indexOf(',') != -1) {
        
        Serial.println(">> Identificado: Estação Meteorológica. Montando URL...");
        
        String dirVento   = getValue(dadosRecebidos, ',', 0);
        String velMed     = getValue(dadosRecebidos, ',', 1);
        String velMax     = getValue(dadosRecebidos, ',', 2);
        String chuvaHora  = getValue(dadosRecebidos, ',', 3);
        String chuvaDia   = getValue(dadosRecebidos, ',', 4);
        String temp       = getValue(dadosRecebidos, ',', 5);
        String umidade    = getValue(dadosRecebidos, ',', 6);
        String pressao    = getValue(dadosRecebidos, ',', 7);

        // URL do GAS da Estação Meteorológica
        String urlGoogleEstacao = "https://script.google.com/macros/s/AKfycbwwtVSDYxuMrBkHjSYhOuZNe2uszAcnouHpRK4c5TJp_XNhsOwJaNwYVWIZQP0dyy47/exec?"
                           "UniqueID=Estacao-2026-Lora"
                           "&dirVento=" + dirVento +
                           "&velMed=" + velMed +
                           "&velMax=" + velMax +
                           "&chuvaHora=" + chuvaHora +
                           "&chuvaDia=" + chuvaDia +
                           "&temp=" + temp +
                           "&umidade=" + umidade +
                           "&pressao=" + pressao;
                           
        enviarParaPlanilha(urlGoogleEstacao);

      } else {
        Serial.println("ERRO: Formato de payload desconhecido.");
      }
    }
  }
} 

void enviarParaPlanilha(const String& url) {
  WiFiClientSecure client;
  client.setInsecure(); 

  HTTPClient http;
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  http.begin(client, url);

  Serial.println("Enviando requisição HTTPS para o Google...");
  int resposta = http.GET();

  if (resposta > 0) {
    if (resposta == 200) {
      Serial.println("SUCESSO: Dados gravados na planilha!");
    } else {
      Serial.print("FALHA: O Google retornou o código HTTP: ");
      Serial.println(resposta);
    }
  } else {
    Serial.print("ERRO DE REDE: Falha na conexão HTTPS. Detalhe: ");
    Serial.println(http.errorToString(resposta));
  }

  http.end();
}