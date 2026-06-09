# Methodologie d'évaluation

Le projet de base fournit le jeu, les rôles, le protocole des bots et la façon de lancer une partie. Notre ajout principal est une boucle d'évaluation autour de ce jeu: le protocole ne change pas, on observe plusieurs parties, puis on décide si une stratégie est meilleure.

## 1. Jouer plusieurs parties

On lance des batchs de parties avec nos deux bots suivis, Gabrielle et Hugo. Chaque partie produit des logs et un résume: qui a gagne, quels rôles avaient nos bots, s'ils ont survécu, s'il y a eu une erreur technique, etc.

## 2. Transformer les resultats en indicateurs

Les résultats sont regroupés dans un tableau de métriques. On regarde surtout:

- le nombre de parties terminées;
- le taux de victoire de notre équipe;
- les erreurs ou timeouts;
- la survie de Gabrielle et Hugo;
- les rôles joués, pour savoir si la stratégie marche aussi bien comme villageois, voyante ou loup-garou.

## 3. Décider si c'est bien ou pas

Une stratégie est considerée bonne si elle gagne plus souvent, survit mieux, et ne provoque pas plus d'erreurs. Le score combine donc trois idées simples: beaucoup de victoires, un peu de bonus pour la survie, et une pénalité si des parties échouent. On compare ensuite ce score avec la meilleure stratégie connue, appelée le champion.

## 4. Comprendre les défaites

Quand une partie est perdue, les logs sont relus pour trouver des motifs simples: nos bots ont-ils voté contre un allié, aide à éliminer un innocent, mal utilisé le role de voyante (pmal ou pas donné d'indications), ou perdu surtout quand ils etaient villageois ? Ces diagnostics donnent une idée de ce qu'il faut corriger.

## 5. Tester un patch

Au lieu de modifier automatiquement tout le code, on change surtout des paramètres de strategie: protection du coéquipier, poids donné aux votes suspects, bonus quand un loup est identifié, probabilité de parler, etc. Ce patch devient un challenger.

## 6. Garder seulement ce qui progresse

Le challenger rejoue un batch de parties. S'il a assez de parties terminées et que son score dépasse celui du champion, il est promu et devient la nouvelle meilleure stratégie. Sinon, il est rejeté et on restaure le champion.

En résume: on évalue par expériences répètées, pas sur une seule partie. La methode est: batch de parties, métriques, score, diagnostic des erreurs, petit patch contrôle, puis comparaison avec le champion.
