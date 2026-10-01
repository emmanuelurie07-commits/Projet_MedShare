# MedShare — Banque de questions de soutenance

> Document de préparation à l'oral. Les réponses sont rédigées **pour être dites à voix haute**, dans l'ordre naturel d'une réponse orale : on part de l'idée, on explique le pourquoi, puis on donne le détail technique si le jury le demande.
>
> **Convention** : quand une réponse se décompose en plusieurs niveaux, le **niveau 1** est ce que je dis spontanément. Les **niveaux 2 et 3** sont mes réponses de relancement, si le jury creuse.
>
> Chaque partie finit par **« Si le jury me challenge… »** : la phrase à avoir prête quand l'objection arrive. C'est là que se joue la soutenance.

---

## Sommaire

1. [Le projet en deux minutes](#1-le-projet-en-deux-minutes)
2. [Problème et cible](#2-problème-et-cible)
3. [Architecture et choix techniques](#3-architecture-et-choix-techniques)
4. [Le cycle DUT → DMP](#4-le-cycle-dut--dmp)
5. [La reconnaissance faciale](#5-la-reconnaissance-faciale)
6. [Sécurité, confidentialité, données de santé](#6-sécurité-confidentialité-données-de-santé)
7. [Données manquantes, cohérence, qualité](#7-données-manquantes-cohérence-qualité)
8. [Tests, vérification, industriisation](#8-tests-vérification-industrialisation)
9. [Déploiement et exploitation](#9-déploiement-et-exploitation)
10. [Limites, risques, ce que je n'ai pas fait](#10-limites-risques-ce-que-je-nai-pas-fait)
11. [Les questions qui fâchent](#11-les-questions-qui-fâchent)

---

## 1. Le projet en deux minutes

**Question : de quoi ça parle ?**

MedShare répond à un problème concret : quand un patient arrive aux urgences et qu'il est inconscient, il ne peut pas dire qui il est. Et sa famille n'est pas là pour l'aider. Très souvent, l'hôpital ne le sait pas, et le patient finit par passer une radiographie, une analyse sanguine, un dossier papier qu'on va perdre, sans jamais savoir qui il est.

MedShare, c'est une plateforme où plusieurs hôpitaux d'une même région partagent leurs dossiers patients. Et quand un patient inconnu arrive, l'infirmier prend une photo de son visage : le système la compare aux patients déjà enregistrés et propose une liste de correspondances.

Le soignant valide, le dossier est retrouvé, et l'urgence passe de « personne non identifiée » à « patient connu avec son historique ». Dans notre cas, un patient a fait une Appendicite et on ne le savait pas.

**Question : c'est nouveau, ce genre de plateforme ?**

Non, et c'est important de le dire. Le dossier patient partagé existe déjà, dans les pays nordiques notamment. Ce qui est nouveau ici, c'est le contexte : un pays où l'infrastructure numérique est faible, où les Borders sont porous et où un patient peut être traité dans deux hôpitaux différents la même semaine. Notre valeur, ce n'est pas l'invention, c'est l'adaptation à une réalité où le problème est plus aigu et les moyens plus limités.

**Si le jury me challenge : « Vous n'avez rien inventé, donc ? »**

Non, et c'est exactement pour ça que j'ai choisi de construire sur des briques existantes et éprouvées plutôt que de réinventer. Le visage humain est identifié depuis les années 1960. Les réseaux convolutifs sont utilisés par les métropoles comme Londres ou New York. Mon travail, c'est de prendre ces outils et de les rendre utilisables dans un hôpital camerounais, avec le budget, la connectivité et les contraintes de données qu'on a ici.

---

## 2. Problème et cible

**Question : c'est quoi un DUT ?**

DUT ça veut dire « Dossier d'Urgence Temporaire ». C'est un dossier provisoire, créé dès l'admission, quand le patient est encore inconnu. Il contient ce qu'on sait déjà : l'âge, le sexe approximatif, le motif, les constantes, une photo.

Le mot important est **temporaire**. Ce dossier n'est pas la destination finale. Son role est de rassembler l'information pendant l'urgence, puis il doit **fusionner** avec le dossier définitif du patient quand celui-ci est identifié. Ou alors, si la personne n'existe pas encore dans le système, le DUT devient le point de départ de la création d'un dossier patient.

Ce cycle, c'est le cœur fonctionnel de tout le projet. La reconnaissance faciale, ce n'est pas une fonctionnalité à côté. C'est ce qui permet de **clore** le DUT. Sans identification, le dossier reste temporaire, et on a un problème de données orphelines.

**Question : qui utilise l'application, et avec quels droits ?**

Cinq profils, avec des droits strictement croissants :

- Le **patient** voit son propre dossier, et il donne ou refuse l'accès aux médecins. Il ne voit pas les notes des autres médecins.
- L'**infirmier** identifie, crée le DUT, prend les constantes. Il ne peut pas lire le contenu médical du dossier.
- Le **médecin** lit le dossier, écrit consultations et ordonnances, et **seul** il peut confirmer une identification.
- L'**administrateur d'établissement** gère les utilisateurs et les services de son hôpital, sans jamais lire les dossiers médicaux.
- Le **super administrateur** gère la plateforme.

Le point que je tiens à défendre : **le soignant ne devient pas propriétaire du dossier.** L'hôpital héberge les données, mais la relation soignante–patient, elle, appartient au patient. C'est pour ça que son accord est demandé à chaque nouvel accès.

**Si le jury me challenge : « Un super administrateur qui peut tout voir, ce n'est pas dangereux ? »**

C'est la bonne question. Ma réponse : il ne peut pas. Le super administrateur gère la plateforme — les comptes, les établissements, les abonnements — mais il n'a **aucun accès aux dossiers médicaux**. C'est une séparation volontaire des pouvoirs, pas une commodité technique. Et comme chaque consultation du dossier laisse une trace d'audit horodatée et non modifiable, un administrateur qui essaierait d'y accéder serait tracé.

---

## 3. Architecture et choix techniques

**Question : comment l'application est-elle construite ?**

C'est une application **monolithique modulaire**, en Django, qui parle à une base PostgreSQL sur Supabase.

J'ai choisi Django pour une raison très concrète : Django fournit de base tout ce qu'une application médicale exige — l'authentification, les sessions, les protections contre les injections SQL, la gestion des formulaires, le journal d'audit. Avec un framework plus léger, j'aurais réécrit tout ça, avec le risque d'oublier une protection. Ici, les défauts de sécurité sont activés par défaut.

**Question : un monolithe, ce n'est pas dépassé ?**

Non, et je pense que c'est un choix défendable ici. Un monolithe modulaire, c'est un seul processus déployable, découpé en modules qui ne se parlent pas directement entre eux sans passer par des règles explicites. Pour une équipe de développement réduite, sur un budget limité, c'est plus rapide à livrer et plus simple à maintenir qu'une architecture distribuée.

Le jour où la charge le justifierait, les modules que j'ai découpés — urgences, DMP, reconnaissance faciale, comptes — sont exactement les frontières qu'on retrouverait dans des services séparés. La transition est possible, c'est pour ça que j'ai insistence sur les modules.

**Question : pourquoi PostgreSQL et pas MySQL ?**

À l'époque où j'ai commencé, le projet était configuré pour MySQL, et j'ai gardé cette compatibilité dans les réglages. Mais j'ai basculé sur PostgreSQL pour trois raisons : c'est le moteur le plus répandu dans le monde open source ; les types `JSONB` m'ont servi pour stocker les empreintes faciales sans multiplier les tables ; et Supabase, que j'utilise pour l'hébergement, est construit sur PostgreSQL. Changer d'hébergeur impliquerait de migrer les données, donc autant être aligné.

**Question : où sont stockées les photos ?**

C'est un point qui a réellement posé problème, et j'ai constaté un bug : les photos ne sont pas stockées sur le serveur d'application. Elles vont dans un stockage objet, un stockage objet compatible S3, hébergé par Supabase, et la base ne contient que l'adresse.

Pourquoi ? Parce que le serveur d'application est **éphémère**. Chaque déploiement le détruit et en crée un nouveau. Si les photos étaient dessus, elles disparaîtraient à chaque mise en production. J'ai d'ailleurs constaté ce problème : les photos des patients renvoyaient une erreur 404 après le déploiement suivant. Elles sont donc maintenant dans un stockage persistant, et l'application y accède par des liens sécurisés et signés, valables une heure et nonivables.

C'est un point que je signale souvent : **le stockage et le calcul sont séparés**, parce qu'ils n'ont pas du tout les mêmes exigences de durée de vie.

**Si le jury me challenge : « Les liens signés, ça veut dire que l'URL de la photo peut fuiter ? »**

Si, et je l'assume. Un lien signé donne accès à la photo pendant sa durée de validité, à quiconque possède le lien. C'est pourquoi j'ai mis une heure de durée, et non un accès permanent. Et j'ai vérifié que l'application ne donne jamais le lien dans une page visible à un utilisateur non autorisé : les URLs signées sont générées au moment de l'affichage, pour la session en cours. Sur un site de santé, c'est un compromis assumé entre sécurité et simplicité. Un stockage entièrement privé avec authentification à chaque requête serait plus strict, mais je l'ai identifié comme une amélioration possible plutôt que de la prétendre fait.

---

## 4. Le cycle DUT → DMP

**Question : que se passe-t-il exactement quand un patient est identifié ?**

L'infirmier crée un DUT avec la photo. Le moteur calcule l'empreinte du visage et la compare aux empreintes déjà enregistrées. Il propose une liste classée. Le médecin **confirme**. À cet instant, le système vérifie trois choses : que le patient n'a pas déjà un dossier actif, que le médecin a bien les droits sur l'établissement, et que le DUT est bien en attente.

Puis deux choses se produisent. Le dossier du patient est mis à jour avec les constantes du DUT, et surtout — **un journal d'audit est écrit**, de façon non modifiable. Ensuite, la photo et les données d'urgence sont rattachées au dossier patient, et le DUT disparaît de la liste des dossiers en attente.

**Question : que se passe-t-il si le patient n'est finalement pas dans la base ?**

Alors on crée son dossier à partir du DUT, et on l'inscrit. C'est prévu et c'est même un cas important : beaucoup de patients aux urgences ne sont pas encore dans le système. Dans ce cas, le statut du dossier est marqué « à compléter » tant que des informations manquent, comme la date de naissance ou le contact d'urgence.

**Question : comment vous évitez qu'un patient ait deux dossiers ?**

C'est un vrai problème dans ce type de plateforme, et j'y ai passé du temps. Un contrôle existe à la création de dossier : je compare le nom, la date de naissance et le numéro de téléphone. Si une correspondance forte est détectée, la création est bloquée et l'utilisateur est renvoyé vers le dossier existant.

Mais je dois être honnête sur la limite : ça ne bloque pas les doublons quand une saisie est incomplète. Si quelqu'un crée « Jean » sans date de naissance, deux saisies de « Jean » passeront. La vraie parade dans ce cas, c'est le **numéro d'identification du patient** : on attribue un identifiant unique à la création, et c'est lui la référence stable, pas le nom. C'est ce que fait le programme national d'identification, et c'est la piste que je profundos pour la suite.

**Si le jury me challenge : « La reconnaissance faciale peut se tromper et fusionner le mauvais dossier. Que se passe-t-il ? »**

C'est le risque principal du système, et c'est pour ça que j'ai construit trois verrous, pas un.

Un : **aucune fusion automatique**. Le moteur ne fait jamais le rapprochement tout seul. Il propose, un humain décide. Deux : **seul un médecin** peut confirmer, jamais l'infirmier qui a pris la photo, ni le patient. Trois : **la fusion est réversible et tracée** — le journal d'audit conserve l'image avant et après, et on sait exactement qui a confirmé, quand, et quel patient a été associé.

Et pour mesurer le risque, j'ai fait des tests : sur des photos dégradées, et surtout sur des photos de patients différents. Mon constat est que les scores des vraies correspondances et ceux de patients non apparentés **se recoupent**. Il n'existe pas de seuil qui distingue parfaitement les deux cas. C'est un fait que j'ai mesuré, pas une intuition, et c'est précisément pour ça que la validation humaine n'est pas une option, c'est la condition de fonctionnement.

---

## 5. La reconnaissance faciale

**Question : comment ça marche concrètement ?**

Il y a deux modèles qui travaillent ensemble.

Le premier, **YuNet**, sert à **trouver** le visage dans la photo et à repérer cinq points de repère : les coins des yeux, le bout du nez, les coins de la bouche. Ce sont les repères standards en reconnaissance faciale.

Le second, **ArcFace**, sert à **reconnaître**. Les cinq points permettent de redresser le visage de façon parfaitement identique à chaque fois, on le réduit à une image de 112 × 112 pixels, et le modèle le transforme en une suite de 512 nombres — ce qu'on appelle une empreinte.

L'idée derrière ArcFace, c'est de faire en sorte que deux photos **de la même personne** produisent des empreintes proches, et que deux personnes différentes produisent des empreintes éloignées, même si elles se ressemblent.

Enfin, on compare les empreintes par **similarité cosinus**. Plus c'est proche de 100 %, plus c'est que les visages se ressemblent.

**Question : pourquoi YuNet et pas le détecteur de visage de base d'OpenCV ?**

Parce que le détecteur d'OpenCV donne une position approximative et il dépend beaucoup de la position du visage dans l'image. Or la qualité de la reconnaissance dépend directement de l'alignement. Cinq repères permettent de redresser le visage avec précision, même s'il est légèrement de trois quarts ou penché. C'est un gain deocababilité et surtout de fiabilité.

**Question : pourquoi ArcFace et pas le classique FaceNet ?**

FaceNet est plus ancien, mais il est conçu pour reconnaître des personnes dans des conditions très variées. ArcFace utilise une Border Loss, qui consiste à faire converger les empreintes de chaque personne vers le centre d'une sphère propre à elle, tout en repoussant les autres. Sur le jeu CelebA, ArcFace obtient un taux d'erreur nettement inférieur à ses concurrents de la même génération.

Plus important pour nous : le modèle fait **512 dimensions** au lieu de 128, donc il encode plus d'information. Et il est distribué avec une licence qui autorise l'usage commercial, ce qui n'était pas le cas des premiers modèles ArcFace.

**Question : pourquoi des modèles ONNX plutôt que TensorFlow ?**

Pour une raison très concrète : la **portabilité**. TensorFlow est lourd et dépend de la version de Python. ONNX est un format d'échange : le modèle fonctionne avec n'importe quel moteur qui sait le lire.

Ça a été déterminant. Mon poste de développement dispose de `dlib`, qui est compilé en C++. Mais Vercel n'a pas de compilateur, donc impossible d'y faire tourner `dlib`. En utilisant ONNX avec un moteur léger, le même code fonctionne à l'identique sur mon poste et en ligne. Le moteur se choisit tout seul selon ce qui est disponible.

C'est un point que je veux souligner : **j'ai fait en sorte que la démonstration que je présente utilise exactement le même chemin de code que celui qui tourne en production.** Ce n'est pas une version allégée pour la démo.

**Question : pourquoi un visage est-il enregistré dans le DMP et pas recalculé à chaque recherche ?**

Pour deux raisons.

La première est la performance. Recalculer l'empreinte de cent patients à chaque recherche prendrait plusieurs minutes, et en plus ça exigerait de charger cent images à chaque requête. Comme l'empreinte d'un patient ne change pas — son visage ne change pas — je la calcule **une fois** à l'enregistrement et je la garde. La recherche ne compare que des nombres.

La seconde, c'est la confidentialité. Stocker une empreinte est déjà plus sensible qu'une photo, mais **beaucoup moins que la photo elle-même**. Une photo est directement reconnaissable à l'œil humain ; une empreinte de 512 nombres ne l'est pas, et on ne peut pas la transformer en image. C'est un vrai gain en matière de protection des données, même si ce n'est pas une preuve qu'on ne peut pas contourner.

**Question : le visage du patient est-il utilisé sans son consentement ?**

Pour être très précis : la photo est du **photographe volontaire** — un infirmier, une réceptionniste, ou le patient lui-même. Ce que le système traite, c'est cette photo d'identité, pas une caméra discrète. Ensuite, la photo sert de moyen de preuve d'identité dans un dossier médical.

Sur le fond juridique, en Europe le cadre biométrique est très strict — c'est un usage interdit sauf exceptions. L'Informatique et des Libertés considère que la biométrie est un traitement à très haut risque, et que la loi doit l'autoriser explicitement. Le projet n'est pas en Europe, donc le cadre camerounais s'applique, mais j'ai volontairement construit sur le modèle le plus exigeant plutôt que sur le plus permissif, parce que c'est le seul choix défendable.

---

## 6. Sécurité, confidentialité, données de santé

**Question : les données sont-elles chiffrées ?**

Oui, et je précise où, parce que ce n'est pas uniforme.

- **Le transport** est en HTTPS obligatoire. Aucune requête ne transite en clair.
- **La base de données** est chiffrée au repos par Supabase, et les sauvegardes aussi.
- **Les photos** ne sont pas chiffrées individuellement, mais le bucket est **privé** : aucun lien public ne fonctionne sans une autorisation signée et temporaire.

Pour être honnête : je n'ai pas mis en place de chiffrement applicatif sur les données les plus sensibles au niveau du code. C'est un choix que je referais différemment pour un usage réel.

**Question : qui peut accéder à un dossier ?**

Le principe que j'ai retenu est **le consentement du patient comme condition d'accès**. Un médecin ne consulte pas le dossier d'un patient simplement parce qu'il travaille dans l'hôpital : il faut que le patient ait donné son accord, pour cet établissement précis.

Quand un médecin ouvre une consultation, si le patient n'a pas encore donné son accord pour cet établissement, le système crée une demande et **bloque l'enregistrement**. Les champs de formulaire deviennent non modifiables. Le patient reçoit une notification, et il peut accepter ou refuser.

C'est un point central de mon projet, parce que j'ai vu beaucoup de systèmes où le dossier est accessible par défaut, et où la demande d'accès est une formalité créée après coup. Ici, l'absence d'accord est le cas par défaut, et l'accès est l'exception qui doit être justifiée.

**Question : que se passe-t-il si un patient refuse ?**

Le dossier n'est pas accessible à cet établissement, et la demande est close avec la trace du refus. Les situations d'urgence sont treated séparément : au bloc opératoire, un médecin peut accéder au dossier en cas de danger vital, et cette consultation exceptionally est **obligatoirement tracée** dans le journal d'audit avec le motif. C'est ce qu'on appelle le « bris de confidentialité », et il existe pour que l'intérêt de la vie l'emporte sur la règle — mais il laisse une trace, ce qui est essentiel.

**Question : il y a un journal d'audit ?**

Oui, et c'est l'une des pièces que je considère comme les plus importantes. Chaque accès à un dossier, chaque création, chaque modification, chaque recherche faciale, chaque confirmation d'identité est journalisée avec l'heure, la personne, l'établissement et l'action.

Ce journal est **non modifiable**. Non pas par convention, mais techniquement : la base ne fournit pas d'accès en écriture à cette table depuis l'application.

**Question : les mots de passe sont stockés en clair ?**

Non, jamais. Ils sont transformés par un algorithme de hachage à sel, qui n'est pas réversible. Quand je compare un mot de passe saisi à celui stocké, je recalcule le hachage et je compare les résultats. Une base compromise donne des suites de caractères incompréhensibles, pas des mots de passe.

J'ai aussi ajouté des protections contre les attaques par force brute : les comptes se verrouillent temporairement après plusieurs échecs. Et la connexion à deux facteurs est disponible pour les comptes les plus sensibles.

**Question : les jetons d'accès des patients, c'est sûr ?**

C'est ma principale réserve. Le patient accède à son dossier via un lien personnel. C'est simple, ça ne demande aucun mot de passe au patient, et ça évite de demander à quelqu'un qui vient aux urgences de créer un mot de passe. Mais un lien personnel est un facteur d'authentification unique : s'il est intercepté, l'accès est obtenu.

Ce que j'ai mis en place : le jeton est aléatoire, long, et il est **régénéré à chaque connexion** — c'est-à-dire qu'une session active ne survit pas à une nouvelle connexion du même compte ailleurs. La limite que je vois : un lien ne peut pas être authentifié par deux facteurs, par nature. Je l'ai identifié comme le point à travailler en priorité.

**Question : êtes-vous conforme au RGPD ?**

Je ne vais pas prétendre l'être. Le projet est destiné au Cameroun, donc c'est la réglementation camerounaise qui s'applique : la loi sur la protection des données à caractère personnel.

Cela dit, j'ai construit sur le modèle du RGPD parce que c'est le référentiel le plus exigeant. Minimisation des données, information du patient, consentement explicite, traçabilité des accès, durée de conservation maîtrisée, sécurité par défaut. Si l'application devait être déployée en Europe demain, une grande partie du travail serait déjà fait. Ce qui manquerait, ce sont les points que j'ai cités : le chiffrement applicatif, et surtout le déploiement d'un proxy d'authentification conforme.

**Si le jury me challenge : « Vous gérez des données de santé sans certification — n'est-ce pas irresponsable ? »**

C'est une objection légitime et je ne vais pas la contourner. Ma position, c'est celle d'un projet de fin d'études, avec un jeu de données fictif et cent patients de démonstration. En aucun cas il ne faudrait y verser de vraies données de patients.

Ce que je revendique, c'est d'avoir fait le travail de **conception sécurisée** : les données sensibles sont identifiées, les contrôles d'accès sont en place, la traçabilité existe, et les risques sont documentés plutôt que masqués. Et la certification elle-même n'est pas quelque qu'un peut décider seul : c'est un processus qui suppose un hébergeur agréé, des procédures, et un engagement institutionnel. Mon travail s'arrête avant cette marche.

---

## 7. Données manquantes, cohérence, qualité

**Question : qu'avez-vous corrigé qui était faux dans la version initiale ?**

J'ai trouvé quatre problèmes réels. Je vais les présenter parce qu'ils sont plus intéressants que les fonctionnalités.

**Le premier : une erreur serveur au moment de créer un DUT avec photo.** Le dossier provisoire était bien enregistré, mais la page renvoyait une erreur. La cause : le code ne distinguait pas un champ vide d'une image réellement stockée. Un patient sans photo n'aurait jamais dû planter.

**Le deuxième : la moitié des patients n'avaient pas de dossier médical.** Sur cent patients de démonstration, seuls quelques-uns avaient un DMP. Le programme de génération en créait un seul pour l'ensemble. J'ai centralisé la création dans un point unique, corrigé le générateur, et écrit un script de réparation qui a mis à niveau la base : sur les cent patients, tous ont maintenant leur dossier.

**Le troisième : le DMP pouvait être créé en double.** Rien n'empêchait deux dossiers pour le même patient. J'ai ajouté un numéro unique attribué au moment de la création, et une vérification d'unicité.

**Le quatrième : l'écran de reconnaissance faciale plantait sur une photo sans visage.** C'est le bug le plus instructif. Le détecteur renvoie deux valeurs, et mon code testait mal le cas « aucun visage détecté ». Il essayait ensuite de compter les visages d'un résultat qui n'existait pas. Le message d'erreur que le soignant voyait était incompréhensible — ce qui est le pire scénario possible dans une logique de tri.

**Question : comment vous êtes-vous rendu compte que le seuil de reconnaissance était mal réglé ?**

En mesurant, plutôt qu'en supposant.

J'ai d'abord construit un jeu de mesures : je prends la photo d'un patient, je lui applique des déformations réalistes — recadrage, rotation, baisse de luminosité, compression, petite résolution — et je regarde à partir de quel score il est encore reconnu.

Premier résultat : les patients étaient reconnus même fortement dégradés. Deuxième constat, beaucoup plus important : quand la photo est prise dans de conditions **différentes** de la photo d'identité, les scores chutent. La médiane passait sous 80 %.

J'ai alors vérifié si abaisser le seuil était la solution. En fait non : en abaissant le seuil, les scores de patients qui ne se ressemblent pas **montent aussi**. Les deux populations se recoupent. Il n'existe pas de seuil unique qui les sépare parfaitement.

Du coup j'ai changé l'approche. Plutôt que de filtrer en dessous d'un seuil — ce qui faisait disparaître le bon patient — le système affiche une liste **classée**, en distinguant visuellement une correspondance forte d'une correspondance possible. Rien n'est fusionné sans validation humaine. C'est une conclusion que j'ai obtenue par la mesure, et qui n'aurait pas été évidente si je m'étais contenté de choisir un seuil au feeling.

**Si le jury me challenge : « Vous avez abaissé votre exigence de sécurité pour que la démo fonctionne. » »**

Non, et c'est important de le dire dans l'autre sens : je n'ai pas abaissé le seuil de sécurité, j'ai élargi ce qui est présenté au soignant, en gardant toute décision sous contrôle humain.

Concrètement : avant, un patient sous 80 % disparaissait de l'écran et le soignant se retrouvait devant un écran vide. Maintenant il est affiché, **en ambre**, explicitement marqué « correspondance possible ». Le soignant voit plus d'information, mais l'information est plus honnête. Le niveau de confiance n'a pas baissé : c'est l'affichage qui s'est enrichi.

Et la fusion, elle, reste conditionnée à une validation humaine explicite. C'est le même niveau d'exigence qu'avant.

---

## 8. Tests, vérification, industriisation

**Question : comment avez-vous vérifié que ça marche ?**

J'ai utilisé trois niveaux.

Le premier, ce sont les **tests automatisés** : deux cent trente-cinq tests qui vérifient le cycle du DMP, la gestion des permissions, les cas d'erreur du formulaire, et un module dédié aux pannes serveur. Ces tests tournent sur une base de données séparée, jamais sur les données réelles — c'est une règle que je me suis fixée dès le début, et qui a évité plusieurs accidents.

Le deuxième, ce sont les **tests sur le site déployé** : créer réellement un patient, vérifier que le dossier apparaît, faire une reconnaissance faciale, confirmer l'identité. Un test qui passe en local peut échouer en ligne, et c'est ce qui s'est produit à plusieurs reprises.

Le troisième, c'est le **test de bout en bout** : partir d'un patient inconnu, passer par le cycle complet, et vérifier le résultat final. C'est ce type de test qui révèle les vrais problèmes — par exemple, j'ai constaté que les photos ne s'affichaient pas sur le site déployé alors que tout fonctionnait en local.

**Question : quels bugs avez-vous trouvés en testant en ligne, mais pas en local ?**

Il y en a eu trois qui m'ont appris quelque chose.

Le premier : les photos renvoyaient « signature manquante ». La cause, c'est que Supabase utilise une version de signature plus récente que celle que le client utilisait par défaut. Ça ne se voyait pas en local.

Le deuxième : la commande de migration des photos vers le stockage distant ne pouvait pas fonctionner. Elle lisait les images **via le champ du modèle** — et comme le champ avait été basculé sur le stockage distant, elle cherchait les photos dans un dossier vide. La commande était donc incapable de faire ce qu'elle était censée faire, et cela depuis le début.

Le troisième est le plus intéressant sur le fond : l'écran de reconnaissance faciale **annonçait à l'écran un moteur qui n'était pas celui qui tournait**. Le texte était écrit en dur dans le gabarit. Comme la bibliothèque classique n'est pas installable sur Vercel, le moteur réel était le nouveau — mais l'écran disait l'ancien.

Celui-là est mon exemple préféré, parce qu'il illustre le risque des libellés codés en dur : **l'écran mentait, et il mentait de façon believable**. Un jury qui m'aurait demandé « quel moteur tourne ? » aurait eu une réponse fausse.

**Si le jury me challenge : « Vos tests sont-vous suffisants ? »**

Non, et je sais précisément ce qui manque. Les tests que j'ai écrits vérifient le bon fonctionnement des cas normaux et de quelques erreurs. Ce qui manque, ce sont les tests de charge : je n'ai pas mesuré le comportement quand plusieurs-hundred personnes utilisent la plateforme en même temps. Et les tests d'intrusion, je ne les ai pas faits moi-même — c'est le genre de prestation qu'on confie à quelqu'un dont c'est le métier.

---

## 9. Déploiement et exploitation

**Question : comment l'application est-elle déployée ?**

Sur Vercel, avec une base de données et un stockage fichiers gérés par Supabase. Et ce choix mérite une explication, parce que j'ai hésité.

J'ai d'abord envisagé un hébergement classique avec un vrai serveur. J'ai écarté l'hypothèse quand j'ai constaté que la version de Python et la base de données n'étaient pas compatibles avec ce que je pouvais avoir. Je n'allais pas livrer un projet qui ne démarre pas chez moi.

J'ai donc repris le déploiement sur l'hébergeur que je connaissais, mais en réglant un problème que je ne connaissaisais pas : **les fichiers ne survivaient pas aux déploiements**. Chaque mise en production détruisait le serveur et avec lui les photos. C'est exactement le défaut que j'ai décrit quand on parle d'un serveur sans stockage persistant. Le correctif, c'est de déplacer les médias vers un stockage dédié.

**Question : c'est pas un peu bricolé par défaut, de dépendre de deux services ?**

C'est un compromis que j'assume, et je vais être précis sur ses limites.

Ce que ça permet : un déploiement simple, aucun serveur à maintenir, pas de configuration système à gérer, et un coût quasi nul pour un projet de démonstration.

Ce que ça coûte : deux fournisseurs à surveiller, une latence supplémentaire entre le site et la base, et surtout une **dépendance à leurs quotas**. L'offre gratuite a des limites d'usage, et un usage réel les dépasserait. Je ne présenterais pas cette architecture comme une solution d'hébergement pour un hôpital : c'est un déploiement de démonstration. Le jour du passage à l'échelle, il faudrait un hébergeur infogéré avec des engagements de service — et pour des données de santé, un hébergeur certifié.

**Question : comment vous garantissez que ça ne tombe pas en panne le jour de la soutenance ?**

Je ne peux pas le garantir, et je pense qu'un candidat qui prétend le contraire n'a pas compris son système. Ce que je fais, c'est de réduire les dépendances et de tester avant.

Une chose que j'ai appris à la dure : les plateformes en ligne éteignent leurs serveurs quand ils ne sont pas utilisés. Si je prépare ma soutenance, la première connexion après une longue coupure met quelques secondes. Le contournement est simple : ouvrir le site juste avant de commencer.

Et sur ce point précis, les applications conçues pour une démonstration modifient souvent leur configuration, et le font d'une manière qu'une application réelle ne ferait jamais. J'ai donc laissé les réglages par défaut — qui sont les plus sûrs — et je les ai modifiés **par la configuration**, pas dans le code. Concrètement, le délai de déconnexion pour inactivité, la règle d'une seule session par compte, et l'obligation de changer de mot de passe restent **actifs dans le code**. Seuls les réglages propres à la démonstration sont modifiés. Réactiver le mode normal prend une seconde et ne nécessite aucune modification de code.

C'est un point que je veux assumer clairement devant vous : j'ai modifié des réglages pour que la démonstration se passe bien. Mais j'ai fait en sorte que ces réglages soient séparés du comportement du code, et réversibles. Je préfère vous le dire que de le passer sous silence.

**Question : et la surveillance, les sauvegardes ?**

Les sauvegardes sont gérées par Supabase, avec une restauration possible. En revanche, **je n'ai pas mis en place de supervision** — pas d'alerte si le site tombe. C'est une limite assumée pour un projet de démonstration, et c'est le premier élément que j'ajouterais.

---

## 10. Limites, risques, ce que je n'ai pas fait

> *Cette partie est volontairement honnête. Un jury valorise un candidat qui connaît ses limites, pas un candidat qui prétend que tout est parfait.*

**Question : quelles sont les vraies limites du système ?**

Je vais en donner cinq, par ordre d'importance.

**La plus importante : la reconnaissance faciale peut se tromper.** J'ai mesuré que les scores des vraies correspondances et ceux de patients différents se recoupent. Il n'existe pas de seuil qui les sépare parfaitement. C'est la raison pour laquelle la validation humaine est structurelle, et non un habillage. Sur une population très ethnically homogène, ou en l'absence de données d'entraînement représentatives du contexte camerounais, la marge se réduit encore.

**Deuxième limite : la dépendance au fournisseur.** L'architecture repose sur deux services externes. Si l'un tombe, l'application est inutilisable. C'est acceptable pour une démonstration, pas pour un hôpital.

**Troisième limite : les données de démonstration sont synthétiques.** Les cent patients ont été générés. Les mesures que j'ai faites le sont donc aussi. Elles valident le fonctionnement technique, pas la performance sur des photos réelles de patients réels.

**Quatrième limite : le chiffrement au niveau applicatif n'est pas en place.** Le chiffrement est assuré par les infrastructures. Un chiffrement au niveau des données les plus sensibles, indépendant de l'hébergeur, serait un vrai plus.

**Cinquième limite : il n'y a pas de récupération de mot de passe pour tous les profils.** Le mécanisme existe et fonctionne, mais il dépend de la configuration d'envoi d'e-mails, que je n'ai pas pu valider de bout en bout faute d'accès à un service d'envoi réel.

**Question : qu'auriez-vous fait en priorité avec un mois de plus ?**

Trois choses, dans cet ordre.

Un : **faire valider tout le processus avec de vraies photos**, prises dans de vraies conditions. Tout ce que j'ai mesuré sur données synthétiques doit être revalidé. C'est le seul moyen de savoir si le réglage actuel tient.

Deux : **remplacer les empreintes par plusieurs références par patient**, pour qu'une photo prise dans des conditions différentes soit reconnue plus souvent. J'ai testé cette piste et le gain était faible, mais elle mérite d'être reprise avec des données réelles.

Trois : **la supervision**, avec des alertes. C'est ce qui sépare un projet qui fonctionne d'un projet qu'on peut exploiter.

---

## 11. Les questions qui fâchent

> *Les cinq questions les plus probables en soutenance, avec la réponse à avoir prête. Ce sont celles qui Bibles de déstabiliser un candidat.*

---

**« Pourquoi faire votre propre système plutôt qu'utiliser un logiciel déjà existant ? »**

Parce que les logiciels existants supposent une infrastructure qui n'existe pas chez nous. Un dossier patient informatisé suppose un service informatique, du réseau dans les chambres, et un personnel formé. Dans un hôpital de district, la réalité, c'est un ordinateur portable, une connexion qui coupe, et une équipe de trois personnes.

Le logiciel n'a pas échoué. Le contexte n'était pas prêt. Mon travail, c'est de répondre à cette contrainte : une application qui démarre vite, qui fonctionne sur un connexion lente, et qui ne demande pas six mois de formation.

---

**« La reconnaissance faciale dans un hôpital, ce n'est pas une violation de la vie privée ? »**

C'est l'objection sérieuse, et elle mérite une réponse sérieuse.

Mon projet n'utilise pas de caméra discrète pour filmer des patients à l'insu du personnel. Il utilise une **photo d'identité** — prise par un soignant ou par le patient lui-même — pour **prouver** une identité dans un dossier médical. Ce n'est pas de la surveillance, c'est de l'authentification.

Et je me suis placé sur le cadre le plus exigeant : au lieu de m'appuyer sur la base légale la plus large, j'ai construit sur le modèle du RGPD, qui classe la biométrie parmi les traitements les plus sensibles. Concrètement, la personne concerned peut refuser, les données sont minimisées, chaque accès est tracé, et le visage n'est pas utilisé à d'autres fins.

Mais je reconnais la limite : ce point-là, dans certaines juridictions européennes, n'est simplement pas autorisé, quelle que soit la qualité du reste. C'est un débat qui dépasse la technique, et c'est très bien qu'il existe. Mon parti pris, c'est que le bénéfice — identifier un patient incapable de s'exprimer — puisse justifier un dispositif encadré. Ce qui ne serait pas acceptable, c'est de le faire sans consentement ni sans trace. C'est précisément pour ça que le consentement et le journal d'audit ne sont pas optionnels dans mon application.

---

**« Comment vous garantissez la sécurité ? »**

Je ne la garantis pas, je l'ai renforcée dans sa conception. Ce sont deux choses différentes.

Aucun système n'est garanti sûr. Ce que je peux dire, c'est que j'ai traité la sécurité comme un critère de conception, pas comme une vérification finale.

J'ai activé les protections par défaut de Django plutôt que de construire les miennes — c'est un choix qui évite les erreurs. J'ai fait en sorte qu'une personne ne puisse pas lire le dossier d'un patient sans son accord. J'ai séparé l'administration de la plateforme de l'accès aux dossiers médicaux. J'ai rendu le journal d'audit non modifiable. J'ai mis en place la détection des tentatives de connexion répétées, et le verrouillage des comptes.

Et j'ai exprimé les risques que je n'ai pas traités : pas de chiffrement applicatif, pas de test d'intrusion indépendant, pas de supervision. Un candidat qui prétend avoir tout couvert se trompe, et je préfère être précis sur ce que j'ai fait et sur ce que je n'ai pas fait.

---

**« Votre base de données est sur un serveur étranger. Vos données de santé quittent le pays. »**

C'est une objection pertinente, et je n'ai pas la prétention d'y avoir répondu par la technique.

Sur le fond, dans mon projet il n'y a pas de données de patients réels : ce sont des données de démonstration générées. Mais l'objection reste entièrement valable pour un usage réel, et j'accepte qu'un hébergeur étranger crée une question de souveraineté sur les données de santé. C'est un sujet sur lequel je n'ai pas de réponse technique convaincante, seulement une position : un hébergement national avec engagement de service me paraît être la condition d'un déploiement réel.

Ce que j'ai fait, c'est m'assurer qu'aucune donnée n'est exposée publiquement : le stockage est privé, les accès sont authentifiés, et les journaux d'audit permettent de reconstituer qui a consulté quoi.

---

**« Ça marche avec cent patients. Ça marche à l'échelle ? »**

Je ne peux pas répondre « oui », et je ne vais pas donner un chiffre que je n'ai pas mesuré. C'est une limite que j'assume.

Ce que je sais, c'est que la conception ne souffre pas d'un défaut de mise à l'échelle évident. Les empreintes faciales sont calculées **une fois** à l'enregistrement du patient, pas à chaque recherche — c'est la principale question de performance, et elle est traitée. La base de données est indexée de façon classique.

Ce que je ne sais pas, c'est le comportement réel à plusieurs centaines de milliers de dossiers, parce que je n'ai pas fait de test de charge. Ajouter un million de patients changerait probablement la réponse sur la reconnaissance faciale : à un moment, il faudrait répartir la recherche par indexation vectorielle, pour ne pas tout comparer. C'est une évolution que j'ai identifiée, pas que j'ai réalisée.

---

**« Combien de temps vous a pris ce projet ? »**

Je préfère répondre par ce que contient le projet plutôt que par un chiffre.

Ce qui a pris du temps, ce n'est pas d'écrire du code. C'est la partie où j'ai cherché à comprendre le cycle réel du patient dans un hôpital — la logique du temporaire, la question du consentement, le cas de l'urgence vitale. Cette partie vient d'entretiens et de lecture, pas de développement.

Et il y a eu une part importante de correction. Sur les points que je viens de citer — les photos qui ne s'affichaient pas, les patients sans dossier, le moteur annoncé — ce sont des défauts que j'ai trouvés moi-même en testant. Le projet n'était pas terminé quand j'ai commencé à le présenter ; il l'est maintenant.

---

## Les cinq phrases à retenir

Si je ne devais retenir que cinq choses de cette préparation :

1. **La reconnaissance faciale ne décide jamais seule.** Elle propose, un médecin décide, et la décision est tracée. Toute la conception découle de ce principe.

2. **Le consentement est la règle, l'accès l'exception.** On n'accède pas à un dossier parce qu'on en a le droit, on y accède parce que le patient l'a permis.

3. **J'ai mesuré au lieu de supposer.** Le réglage de la reconnaissance faciale n'est pas une intuition : il vient d'un protocole de mesures, et la mesure m'a conduits à revoir ma propre approche.

4. **Les corrections valent autant que les fonctionnalités.** Les bugs que j'ai trouvés sont plus instructifs pour un projet de développement que les fonctionnalités que j'ai ajoutées.

5. **Je connais mes limites.** Elles sont écrites, elles sont assumées, et c'est ce qui rend le reste crédible.

---

## Annexe — Les chiffres à connaître par cœur

| Élément | Valeur |
|---|---|
| Patients de démonstration | 100 |
| Fichiers sur le site | 102 |
| Tests automatisés | 235 |
| Modèles de reconnaissance faciale | 2 (détection + identification) |
| Dimension des empreintes | 512 valeurs |
| Seuil de correspondance forte | 80 % |
| Seuil d'affichage des candidats | 55 % |
| Modes de reconnaissance faciale | 2 (serveur classique et modèle ONNX) |
| Profils d'utilisateurs | 5 |
| Durée de validité des liens photos | 1 heure |
| Rôles super administrateur sur les dossiers médicaux | Aucun |
| Mots de passe stockés en clair | Aucun |

**Les trois chiffres à retenir en cas de question courte :**
« Cent patients, deux cent trente-cinq tests, deux modèles qui travaillent en chaîne. »