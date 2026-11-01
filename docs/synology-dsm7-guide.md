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
- **LiveKit SFU** et **MatrixRTC Authorisation Service** (`lk-jwt-service`) : le backend des appels audio/vidéo **Element Call** (appels 1:1 et de groupe dans Element Web et Element X, salons vidéo).
- **coturn** : serveur TURN utilisé par les appels 1:1 « historiques » des applications Element classiques (Element Android / iOS).
- **Caddy (Reverse proxy interne)** : Aiguille automatiquement les requêtes du port 8080 (`/_matrix`, `/_synapse`, `/auth`, `/livekit`, `/` et `.well-known`) et sert Element Admin sur un port dédié, 8088.
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

4. **Redirection de ports sur votre box / routeur** : redirigez les ports suivants vers l'adresse IP locale de votre NAS Synology (même numéro de port côté box et côté NAS) :

   | Port(s) | Protocole | Usage | Obligatoire |
   |---|---|---|---|
   | 80, 443 | TCP | Accès web HTTPS et certificat Let's Encrypt | Oui |
   | 8443 | TCP | Console d'administration Element Admin | Voir ci-dessous |
   | 7881 | TCP | Appels Element Call (flux audio/vidéo, repli TCP) | Pour les appels |
   | 7882 | UDP | Appels Element Call (flux audio/vidéo) | Pour les appels |
   | 3478 | UDP **et** TCP | Serveur TURN (appels 1:1 des applications Element classiques) | Recommandé |
   | 49160-49169 | UDP | Serveur TURN : ports de relais | Recommandé |

   > Le port 8443 est nécessaire pour ouvrir Element Admin **depuis Internet**, mais aussi depuis le réseau local avec l'adresse `https://matrix.votredomaine.fr:8443` : celle-ci pointe vers l'IP publique, et la box ne renvoie le trafic vers le NAS que pour les ports redirigés. Pour limiter la console au réseau local, redirigez-le quand même et restreignez l'accès dans DSM (voir [Configuration du Proxy Inversé](#configuration-du-proxy-inversé-et-du-ssl-dans-synology-dsm-71)).
   >
   > Les ports d'appel ne passent **pas** par le proxy inversé de DSM : ce sont des flux directs, qui doivent arriver tels quels jusqu'au conteneur. Sans eux, la connexion et les messages fonctionnent, mais les appels restent sans son ni image.

   Si votre box le permet, attribuez aussi au NAS une **adresse IP locale fixe** (bail DHCP statique), sans quoi les redirections cesseront de fonctionner le jour où son adresse change.

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
2. **Réseau** :
   - Sélectionnez **Utiliser les réseaux sélectionnés**, et choisissez **bridge**.

3. **Paramètres généraux** :
   - Nom du conteneur : `ess-community`
   - Cochez **Activer le redémarrage automatique**.
   - Cliquez sur **Paramètres avancés**.

4. **Variables d'environnement** :
   - Allez dans l'onglet **Environnement** et ajoutez/modifiez les variables suivantes :
     - `SERVER_NAME` : `matrix.votredomaine.fr` (votre nom de domaine)
     - `PUBLIC_BASEURL` : `https://matrix.votredomaine.fr`
     - `INITIAL_ADMIN_USER` : `admin` (nom du compte administrateur initial)
     - `INITIAL_ADMIN_PASSWORD` : `UnMotDePasseTresSecurise!`
     - `TZ` : `Europe/Paris`
   - Facultatif, pour la console d'administration : `ADMIN_BASEURL`, son adresse publique. Sans cette variable, l'adresse utilisée est celle de `PUBLIC_BASEURL` sur le port 8443 (`https://matrix.votredomaine.fr:8443`). Renseignez-la seulement si vous publiez la console autrement (autre port ou sous-domaine), par exemple `https://admin.votredomaine.fr`.
   - Facultatif, pour les appels audio/vidéo (voir [Appels audio et vidéo](#appels-audio-et-vidéo-element-call-et-turn)) :
     - `PUBLIC_IP` : l'adresse IP publique de votre box. À laisser vide dans un premier temps : elle est détectée automatiquement. Renseignez-la seulement si les appels se connectent mais restent sans son ni image.
     - `ENABLE_MATRIX_RTC` et `ENABLE_TURN` sont pré-remplies à `true`. Passez-les à `false` pour désactiver respectivement Element Call ou le serveur TURN.
   - Laissez les autres variables pré-remplies (héritées de l'image) telles quelles.
   - Si DSM refuse d'enregistrer parce qu'une variable est vide (cas de `SYNAPSE_VERSION_STRING` sur les images antérieures à ce correctif), renseignez-y la version de Synapse, par exemple `1.162.0` : cette valeur sert uniquement à l'affichage de la version du serveur.
   - Cliquez sur **Sauvegarder**, puis sur **Suivant**

5. **Paramètres des port** : DSM pré-remplit une ligne par port déclaré par l'image. Pour chacune, indiquez le **Port local** comme suit :

   | Port du conteneur | Type | Port local |
   |---|---|---|
   | 8080 | TCP | `8080` (ou un port libre de votre choix, à reporter dans le proxy inversé) |
   | 8088 | TCP | `8088` (ou un port libre de votre choix, à reporter dans le proxy inversé) |
   | 8448 | TCP | laissez `Auto` (inutilisé) |
   | 7881 | TCP | `7881` |
   | 7882 | UDP | `7882` |
   | 3478 | TCP | `3478` |
   | 3478 | UDP | `3478` |
   | 49160 à 49169 | UDP | le **même numéro** que le port du conteneur (`49160`, `49161`… `49169`) |

   - Hormis 8080 et 8088, les ports locaux doivent être **identiques** aux ports du conteneur : les clients se connectent directement au numéro de port annoncé par le serveur. Ne laissez pas `Auto`, qui attribuerait un port au hasard.
   - Si une ligne manque, ajoutez-la avec le bouton **+** en choisissant le bon type (TCP/UDP).
   - Si le TURN est désactivé (`ENABLE_TURN=false`), vous pouvez supprimer les lignes 3478 et 49160-49169.
   - Cliquez sur **Suivant**

6. **Paramètres de volume** :
   - Cliquez sur **Ajouter un dossier**.
   - Dossier sur le NAS : `docker/element`
   - Chemin d'accès dans le conteneur : `/data` (en lecture/écriture).
   - Cliquez sur **Suivant**

7. **Résumé** :
   - Vérifiez les éléments indiqués
   - Cochez la case **Exécuter ce conteneur lorsque l'assistant a terminé**
   - Cliquez sur **Effectué**

---

### Méthode 2 : Installation via Docker Compose ou Planificateur de tâches DSM

Si vous préférez déployer en ligne de commande ou via le planificateur de tâches de DSM :

1. Déposez le fichier `docker-compose.yml` dans `/volume1/docker/element/docker-compose.yml`.
2. Modifiez les variables `SERVER_NAME` et `PUBLIC_BASEURL` avec votre nom de domaine. Le port 8088 d'Element Admin et les ports d'appel (7881, 7882, 3478, 49160-49169) y sont déjà publiés : il reste à les rediriger sur la box (voir les prérequis).
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

4. Cliquez de nouveau sur **Créer** pour la console **Element Admin**. Element Admin ne fonctionne qu'à la racine d'une adresse : il dispose donc de son propre port, et non d'un chemin `/admin`.
   - **Général** :
     - Nom de la description : `Element Admin ESS`
     - **Source** :
       - Protocole : `HTTPS`
       - Nom d'hôte : `matrix.votredomaine.fr` (le même que pour la règle précédente : le certificat existant convient)
       - Port : `8443`
       - Cochez **Activer HSTS**.
       - Facultatif : dans **Profil de contrôle d'accès**, choisissez un profil qui n'autorise que votre réseau local (par exemple `192.168.1.0/24`), pour que la console ne soit pas joignable depuis Internet. Les profils se créent dans **Portail de connexion** > **Avancé** > **Profil de contrôle d'accès**.
     - **Destination** :
       - Protocole : `HTTP`
       - Nom d'hôte : `localhost`
       - Port : `8088`
   - Aucun en-tête personnalisé n'est nécessaire.
   - Si vous publiez la console sur un autre port ou sous un autre nom d'hôte, renseignez son adresse dans la variable `ADMIN_BASEURL` du conteneur (ex : `https://admin.votredomaine.fr`).

5. **Association du certificat SSL** :
   - Allez dans **Panneau de configuration** > **Sécurité** > **Certificat**.
   - Cliquez sur **Paramètres**.
   - Repérez les lignes correspondant à vos deux règles de proxy inversé (`matrix.votredomaine.fr` et `matrix.votredomaine.fr:8443`) et assignez-leur votre certificat Let's Encrypt.
   - Cliquez sur **OK**.

---

### Appels audio et vidéo (Element Call et TURN)

Le conteneur fournit tout ce qu'il faut pour les appels. Aucun service supplémentaire n'est à installer : il suffit d'ouvrir les ports.

#### Comment ça fonctionne

- **Element Call (MatrixRTC)** : c'est le système d'appel d'Element Web et d'Element X, pour les appels 1:1 comme pour les appels de groupe et les salons vidéo. Les clients découvrent automatiquement le service via `https://matrix.votredomaine.fr/.well-known/matrix/client`. Ils obtiennent ensuite un jeton auprès du *MatrixRTC Authorisation Service* (`/livekit/jwt`), puis se connectent au SFU LiveKit : la signalisation passe en WebSocket par `/livekit/sfu` (via le proxy inversé de DSM), et les flux audio/vidéo directement sur les ports **7881/TCP** et **7882/UDP**.
- **TURN (coturn)** : les applications Element « classiques » (Element Android / iOS, hors Element X) passent encore par des appels 1:1 historiques en pair à pair. Synapse leur fournit l'adresse du serveur TURN intégré et des identifiants temporaires. Le TURN relaie alors l'audio/vidéo quand les deux appareils ne peuvent pas se joindre directement (ports **3478** et **49160-49169/UDP**). Ces appels historiques sont limités à **deux personnes** : les appels de groupe nécessitent Element Call, donc Element X, Element Web ou Element Desktop.

Tous les secrets nécessaires (clé LiveKit, jetons de l'application service, secret TURN) sont générés au premier démarrage dans `docker/element/secrets/`.

#### Étape 1 : Ouvrir les ports

1. **Sur la box** : vérifiez les redirections de ports listées dans les [prérequis](#prérequis-sur-votre-synology-nas) (7881/TCP, 7882/UDP, 3478/UDP+TCP, 49160-49169/UDP).
2. **Dans Docker** : vérifiez que ces ports sont publiés avec des ports locaux identiques (étape 2.5 de la Méthode 1, ou `docker-compose.yml` de la Méthode 2).
3. **Dans le pare-feu de DSM** (seulement s'il est activé : **Panneau de configuration** > **Sécurité** > **Pare-feu**) :
   - Cliquez sur **Modifier les règles** pour le profil actif, puis sur **Créer**.
   - **Ports** : **Personnalisé**, puis **Personnaliser** : Type **Port de destination**, Protocole **TCP**, ports `7881,3478`.
   - **IP source** : **Toutes**. **Action** : **Autoriser**. Validez.
   - Créez une seconde règle identique avec le Protocole **UDP** et les ports `7882,3478,49160-49169`.
   - Placez ces règles **au-dessus** d'une éventuelle règle « Refuser tout », puis cliquez sur **OK**.

#### Étape 2 : Vérifier le fonctionnement

1. Dans l'application **Docker** de DSM, **Conteneur** > `ess-community` > **Détails** > **Journal** :
   - le bandeau de démarrage affiche les lignes `MatrixRTC` et `TURN (coturn)` ;
   - la ligne `IP publique annoncée par coturn : …` doit montrer l'adresse IP publique de votre box. Un message `ATTENTION : IP publique introuvable` signifie qu'il faut renseigner la variable `PUBLIC_IP` ;
   - les services `livekit`, `lk-jwt-service` et `coturn` doivent passer à l'état `RUNNING` sans redémarrer en boucle.
2. Depuis un navigateur :
   - `https://matrix.votredomaine.fr/.well-known/matrix/client` doit contenir `org.matrix.msc4143.rtc_foci` ;
   - `https://matrix.votredomaine.fr/livekit/jwt/healthz` doit répondre sans erreur (code 200) ;
   - `https://matrix.votredomaine.fr/livekit/sfu/` doit afficher `OK`.
3. Dans Element Web, rechargez complètement la page (**Ctrl + F5**) pour prendre en compte la nouvelle configuration. Lancez ensuite un appel vers un autre compte, idéalement depuis un smartphone **en 4G/5G** (hors de votre réseau Wi-Fi), pour tester le chemin réel depuis Internet.

#### Dépannage

- **Le message « Call failed due to misconfigured server » / « configurer un serveur TURN » apparaît encore** :
  - dans Element Web, rechargez la page (**Ctrl + F5**) : les appels doivent désormais passer par Element Call ;
  - depuis une application Element classique, vérifiez les ports TURN (3478 et 49160-49169) et la ligne `IP publique annoncée par coturn` du journal.
- **Ça sonne, mais après avoir décroché l'appel reste bloqué sur « Connexion en cours »** :
  - **Avec Element X** (Element Call) : dans le journal, cherchez les requêtes `/livekit/jwt/sfu/get`. Si seules des requêtes `OPTIONS` apparaissent, sans `POST` ni connexion à `/livekit/sfu`, le jeton d'appel n'est jamais obtenu. Cela se produisait avec les images antérieures à ce correctif, à cause d'en-têtes CORS envoyés en double : mettez à jour l'image.
  - **Avec les applications Element Classic** (appels historiques via TURN) : quand l'un des appareils est en 4G/5G, la connexion directe est presque toujours impossible (les opérateurs mobiles partagent leurs adresses IP), et tout passe par le relais coturn. Vérifiez en priorité la redirection des ports **49160-49169/UDP** (box, Docker, pare-feu DSM) : sans eux, l'appareil s'enregistre bien auprès du TURN, mais aucun son ne transite. Fermez ensuite complètement les applications Element Classic, puis relancez-les : elles ne redemandent les identifiants TURN qu'à leur démarrage.
  - **Le plus fiable** : utilisez **Element X** sur tous les appareils (Android et iOS). Ses appels passent par le serveur LiveKit, joignable directement, et ne dépendent pas du TURN.
- **Les appels à deux fonctionnent, mais pas les appels de groupe (3 personnes ou plus)** : il y a deux causes possibles, à vérifier dans l'ordre.
  1. **Les applications Element Classic (Element Android / iOS, hors Element X) ne savent pas rejoindre un appel de groupe Element Call.** Leurs appels historiques via le TURN sont strictement limités à deux personnes, en pair à pair. Au-delà, il faut Element Call, que seuls Element X, Element Web et Element Desktop prennent en charge. Tous les participants d'un appel de groupe doivent utiliser l'une de ces applications.
  2. **Dans un salon de groupe, seuls les modérateurs peuvent rejoindre l'appel.** Rejoindre un appel Element Call revient à publier un événement d'état (`org.matrix.msc3401.call.member`). Par défaut, Matrix réserve ces événements aux modérateurs (niveau 50). Element Web abaisse ce niveau à la création d'un salon, mais Element Classic et d'autres clients ne le font pas. Les appels à deux, eux, fonctionnent : dans un salon privé à deux, les deux personnes sont administrateurs. Dans le journal du conteneur, ce cas se signale par une erreur `You don't have permission to post that to the room. user_level (0) < send_level (50)` sur une requête `PUT …/state/org.matrix.msc3401.call.member/…`.
     - **Nouveaux salons** : le conteneur règle désormais ce niveau à 0 pour tous les salons de groupe, quel que soit le client utilisé pour les créer. Mettez l'image à jour.
     - **Salons existants** : le réglage ne s'applique pas rétroactivement. Un administrateur du salon doit le modifier une fois, dans Element Web ou Element Desktop : **Paramètres du salon** > **Rôles et permissions** > **Rejoindre des appels Element** : choisissez **Par défaut** (ou *Utilisateur*), puis enregistrez. Element X ne propose pas ce réglage.
- **Message `A peer IP 10.x.x.x denied` dans le journal de coturn** : il est normal et sans conséquence. Ce sont des adresses privées (réseau local, ou réseau interne de l'opérateur mobile) que les appareils proposent parmi d'autres, et vers lesquelles le relais refuse volontairement de relayer.
- **L'appel se connecte mais reste sans son ni image** : les flux audio/vidéo n'atteignent pas le conteneur.
  - Vérifiez les redirections 7881/TCP et 7882/UDP sur la box, dans Docker et dans le pare-feu DSM.
  - Renseignez la variable `PUBLIC_IP` avec l'IP publique de votre box (consultable sur l'interface de la box ou sur un site comme `ifconfig.me`), puis redémarrez le conteneur.
- **Les appels marchent en 4G mais pas depuis le Wi-Fi de la maison** (ou l'inverse) : depuis le réseau local, les appareils joignent le NAS par l'IP publique. La box doit donc savoir renvoyer ce trafic vers le réseau local (fonction *NAT loopback* / *hairpinning*, généralement active sur les box françaises). Consultez la documentation de votre box.
- **Votre IP publique change régulièrement** : LiveKit et coturn détectent l'IP publique au démarrage. Après un changement d'IP, redémarrez le conteneur. Une IP fixe, si votre fournisseur en propose, évite ce problème.
- **IP publique partagée (CGNAT)** : si l'IP « WAN » affichée par la box commence par `100.64.` à `100.127.`, ou si la box n'autorise qu'une plage de ports restreinte (IPv4 partagée), les redirections ne peuvent pas fonctionner. Demandez à votre fournisseur une IPv4 publique dédiée (certains l'attribuent gratuitement, sur simple demande depuis l'espace abonné).
- **Désactiver une fonctionnalité** : passez `ENABLE_MATRIX_RTC` ou `ENABLE_TURN` à `false` dans les variables d'environnement du conteneur (conteneur arrêté : **Modifier** > **Paramètres avancés** > **Environnement**), puis redémarrez-le. Avec `ENABLE_MATRIX_RTC=false`, Element Web revient aux appels historiques.

---

### Accès aux Services & Utilisation

Une fois le proxy inversé configuré, votre suite Element est immédiatement disponible :

- **Client Web Element** : `https://matrix.votredomaine.fr/`
- **Console d'administration Element Admin** : `https://matrix.votredomaine.fr:8443/` (l'ancienne adresse `https://matrix.votredomaine.fr/admin/` y redirige). Connectez-vous avec un compte administrateur, comme le compte `admin` initial : Element Admin passe par la page de connexion de MAS, puis revient sur la console.
- **Point d'entrée Matrix (Synapse)** : `https://matrix.votredomaine.fr/_matrix/`
- **Service d'authentification (MAS)** : `https://matrix.votredomaine.fr/auth/`

#### Connexion initiale :
1. Rendez-vous sur `https://matrix.votredomaine.fr/`.
2. Connectez-vous avec l'identifiant `admin` et le mot de passe défini dans `INITIAL_ADMIN_PASSWORD`.

#### Extensions (widgets) : « vous n'avez pas la permission » pour le créateur du salon

Le gestionnaire d'extensions d'Element (panneau d'informations du salon > **Extensions** > **Ajouter des extensions**, service `scalar.vector.im`) refuse l'ajout d'une extension au créateur d'un salon récent.

- **Cause** : Synapse crée les salons en **version 12**. Dans cette version, le créateur a un pouvoir illimité, mais il ne figure plus dans la liste des niveaux de droits du salon. Le gestionnaire d'extensions calcule lui-même le niveau de l'utilisateur à partir de cette liste, sans connaître cette règle : il attribue au créateur le niveau par défaut (0), inférieur au niveau 50 requis. Ce défaut est propre au service d'Element : Synapse, lui, accepte la modification.
- **Administrateur du serveur** : il n'a aucun droit particulier dans les salons, par conception de Matrix. Il est traité comme n'importe quel membre.
- **Contournements** :
  - **Ajouter l'extension par son adresse**, sans le gestionnaire : dans la zone de saisie du salon (Element Web ou Element Desktop), tapez `/addwidget https://adresse-de-l-extension`. Element Web vérifie lui-même les droits, et reconnaît le créateur. Exemple avec Jitsi Meet ci-dessous.
  - **Nommer un second administrateur** : dans **Paramètres du salon** > **Rôles et permissions**, donnez le rôle *Administrateur* à un autre compte. Il apparaît alors dans la liste des niveaux, et le gestionnaire d'extensions devrait l'autoriser (non vérifié).
  - Régler **Modifier les widgets** sur *Par défaut* ne suffit pas : le gestionnaire d'extensions refuse toujours l'ajout.

**Ajouter une visioconférence Jitsi Meet** : tapez dans le salon

```text
/addwidget https://meet.element.io/NomDeLaConference
```

en remplaçant `NomDeLaConference` par un nom de votre choix, sans espace ni accent (par exemple `ReunionFamille-7k3Fq9`).

- Element Web reconnaît une adresse sur `meet.element.io`, son serveur Jitsi par défaut, et crée un véritable widget Jitsi, et non une simple page web intégrée. Le widget apparaît dans **Extensions**, et chaque membre clique sur **Join Conference** (bouton non traduit). Une autre adresse Jitsi, comme `meet.jit.si`, est ajoutée comme page web ordinaire.
- `meet.element.io` est un service public d'Element, sans compte : toute personne qui connaît le nom de la conférence peut la rejoindre. Choisissez donc un nom difficile à deviner. Les flux audio/vidéo passent par les serveurs d'Element, et non par votre NAS.
- Pour une visioconférence hébergée sur votre NAS et chiffrée de bout en bout, préférez le bouton d'appel vidéo du salon, qui utilise Element Call (voir [Appels audio et vidéo](#appels-audio-et-vidéo-element-call-et-turn)).
- Pour retirer le widget : **Extensions**, menu **⋯** du widget > **Supprimer pour tout le monde**.

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

**Créer un utilisateur :**
```bash
docker exec -it ess-community mas-cli manage register-user --yes --admin --password "MotDePasseAlice123!" alice --config /data/config/mas.yaml
```

**Lister les utilisateurs enregistrés :**

`mas-cli` ne propose pas de commande de listing ; on interroge directement la base de données de MAS (`matrixauthenticationservice` par défaut, ou la valeur de `MAS_DB_NAME`) :
```bash
docker exec -it ess-community su - postgres -c "psql -d matrixauthenticationservice -c 'SELECT username, created_at, can_request_admin AS admin, locked_at, deactivated_at FROM users ORDER BY username;'"
```
Les colonnes `locked_at` et `deactivated_at` sont renseignées pour les comptes verrouillés ou désactivés.

**Modifier le mot de passe d'un utilisateur :**
```bash
docker exec -it ess-community mas-cli manage set-password alice "NouveauMotDePasse456!" --config /data/config/mas.yaml
```
Les sessions déjà ouvertes restent actives. Pour forcer l'utilisateur à se reconnecter partout avec le nouveau mot de passe :
```bash
docker exec -it ess-community mas-cli manage kill-sessions alice --config /data/config/mas.yaml
```

**Supprimer (désactiver) un utilisateur :**

Dans Matrix, un compte ne peut pas être effacé définitivement : son identifiant (`@alice:votredomaine.fr`) reste réservé pour éviter toute usurpation. La « suppression » consiste à désactiver le compte, ce qui ferme ses sessions, le retire de ses salons et l'empêche de se reconnecter :
```bash
docker exec -it ess-community mas-cli manage lock-user --deactivate alice --config /data/config/mas.yaml
```
Sans l'option `--deactivate`, le compte est seulement verrouillé (connexion bloquée) et peut être réactivé plus tard avec :
```bash
docker exec -it ess-community mas-cli manage unlock-user alice --config /data/config/mas.yaml
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
     - `secrets/` : Clés privées de signature Synapse, RSA/ECDSA pour MAS, secrets LiveKit et TURN, et tokens.
     - `postgres/` : Bases de données PostgreSQL complètes (comptes, salons, messages chiffrés).
     - `media/` : Photos, fichiers et pièces jointes partagés.

2. **Restauration** :
   - Restaurez le dossier `docker/element` sur n'importe quel Synology ou serveur Docker et relancez le conteneur : votre serveur redémarre exactement à l'état sauvegardé sans perte de données.

---

### Mise à jour du conteneur déjà déployé

Toutes les données étant stockées dans `/volume1/docker/element`, mettre à jour revient à remplacer l'image du conteneur : les comptes, salons, messages, médias et clés sont conservés. Au redémarrage, l'entrypoint régénère les fichiers de `config/` à partir des templates de la nouvelle image et applique les migrations de base de données de Synapse et de MAS.

> **Important :** les migrations de base de données ne sont pas réversibles. Faites une sauvegarde du dossier `docker/element` (voir la section précédente) **avant** chaque mise à jour, conteneur arrêté, pour pouvoir revenir à l'ancienne version en cas de problème.

#### Étape 1 : Télécharger la nouvelle image

Comme pour l'installation, l'application Docker de DSM 7.1 ne sait pas télécharger l'image depuis GHCR : connectez-vous au NAS en SSH et exécutez :

```bash
# Conserve l'image actuelle sous l'étiquette "previous" pour pouvoir revenir en arrière
sudo docker tag ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest \
                ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:previous

sudo docker pull ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest
```

Si le package est privé, un `sudo docker login ghcr.io -u <votre-utilisateur>` préalable peut être nécessaire. Sans accès SSH, utilisez l'alternative hors ligne décrite à l'[Étape 1 de la Méthode 1](#étape-1--téléchargement-de-limage) (`docker save` puis **Ajouter à partir d'un fichier**).

Le téléchargement remplace l'étiquette `latest` mais ne modifie pas le conteneur en cours d'exécution : il continue d'utiliser l'ancienne image tant qu'il n'a pas été recréé.

#### Étape 2 : Recréer le conteneur

**Si le conteneur a été créé avec l'interface graphique (Méthode 1) :**

1. Dans l'application **Docker** de DSM, onglet **Conteneur**, sélectionnez `ess-community` et cliquez sur **Arrêter**.
2. Toujours sur `ess-community`, cliquez sur **Action** > **Réinitialiser** (*Clear*). DSM recrée le conteneur à partir de la nouvelle image `latest` en conservant ses paramètres : volume `/data`, ports, variables d'environnement et redémarrage automatique.
3. Cliquez sur **Démarrer**.

> **Variables d'environnement :** le conteneur garde les variables enregistrées lors de sa création ; les nouvelles valeurs par défaut de l'image ne sont pas reprises. Si la nouvelle image change de version de Synapse, mettez à jour la variable `SYNAPSE_VERSION_STRING` (conteneur arrêté : **Modifier** > **Paramètres avancés** > **Environnement**) : elle ne sert qu'à l'affichage de la version, mais gardera sinon l'ancienne valeur.

> **Première mise à jour vers une image avec les appels audio/vidéo :** **Réinitialiser** conserve les anciens paramètres de ports, qui ne comprennent pas les ports d'appel. Avant de démarrer le conteneur, ouvrez **Modifier** > **Paramètres des ports** et ajoutez les ports 7881/TCP, 7882/UDP, 3478/TCP, 3478/UDP et 49160 à 49169/UDP, avec des ports locaux identiques (voir l'[étape 2.5 de la Méthode 1](#étape-2--création-du-conteneur)). Si DSM ne permet pas de modifier les ports, supprimez puis recréez le conteneur comme indiqué ci-dessous. Pensez aussi aux redirections sur la box et au pare-feu (voir [Appels audio et vidéo](#appels-audio-et-vidéo-element-call-et-turn)).

> **Première mise à jour vers une image avec le port dédié d'Element Admin :** Element Admin n'est plus servi sous `/admin`, mais sur le port 8088 du conteneur. Comme pour les ports d'appel, ajoutez le port 8088/TCP (port local `8088`) dans **Modifier** > **Paramètres des ports**, puis créez la règle de proxy inversé du port 8443 et la redirection de ce port sur la box (voir [Configuration du Proxy Inversé](#configuration-du-proxy-inversé-et-du-ssl-dans-synology-dsm-71)).

Si l'action **Réinitialiser** n'est pas disponible, supprimez le conteneur (conteneur arrêté : **Action** > **Supprimer**) puis recréez-le en suivant l'[Étape 2 de la Méthode 1](#étape-2--création-du-conteneur) avec exactement les mêmes paramètres, en particulier le même dossier `docker/element` monté sur `/data`. Supprimer le conteneur n'efface pas ce dossier.

**Si le conteneur a été créé avec Docker Compose (Méthode 2) :**

```bash
cd /volume1/docker/element
sudo docker-compose pull
sudo docker-compose up -d
```

`docker-compose up -d` recrée automatiquement le conteneur s'il utilise une image plus récente. Si votre `docker-compose.yml` date d'avant l'ajout des appels audio/vidéo ou du port d'Element Admin, remplacez-le d'abord par la nouvelle version (ports 8088, 7881, 7882, 3478 et 49160-49169), en y reportant vos valeurs, et créez la règle de proxy inversé du port 8443.

#### Étape 3 : Vérifier le redémarrage

1. Dans l'application **Docker**, onglet **Conteneur** > `ess-community` > **Détails** > **Journal**, vérifiez que les services (`postgresql`, `synapse`, `mas`, `caddy`, ainsi que `livekit`, `lk-jwt-service` et `coturn` si les appels sont activés) passent à l'état `RUNNING` et ne redémarrent pas en boucle (lignes `exited: … (exit status 1; not expected)` répétées). Le premier démarrage après une mise à jour peut prendre un peu plus longtemps à cause des migrations.
2. Ouvrez `https://matrix.votredomaine.fr/_matrix/client/versions` : la page doit afficher une réponse JSON.
3. Connectez-vous à Element Web avec un compte existant.

En cas d'échec, revenez à la version précédente :

1. Arrêtez le conteneur et restaurez la sauvegarde du dossier `docker/element` (indispensable : la base de données a pu être migrée vers un schéma que l'ancienne version ne comprend pas).
2. Remettez l'ancienne image sous l'étiquette `latest`, puis recréez le conteneur comme à l'étape 2 :
   ```bash
   sudo docker tag ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:previous \
                   ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest
   ```
   Avec Docker Compose, lancez uniquement `sudo docker-compose up -d`, sans `pull`.

#### Étape 4 (facultative) : Libérer l'espace disque

Les anciennes images restent stockées sur le NAS. Une fois la nouvelle version validée, supprimez-les depuis l'onglet **Image** de l'application Docker (image `ess-synology:previous` et images sans étiquette, marquées `<none>`) ou en SSH :

```bash
sudo docker rmi ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:previous
sudo docker image prune
```

---

### Tester sous Windows

Pour essayer une modification de l'image avant de la publier, vous pouvez construire et lancer le conteneur sur un PC Windows.

#### Prérequis

1. **WSL 2** : dans un terminal PowerShell ouvert en administrateur, exécutez `wsl --install`, puis redémarrez le PC. La virtualisation doit être activée dans le BIOS/UEFI (vérifiable dans le **Gestionnaire des tâches** > **Performance** > **Processeur** > *Virtualisation*). Sous Windows 11 Famille, Hyper-V n'est pas disponible : WSL 2 est le seul moteur possible.
2. **Docker Desktop** : installez-le depuis [docker.com](https://www.docker.com/products/docker-desktop/) en conservant l'option **Use WSL 2 based engine**. Il fournit les commandes `docker`, `docker compose` et `docker buildx`.
3. **Fins de ligne** : le fichier `.gitattributes` du dépôt force les fichiers de `docker/synology/` en fins de ligne LF. Si votre copie du dépôt date d'avant son ajout, ces fichiers peuvent être en CRLF : le conteneur échoue alors au démarrage (`/bin/bash^M: bad interpreter`). Rechargez-les avec :
   ```powershell
   git rm --cached -r docker/synology
   git reset --hard
   ```
   (cette commande annule les modifications locales non commitées).

#### Construire et lancer

Depuis le dossier `docker/synology` :

```powershell
docker compose -f docker-compose.dev.yml up --build
```

Le fichier `docker-compose.dev.yml` construit l'image locale `ess-synology:dev` et la sert sur `http://localhost:8080` (Element Admin sur `http://localhost:8088`), avec le compte `admin` / `Local-Dev-Admin-2026!`. Les données sont conservées dans un volume Docker nommé, et non dans un dossier Windows : PostgreSQL refuse de démarrer sur un montage NTFS, dont il ne peut pas contrôler les droits.

- Arrêter : **Ctrl + C**, ou `docker compose -f docker-compose.dev.yml down`.
- Repartir de zéro (comptes, base de données, secrets) : `docker compose -f docker-compose.dev.yml down -v`.
- Ouvrir un terminal dans le conteneur : `docker exec -it ess-community-dev bash`.

Pour tester l'image publiée plutôt que le code local, remplacez la construction par `docker pull ghcr.io/<votre-utilisateur-ou-organisation>/<nom-du-dépôt>/ess-synology:latest`. Pour reproduire un NAS ARM, ajoutez `--platform linux/arm64` : l'image est alors émulée, et nettement plus lente.

#### Tests automatisés

La suite `tests/synology` vérifie l'image sans intervention manuelle. Elle nécessite [uv](https://docs.astral.sh/uv/getting-started/installation/) et Docker Desktop démarré. Depuis la racine du dépôt :

```powershell
uv sync
uv run pytest -v tests/synology
```

- `test_files.py` contrôle les fichiers de `docker/synology` sans Docker : fins de ligne LF, variables des templates et de `supervisord.conf` bien définies par l'image ou l'entrypoint, fichiers copiés par le `Dockerfile`, YAML valides.
- `test_container.py` construit l'image `ess-synology:test`, puis lance un conteneur comme `docker-compose.dev.yml` (appels désactivés). Il vérifie les `.well-known`, MAS, Element Web, Element Admin sur son port 8088 (configuration injectée, scripts, routes, redirection de `/admin`, enregistrement auprès de MAS), la connexion du compte administrateur initial, l'envoi d'un message, la commande `register-user`, l'absence d'en-têtes CORS en double, et la conservation des données après un redémarrage.
- `test_container_calls.py` lance un second conteneur avec `ENABLE_MATRIX_RTC=true`, `ENABLE_TURN=true` et une `PUBLIC_IP` fictive. Il vérifie la déclaration d'Element Call, le démarrage de LiveKit, de lk-jwt-service et de coturn, le relais des demandes de jeton par Synapse jusqu'au contrôle d'appartenance au salon, la possibilité pour un membre ordinaire de rejoindre un appel de groupe, les identifiants TURN et l'IP annoncée. La délivrance complète d'un jeton et les flux audio/vidéo ne sont pas testés : lk-jwt-service rappelle le serveur par son adresse publique HTTPS, qui n'existe que sur le NAS.

Chaque conteneur est publié sur un port libre de `127.0.0.1` et supprimé à la fin, avec son volume : les tests n'entrent pas en conflit avec `docker-compose.dev.yml`. Le premier lancement construit l'image et prend plusieurs minutes. Sans Docker, seuls les tests de `test_files.py` s'exécutent ; les autres sont ignorés.

Variables d'environnement utiles :

| Variable | Effet |
|---|---|
| `ESS_SYNOLOGY_IMAGE` | Teste une image existante au lieu de la construire (ex : `ghcr.io/devfred78/ess-helm/ess-synology:latest`) |
| `ESS_SYNOLOGY_KEEP=1` | Conserve les conteneurs après les tests, pour les inspecter (`docker ps -a`) ; supprimez-les ensuite avec `docker rm -f -v` |
| `ESS_SYNOLOGY_STARTUP_TIMEOUT` | Délai maximal de démarrage en secondes (600 par défaut) ; à augmenter pour une image émulée |

Les journaux des conteneurs sont enregistrés dans `ess-helm-logs/synology/`. Le workflow GitHub Actions `docker-synology.yml` exécute la même suite avant de publier l'image.

Sous PowerShell, une variable se définit avant la commande : `$env:ESS_SYNOLOGY_IMAGE = "ghcr.io/..."`.

#### Limites du test local

- **Fonctionnent** : Element Web, la connexion via MAS et la messagerie. Les navigateurs considèrent `http://localhost` comme sûr, HTTPS n'est donc pas nécessaire.
- **Element Admin** : la console s'affiche sur `http://localhost:8088`, mais la connexion échoue. Element Admin cherche toujours le serveur à l'adresse `https://<SERVER_NAME>/.well-known/matrix/client`, en HTTPS, ce que le test local ne fournit pas. La connexion se teste sur le NAS.
- **Appels audio/vidéo** : ils sont désactivés (`ENABLE_MATRIX_RTC=false`, `ENABLE_TURN=false`). Element Call exige une adresse en HTTPS (`wss://`) et une IP publique joignable : ils se testent sur le NAS.
- **Applications mobiles** : elles ne peuvent pas joindre `localhost`. Testez-les sur le NAS.
- **Port 8080 déjà utilisé** : remplacez `"8080:8080"` par `"8090:8080"` dans `docker-compose.dev.yml`, et `PUBLIC_BASEURL` par `http://localhost:8090`. De même pour le port 8088 : remplacez `"8088:8088"` par `"8098:8088"`, et ajoutez `ADMIN_BASEURL=http://localhost:8098`.
