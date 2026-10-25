# CheckLoc

CheckLoc est une application Streamlit de pointage GPS. Les utilisateurs se
connectent avec Authentik, choisissent un POI, puis enregistrent une arrivée
(`Check-in`) ou un départ (`Check-out`). Chaque pointage est ajouté à
`log_location.csv` avec l'utilisateur, le POI, l'horodatage, les coordonnées GPS,
la précision de localisation et une empreinte de l'appareil.

## Prérequis et configuration

- Python et un environnement virtuel dans `.venv`.
- Les dépendances et commandes du projet sont déclarées dans `pyproject.toml`.
- Un fournisseur Authentik configuré pour l'authentification Streamlit.

Avec `uv`, installez les dépendances et les commandes du projet depuis la racine :

```bash
uv sync
```

Cette installation rend disponibles les commandes `checkloc` (application
Streamlit) et `analyse-poi` (analyse des pointages). `requirements.txt` conserve
également la liste des dépendances pour les installations qui l'utilisent. Pour
une installation avec pip, activez votre environnement virtuel puis lancez
`pip install .`. Avec `uv`, l'analyse se lance avec `uv run analyse-poi`.

Avant le premier démarrage, configurez les secrets localement :
- `.streamlit/secrets.toml` doit contenir la configuration d'authentification
  Streamlit, notamment les sections `[auth]` et `[auth.authentik]` adaptées à
  votre fournisseur. 


Ne publiez pas ces fichiers ni leurs valeurs. Le script s'arrête au démarrage
si les identifiants Authentik ou la configuration Streamlit sont absents.

### Note: app_simpleauth.py
app_simpleauth est une version de l'app primitive, sans authentitication par Authentik (simple login).
Cette version n'est plus maintenue, elle est présente pour reference uniquement


## Démarrage avec PM2

Depuis la racine du projet, initialisez le processus PM2 avec :

```bash
pm2 start /home/jch_m/Proj/CheckLoc/.venv/bin/streamlit \
  --name "CheckLoc" \
  --cwd /home/jch_m/Proj/CheckLoc \
  --interpreter /home/jch_m/Proj/CheckLoc/.venv/bin/python \
  -- run /home/jch_m/Proj/CheckLoc/app.py \
  --server.port 8520 \
  --server.address 0.0.0.0
```

L'interpréteur Python de l'environnement `.venv` doit être indiqué explicitement
à PM2 ; `--interpreter python3` peut sélectionner un Python système qui ne
contient pas les dépendances du projet. L'application écoute sur le port `8520`.
Le répertoire de travail est fixé à la racine du projet afin que les chemins
relatifs, notamment celui de `log_location.csv`, pointent au bon endroit.

Commandes utiles pour gérer le processus :

```bash
pm2 status
pm2 logs CheckLoc
pm2 restart CheckLoc
pm2 save
```

## Analyse et visualisation des POI

`analyse_poi.py` lit les pointages, génère une carte interactive et exporte des
statistiques par POI. Après avoir enregistré des pointages, lancez depuis la
racine du projet :

```bash
analyse-poi
```

Par défaut, le script lit `log_location.csv` et crée dans `analyse_result/` :

- `carte_poi.html` : carte Folium avec marqueurs regroupés par POI. Les fenêtres
  des marqueurs affichent la fréquence des arrivées, la durée moyenne, le
  nombre de pointages à ces coordonnées et la précision GPS moyenne.
- `statistiques_poi.csv` : fréquence des check-ins et statistiques de durée
  (nombre de visites appariées, moyenne, médiane et durée totale en minutes).

Les durées sont calculées en associant les check-ins et check-outs du même
utilisateur et du même POI. Les pointages sans événement correspondant sont
signalés et ne contribuent pas aux durées. La fréquence, elle, compte tous les
check-ins.

Les chemins d'entrée et de sortie peuvent être remplacés :

```bash
analyse-poi \
  --input chemin/vers/pointages.csv \
  --map-output analyse_result/carte_poi.html \
  --stats-output analyse_result/statistiques_poi.csv
```

Le CSV doit contenir les colonnes `Horodatage`, `Utilisateur`, `POI`, `Action`,
`Latitude` et `Longitude`. `Action` doit être `Check-in` ou `Check-out`.
`Précision (m)` est facultative ; en son absence, les précisions ne sont pas
disponibles dans les résultats.
Les lignes dont le POI est vide sont ignorées avec un avertissement ; les autres
données manquantes ou invalides restent signalées comme une erreur.
