---
pdf_page: 8
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_008.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_008.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
# Cours

## I.3 Opérations sur les limites

Soit L et L' deux réels.

Les résultats qui suivent concernent les opérations sur les limites en un réel ou à l'infini.

| $\lim f$ | $\lim g$ | $\lim (f+g)$ |
|---|---|---|
| L | L' | L+L' |
| L | $+\infty$ | $+\infty$ |
| $-\infty$ | L' | $-\infty$ |
| $+\infty$ | $+\infty$ | $+\infty$ |
| $-\infty$ | $-\infty$ | $-\infty$ |

| $\lim f$ | $\lim g$ | $\lim (f \times g)$ |
|---|---|---|
| L | L' | $L \times L'$ |
| $+\infty$ | $L'>0$ | $+\infty$ |
| $+\infty$ | $L'<0$ | $-\infty$ |
| $+\infty$ | $+\infty$ | $+\infty$ |
| $+\infty$ | $-\infty$ | $-\infty$ |
| $-\infty$ | $-\infty$ | $+\infty$ |

| $\lim f$ | $\lim g$ | $\lim \left(\dfrac{f}{g}\right)$ |
|---|---|---|
| L | $L' \neq 0$ | $\dfrac{L}{L'}$ |
| $+\infty$ | $L'>0$ | $+\infty$ |
| $+\infty$ | $L'<0$ | $-\infty$ |
| L | $+\infty$ | 0 |
| L | $-\infty$ | 0 |
| $L \neq 0$ | 0 | $\infty$ ( On applique la règle des signes). |

| $\lim f$ | $\lim \lvert f \rvert$ | $\lim \sqrt{\lvert f \rvert}$ |
|---|---|---|
| L | $\lvert L \rvert$ | $\sqrt{\lvert L \rvert}$ |
| $+\infty$ | $+\infty$ | $+\infty$ |
| $-\infty$ | $+\infty$ | $+\infty$ |

Les règles énoncées dans les tableaux précédents ne s'appliquent pas lorsqu'il s'agit d'étudier

* la limite de la somme de deux fonctions dont l'une tend vers $+\infty$ l'autre tend vers $-\infty$.
* la limite du produit de deux fonctions dont l'une tend vers l'infini l'autre tend vers 0.
* la limite du quotient de deux fonctions qui tendent toutes les deux vers l'infini ou toutes les deux vers 0.

Une transformation d'écriture adéquate pourra nous ramener à l'un des théorèmes résumés dans les tableaux ci-dessus.

<bloc type="theoreme">
- La limite d'une fonction polynôme à l'infini est la même que celle de son terme de plus haut degré.
- La limite d'une fonction rationnelle à l'infini est la même que celle du quotient des termes de plus haut degré.
</bloc>

<bloc type="activite">
Déterminer les limites ci-dessous.

1. $\lim\limits_{x \to -\infty} 2x + \dfrac{1}{x^2+1}$.
2. $\lim\limits_{x \to -\infty} \sqrt{-5x+1} - 3x$.
3. $\lim\limits_{x \to +\infty} \left(-x^2-x\right)^2 + \sqrt{2}\,x$.
4. $\lim\limits_{x \to 2} 5x^3 + \left(\dfrac{3x-1}{\lvert x-2 \rvert}\right)^5$.
5. $\lim\limits_{x \to 3} \sqrt{2x-3}\left(\dfrac{3}{(x-3)^2}-2\right)$.
6. $\lim\limits_{x \to +\infty} \left(\dfrac{5}{\sqrt{x^2+1}}-2x\right)(x^3+x)$.
7. $\lim\limits_{x \to +\infty} \sqrt{x} - x$.
</bloc>
