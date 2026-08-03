"""
Demo localizations for the LumaSkin ad script.
Used as fallback when no API keys are available.
"""

DEMO_LOCALIZED_EN = """TITLE: LumaSkin -- 30s Ad Script (English)
LANGUAGE: en
TARGET_PLATFORM: Meta / TikTok

---

[HOOK - 0-5s, fast-paced, on-screen text]
"Tired of skincare that promises the world and delivers nothing?"

[PROBLEM - 5-12s, B-roll of frustrated woman looking at mirror]
"You've tried the 12-step routines. The $200 creams. The viral hacks.
And your skin still isn't where you want it to be."

[SOLUTION - 12-22s, product hero shot, glowing skin results]
"Meet LumaSkin. The serum 50,000 women switched to last month.
One drop. Clinically-proven results in 7 days. No parabens. No false promises.
Just science-backed radiance that actually works."

[CTA - 22-30s, urgency, link overlay]
"Try LumaSkin risk-free for 30 days. If you don't see results, it's free.
Tap the link in bio. Your skin is waiting."
"""

DEMO_LOCALIZED_ES = """TITLE: LumaSkin -- Anuncio 30s (Espanol)
LANGUAGE: es
TARGET_PLATFORM: Meta / TikTok

---

[HOOK - 0-5s, ritmo rapido, texto en pantalla]
"Cansada de cremas que prometen milagros y no cumplen nada?"

[PROBLEM - 5-12s, B-roll de mujer frustrada mirandose al espejo]
"Probaste la rutina de 12 pasos. Las cremas de $200. Los trucos virales.
Y tu piel? Sigue sin estar donde queres."

[SOLUTION - 12-22s, plano hero del producto, resultados visibles]
"Conoce LumaSkin. El serum que 50.000 mujeres eligieron el mes pasado.
Una gota. Resultados comprobados en 7 dias. Cero parabenos. Cero promesas vacias.
Solo luminosidad respaldada por la ciencia. Resultados que se ven."

[CTA - 22-30s, urgencia, link en pantalla]
"Proba LumaSkin sin riesgo por 30 dias. Si no ves resultados, te devolvemos tu dinero.
Entra al link en la bio. Tu piel te esta esperando."
"""

DEMO_LOCALIZED_FR = """TITLE: LumaSkin -- Pub 30s (Francais)
LANGUAGE: fr
TARGET_PLATFORM: Meta / TikTok

---

[HOOK - 0-5s, rythme rapide, texte a l'ecran]
"Marre des cremes qui promettent la lune et ne font rien?"

[PROBLEM - 5-12s, B-roll d'une femme frustree devant son miroir]
"Tu as tout essaye. La routine en 12 etapes. Les cremes a 200 euros. Les astuces virales.
Et ta peau? Toujours pas la ou tu veux qu'elle soit."

[SOLUTION - 12-22s, plan produit hero, resultats eclatants]
"Voici LumaSkin. Le serum que 50 000 femmes ont adopte le mois dernier.
Une goutte. Des resultats cliniquement prouves en 7 jours. Sans parabene. Sans fausse promesse.
Juste un eclat scientifiquement prouve. Des resultats visibles."

[CTA - 22-30s, urgence, lien superpose]
"Essayez LumaSkin sans risque pendant 30 jours. Sans resultat? Rembourse.
Cliquez sur le lien dans la bio. Votre peau n'attend plus que vous."
"""

DEMO_LOCALIZED_DE = """TITLE: LumaSkin -- 30s Werbespot (Deutsch)
LANGUAGE: de
TARGET_PLATFORM: Meta / TikTok

---

[HOOK - 0-5s, schnelles Tempo, Texteinblendung]
"Keine Lust mehr auf Hautpflege, die alles verspricht und nichts halt?"

[PROBLEM - 5-12s, B-Roll einer frustrierten Frau vor dem Spiegel]
"Du hast die 12-Schritte-Routine ausprobiert. Die 200-Euro-Cremes. Die viralen Hacks.
Und deine Haut? Noch immer nicht da, wo du sie haben willst."

[SOLUTION - 12-22s, Produkt-Hero-Shot, strahlende Haut-Ergebnisse]
"Das ist LumaSkin. Das Serum, zu dem 50.000 Frauen letzten Monat gewechselt haben.
Ein Tropfen. Klinisch belegte Ergebnisse in 7 Tagen. Ohne Parabene. Ohne leere Versprechen.
Nur wissenschaftlich fundierte Strahlkraft. Ergebnisse, die man sieht."

[CTA - 22-30s, Dringlichkeit, Link-Overlay]
"Teste LumaSkin 30 Tage risikofrei. Keine Ergebnisse? Du bekommst dein Geld zurueck.
Klick auf den Link in der Bio. Deine Haut wartet auf dich."
"""

LANGUAGE_MAP = {
    "en": DEMO_LOCALIZED_EN,
    "es": DEMO_LOCALIZED_ES,
    "fr": DEMO_LOCALIZED_FR,
    "de": DEMO_LOCALIZED_DE,
}


def get_demo_localization(lang: str) -> str:
    """Return a handcrafted demo localization for the given language."""
    if lang in LANGUAGE_MAP:
        return LANGUAGE_MAP[lang].strip()
    return f"[DEMO LOCALIZED SCRIPT - {lang}]\n\nLocalized script would appear here.\nSet OPENAI_API_KEY or ANTHROPIC_API_KEY for live AI translation."
