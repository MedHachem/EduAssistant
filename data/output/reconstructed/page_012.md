---
pdf_page: 12
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_012.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_012.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
<bloc type="activite" numero="2">
Dans chacun des cas suivants, déterminer deux fonctions u et v telles que $f = v \circ u$.

1. $f : x \mapsto \cos(\pi x + 1)$.
2. $f : x \mapsto x\sin\left(\frac{1}{x}\right)$.
3. $f : x \mapsto \tan\left(\frac{\pi}{2x}\right)$.
</bloc>

## III. 2 Continuité d'une fonction composée

<bloc type="theoreme">
Soit u une fonction définie sur un intervalle ouvert I contenant un réel a et v une fonction définie sur un intervalle ouvert J contenant le réel $u(a)$.

Si u est continue en a et v est continue en $u(a)$, alors la fonction $v \circ u$ est continue en a.
</bloc>

Démonstration

Soit un réel $\beta > 0$. La fonction v étant continue en $u(a)$, il existe un réel $\alpha > 0$ tel que

$$y \in J, \ |y - u(a)| < \alpha \Rightarrow |v(y) - v(u(a))| < \beta.$$

Puisque la fonction u est continue en a, alors il existe un réel $\alpha_1 > 0$ tel que

$$x \in I, \ |x-a| < \alpha_1 \Rightarrow |u(x) - u(a)| < \alpha.$$

On peut donc écrire

$$x \in I, \ |x-a| < \alpha_1 \Rightarrow |u(x) - u(a)| < \alpha \Rightarrow |v(u(x)) - v(u(a))| < \beta$$

Il en résulte que la fonction $v \circ u$ est continue en a.

<bloc type="propriete">
La composée de deux fonctions continues est continue.
</bloc>

<bloc type="activite">
Etudier dans chaque cas la continuité de f sur l'intervalle I.

1. $f : x \mapsto \sin\left(x^2 + \frac{\pi}{4}\right)$   $I = \mathbb{R}$.
2. $f : x \mapsto \cos\left(\frac{x+1}{x-1}\right)$   $I = ]1, +\infty[$.
</bloc>

## III. 3 Limite d'une fonction composée

<bloc type="theoreme">
Soit I et J deux intervalles ouverts, a un réel de I, $\ell$ un réel de J et $\ell'$ un réel.

Soit u une fonction définie sur I, sauf peut être en a et v une fonction définie sur J, sauf peut être en $\ell$.

Si $\lim_{x \to a} u(x) = \ell$ et $\lim_{x \to \ell} v(x) = \ell'$, alors $\lim_{x \to a} v \circ u(x) = \ell'$.
</bloc>

<bloc type="activite" numero="1">
Déterminer dans chaque cas la limite de $f(x)$ lorsque x tend vers a.

1. $f : x \mapsto \dfrac{\cos(x^2) - 1}{x^2}$   $a = 0$.
2. $f : x \mapsto \dfrac{\sin(\sqrt{x} - 1)}{\sqrt{x} - 1}$   $a = 1$.
</bloc>
