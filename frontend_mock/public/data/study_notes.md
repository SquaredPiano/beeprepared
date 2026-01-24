# Introductory Calculus Lecture 1: Syllabus and Review

## Practical Information and Course Structure
The introductory calculus course covers 16 lectures, held twice weekly (Mondays and Wednesdays at 10 AM). All lecture notes are available online. Assessment heavily relies on the completion and understanding of **8 problem sheets**, which are discussed further during dedicated college tutorials.

### Key Points
- The course consists of 16 lectures, delivered by Dan Ciubotaru.
- There are 8 required problem sheets, supported by 4 college tutorials.
- Recommended reading: *Mathematical Methods in the Physical Sciences* by Mary Boas.

> [!NOTE]
> Logistics: Lecturer prefers to be called 'Dan'.

> [!NOTE]
> Resource: Lecture notes written by Cath Wilkins are foundational material.

## Syllabus Overview
The syllabus is structured sequentially, beginning with a deep dive into **Differential Equations** (both Ordinary (ODEs) and Partial (PDEs)). The middle section focuses on higher-dimensional integration, specifically **Line and Double Integrals**. The course concludes with an introduction to multivariable calculus, covering topics such as:

*   Surfaces and Gradient Normal Vectors
*   Taylor's Theorem (in multiple dimensions)
*   Critical Points and Optimization
*   Lagrange Multipliers

This material is crucial for succeeding in related courses like Dynamics, Analysis 2, and further PDE studies.

### Key Points
- Part 1: Differential Equations (ODEs and PDEs).
- Part 2: Line and double integrals (3 lectures).
- Part 3: Calculus of functions in two variables (multivariable concepts).
- The course serves as a mandatory foundation for several advanced mathematics and physics topics.

> [!NOTE]
> Interdisciplinary Link: This course feeds directly into Multivariable Calculus and Fourier Series topics.

> [!NOTE]
> Focus: The first half dedicates 7-8 lectures exclusively to Differential Equations.

## Differential Equations in Practice
### Definition and Order
An ODE involves an independent variable ($x$), a function $y(x)$, and derivatives such as $\frac{dy}{dx}$. The **order** of the ODE is determined by the highest derivative present. The simplest form, $\frac{dy}{dx} = f(x)$, is solved simply by direct integration.

### Physical Examples

1.  **Mechanics (Newton's Second Law)**: Since force ($F$) equals mass ($m$) times acceleration ($a$), and acceleration is the second derivative of displacement ($r$):
    $$ F(t) = m \frac{d^2r}{dt^2} $$
    This is generally a second-order ODE.

2.  **RLC Electrical Circuit**: Applying Kirchhoff's Law relating voltage ($V$), current ($I$), resistance ($R$), inductance ($L$), and capacitance ($C$), where $I = dQ/dt$, yields a second-order linear ODE for charge $Q$:
    $$ L \frac{d^2Q}{dt^2} + R \frac{dQ}{dt} + \frac{1}{C}Q = V(t) $$

*(Exercise: Radioactive decay rate is proportional to the remaining number of atoms. Set up the ODE.)*

### Key Points
- An ODE involves an independent variable, a function, and its derivatives.
- The order of an ODE is defined by its highest derivative.
- Physical laws (e.g., Newton's Second Law) are naturally expressed as ODEs.
- RLC circuits provide a common engineering application leading to a second-order ODE.

> [!NOTE]
> Formula: The voltage across an inductor is $V_L = L \frac{dI}{dt}$.

> [!NOTE]
> Concept Check: $F=ma$ becomes a second-order ODE because displacement is differentiated twice.

## Review of Core Integration Techniques
### Integration by Parts
Based on the product rule $(fg)' = f'g + fg'$, integration by parts allows the integration of a product of two functions. The formula is:
$$ \int fg' dx = fg - \int f'g dx $$

**Example Application**: Solving $\int x^2 \sin(x) dx$.
*   Let $f = x^2$ (easily differentiable) and $g' = \sin(x)$ (easily integrable).
*   Applying the formula results in: $-x^2 \cos(x) + 2 \int x \cos(x) dx$.

### Reduction Formulas
These recursive formulas allow complex integrals to be reduced to simpler forms. For $I_n = \int \cos^n(x) dx$, the reduction formula is:
$$ I_n = \frac{1}{n}\cos^{n-1}(x)\sin(x) + \frac{n-1}{n}I_{n-2} $$

### Separable Equations
A first-order ODE $\frac{dy}{dx}$ is **separable** if it can be written as a product of a function of $x$ and a function of $y$: $\frac{dy}{dx} = a(x)b(y)$.

**Solution Method**:
1.  Separate variables: $\frac{1}{b(y)} dy = a(x) dx$
2.  Integrate both sides: $\int \frac{1}{b(y)} dy = \int a(x) dx$

**Example Solution**: The separable equation $x(y^2-1) + y(x^2-1)\frac{dy}{dx} = 0$ has the general solution $(1-y^2)(1-x^2) = C$, where $C \ge 0$.

### Key Points
- Integration by Parts is derived from the product rule of differentiation.
- Reduction formulas simplify integrating high powers of trigonometric functions.
- Separable Equations are solved by isolating variables and integrating both sides.

> [!NOTE]
> Formula (IBP): $\int u dv = uv - \int v du$

> [!NOTE]
> Critical Step: When solving separable equations, always ensure you handle the variables correctly before integrating.

## Glossary
- **Problem Sheets**
- **Tutorials**
- **Recommended Reading**
- **ODEs**
- **PDEs**
- **Line Integral**
- **Double Integral**
- **Lagrange Multipliers**
- **Order of ODE**
- **Newton's Second Law**
- **Kirchhoff's Law**
- **RLC Circuit**
- **Integration by Parts**
- **Product Rule**
- **Reduction Formula**
- **Separable Equation**
