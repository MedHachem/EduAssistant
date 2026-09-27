---
pdf_page: 17
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_017.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_017.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
# Cours

<bloc type="activite" numero="5">
La courbe représentée ci-contre est celle de la fonction

$$f: x \mapsto x^3 + x - 1.$$

<figure id="courbe_f_activite5" status="described">Courbe représentative de la fonction $f: x \mapsto x^3+x-1$ tracée dans un repère orthogonal, axes gradués de $-2$ à $2$ en abscisses et de $-4$ à $4$ en ordonnées, courbe croissante passant approximativement par $(0,-1)$ et coupant l'axe des abscisses entre $0$ et $1$.</figure>

I/ 1. Donner l'ensemble de définition de f.

2. Justifier la continuité de f sur $\mathbb{R}$.

3. Montrer que l'équation $f(x) = 0$ admet une unique solution $\alpha$ dans $[0,1]$.

4. On se propose de trouver un encadrement de plus en plus précis de $\alpha$, en divisant à chaque fois l'intervalle contenant $\alpha$ en deux intervalles de même amplitude.
(Ce procédé est appelé « méthode de dichotomie »).

a. Calculer $f\left(\frac{1}{2}\right)$ et en déduire que $\alpha$ appartient à l'intervalle $[\frac{1}{2}, 1]$.

b. Calculer $f\left(\frac{3}{4}\right)$ et en déduire que $\alpha$ appartient à l'intervalle $[\frac{1}{2}, \frac{3}{4}]$.

c. Poursuivre le procédé pour déduire un encadrement de $\alpha$ d'amplitude $10^{-1}$.

d. Donner un encadrement de $\alpha$ d'amplitude $10^{-2}$.

II/ Avec l'ordinateur

Pour réaliser la feuille de calcul ci-contre avec le tableur Excel,

- dans les cellules A1, B1, C1, D1, E1 et F1 taper respectivement a, b, $(a+b)/2$, $f(a)$, $f(b)$ et $f((a+b)/2)$ ;

<figure id="feuille_calcul_excel" status="described">Tableau de calcul avec colonnes A (a), B (b), C ((a+b)/2), D (f(a)), E (f(b)), F (f((a+b)/2)), lignes 1 à 14 contenant les valeurs numériques successives de l'algorithme de dichotomie appliqué à $f(x)=x^3+x-1$ sur $[0,1]$.</figure>

- dans la cellule A2, taper 0 ; dans la cellule B2, taper 1 (encadrement initial) ;
- dans la cellule C2, taper

$$=(A2+B2)/2$$

dans la cellule D2, taper

$$=\text{PUISSANCE}(A2;3)+A2-1$$

et recopier vers la droite en E2 et F2 ;

- dans la cellule A3, taper $=\text{SI}(F2*E2>0;A2;C2)$ et dans la cellule B3, taper

$$=\text{SI}(F2*E2>0;C2;B2)$$ ;

Déterminer un encadrement de $\alpha$ d'amplitude $10^{-3}$.
</bloc>

<bloc type="theoreme">
Soit f une fonction continue sur un intervalle I.
Si la fonction f ne s'annule en aucun point de I alors elle garde un signe constant sur I.
</bloc>
