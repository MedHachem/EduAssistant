---
pdf_page: 6
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_006.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_006.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
# Chapitre 1

# Continuité et limites

## I. Rappels

Dans ce paragraphe nous rappelons les principaux théorèmes vus en troisième année.

### I.1 Continuité et limite en un réel

<bloc type="activite" numero="1">
Dans chacun des cas suivants déterminer l'ensemble de définition de la fonction f et justifier la continuité de f en tout réel de son ensemble de définition.

1. $f : x \mapsto 1 - x + x^2$.
2. $f : x \mapsto x - \dfrac{1}{x-1}$.
3. $f : x \mapsto \dfrac{\sin x + 1}{2 + \cos x}$.
4. $f : x \mapsto \dfrac{|-5x+1|-2}{x+3}$.
5. $f : x \mapsto \sqrt{\dfrac{x^2+1}{x-1}}$.

- Toute fonction polynôme est continue en tout réel.
- Toute fonction rationnelle est continue en tout réel de son ensemble de définition.
- Les fonctions $x \mapsto \cos x$ et $x \mapsto \sin x$ sont continues en tout réel.
</bloc>

<bloc type="theoreme">
Soit f et g deux fonctions définies sur un intervalle ouvert I et a un réel de I.

- Si f est continue en a, alors les fonctions $\alpha f$ $(\alpha \in \mathbb{R})$, $|f|$ et $f^n$ $(n \in \mathbb{N}^*)$ sont continues en a.
- Si f est continue en a et $f(a) \neq 0$, alors les fonctions $\dfrac{1}{f}$ et $\dfrac{1}{f^n}$ $(n \in \mathbb{N}^*)$ sont continues en a.
- Si f et g sont continues en a, alors $f+g$ et $f \times g$ sont continues en a.
- Si f et g sont continues en a et $g(a) \neq 0$, alors $\dfrac{f}{g}$ est continue en a.
- Si f est positive sur I et f est continue en a, alors la fonction $\sqrt{f}$ est continue en a.
</bloc>

<bloc type="activite" numero="2">
Soit la fonction $f : x \mapsto \dfrac{2x^2-4x+2}{|x-1|}$.

1. Vérifier que pour tout réel $x \neq 1$, $f(x) = 2|x-1|$.
2. En déduire $\lim_{x \to 1} f(x)$.
</bloc>

<bloc type="theoreme">
Soit f une fonction définie sur un intervalle ouvert I, sauf peut-être en un réel a de I.
S'il existe une fonction g définie sur I, continue en a et telle que $g(x) = f(x)$ pour tout $x \neq a$, alors $\lim_{x \to a} f(x) = g(a)$.
</bloc>
