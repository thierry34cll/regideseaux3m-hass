# Changelog

Tous les changements notables de ce projet seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/fr-FR/1.0.0/),
et ce projet adhère à [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.1] - 2026-11-21

### Ajouté
- **Réauthentification** : si les identifiants deviennent invalides (mot de passe changé côté Régie), HA propose de les ressaisir sans supprimer l'entrée de configuration
- **Relevé quotidien à heure fixe** (champ « Heure de relevé quotidienne », défaut `05:00`, à l'installation et dans les options) à la place de l'intervalle glissant : l'heure de relevé ne dépend plus du dernier redémarrage de HA
- **Horodatage des statistiques à 23:00** (heure locale, heure pile requise par HA) au lieu de 00:00 : la conso du jour apparaît en fin de journée dans l'interface Statistiques
- **Sommes relatives** dans la statistique externe (index − index du premier relevé) : les deltas journaliers restent identiques dans le tableau Énergie, mais plus de pic artificiel du 1er jour (l'index complet compté comme conso d'un seul jour)
- **Attribution des relevés à leur date réelle de consommation** : les relevés (qui portent `dateReleve` côté API) sont écrits comme **statistique externe** `regiedeseauxmpl:<compteur>` (à sélectionner dans Énergie → Eau) via `async_add_external_statistics`, à la date du `dateReleve` (vérifié contre le site de la Régie) — HA ne permet pas d'antidater un état, et le capteur TOTAL_INCREASING a déjà ses propres statistiques
- **Option de lissage** (présente dès le formulaire d'installation et dans les options) (« Lisser la consommation sur les jours sans relevé ») : répartit la consommation cumulée d'un relevé sur les jours sans relevé (ex. 1 m³ après 3 jours → ~0,33 m³/jour)
- **Import de l'historique à l'installation** (option cochée par défaut, fenêtre large demandée à l'API) + option « écraser les données existantes » (purge via les API recorder uniquement, jamais d'accès direct à la base). Gardes-fous : exécution unique par entrée (flag persistant) et import idempotent (les jours déjà présents en statistiques ne sont jamais réimportés)
- Support multi-compteurs avec gestion individuelle
- Intégration native au tableau de bord Énergie/Eau de Home Assistant
- Service `regiedeseauxmpl.refresh_meters` pour rafraîchir manuellement
- Outils de diagnostic via l'intégration Diagnostics
- Traductions complètes en français et anglais
- Documentation complète pour HACS

### Modifié
- Migration des entrées existantes (v1 → v2) : `scan_interval` remplacé par `update_time` (`05:00` par défaut)
- Rechargement automatique de l'entrée quand les options changent
- Amélioration de la gestion des erreurs et des timeouts
- Optimisation de la session HTTP avec curl_cffi
- Meilleure restauration des états après redémarrage
- Amélioration des messages de log

### Corrigé
- Gestion des cookies BIG-IP pour une connexion stable
- Problèmes de TLS fingerprinting avec l'API
- Affichage des attributs des entités

---

## [0.2.2] - 2026-10-23

### Corrigé
- Paramètre `via_device` déprécié (HA 2026.8+, supprimé en 2027.8) retiré du `DeviceInfo` : il pointait vers un appareil parent jamais créé (#1)

### Ajouté
- Tests d'intégration sur un vrai Home Assistant (`tests_ha/`, `make test-ha`, étape CI)

---

## [0.2.1] - 2026-05-22

### Corrigé
- Ré-authentification automatique à l'expiration du `tokenAuthentique` :
  un 401/403 sur un appel de données déclenche désormais une nouvelle
  authentification suivie d'une nouvelle tentative. Auparavant, dès que le
  token expirait (sous l'intervalle de scrutation), l'intégration restait
  bloquée en erreur 401 indéfiniment et les capteurs passaient en
  `unavailable` jusqu'à un rechargement manuel.
- `async_add_entities` n'est plus `await` (callback synchrone) — corrige le
  `TypeError: 'NoneType' object can't be awaited` au démarrage de la
  plateforme `sensor`.

---

## [0.2.0] - 2025-01-XX

### Ajouté
- Version initiale pour HACS
- Interface de configuration UI complète
- Support de RestoreSensor pour persister les données
- Gestion des erreurs d'authentification

---

## [0.1.0] - 2024-XX-XX

### Ajouté
- Première version de l'intégration
- API client fonctionnel avec curl_cffi
- Récupération des index des compteurs
- Flux de configuration basique

[non publié]: https://github.com/iopsthecloud/regideseaux3m-hass/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/iopsthecloud/regideseaux3m-hass/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/iopsthecloud/regideseaux3m-hass/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/iopsthecloud/regideseaux3m-hass/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/iopsthecloud/regideseaux3m-hass/releases/tag/v0.1.0
