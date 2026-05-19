"""
Plota minutos de áudio coletados por música.
Uso: python stats.py    (gera stats.png)
"""

import matplotlib.pyplot as plt

DATA = [
    ("Hotel California", 5.50),
    ("November Rain", 5.16),
    ("Love i Need", 3.32),
    ("Ode to the Mets", 3.30),
    ("Counting Stars", 2.85),
    ("Dragostea Din Tei", 2.49),
    ("Disritmia", 2.49),
    ("Price Tag", 2.46),
    ("Fallen Down", 2.39),
    ("Vienna", 2.33),
    ("Please Mister Postman", 2.30),
    ("God's Plan", 2.08),
    ("Samurai", 1.68),
    ("País do Futebol", 1.66),
    ("Mulher de Fases", 1.56),
    ("Fico assim sem voce", 1.56),
    ("Jesus Chorou", 1.55),
    ("The Logical Song", 1.43),
    ("Dont look back in anger", 1.42),
    ("Knocking On Heavens Door", 1.40),
    ("Dogs", 1.38),
    ("Heroes", 1.32),
    ("Con Calma", 1.32),
    ("Just dance", 1.30),
    ("Like a rolling stone", 1.28),
    ("Spectre", 1.27),
    ("With or without you", 1.27),
    ("Blue Suede Shoes", 1.26),
    ("Bitch Lasagna", 1.26),
    ("Balada", 1.17),
    ("Ultima Noite", 1.15),
    ("Without Me", 1.11),
    ("Im Yours", 0.83),
    ("Convoque Seu Buda", 0.80),
    ("Every breath you take", 0.51),
    ("Stand by me", 0.35),
    ("Cidade Vizinha", 0.19),
    ("Garota de Ipanema", 0.18),
    ("Don't Stand So Close To me", 0.13),
]

DATA.sort(key=lambda x: x[1], reverse=True)
labels = [d[0] for d in DATA]
values = [d[1] for d in DATA]
total = sum(values)

fig, ax = plt.subplots(figsize=(14, 8))
bars = ax.bar(range(len(values)), values, color="#346538", edgecolor="white", linewidth=0.5)

ax.set_xticks(range(len(labels)))
ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=9)
ax.set_ylabel("Minutos de áudio", fontsize=11)
ax.set_title(tados por música  ({len(values)} músicas · {total:.1f} min total)",
    fontsize=13,
    pad=14,
)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.grid(axis="y", linestyle="--", alpha=0.3)

for bar, v in zip(bars, values):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.05,
        f"{v:.2f}",
        ha="center",
        va="bottom",
        fontsize=7,
        color="#555",
    )

plt.tight_layout()
plt.savefig("stats.png", dpi=160, bbox_inches="tight")
print(f"saved stats.png — {len(values)} músicas, {total:.2f} min")
