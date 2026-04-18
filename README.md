# CIH Farm Stage Classifier

Microservice déployé sur Render qui reçoit un rapport d'évaluation satellitaire d'une exploitation agricole et retourne :
- le **stade agricole actuel** (en français)
- un niveau de **confiance**
- un **paragraphe analytique** destiné à l'équipe crédit CIH

---

## Contexte projet

Ce service est le deuxième modèle du pipeline AgriCrédit CIH. Il s'insère après le modèle de scoring de qualité (modèle 1) qui interroge Google Earth Engine pour produire un rapport satellitaire sur 24 mois. Ce rapport est envoyé ici pour être interprété et classifié.

**Problème adressé :** Les agriculteurs ruraux marocains n'ont pas accès aux services bancaires (pas d'agence proche, pas d'historique de crédit). AgriCrédit leur permet d'envoyer leur localisation via WhatsApp — le pipeline satellite calcule un score de risque crédit et classe l'exploitation, sans que l'agriculteur n'ait à se déplacer.

---

## Architecture du pipeline complet

```
WhatsApp (agriculteur envoie sa localisation)
        ↓
      n8n
        ↓
Modèle 1 — /assess  (Google Earth Engine + XGBoost)
  Sentinel-2 · MODIS · CHIRPS · SMAP → rapport JSON 24 mois
        ↓
Modèle 2 — /classify  (ce service)
  Claude Haiku → stade agricole + paragraphe analytique
        ↓
Dashboard CIH — décision crédit + proposition de services
  (collecte · stockage · vente)
```

---

## Données satellitaires utilisées (entrée)

Le rapport JSON en entrée est produit par le Modèle 1 à partir de 4 sources satellites :

| Source | Variable | Capteur |
|--------|----------|---------|
| Sentinel-2 | NDVI, GNDVI, NDWI, SAVI | ESA / Copernicus |
| MODIS MOD11A1 | Température de surface (LST) | NASA |
| CHIRPS | Précipitations quotidiennes | UCSB-CHG |
| SMAP SPL4SMGP | Humidité du sol | NASA |

---

## Méthodologie de classification

Le modèle utilise **Claude Haiku** avec `temperature=0` (sorties déterministes) et un prompt système de ~200 lignes encodant 4 règles agronomiques prioritaires.

### Stades possibles

| # | Stade |
|---|-------|
| 1 | préparation de la terre |
| 2 | semis / plantation |
| 3 | croissance végétative |
| 4 | montaison / maturation |
| 5 | récolte |
| 6 | repos / jachère |

### Règles de classification (par ordre de priorité)

**Règle 1 — Tendance NDVI (poids absolu)**
Combine `ndvi_trend` + `ndvi_slope_per_month` + `mean_ndvi` :
- `improving` + slope > 0.0015 + NDVI < 0.25 → semis / plantation
- `improving` + slope > 0.0015 + NDVI ≥ 0.25 → croissance végétative
- `improving` + slope ≤ 0.0015 → semis / plantation (hausse lente)
- `declining` + NDVI > 0.28 → récolte
- `declining` + NDVI ≤ 0.28 → repos / jachère ou préparation

**Règle 2 — Niveau absolu NDVI (confirmation)**
- ≥ 0.40 → montaison / maturation
- 0.28–0.39 → croissance végétative ou montaison
- 0.18–0.27 → semis / plantation
- < 0.18 → préparation de la terre ou repos

**Règle 3 — Humidité du sol (affinage)**
- soil_moisture > 25 % + NDVI < 0.22 → semis / plantation
- soil_moisture < 15 % + NDVI > 0.30 → montaison / maturation
- dry_season_sm < 12 % + NDVI élevé → récolte imminente

**Règle 4 — Calendrier agricole marocain (tie-breaker)**

| Mois | Stade probable |
|------|---------------|
| Oct–Nov | préparation / semis céréales d'hiver |
| Déc–Fév | croissance végétative |
| Mar–Avr | montaison / maturation |
| Mai–Juin | récolte céréales ou semis maraîchage |
| Juil–Sept | repos / jachère |

### Niveau de confiance
- **haute** : règles 1, 2 et 3 concordantes
- **moyenne** : règles 1 et 2 concordantes
- **faible** : règles contradictoires ou données insuffisantes

---

## API

### `GET /`
Health check.

**Réponse :**
```json
{ "status": "ok", "service": "CIH Farm Stage Classifier" }
```

---

### `POST /classify`

**Corps de la requête (JSON) :** rapport complet produit par le Modèle 1.

```json
{
  "farm": { "lat": 33.88, "lon": -5.55, "region": "Meknès, Morocco" },
  "assessment_date": "2026-04-18",
  "data_window": { "from": "2024-04", "to": "2026-03", "months": 24 },
  "quality_score": 47.0,
  "sub_scores": {
    "productivity": 87.8,
    "consistency": 24.5,
    "trend": 43.1,
    "vegetation": 15.9,
    "resilience": 34.9
  },
  "vegetation": {
    "mean_ndvi": 0.2562,
    "mean_gndvi": 0.3676,
    "peak_ndvi": 0.3339,
    "peak_ndvi_month": "2026-02",
    "green_months": 9,
    "ndvi_slope_per_month": 0.000903,
    "ndvi_trend": "improving"
  },
  "climate": {
    "avg_temperature_c": 26.75,
    "avg_rainfall_mm_month": 41.48,
    "total_rainfall_mm": 995.5,
    "avg_soil_moisture_pct": 22.8,
    "dry_season_sm_pct": 15.51,
    "stress_months_count": 7,
    "stress_months": ["2024-06", "2024-07", "2024-08", "2025-06", "2025-07", "2025-08", "2025-09"]
  },
  "resilience": {
    "avg_sm_during_stress": 15.31,
    "stress_months_count": 7
  }
}
```

**Réponse :**
```json
{
  "stage": "semis / plantation",
  "confidence": "moyenne",
  "paragraph": "L'exploitation située à Meknès présente un NDVI moyen de 0.26 en légère hausse (slope +0.0009/mois), confirmant un stade de semis ou de début de croissance en avril, période cohérente avec la fin du cycle des céréales d'hiver marocaines. Avec un score de productivité élevé (87.8/100) mais une consistance faible (24.5/100), l'exploitation démontre un fort potentiel de rendement mais une variabilité inter-annuelle préoccupante pour le remboursement d'un crédit. L'analyste CIH devra prêter attention aux 7 mois de stress hydrique enregistrés et à l'absence probable d'irrigation (humidité en saison sèche à 15.5 %), facteurs de risque à intégrer dans la décision de crédit."
}
```

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| API | FastAPI + Uvicorn |
| LLM | Claude Haiku (`claude-haiku-4-5-20251001`) |
| SDK | Anthropic Python SDK |
| Déploiement | Render (free tier) |
| Python | 3.11.9 |

---

## Installation locale

```bash
git clone https://github.com/RedaMohssine/cih_hackathon_model2.git
cd cih_hackathon_model2

pip install -r requirements.txt

# Créer le fichier .env
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Lancer l'API
uvicorn main:app --reload

# Tester en CLI
python classify_farm.py test_report.json
```

---

## Variables d'environnement

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Clé API Anthropic (Claude Enterprise) |

Sur Render, cette variable est configurée dans **Settings → Environment** et n'est jamais commitée dans le dépôt (`.env` est dans `.gitignore`).

---

## Intégration n8n

Ajouter un nœud **HTTP Request** après le nœud qui produit le rapport JSON :

- **Method :** POST
- **URL :** `https://cih-hackathon-model2-1.onrender.com/classify`
- **Body Content Type :** JSON
- **JSON Body :** `{{ JSON.stringify($json) }}`

La réponse `{ stage, confidence, paragraph }` est disponible dans le nœud suivant via `$json`.
