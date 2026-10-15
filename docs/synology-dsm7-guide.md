# Déploiement de Element Server Suite Community sur Synology DSM 7.1

Ce guide vous accompagne pas à pas dans l'installation et la configuration de **Element Server Suite Community (ESS Community)** sur votre NAS Synology équipé de **DSM 7.1**.

---

### Architecture du conteneur Synology All-in-One

Le conteneur regroupe de manière optimisée et autonome tous les composants nécessaires d'Element Server Suite Community :

- **Synapse** : Le serveur Matrix de référence.
- **Matrix Authentication Service (MAS)** : Le moteur moderne d'authentification et de gestion des identités (Matrix 2.0 / OIDC).
- **Element Web** : Le client web officiel Matrix préconfiguré.
- **Element Admin** : La console web d'administration de votre serveur.
- **PostgreSQL 16** : Base de données relationnelle haute performance préconfigurée en interne.
- **Caddy (Reverse proxy interne)** : Aiguille automatiquement les requêtes (`/_matrix`, `/_synapse`, `/auth`, `/admin`, `/` et `.well-known`).
- **Supervisor** : Gestionnaire de processus robuste assurant la persistance et le redémarrage des services.

Toutes les données, configurations, bases de données, clés de chiffrement et médias sont stockés de façon persistante dans un unique dossier `/data` sur votre NAS.

---

### Prérequis sur votre Synology NAS

1. **Paquet Docker** :
   - Ouvrez le **Centre de paquets** de DSM 7.1.
   - Recherchez et installez le paquet officiel **Docker** (fourni par Synology).

2. **Dossier de stockage persistant** :
   - Ouvrez **File Station**.
   - Dans le dossier partagé `docker`, créez un sous-dossier `element` (chemin complet : `/volume1/docker/element`).

3. **Nom de domaine & DNS** :
   - Disposez d'un nom de domaine ou sous-domaine (ex: `matrix.votredomaine.fr` ou votre DDNS Synology `votrenas.synology.me`).
   - Les enregistrements DNS (A / CNAME) doivent pointer vers l'adresse IP publique de votre box/routeur.

4. **Redirection de ports sur votre box / routeur** :
   - Redirigez les ports **TCP 80** et **TCP 443** vers l'adresse IP locale de votre NAS Synology.

5. **Certificat SSL Let's Encrypt dans DSM** :
   - Dans DSM, allez dans **Panneau de configuration** > **Sécurité** > **Certificat**.
   - Cliquez sur **Ajouter** > **Ajouter un nouveau certificat** > **Obtenir un certificat auprès de Let's Encrypt**.
   - Indiquez votre nom de domaine (ex: `matrix.votredomaine.fr`).

---

### Méthode 1 : Installation via l'interface graphique Docker de DSM 7.1 (Recommandée)

Cette méthode ne nécessite aucune ligne de commande.

#### Étape 1 : Téléchargement de l'image

L'image est construite par le workflow GitHub Actions `docker-synology.yml` et publiée sur le GitHub Container Registry (GHCR) à l'adresse :

`ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest`

(par exemple `ghcr.io/devfred78/ess-helm/ess-synology:latest`). Elle est disponible pour les architectures `linux/amd64` et `linux/arm64`.

> **Note :** l'artefact `*.dockerbuild` attaché à l'exécution du workflow n'est qu'un historique de build : il ne contient pas l'image.

1. **Visibilité du package** : un package GHCR est généralement privé lors de sa première publication. Sur GitHub, ouvrez l'onglet **Packages** de votre profil, puis **ess-synology** > **Package settings** > **Change visibility** :
   - rendez-le **Public** pour pouvoir le télécharger sans authentification ;
   - ou laissez-le privé et créez un *Personal Access Token (classic)* disposant du scope `read:packages`.

2. **Téléchargement sur le NAS (SSH)** : l'onglet **Registre** de l'application Docker de DSM 7.1 ne sait pas rechercher d'images sur GHCR. Activez SSH (**Panneau de configuration** > **Terminal & SNMP**), connectez-vous au NAS puis exécutez :
   ```bash
   # Uniquement si le package est privé (mot de passe = votre token read:packages)
   sudo docker login ghcr.io -u <votre-utilisateur>

   sudo docker pull ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest
   ```

3. **Alternative hors ligne** : depuis un PC équipé de Docker, exportez l'image dans une archive (remplacez `linux/amd64` par `linux/arm64` pour un NAS ARM 64 bits) :
   ```bash
   docker pull --platform linux/amd64 ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest
   docker save -o ess-synology.tar ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest
   ```
   Puis, dans l'application **Docker** de DSM : onglet **Image** > **Ajouter** > **Ajouter à partir d'un fichier** et sélectionnez `ess-synology.tar`.

#### Étape 2 : Création du conteneur
1. Allez dans l'onglet **Image**, sélectionnez `ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest` et cliquez sur **Lancer**.
2. **Paramètres généraux** :
   - Nom du conteneur : `ess-community`
   - Cochez **Activer le redémarrage automatique**.
   - Cliquez sur **Paramètres avancés**.

3. **Paramètres de volume** :
   - Allez dans l'onglet **Volume** > **Ajouter un dossier**.
   - Dossier sur le NAS : `docker/element`
   - Chemin d'accès dans le conteneur : `/data` (en lecture/écriture).

4. **Paramètres de port** :
   - Allez dans l'onglet **Paramètres de port**.
   - Port local : `8080` (ou un port libre de votre choix).
   - Port du conteneur : `8080`.
   - Type : `TCP`.

5. **Variables d'environnement** :
   - Allez dans l'onglet **Environnement** et ajoutez/modifiez les variables suivantes :
     - `SERVER_NAME` : `matrix.votredomaine.fr` (votre nom de domaine)
     - `PUBLIC_BASEURL` : `https://matrix.votredomaine.fr`
     - `INITIAL_ADMIN_USER` : `admin` (nom du compte administrateur initial)
     - `INITIAL_ADMIN_PASSWORD` : `UnMotDePasseTresSecurise!`
     - `TZ` : `Europe/Paris`

6. Cliquez sur **Appliquer**, puis **Suivant** et enfin **Terminé** pour démarrer le conteneur.

---

### Méthode 2 : Installation via Docker Compose ou Planificateur de tâches DSM

Si vous préférez déployer en ligne de commande ou via le planificateur de tâches de DSM :

1. Déposez le fichier `docker-compose.yml` dans `/volume1/docker/element/docker-compose.yml`.
2. Modifiez les variables `SERVER_NAME` et `PUBLIC_BASEURL` avec votre nom de domaine.
   Vérifiez également la ligne `image:` : sans variable `GITHUB_REPOSITORY` définie, elle pointe vers `ghcr.io/element-hq/ess-helm/ess-synology:latest`. Remplacez-la par le chemin de votre image (ex : `ghcr.io/devfred78/ess-helm/ess-synology:latest`) ou lancez la commande avec `GITHUB_REPOSITORY=<utilisateur>/<dépôt>` en préfixe.
3. Exécutez la commande suivante en SSH (ou via une tâche utilisateur déclenchée dans DSM) :
   ```bash
   cd /volume1/docker/element
   docker-compose up -d
   ```

---

### Configuration du Proxy Inversé et du SSL dans Synology DSM 7.1

Pour que votre serveur soit accessible de manière sécurisée en HTTPS avec Let's Encrypt et WebSocket activé :

1. Ouvrez le **Panneau de configuration** de DSM.
2. Allez dans **Portail de connexion** (ou *Portail des applications* selon la version) > onglet **Avancé** > **Proxy inversé**.
3. Cliquez sur **Créer** :
   - **Général** :
     - Nom de la description : `Element Matrix ESS`
     - **Source** :
       - Protocole : `HTTPS`
       - Nom d'hôte : `matrix.votredomaine.fr`
       - Port : `443`
       - Cochez **Activer HSTS**.
     - **Destination** :
       - Protocole : `HTTP`
       - Nom d'hôte : `localhost` (ou `127.0.0.1`)
       - Port : `8080`
   - **En-tête personnalisé** (Indispensable pour le protocole Matrix et les WebSockets) :
     - Cliquez sur **Créer** > **WebSocket**.
     - DSM configure automatiquement les en-têtes `Upgrade` et `Connection`.

4. **Association du certificat SSL** :
   - Allez dans **Panneau de configuration** > **Sécurité** > **Certificat**.
   - Cliquez sur **Paramètres**.
   - Repérez la ligne correspondant à votre proxy inversé `matrix.votredomaine.fr` et assignez-lui votre certificat Let's Encrypt.
   - Cliquez sur **OK**.

---

### Accès aux Services & Utilisation

Une fois le proxy inversé configuré, votre suite Element est immédiatement disponible :

- **Client Web Element** : `https://matrix.votredomaine.fr/`
- **Console d'administration Element Admin** : `https://matrix.votredomaine.fr/admin/`
- **Point d'entrée Matrix (Synapse)** : `https://matrix.votredomaine.fr/_matrix/`
- **Service d'authentification (MAS)** : `https://matrix.votredomaine.fr/auth/`

#### Connexion initiale :
1. Rendez-vous sur `https://matrix.votredomaine.fr/`.
2. Connectez-vous avec l'identifiant `admin` et le mot de passe défini dans `INITIAL_ADMIN_PASSWORD`.

---

### Gestion des Utilisateurs

Par défaut, l'auto-inscription publique est désactivée par sécurité. Vous pouvez créer de nouveaux utilisateurs à tout moment.

#### Option A : Depuis l'interface Docker de DSM
1. Dans l'application **Docker** de DSM, allez dans **Conteneur**, sélectionnez `ess-community` et cliquez sur **Détails**.
2. Allez dans l'onglet **Terminal** > **Créer** > lancez `bash`.
3. Tapez la commande suivante :
   ```bash
   register-user
   ```
4. Suivez l'assistant interactif pour saisir le nom d'utilisateur, le mot de passe et définir s'il est administrateur.

#### Option B : En ligne de commande non interactive (SSH)
```bash
docker exec -it ess-community mas-cli manage register-user --yes --admin alice --config /data/config/mas.yaml
docker exec -it ess-community mas-cli manage set-password --yes --password "MotDePasseAlice123!" alice --config /data/config/mas.yaml
```

---

### Connexion avec les Applications Mobiles et Desktop (Element X, iOS, Android, Desktop)

1. Installez **Element** ou **Element X** sur votre smartphone ou ordinateur.
2. Choisissez **Changer de serveur d'accueil** (*Change homeserver*).
3. Entrez simplement votre nom de domaine : `matrix.votredomaine.fr`.
4. La découverte automatique `.well-known` configurée dans le conteneur orientera automatiquement l'application vers votre serveur et son service d'authentification MAS.
5. Saisissez vos identifiants pour vous connecter.

---

### Sauvegarde et Restauration sur Synology

Toutes les données vitales se trouvant dans `/volume1/docker/element`, la sauvegarde est ultra simple :

1. **Sauvegarde complète** :
   - Utilisez **Hyper Backup** ou **Snapshot Replication** sur DSM pour sauvegarder le dossier `docker/element`.
   - Cela sauvegarde l'ensemble :
     - `config/` : Fichiers de configuration générés.
     - `secrets/` : Clés privées de signature Synapse, RSA/ECDSA pour MAS et tokens.
     - `postgres/` : Bases de données PostgreSQL complètes (comptes, salons, messages chiffrés).
     - `media/` : Photos, fichiers et pièces jointes partagés.

2. **Restauration** :
   - Restaurez le dossier `docker/element` sur n'importe quel Synology ou serveur Docker et relancez le conteneur : votre serveur redémarre exactement à l'état sauvegardé sans perte de données.
