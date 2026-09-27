---
pdf_page: 21
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_021.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_021.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
<bloc type="exercice" continues_from_previous_page="true" continues_on_next_page="true">

2. Montrer que $g(0)+g\left(\frac{1}{n}\right)+g\left(\frac{2}{n}\right)+\ldots+g\left(\frac{n-1}{n}\right) = 0$.

3. En déduire qu'il existe $\alpha \in [0, 1-\frac{1}{n}]$ tel que $f\left(\alpha + \frac{1}{n}\right) = f(\alpha)$.

### Solution

I.1.a. $f(x) = 16\left(x(1-x)\right)^2$, $x \in [0, 1]$.

On considère la fonction $f_1$ définie sur $[0, 1]$ par $f_1(x) = x(1-x)$.

Comme la fonction $f_1$ atteint son maximum sur $[0, 1]$ en $\frac{1}{2}$, on en déduit que

$$f(x) \leq f\left(\frac{1}{2}\right), x \in [0, 1].$$

b. La fonction f est continue sur le fermé borné $[0,1]$, il existe deux réels $\alpha$ et $\beta$ tels que

$$f([0, 1]) = [f(\alpha), f(\beta)].$$

$f(\alpha)$ est le minimum de f sur $[0, 1]$ et $f(\beta)$ est le maximum de f sur $[0, 1]$.

Pour tout $x \in [0, 1]$, $0 \leq f(x) \leq f\left(\frac{1}{2}\right)$ et $f(0) = 0$, $f\left(\frac{1}{2}\right) = 1$.

On en déduit que $f([0, 1]) = [0, 1]$.

2. Considérons la fonction h définie sur l'intervalle $[0, 1-\frac{1}{n}]$ par $h(x) = f(x) - f\left(x + \frac{1}{n}\right)$ ;

La fonction h est une fonction polynôme donc elle est continue sur $[0, 1-\frac{1}{n}]$ et

$$h(0).h\left(1-\frac{1}{n}\right) < 0.$$

On en déduit, d'après le théorème des valeurs intermédiaires que l'équation $h(x) = 0$

admet au moins une solution sur $[0, 1-\frac{1}{n}]$.

II. 1. On peut écrire $g = f - f \circ u$, où u est la fonction définie sur $[0, 1-\frac{1}{n}]$ par $u(x) = x + \frac{1}{n}$ ;

La fonction u est continue sur $[0, 1-\frac{1}{n}]$ et $u(x) \in \left[\frac{1}{n}, 1\right] \subset [0, 1]$.

D'autre part, la fonction f est continue sur $[0, 1]$.

Il en résulte d'après la continuité d'une fonction composée sur un intervalle que $f \circ u$

est continue sur $[0, 1-\frac{1}{n}]$ et par suite la fonction g est continue sur $[0, 1-\frac{1}{n}]$.

</bloc>
