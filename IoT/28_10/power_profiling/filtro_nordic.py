import time

import numpy as np
from ppk2_api.ppk2_api import PPK2_API

PORTA = "/dev/cu.usbmodemE52AC03CFDE12"
SEGUNDOS = 10
ADC_MULT = 1.8 / 163840
VDDS_MV = (3300, 5000)          # compara os dois valores de VDD na formula
CHAVES_CAL = ("R", "GS", "GI", "O", "S", "I", "UG")

# Parametros do spike filter do app (nordicsemi/pc-nrfconnect-ppk, serialDevice.ts)
ALPHA = 0.18                    # faixas 0 a 3
ALPHA5 = 0.06                   # faixa 4
AMOSTRAS_SPIKE = 3              # amostras apos a troca de faixa que usam a media movel


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


def corrente_ua(a, faixa, mods, vdd_mv):
    """Mesma formula do app (getAdcResult, sem o filtro), em microampere."""
    adc = (a & 0x3FFF).astype(np.float64) * 4
    rwg = (adc - mods["O"][faixa]) * (ADC_MULT / mods["R"][faixa])
    return 1e6 * mods["UG"][faixa] * (
        rwg * (mods["GS"][faixa] * rwg + mods["GI"][faixa])
        + (mods["S"][faixa] * (vdd_mv / 1000) + mods["I"][faixa])
    )


def filtro_app(valores, faixas):
    """Reproduz o spike filter do app, amostra por amostra (e sequencial por natureza)."""
    saida = np.empty(len(valores))
    media = media4 = None
    faixa_ant = None
    apos_spike = 0
    consecutivas = 0
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
                # nas 2 primeiras amostras da faixa 4, usa a media anterior a troca
                if consecutivas < 2 and media4_ant is not None:
                    media4, media = media4_ant, media_ant
                adc = media4
            else:
                adc = media
            apos_spike -= 1

        faixa_ant = faixa
        saida[i] = adc
    return saida


def resumo(nome, v):
    print(f"{nome:<34} media {v.mean():9.2f} | mediana {np.median(v):9.2f} | max {v.max():10.2f}")


def main():
    p = PPK2_API(PORTA)
    p.ser.write(bytes([0x07]))   # AVERAGE_STOP
    if not drenar(p):
        raise SystemExit("A porta continua recebendo dados. Reconecte o cabo USB.")

    mods = ler_calibracao(p)
    if mods is None:
        raise SystemExit("Nao consegui ler a calibracao. Reconecte o cabo USB.")
    print("Calibracao lida do aparelho: O =", mods["O"].round(2), "| R =", mods["R"].round(3))

    p.use_ampere_meter()
    p.set_source_voltage(3300)
    p.toggle_DUT_power("ON")
    p.start_measuring()

    bruto = bytearray()
    try:
        fim = time.time() + SEGUNDOS
        while time.time() < fim:
            n = p.ser.in_waiting
            if n:
                bruto += p.ser.read(n)
            else:
                time.sleep(0.002)
    finally:
        p.stop_measuring()

    dados = bytes(bruto)
    off, pct = achar_alinhamento(dados[:4000])
    dados = dados[off:]
    dados = dados[:len(dados) // 4 * 4]
    a = np.frombuffer(dados, dtype="<u4")
    faixa = np.minimum((a >> 14) & 0x7, 4).astype(np.int64)
    cont = ((a >> 18) & 0x3F).astype(np.int64)
    perdidas = int(np.sum(((np.diff(cont) % 64) - 1)[((np.diff(cont) % 64) - 1) > 0]))
    trocas = np.flatnonzero(np.diff(faixa) != 0) + 1

    print(f"\nalinhamento: offset {off} (contador {pct*100:.1f}%) | {len(a)} amostras | "
          f"perdidas: {perdidas} | trocas de faixa: {len(trocas)}")
    print("amostras por faixa:", {r: int((faixa == r).sum()) for r in range(5)})

    valido = np.ones(len(a), dtype=bool)
    for k in range(-1, 5):
        idx = trocas + k
        valido[idx[(idx >= 0) & (idx < len(a))]] = False

    for vdd in VDDS_MV:
        ua = corrente_ua(a, faixa, mods, vdd)
        filtrado = filtro_app(ua, faixa)

        n = len(ua) // 100 * 100        # blocos de 100 amostras = 1 ms = 1000 amostras/s do app
        blocos_raw = ua[:n].reshape(-1, 100).mean(axis=1)
        blocos_fil = filtrado[:n].reshape(-1, 100).mean(axis=1)

        print(f"\n===== VDD = {vdd} mV  (unidade: uA) =====")
        resumo("1) sem filtro, tudo incluido", ua)
        resumo("2) filtro do app (spike filter)", filtrado)
        resumo("3) excluindo ao redor das trocas", ua[valido])
        print(f"   max das medias de 1 ms: sem filtro {blocos_raw.max():.1f} | "
              f"filtro do app {blocos_fil.max():.1f}")

    print("\nCompare a linha 2 com o average e o max do app (mesmo circuito, mesma hora).")


if __name__ == "__main__":
    main()