import csv
import os
import sys
from datetime import datetime

import numpy as np

PASTA = "/Users/iot/ppk_logs"

if len(sys.argv) > 1:
    caminho = sys.argv[1]
else:
    caminho = os.path.join(PASTA, datetime.now().strftime("%Y-%m-%d") + ".csv")

horas = {}
with open(caminho, newline="") as f:
    for linha in csv.DictReader(f):
        try:
            hora = linha["timestamp"][11:13]
            valores = (
                float(linha["media_app_uA"]),
                float(linha["mediana_uA"]),
                float(linha["max_1ms_uA"]),
                float(linha["media_sem_trocas_uA"]),
                int(linha["n_perdidas"]),
            )
        except (ValueError, KeyError, TypeError):
            continue   # linha vazia ou incompleta
        horas.setdefault(hora, []).append(valores)

if not horas:
    raise SystemExit(f"Sem dados validos em {caminho}")

print(f"Arquivo: {caminho}\n")
print("hora | linhas | media_app | mediana | media_sem_trocas | max_1ms | perdidas")
tudo = []
for hora in sorted(horas):
    d = np.array(horas[hora])
    tudo.append(d)
    print(f"{hora}h  | {len(d):6d} | {d[:, 0].mean():9.1f} | {np.median(d[:, 1]):7.1f} | "
          f"{d[:, 3].mean():16.1f} | {d[:, 2].max():7.1f} | {int(d[:, 4].sum()):8d}")

d = np.vstack(tudo)
print(f"\nTOTAL: {len(d)} linhas ({len(d)/3600:.2f} h)")
print(f"  media (filtro do app):   {d[:, 0].mean():.1f} uA")
print(f"  mediana das medianas:    {np.median(d[:, 1]):.1f} uA")
print(f"  media sem trocas:        {d[:, 3].mean():.1f} uA")
print(f"  maior pico de 1 ms:      {d[:, 2].max():.1f} uA")
print("  (valores em microampere; unidades como no app: 1000 uA = 1 mA)")