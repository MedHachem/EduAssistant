---
pdf_page: 20
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_020.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_020.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
## Cours

Exemples

| Intervalle I | Si f est strictement croissante sur I | Si f est strictement décroissante sur I |
|---|---|---|
| $I=[a,b]$ | $f(I)=[f(a),f(b)]$ | $f(I)=[f(b),f(a)]$ |
| $I=[a,b[\ (a\in\mathbb{R}, b\in\mathbb{R})$ | $f(I)=[f(a),\lim_{b^-}f[$ | $f(I)=]\lim_{b^-}f,f(a)]$ |
| $I=[a,+\infty[\ (a\in\mathbb{R})$ | $f(I)=[f(a),\lim_{+\infty}f[$ | $f(I)=]\lim_{+\infty}f,f(a)]$ |
| $I=]a,b[\ (a\in\mathbb{R}, b\in\mathbb{R})$ | $f(I)=]\lim_{a^+}f,\lim_{b^-}f[$ | $f(I)=]\lim_{b^-}f,\lim_{a^+}f[$ |

<bloc type="activite" numero="2">
Déterminer l'image de l'intervalle I par la fonction f dans chacun des cas ci-dessous.

1. $f: x \mapsto \dfrac{x+1}{x-2}$, $I=]2, +\infty[$.

2. $f: x \mapsto \sqrt{x^2-2x}$, $I=]-\infty, 0]$.

3. $f: x \mapsto \tan(x\pi)$, $I=]-\dfrac{1}{2}, 0[$.
</bloc>

### Problème résolu

<bloc type="exercice" continues_on_next_page="true">
I. 1. Soit la fonction f définie sur l'intervalle $[0,1]$ par $f(x)=16x^2(1-x)^2$.

a. Vérifier que pour tout $x \in [0,1]$, $f(x) \leq f\left(\dfrac{1}{2}\right)$.

b. Montrer que $f([0, 1]) = [0, 1]$.

2. Soit un entier $n \geq 2$. Montrer que l'équation $f\left(x+\dfrac{1}{n}\right)=f(x)$ admet au moins une solution dans l'intervalle $[0, 1-\dfrac{1}{n}]$.

II. Le but de cette partie est de montrer que si f est une fonction continue sur l'intervalle $[0, 1]$ telle que $f(0)=f(1)$ et $f([0, 1]) = [0, 1]$, alors pour tout entier $n \geq 2$, l'équation $f\left(x+\dfrac{1}{n}\right)=f(x)$ admet au moins une solution dans l'intervalle $[0, 1-\dfrac{1}{n}]$.

Soit g la fonction définie sur $[0, 1-\dfrac{1}{n}]$ par $g(x)=f(x)-f\left(x+\dfrac{1}{n}\right)$.

1. Montrer que g est continue sur $[0, 1-\dfrac{1}{n}]$.
</bloc>
