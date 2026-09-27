---
pdf_page: 7
source_image: C:/Users/ASUS/Desktop/EduAssistant/data/output/page_images/page_007.png
cleaned_source: C:/Users/ASUS/Desktop/EduAssistant/data/output/cleaned/page_007.txt
needs_review: false
uncertain_count: 0
gap_count: 0
---
# Cours

<bloc type="activite" numero="3">
Soit f la fonction définie sur $\mathbb{R}^*$ par $f(x) = \dfrac{x^2 + \sin x}{x}$.

$$\lim_{x \to 0} \frac{\sin x}{x} = 1$$

Montrer que f est prolongeable par continuité en 0 et déterminer son prolongement.
</bloc>

## Théorème

<bloc type="theoreme">
Soit f une fonction définie sur un intervalle ouvert I, sauf en un réel a de I.
Si la fonction f admet une limite finie $\ell$ lorsque x tend vers a, alors la fonction g définie sur I par $g(x) = \begin{cases} f(x) & \text{si } x \neq a, \\ \ell & \text{si } x = a. \end{cases}$ est continue en a.
</bloc>

<bloc type="activite" numero="4">
Soit f la fonction définie par

$$f(x) = \begin{cases} \dfrac{-4(x^2+x-2)}{3\sqrt{1-x}} & \text{si } x < 1, \\[2mm] \dfrac{x^2-1}{\sqrt{x}-1} & \text{si } x > 1, \\[2mm] 0 & \text{si } x = 1. \end{cases}$$

Une fonction f définie sur un intervalle ouvert I est continue en un réel a de I, si et seulement si, $\lim_{x \to a^-} f(x) = \lim_{x \to a^+} f(x) = f(a)$.

1. Calculer $\lim_{x \to 1^-} f(x)$ et $\lim_{x \to 1^+} f(x)$.
2. La fonction f est-elle continue en 1 ?
</bloc>

<bloc type="activite" numero="5">
Soit la fonction $f : x \mapsto \dfrac{|x+1|}{x+1}$

La fonction f admet-elle une limite en $-1$ ?
</bloc>

## 1.2 Continuité sur un intervalle

<bloc type="activite">
Soit f la fonction définie sur $[0,\pi]$ par

$$\begin{cases} f(x) = \dfrac{1-\cos x}{x} & \text{si } x \in ]0,\pi], \\ f(0) = 0. \end{cases}$$

- Une fonction est continue sur un intervalle ouvert I si elle est continue en tout réel de I.
- Une fonction est continue sur un intervalle $[a,b]$ si elle est continue sur $]a,b[$, à droite en a et à gauche en b.

De façon analogue, on définit la continuité de f sur les intervalles $[a,b[$, $]a,b]$, $[a,+\infty[$ et $]-\infty,a]$.

Montrer que f est continue sur $[0,\pi]$.
</bloc>
