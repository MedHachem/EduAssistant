---
pdf_page: 14
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_014.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_014.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
<bloc type="activite" numero="2">
Dans la figure ci-contre on a représenté les fonctions f et g définies par $f(x)=\sqrt{-x}+\cos x$ et $g(x)=\sqrt{-x}-1$

<figure id="fig-activite2-p14" status="described">Représentation graphique de deux courbes $C_f$ et $C_g$ sur un repère orthogonal, pour des valeurs de x négatives (de -15 à 0 environ) et y allant jusqu'à 5 ; $C_f$ oscille (comportement sinusoïdal amorti) tandis que $C_g$ décroît de façon monotone, les deux courbes se rapprochant l'une de l'autre lorsque x tend vers $-\infty$.</figure>

1. Etudier la position relative de $C_f$ et $C_g$.

2. Que peut-on conjecturer sur la limite de $f(x)$ lorsque x tend vers $-\infty$ ?
</bloc>

## Théorème

<bloc type="theoreme">
Soit f, u et v trois fonctions définies sur un intervalle I sauf peut-être en un réel a de I.
Soit deux réels $\ell$ et $\ell'$.

- Si $u(x) \leq v(x)$ pour tout $x \neq a$ et si $\lim_{a} u = \ell$ et $\lim_{a} v = \ell'$ alors $\ell \leq \ell'$.

- Si $u(x) \leq f(x) \leq v(x)$ pour tout $x \neq a$ et si $\lim_{a} u = \lim_{a} v = \ell$ alors $\lim_{a} f = \ell$.

Les résultats énoncés ci-dessus restent valables lorsque l'on considère des limites à l'infini, à droite en a ou à gauche en a.
</bloc>

<bloc type="theoreme">
Démonstration

- Posons $g(x)=v(x)-u(x)$ pour tout $x \neq a$.

D'après l'hypothèse faite sur les fonctions u et v, la fonction g est positive et $\lim_{a} g = \ell'-\ell$.

On en déduit que $\ell \leq \ell'$.

- Posons $h(x)=f(x)-u(x)$ et $g(x)=v(x)-u(x)$ pour tout $x \neq a$.

D'après l'hypothèse faite sur les fonctions f, u et v, $0 \leq h(x) \leq g(x)$ pour tout $x \neq a$ et $\lim_{a} g = 0$. On en déduit que pour tout $\beta > 0$, il existe $\alpha > 0$ tel que

$$x \in I \text{ et } 0 < |x-a| < \alpha \Rightarrow h(x) \leq g(x) < \beta.$$

Le théorème en découle.
</bloc>

## Théorème

<bloc type="theoreme">
Soit f et u deux fonctions définies sur un intervalle I sauf peut-être en un réel a de I.

- Si $f(x) \geq u(x)$ pour tout $x \neq a$ et si $\lim_{a} u = +\infty$, alors $\lim_{a} f = +\infty$.

- Si $f(x) \leq u(x)$ pour tout $x \neq a$ et si $\lim_{a} u = -\infty$, alors $\lim_{a} f = -\infty$.

Ces résultats restent valables lorsque l'on considère des limites à l'infini, à droite en a ou à gauche en a.
</bloc>

<bloc type="theoreme" continues_on_next_page="true">
Démonstration

- Soit un réel $A > 0$. L'égalité $\lim_{a} u = +\infty$ implique l'existence d'un réel $\alpha > 0$ tel que

$$x \in I \text{ et } 0 < |x-a| < \alpha \Rightarrow u(x) > A.$$
</bloc>
