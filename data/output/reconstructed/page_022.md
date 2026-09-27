---
pdf_page: 22
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_022.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_022.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
<bloc type="exercice" continues_from_previous_page="true">

2. Posons $S_n = g(0) + g\left(\frac{1}{n}\right) + g\left(\frac{2}{n}\right) + \ldots + g\left(\frac{n-1}{n}\right)$, n entier supérieur ou égal à 2.

Montrons que pour tout entier $n \geq 2$, $S_n = 0$.

Pour tout entier $n \geq 2$,

$$S_n = g(0) + g\left(\frac{1}{n}\right) + g\left(\frac{2}{n}\right) + \ldots + g\left(\frac{n-1}{n}\right)$$

$$= \left(f(0) - f\left(\frac{1}{n}\right)\right) + \left(f\left(\frac{1}{n}\right) - f\left(\frac{2}{n}\right)\right) + \ldots + \left(f\left(\frac{n-2}{n}\right) - f\left(\frac{n-1}{n}\right)\right) + \left(f\left(\frac{n-1}{n}\right) - f(1)\right).$$

On en déduit que $S_n = f(0) - f(1) = 0$.

3. Montrons que l'équation $g(x) = 0$ admet une solution dans l'intervalle $[0, 1-\frac{1}{n}]$.

Supposons que pour tout réel $x \in [0, 1-\frac{1}{n}]$, $g(x) \neq 0$.

Il résulte de la continuité de g sur l'intervalle $[0, 1-\frac{1}{n}]$, que g garde un signe constant sur $[0, 1-\frac{1}{n}]$ et par conséquent le réel $g(0) + g\left(\frac{1}{n}\right) + g\left(\frac{2}{n}\right) + \ldots + g\left(\frac{n-1}{n}\right)$ est ou bien strictement positif ou bien strictement négatif ce qui est en contradiction avec le résultat

$$g(0) + g\left(\frac{1}{n}\right) + g\left(\frac{2}{n}\right) + \ldots + g\left(\frac{n-1}{n}\right) = 0.$$

En conclusion, il existe un $\alpha \in [0, 1-\frac{1}{n}]$ tel que $g(\alpha) = 0$, c'est à dire $f\left(\alpha + \frac{1}{n}\right) = f(\alpha)$.

</bloc>
