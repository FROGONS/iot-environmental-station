import csv
import os
import signal
import sys
import time
from datetime import datetime

import numpy as np
from ppk2_api.ppk2_api import PPK2_API

PORTA = "/dev/cu.usbmodemE52AC03CFDE12"
PASTA = "/Users/iot/ppk_logs"
DURACAO_S = 24 * 60 * 60 - 120      # termina 2 min antes da proxima execucao
INTERVALO_S = 1.0                  # 1 linha por segundo
VDD_MV = 3300                      # o teste mostrou que 3300 ou 5000 muda so ~1 uA
ADC_MULT = 1.8 / 163840
CHAVES_CAL = ("R", "GS", "GI", "O", "S", "I", "UG")

# Spike filter do app (nordicsemi/pc-nrfconnect-ppk, serialDevice.ts)
ALPHA = 0.18
ALPHA5 = 0.06
AMOSTRAS_SPIKE = 3

COLUNAS = ["timestamp", "media_app_uA", "mediana_uA", "max_1ms_uA",
           "media_sem_trocas_uA", "n_amostras", "n_perdidas", "n_trocas_faixa"]


def parse_calibracao(texto):
    cal = {}
    for linha in texto.splitlines():
        if ": " in linha:
            k, v = linha.split(": ", 1)
            try:
                cal[k.strip()] = float(v)
            except ValueError:
                pass
    try:
        return {k: np.array([cal[f"{k}{i}"] for i in range(5)]) for k in CHAVES_CAL}
    except KeyError:
        return None


def ler_calibracao(p, tentativas=3):
    for _ in range(tentativas):
        p.ser.reset_input_buffer()
        p.ser.write(bytes([0x19]))   # GET_META_DATA
        bruto = b""
        ultimo = time.time()
        fim = time.time() + 6
        while time.time() < fim:
            n = p.ser.in_waiting
            if n:
                bruto += p.ser.read(n)
                ultimo = time.time()
                if b"END" in bruto:
                    break
            elif bruto and time.time() - ultimo > 0.7:
                break
            time.sleep(0.02)
        mods = parse_calibracao(bruto.decode("utf-8", errors="ignore"))
        if mods is not None:
            return mods
        time.sleep(1)
    return None


def drenar(p, silencio_s=1.0, limite_s=15):
    ultimo = time.time()
    fim = time.time() + limite_s
    while time.time() < fim:
        n = p.ser.in_waiting
        if n:
            p.ser.read(n)
            ultimo = time.time()
        elif time.time() - ultimo > silencio_s:
            return True
        time.sleep(0.05)
    return False


def achar_alinhamento(dados):
    melhor, melhor_pct = 0, -1.0
    for off in range(4):
        n = (len(dados) - off) // 4 * 4
        if n < 400:
            continue
        a = np.frombuffer(dados[off:off + n], dtype="<u4")
        cont = ((a >> 18) & 0x3F).astype(np.int64)
        pct = float(np.mean((np.diff(cont) % 64) == 1))
        if pct > melhor_pct:
            melhor, melhor_pct = off, pct
    return melhor, melhor_pct


class FiltroApp:
    """Spike filter do app Power Profiler. Mantem o estado entre blocos de 1 s."""

    def __init__(self):
        self.media = None
        self.media4 = None
        self.faixa_ant = None
        self.apos_spike = 0
        self.consecutivas = 0

    def processar(self, valores, faixas):
        saida = np.empty(len(valores))
        media, media4 = self.media, self.media4
        faixa_ant = self.faixa_ant
        apos_spike = self.apos_spike
        consecutivas = self.consecutivas

        for i, (adc, faixa) in enumerate(zip(valores.tolist(), faixas.tolist())):
            media4_ant, media_ant = media4, media
            media = adc if media is None else ALPHA * adc + (1.0 - ALPHA) * media
            media4 = adc if media4 is None else ALPHA5 * adc + (1.0 - ALPHA5) * media4

            if faixa_ant is None:
                faixa_ant = faixa

            if faixa_ant != faixa or apos_spike > 0:
                if faixa_ant != faixa:
                    consecutivas = 0
                    apos_spike = AMOSTRAS_SPIKE
                else:
                    consecutivas += 1

                if faixa == 4:
                    if consecutivas < 2 and media4_ant is not None:
                        media4, media = media4_ant, media_ant
                    adc = media4
                else:
                    adc = media
                apos_spike -= 1

            faixa_ant = faixa
            saida[i] = adc

        self.media, self.media4 = media, media4
        self.faixa_ant = faixa_ant
        self.apos_spike = apos_spike
        self.consecutivas = consecutivas
        return saida


def decodificar(dados, mods, cont_anterior):
    """Bytes brutos (multiplo de 4) -> (ua sem filtro, faixa, n_perdidas, ultimo_contador)."""
    a = np.frombuffer(dados, dtype="<u4")
    adc = (a & 0x3FFF).astype(np.float64) * 4
    faixa = np.minimum((a >> 14) & 0x7, 4).astype(np.int64)
    cont = ((a >> 18) & 0x3F).astype(np.int64)

    rwg = (adc - mods["O"][faixa]) * (ADC_MULT / mods["R"][faixa])
    ua = 1e6 * mods["UG"][faixa] * (
        rwg * (mods["GS"][faixa] * rwg + mods["GI"][faixa])
        + (mods["S"][faixa] * (VDD_MV / 1000) + mods["I"][faixa])
    )

    c = np.concatenate([[cont_anterior if cont_anterior is not None else cont[0] - 1], cont])
    saltos = (np.diff(c) % 64) - 1
    n_perdidas = int(np.sum(saltos[saltos > 0]))
    return ua, faixa, n_perdidas, int(cont[-1])


def log(msg):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def conectar(tentativas=15, pausa_s=20):
    """
    Abre a porta, para qualquer medicao pendente e le a calibracao.
    Se a porta nao ficar quieta, fecha e reabre (em vez de desistir de cara).
    Retorna (ppk2, mods) ou (None, None).
    """
    for t in range(1, tentativas + 1):
        ppk2 = None
        try:
            ppk2 = PPK2_API(PORTA)
            ppk2.ser.write(bytes([0x07]))   # AVERAGE_STOP
            time.sleep(0.3)
            ppk2.ser.write(bytes([0x07]))   # repete: o primeiro pode se perder no fluxo
            if drenar(ppk2):
                mods = ler_calibracao(ppk2)
                if mods is not None:
                    return ppk2, mods
                log(f"tentativa {t}/{tentativas}: nao consegui ler a calibracao")
            else:
                log(f"tentativa {t}/{tentativas}: a porta continua recebendo dados")
        except Exception as e:
            log(f"tentativa {t}/{tentativas}: erro ao abrir a porta: {e}")
        if ppk2 is not None:
            try:
                ppk2.ser.close()
            except Exception:
                pass
        time.sleep(pausa_s)
    return None, None


def duracao_ate_2359():
    """Segundos ate 23:59:00 de hoje (ou de amanha, se for tarde demais para hoje)."""
    agora = datetime.now()
    fim = agora.replace(hour=23, minute=59, second=0, microsecond=0)
    resta = (fim - agora).total_seconds()
    if resta < 3600:
        resta += 24 * 3600
    return resta

def iniciar(ppk2):
    ppk2.use_ampere_meter()
    ppk2.set_source_voltage(VDD_MV)
    ppk2.toggle_DUT_power("ON")
    ppk2.start_measuring()


def reconectar(ppk2):
    try:
        ppk2.ser.close()
    except Exception:
        pass
    novo, mods = conectar()
    if novo is not None:
        iniciar(novo)
    return novo, mods

def main():
    duracao = float(sys.argv[1]) if len(sys.argv) > 1 else duracao_ate_2359()
    sufixo = "_teste" if len(sys.argv) > 1 else ""

    os.makedirs(PASTA, exist_ok=True)
    nome_arquivo = os.path.join(PASTA, datetime.now().strftime("%Y-%m-%d") + sufixo + ".csv")

    def encerrar(signum, frame):
        raise SystemExit(0)   # faz o finally rodar e parar o PPK2

    signal.signal(signal.SIGTERM, encerrar)
    signal.signal(signal.SIGINT, encerrar)

    log(f"Iniciando. Duracao prevista: {duracao/3600:.2f} h")
    ppk2, mods = conectar()
    if ppk2 is None:
        log("ERRO: nao consegui conectar ao PPK2. Reconecte o cabo USB.")
        sys.exit(1)
    log(f"Calibracao lida do aparelho: O = {mods['O'].round(2)}")

    iniciar(ppk2)
    zeros_seguidos = 0

    filtro = FiltroApp()
    n_linhas = 0
    resto = b""
    alinhado = False
    cont_ant = None
    faixa_ant_bloco = None
    buffer_s = []
    t0 = time.monotonic()
    t_prox = t0 + INTERVALO_S

    try:
        with open(nome_arquivo, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(COLUNAS)
            f.flush()

            while time.monotonic() - t0 < duracao:
                n = ppk2.ser.in_waiting
                if n:
                    buffer_s.append(ppk2.ser.read(n))   # so le, nao decodifica aqui
                else:
                    time.sleep(0.002)

                if time.monotonic() >= t_prox:
                    t_prox += INTERVALO_S
                    if t_prox < time.monotonic():
                        t_prox = time.monotonic() + INTERVALO_S

                    dados = resto + b"".join(buffer_s)
                    buffer_s = []

                    if not alinhado:
                        if len(dados) < 4000:
                            continue
                        off, pct = achar_alinhamento(dados)
                        dados = dados[off:]
                        alinhado = True
                        log(f"Alinhamento: offset {off} (contador {pct*100:.1f}%)")

                    uteis = len(dados) // 4 * 4
                    resto = dados[uteis:]
                    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    if uteis == 0:
                        w.writerow([agora, "", "", "", "", 0, 0, 0])
                        zeros_seguidos += 1
                        if zeros_seguidos >= 10:
                            log("10 s sem dados do PPK2, reconectando...")
                            f.flush()
                            novo, novo_mods = reconectar(ppk2)
                            if novo is None:
                                log("ERRO: reconexao falhou.")
                                break
                            ppk2, mods = novo, novo_mods
                            filtro = FiltroApp()
                            resto, buffer_s = b"", []
                            alinhado, cont_ant, faixa_ant_bloco = False, None, None
                            zeros_seguidos = 0
                            t_prox = time.monotonic() + INTERVALO_S
                            log("Reconectado, medicao reiniciada.")
                    else:
                        zeros_seguidos = 0
                        ua, faixa, perdidas, cont_ant = decodificar(dados[:uteis], mods, cont_ant)
                        fil = filtro.processar(ua, faixa)

                        f_ref = np.concatenate([[faixa[0] if faixa_ant_bloco is None
                                                 else faixa_ant_bloco], faixa])
                        trocas = np.flatnonzero(np.diff(f_ref) != 0)
                        faixa_ant_bloco = int(faixa[-1])

                        valido = np.ones(len(ua), dtype=bool)
                        for k in range(-1, 5):
                            idx = trocas + k
                            valido[idx[(idx >= 0) & (idx < len(ua))]] = False
                        sem_trocas = float(ua[valido].mean()) if valido.any() else float("nan")

                        nb = len(fil) // 100 * 100          # blocos de 100 amostras = 1 ms
                        max_1ms = (float(fil[:nb].reshape(-1, 100).mean(axis=1).max())
                                   if nb else float(fil.max()))

                        w.writerow([agora,
                                    round(float(fil.mean()), 3),
                                    round(float(np.median(fil)), 3),
                                    round(max_1ms, 3),
                                    round(sem_trocas, 3),
                                    len(ua), perdidas, len(trocas)])
                    f.flush()
                    n_linhas += 1
    finally:
        try:
            ppk2.stop_measuring()
        except Exception as e:
            log(f"aviso: stop_measuring falhou: {e}")
        try:
            ppk2.ser.write(bytes([0x07]))   # garante que o PPK2 pare de enviar
            drenar(ppk2, silencio_s=0.5, limite_s=5)
            ppk2.ser.close()
        except Exception as e:
            log(f"aviso: nao consegui deixar a porta quieta: {e}")
        log(f"Finalizado. Arquivo: {nome_arquivo} ({n_linhas} linhas)")


if __name__ == "__main__":
    main()