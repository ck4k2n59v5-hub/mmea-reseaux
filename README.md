# Rapport quotidien des réseaux MMEA

Chaque matin, GitHub lance `mmea_report.py`, qui :

1. récupère via l'API Meta les abonnés, les likes et les commentaires de la page Facebook et du compte Instagram MMEA ;
2. compare avec la veille (fichier `state.json`, mis à jour automatiquement) ;
3. t'envoie un email brut avec le sujet `[MMEA-STATS] AAAA-MM-JJ`.

Une tâche planifiée Claude lit ensuite cet email (et les notifications LinkedIn), rédige le rapport final avec des propositions de réponse et te l'envoie. Ton ordinateur peut rester éteint.

Coût : 0 CHF (GitHub Actions gratuit, API Meta gratuite).

---

## Mise en place (environ 45 minutes, une seule fois)

### Étape 0 : vérifier les prérequis

* Le compte Instagram MMEA est un **compte professionnel** (Entreprise ou Créateur).
* Il est **lié à la page Facebook MMEA** (Meta Business Suite, Paramètres, Comptes Instagram).
* Ton profil Facebook est **administrateur** de la page MMEA.

### Étape 1 : créer l'app Meta (gratuite)

1. Va sur <https://developers.facebook.com>, connecte-toi avec ton compte Facebook, puis **Mes apps** et **Créer une app**.
2. Nom : `MMEA Rapport`. Choisis le cas d'usage **Autre**, puis le type **Entreprise**.
3. Pas besoin de soumettre l'app à la validation de Meta : tant que tu l'utilises pour tes propres pages, l'accès standard suffit.

### Étape 2 : obtenir le jeton d'accès de la page

1. Ouvre l'**Explorateur de l'API Graph** : <https://developers.facebook.com/tools/explorer>
2. En haut à droite, sélectionne l'app **MMEA Rapport**.
3. Dans **Autorisations**, ajoute :
   `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`, `read_insights`,
   `instagram_basic`, `instagram_manage_comments`, `business_management`
4. Clique sur **Generate Access Token** et, dans la fenêtre qui s'ouvre, coche la page **MMEA** et le compte Instagram **MMEA**.
5. Copie le jeton obtenu et colle-le dans le **Débogueur de jeton** : <https://developers.facebook.com/tools/debug/accesstoken>
   Clique sur **Débugger**, puis en bas sur **Prolonger le jeton d'accès**. Copie ce nouveau jeton (valable 60 jours).
6. Retourne dans l'Explorateur, colle ce jeton long dans le champ **Access Token**, et lance la requête :
   ```
   me/accounts?fields=name,id,access_token,instagram_business_account
   ```
7. Dans la réponse, pour la page MMEA, note :
   * `access_token` : c'est le **META_PAGE_TOKEN** (jeton de page, il n'expire pas) ;
   * `id` : c'est le **FB_PAGE_ID** ;
   * `instagram_business_account.id` : c'est le **IG_USER_ID**.
8. Vérification : colle le `access_token` de la page dans le Débogueur. La ligne « Expire » doit indiquer **Jamais**.

> Ce jeton donne accès à la page MMEA. Ne le colle nulle part ailleurs que dans les secrets GitHub (étape 4), ni dans un email ni dans une conversation.

### Étape 3 : créer un mot de passe d'application Gmail

1. La **validation en deux étapes** doit être activée sur ton compte Google.
2. Va sur <https://myaccount.google.com/apppasswords>, crée un mot de passe nommé `MMEA GitHub`.
3. Copie les 16 caractères (sans les espaces) : c'est le **GMAIL_APP_PASSWORD**.

### Étape 4 : ajouter les secrets dans GitHub

Dans le repo : **Settings**, **Secrets and variables**, **Actions**, **New repository secret**. Crée :

| Nom | Valeur |
|---|---|
| `META_PAGE_TOKEN` | le jeton de page (étape 2.7) |
| `FB_PAGE_ID` | l'id de la page |
| `IG_USER_ID` | l'id Instagram |
| `GMAIL_ADDRESS` | ton adresse Gmail |
| `GMAIL_APP_PASSWORD` | le mot de passe d'application |
| `REPORT_TO` | facultatif, sinon l'email part vers `GMAIL_ADDRESS` |

### Étape 5 : premier test

Onglet **Actions**, workflow **Rapport réseaux MMEA**, bouton **Run workflow**.
Après environ 30 secondes, tu dois recevoir l'email `[MMEA-STATS]`. Au premier passage, les « nouveaux likes » et « nouveaux abonnés » sont vides : ils apparaissent dès le lendemain.

### Étape 6 : filtre Gmail (pour ne pas encombrer ta boîte)

Dans Gmail, crée un filtre : Objet contient `[MMEA-STATS]`, puis **Ignorer la boîte de réception** et **Appliquer le libellé** `MMEA-STATS`. Claude ira le chercher là.

### Étape 7 : LinkedIn

En attendant l'accès à l'API LinkedIn : sur la page MMEA en mode admin, **Paramètres**, **Notifications**, active les notifications **par email** pour les nouveaux abonnés, commentaires, mentions et réactions. Claude les lira dans ton Gmail.

---

## En cas de problème

* **Email non reçu** : onglet Actions, ouvre la dernière exécution et lis l'erreur. GitHub t'envoie aussi une alerte par email si tout échoue.
* **« Error validating access token »** : le jeton a été invalidé (changement de mot de passe Facebook, retrait de ton rôle admin). Refais l'étape 2 et mets à jour le secret.
* **Les noms des auteurs Facebook manquent** : Meta masque parfois les noms des personnes. Le commentaire reste visible.
* **Version de l'API dépassée** : Meta retire les anciennes versions après environ deux ans. Ajoute un secret `GRAPH_VERSION` avec la version actuelle (par exemple `v27.0`), sans toucher au code.
